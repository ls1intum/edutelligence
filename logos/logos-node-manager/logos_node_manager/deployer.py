"""The deployment: pull, swap, verify, and roll back if the new container does not come up.

A deployment moves through the phases of ``Phase``. Every step is safe to repeat, and the record is saved when the
phase changes. If the manager stops in the middle, for example because Docker recreates its own container, the next
start picks the record up and works out from the phase and from what Docker shows where to continue.

The ``draining`` phase is a place holder. A later version waits there for the running requests of the node to finish.
"""

from __future__ import annotations

import logging
import time
from typing import Callable

from logos_node_manager.config import Settings
from logos_node_manager.docker_ops import Docker, split_image_ref
from logos_node_manager.errors import DockerError, Interrupted
from logos_node_manager.rollback import restore_previous
from logos_node_manager.state import MAX_EVENTS, Deployment, FailureKind, Outcome, Phase, StateStore, utc_now
from logos_node_manager.verify import verify_container

logger = logging.getLogger(__name__)

# The local name under which the image of the previous deployment is kept.
PREVIOUS_TAG = "previous"
# The saved log of a failed container is limited, so the record stays small.
MAX_LOG_CHARS = 6000


def short_id(image_id: str | None) -> str:
    """The short form of an image ID, as ``docker images`` prints it."""
    return (image_id or "none").removeprefix("sha256:")[:12]


class Deployer:
    def __init__(
        self,
        settings: Settings,
        docker: Docker,
        store: StateStore,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], str] = utc_now,
        should_stop: Callable[[], bool] = lambda: False,
    ) -> None:
        self.settings = settings
        self.docker = docker
        self.store = store
        self._clock = clock
        self._sleep = sleep
        self._now = now
        self._should_stop = should_stop

    # ------------------------------------------------------------------ Driver

    def process(self, deployment: Deployment) -> Deployment:
        """Run the deployment to its end. Raises ``Interrupted`` if the daemon is asked to stop first."""
        if deployment.started_at is None:
            deployment.started_at = self._now()
        steps = {
            Phase.QUEUED: self._begin,
            Phase.PULLING: self._pull,
            Phase.DRAINING: self._drain,
            Phase.SWAPPING: self._swap,
            Phase.VERIFYING: self._verify,
            Phase.ROLLING_BACK: self._rollback,
        }
        while not deployment.finished:
            if self._should_stop():
                raise Interrupted()
            # Each step either moves the record to another phase or finishes it, so the loop always makes progress.
            steps[deployment.phase](deployment)
        return deployment

    # ------------------------------------------------------------------ Record helpers

    def _event(self, deployment: Deployment, note: str) -> None:
        if note:
            logger.info("Deployment %s (%s): %s", deployment.id, deployment.phase.value, note)
        deployment.events.append({"at": self._now(), "phase": deployment.phase.value, "note": note})
        del deployment.events[:-MAX_EVENTS]

    def _advance(self, deployment: Deployment, phase: Phase, note: str = "") -> None:
        deployment.phase = phase
        self._event(deployment, note)
        self.store.save(deployment)

    def _finish(
        self, deployment: Deployment, outcome: Outcome, failure: FailureKind | None = None, message: str = ""
    ) -> None:
        deployment.outcome = outcome
        deployment.failure = failure
        deployment.message = message
        deployment.finished_at = self._now()
        deployment.phase = Phase.DONE
        self._event(deployment, f"{outcome.value}: {message}" if message else outcome.value)
        self.store.save(deployment)

    def _fail_over(self, deployment: Deployment, kind: FailureKind, reason: str) -> None:
        """The new container is bad: restore the previous version, or give up if there is none."""
        deployment.failure = kind
        deployment.message = reason
        if deployment.previous_image_id:
            self._advance(deployment, Phase.ROLLING_BACK, f"{reason}; restoring {deployment.previous_image_ref}")
        else:
            self._finish(deployment, Outcome.FAILED, kind, f"{reason}; there is no previous version to restore")

    def _capture_logs(self) -> str:
        """The end of the container's log. Must run before a rollback removes the container."""
        try:
            return self.docker.container_logs(40)[-MAX_LOG_CHARS:]
        except Exception:  # noqa: BLE001 - the log is a bonus; it must never hide the real failure
            logger.warning("The log of the failed container could not be read", exc_info=True)
            return ""

    # ------------------------------------------------------------------ Steps

    def _begin(self, deployment: Deployment) -> None:
        """Note what runs now and keep its image under a name of its own."""
        current = self.docker.container()
        if current is not None:
            deployment.previous_container_id = current.id
            deployment.previous_running = current.running
            deployment.previous_image_id = current.image_id
            deployment.previous_image_ref = current.image_ref
            self._keep_previous(deployment)
            note = f"running {current.image_ref} ({short_id(current.image_id)}); deploying tag {deployment.tag}"
        else:
            note = f"no worker container yet; deploying tag {deployment.tag}"
        self._advance(deployment, Phase.PULLING, note)

    def _keep_previous(self, deployment: Deployment) -> None:
        ref = deployment.previous_image_ref or ""
        if not ref or ref.startswith("sha256:"):
            # A container made from a bare image ID has no name to derive "previous" from.
            return
        name, _ = split_image_ref(ref)
        kept = f"{name}:{PREVIOUS_TAG}"
        stale = self.docker.image_id(kept)
        if stale and stale != deployment.previous_image_id:
            deployment.stale_image_id = stale
        self.docker.tag(deployment.previous_image_id, kept)

    def _pull(self, deployment: Deployment) -> None:
        result = self.docker.pull(deployment.tag)
        if not result.ok:
            self._finish(
                deployment,
                Outcome.FAILED,
                FailureKind.PULL_FAILED,
                f"docker compose pull failed: {result.tail()}. The running container was not touched.",
            )
            return
        try:
            reference = self.docker.image_ref(deployment.tag)
            image_id = self.docker.image_id(reference)
        except DockerError as exc:
            self._finish(
                deployment,
                Outcome.FAILED,
                FailureKind.PULL_FAILED,
                f"{exc}. The running container was not touched.",
            )
            return
        if image_id is None:
            self._finish(
                deployment,
                Outcome.FAILED,
                FailureKind.PULL_FAILED,
                f"image {reference} is not on this host after the pull. The running container was not touched.",
            )
            return
        deployment.target_image_ref = reference
        deployment.target_image_id = image_id
        self._advance(deployment, Phase.DRAINING, f"pulled {reference} ({short_id(image_id)})")

    def _drain(self, deployment: Deployment) -> None:
        if self.settings.drain_enabled:
            logger.warning("Draining is not implemented in this version; deployment %s swaps without it", deployment.id)
        self._advance(deployment, Phase.SWAPPING)

    def _swap(self, deployment: Deployment) -> None:
        current = self.docker.container()

        # A step that is repeated after a stop: the container was already replaced before the record was saved.
        if (
            current is not None
            and deployment.previous_container_id
            and current.id != deployment.previous_container_id
            and current.image_id == deployment.target_image_id
        ):
            deployment.new_container_id = current.id
            self._advance(deployment, Phase.VERIFYING, "the container was already replaced")
            return

        result = self.docker.up(deployment.tag)
        after = self.docker.container()

        if not result.ok:
            if after is not None and after.id == deployment.previous_container_id and after.running:
                self._finish(
                    deployment,
                    Outcome.FAILED,
                    FailureKind.SWAP_FAILED,
                    f"docker compose up failed: {result.tail()}. The previous container is still running.",
                )
                return
            deployment.failure_logs = self._capture_logs()
            self._fail_over(deployment, FailureKind.SWAP_FAILED, f"docker compose up failed: {result.tail()}")
            return

        if after is None:
            self._fail_over(deployment, FailureKind.SWAP_FAILED, "there is no worker container after docker compose up")
            return

        # Compose found nothing to change. Only a container that already ran counts as unchanged: a stopped one that
        # Compose just started still has to be checked.
        if (
            after.id == deployment.previous_container_id
            and after.image_id == deployment.target_image_id
            and deployment.previous_running
        ):
            self._finish(
                deployment, Outcome.UNCHANGED, message=f"the container already runs {deployment.target_image_ref}"
            )
            return

        deployment.new_container_id = after.id
        self._advance(deployment, Phase.VERIFYING, f"started container {after.id[:12]}")

    def _verify(self, deployment: Deployment) -> None:
        result = verify_container(
            self.docker,
            self.settings,
            expected_image_id=deployment.target_image_id,
            timeout_s=self.settings.verify_timeout_s,
            clock=self._clock,
            sleep=self._sleep,
            should_stop=self._should_stop,
        )
        if result.ok:
            self._succeed(deployment)
            return
        deployment.failure_logs = self._capture_logs()
        self._fail_over(deployment, FailureKind.VERIFY_FAILED, result.reason)

    def _succeed(self, deployment: Deployment) -> None:
        # The image that "previous" pointed to before this deployment is now two versions old.
        stale = deployment.stale_image_id
        if stale and stale not in (deployment.previous_image_id, deployment.target_image_id):
            self.docker.remove_image(stale)
        self._finish(deployment, Outcome.SUCCEEDED, message=f"now running {deployment.target_image_ref}")

    def _rollback(self, deployment: Deployment) -> None:
        result = restore_previous(
            self.docker,
            self.settings,
            deployment,
            clock=self._clock,
            sleep=self._sleep,
            should_stop=self._should_stop,
        )
        if result.ok:
            self._finish(
                deployment,
                Outcome.ROLLED_BACK,
                deployment.failure,
                f"{deployment.message}. Rolled back to {deployment.previous_image_ref} "
                f"({short_id(deployment.previous_image_id)}).",
            )
        else:
            self._finish(
                deployment,
                Outcome.FAILED,
                FailureKind.ROLLBACK_FAILED,
                f"{deployment.message}. The rollback failed too: {result.reason}.",
            )
