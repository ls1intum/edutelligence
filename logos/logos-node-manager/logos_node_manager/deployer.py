"""The deployment: pull, swap, verify, and roll back if the new container does not come up.

A deployment moves through the phases of ``Phase``. Every step is safe to repeat, and the record is saved when the
phase changes. If the manager stops in the middle, for example because Docker recreates its own container, the next
start picks the record up and works out from the phase and from what Docker shows where to continue.

Images are removed when the deployment has ended and not earlier: until then a rollback may still need them.

In the ``draining`` phase the manager asks the orchestrator to cordon the node, so that it gets no new requests, and
waits until the requests that run have finished. Only one node at a time gets the cordon: another node waits for its
turn. The cordon is held until the deployment ends and then given back, whatever the outcome. Without an orchestrator to
ask, or with the drain switched off, the phase passes at once and the container is replaced as before.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Callable, TypeVar

from logos_node_manager.config import Settings
from logos_node_manager.docker_ops import Docker, split_image_ref
from logos_node_manager.errors import DockerError, Interrupted
from logos_node_manager.orchestrator import CordonReply, OrchestratorClient, OrchestratorUnavailable
from logos_node_manager.rollback import restore_previous
from logos_node_manager.state import (
    MAX_EVENTS,
    PREVIOUS_TAG,
    Deployment,
    FailureKind,
    Outcome,
    Phase,
    StateStore,
    utc_now,
)
from logos_node_manager.verify import VerifyResult, verify_container

logger = logging.getLogger(__name__)

# The saved log of a failed container is limited, so the record stays small.
MAX_LOG_CHARS = 6000
# A record holds at most MAX_EVENTS events. The wait for the drain adds one at most this often, and only if it changed.
PROGRESS_EVENT_EVERY_S = 30.0

_T = TypeVar("_T")


def short_id(image_id: str | None) -> str:
    """The short form of an image ID, as ``docker images`` prints it."""
    return (image_id or "none").removeprefix("sha256:")[:12]


class _Budget:
    """A time limit that survives a restart of the manager.

    The part used before the restart is read from the time saved in the record. The part after it is counted with the
    clock of the deployer.
    """

    def __init__(self, deployer: "Deployer", limit_s: float, started: str | None) -> None:
        self.limit_s = limit_s
        self._clock = deployer._clock
        self._used_before = deployer._seconds_since(started)
        self._begun = self._clock()

    def used(self) -> float:
        return self._used_before + (self._clock() - self._begun)

    def exhausted(self) -> bool:
        return self.used() >= self.limit_s


class Deployer:
    def __init__(
        self,
        settings: Settings,
        docker: Docker,
        store: StateStore,
        *,
        orchestrator: OrchestratorClient | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], str] = utc_now,
        should_stop: Callable[[], bool] = lambda: False,
    ) -> None:
        self.settings = settings
        self.docker = docker
        self.store = store
        self.orchestrator = orchestrator
        self._clock = clock
        self._sleep = sleep
        self._now = now
        self._should_stop = should_stop
        # The last line the wait for the drain recorded, and when. Keeps the record from filling with polls.
        self._last_progress: tuple[str, float] | None = None

    # ------------------------------------------------------------------ Driver

    def process(self, deployment: Deployment) -> Deployment:
        """Run the deployment to its end and clean up. Raises ``Interrupted`` if the daemon is asked to stop first."""
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
        self._clean_up(deployment)
        return deployment

    def give_up(self, deployment: Deployment, error: Exception) -> None:
        """End the attempts after the manager itself failed again and again in the phase of the record.

        Before the swap nothing was replaced, so the deployment just fails. From the swap on, the worker may run an
        image that nobody checked, so the previous version is restored first. The rollback gets attempts of its own.
        If it fails as well, the deployment ends as a failed rollback and every image stays.
        """
        reason = f"the node manager failed {deployment.attempts} times: {error}"
        logger.warning("Deployment %s: giving up in phase %s: %s", deployment.id, deployment.phase.value, reason)
        if deployment.phase is Phase.ROLLING_BACK:
            self._finish(
                deployment,
                Outcome.FAILED,
                FailureKind.ROLLBACK_FAILED,
                f"{deployment.message}. The rollback failed too: {reason}.",
            )
        elif deployment.phase in (Phase.SWAPPING, Phase.VERIFYING):
            deployment.failure_logs = self._capture_logs()
            self._fail_over(deployment, FailureKind.INTERNAL_ERROR, reason)
        else:
            self._finish(deployment, Outcome.FAILED, FailureKind.INTERNAL_ERROR, reason)

    # ------------------------------------------------------------------ Record helpers

    def _event(self, deployment: Deployment, note: str) -> None:
        if note:
            logger.info("Deployment %s (%s): %s", deployment.id, deployment.phase.value, note)
        deployment.events.append({"at": self._now(), "phase": deployment.phase.value, "note": note})
        del deployment.events[:-MAX_EVENTS]

    def _advance(self, deployment: Deployment, phase: Phase, note: str = "") -> None:
        deployment.phase = phase
        # A new phase is progress, so errors of the phase before do not count against this one. This also gives a
        # rollback that starts after repeated errors attempts of its own.
        deployment.attempts = 0
        self._event(deployment, note)
        self.store.save(deployment)

    def _finish(
        self, deployment: Deployment, outcome: Outcome, failure: FailureKind | None = None, message: str = ""
    ) -> None:
        # Before the record says it is over: a stop in between then repeats this step instead of losing the release.
        self._release_cordon(deployment)
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
        """Note what runs now."""
        current = self.docker.container()
        if current is not None:
            deployment.previous_container_id = current.id
            deployment.previous_running = current.running
            deployment.previous_image_id = current.image_id
            deployment.previous_image_ref = current.image_ref
            note = f"running {current.image_ref} ({short_id(current.image_id)}); deploying tag {deployment.tag}"
        else:
            note = f"no worker container yet; deploying tag {deployment.tag}"
        self._advance(deployment, Phase.PULLING, note)

    def _keep_previous(self, deployment: Deployment) -> None:
        """Give the image of the running container the name ``<image>:previous``, just before its container goes.

        A pull can move the tag of that image to the new one. Without a name of its own the old image would be a plain
        unnamed image once its container is gone, and ``docker image prune`` takes those. The name moves only here, so
        a deployment that ends before the swap leaves every name as it was.
        """
        previous = deployment.previous_image_id
        ref = deployment.previous_image_ref or ""
        if not previous or previous == deployment.target_image_id:
            # There was no container, or the container keeps its image.
            return
        if not ref or ref.startswith("sha256:"):
            # A container made from a bare image ID has no name to derive "previous" from.
            return
        name, _ = split_image_ref(ref)
        kept = f"{name}:{PREVIOUS_TAG}"
        held = self.docker.image_id(kept)
        if held == previous:
            # An earlier run of this step already moved the name.
            return
        if held:
            # The image that loses the name is removed when the deployment ends. The record is saved before the name
            # moves, so that a stop in between does not lose track of it.
            deployment.stale_image_id = held
            self.store.save(deployment)
        self.docker.tag(previous, kept)

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
        """Cordon the node at the orchestrator and wait until the requests that run on it are done.

        The cordon is held until the deployment ends. If the orchestrator cannot be asked, the deployment goes on
        without a drain: an orchestrator problem must not stop the deployments that may repair it.
        """
        if not self.settings.drain_enabled:
            self._advance(deployment, Phase.SWAPPING)
            return
        client = self.orchestrator
        if client is None:
            self._advance(
                deployment, Phase.SWAPPING, "draining skipped: the manager has no orchestrator address or node key"
            )
            return
        try:
            drained = self._wait_for_drain(deployment, client)
        except OrchestratorUnavailable as exc:
            logger.warning("Deployment %s: draining skipped: %s", deployment.id, exc)
            self._advance(deployment, Phase.SWAPPING, f"draining skipped: {exc}")
            return
        if drained:
            self._advance(deployment, Phase.SWAPPING, "the node has drained; replacing the container")

    def _wait_for_drain(self, deployment: Deployment, client: OrchestratorClient) -> bool:
        """Ask for the cordon until the node has drained. False if the deployment ended instead.

        Every call asks for the cordon again, which the orchestrator answers with the state of the node. That is also
        what renews the cordon, and what takes it again if the orchestrator forgot it, for example after a restart.
        The limits count from times saved in the record, so a restart of the manager does not extend them.
        """
        self._last_progress = None
        if deployment.drain_requested_at is None:
            deployment.drain_requested_at = self._now()
            self.store.save(deployment)
        turn = _Budget(self, self.settings.turn_timeout_s, deployment.drain_requested_at)
        drain = _Budget(self, self.settings.drain_timeout_s, deployment.cordoned_at) if deployment.cordoned_at else None
        while True:
            self._check_stop()
            reply = self._ask(lambda: client.cordon(deployment.id))
            if not reply.granted:
                if deployment.cordoned_at is not None:
                    # The orchestrator forgot the cordon and another node holds it now.
                    self._event(deployment, "the cordon was lost; waiting for the turn of the node again")
                    deployment.cordoned_at = None
                    deployment.drain_requested_at = self._now()
                    drain = None
                    turn = _Budget(self, self.settings.turn_timeout_s, deployment.drain_requested_at)
                    self.store.save(deployment)
                why = self._why_denied(reply)
                if turn.exhausted():
                    self._finish(
                        deployment,
                        Outcome.FAILED,
                        FailureKind.DRAIN_BLOCKED,
                        f"the node did not get its turn within {int(turn.limit_s)} s: {why}. "
                        "The running container was not touched.",
                    )
                    return False
                self._progress(deployment, f"waiting for its turn: {why}")
                self._pause()
                continue

            if deployment.cordoned_at is None:
                deployment.cordoned_at = self._now()
                deployment.sole_replica_models = list(reply.sole_replica_models)
                drain = _Budget(self, self.settings.drain_timeout_s, deployment.cordoned_at)
                self._event(deployment, self._cordon_note(reply))
                self.store.save(deployment)

            if reply.drained:
                deployment.drained_at = self._now()
                # The worker session that goes away with the old container. The new container shows up as another one.
                deployment.session_before = reply.session_id
                self._event(deployment, f"the node has drained after {int(drain.used())} s")
                return True
            if drain.exhausted():
                self._finish(
                    deployment,
                    Outcome.FAILED,
                    FailureKind.DRAIN_TIMEOUT,
                    f"the node did not drain within {int(drain.limit_s)} s: {self._in_flight_text(reply)} "
                    "still running. The cordon was lifted and the running container was not touched.",
                )
                return False
            self._progress(deployment, f"waiting for the node to drain: {self._in_flight_text(reply)} running")
            self._pause()

    @staticmethod
    def _why_denied(reply: CordonReply) -> str:
        if reply.reason == "another_node_in_maintenance":
            return f"{reply.holder or 'another node'} is being replaced"
        if reply.reason == "calibrating":
            return "the node runs a calibration session"
        return reply.reason or "the orchestrator did not grant the cordon"

    @staticmethod
    def _in_flight_text(reply: CordonReply) -> str:
        total = reply.in_flight_orchestrator + reply.in_flight_worker
        return (
            f"{total} request(s) ({reply.in_flight_orchestrator} tracked by the orchestrator, "
            f"{reply.in_flight_worker} on the worker)"
        )

    @staticmethod
    def _cordon_note(reply: CordonReply) -> str:
        if reply.sole_replica_models:
            return (
                "cordoned the node at the orchestrator; no other node serves "
                f"{', '.join(reply.sole_replica_models)}, so requests for them wait until this node is back"
            )
        return "cordoned the node at the orchestrator"

    def _progress(self, deployment: Deployment, text: str) -> None:
        """Record a line about the wait, unless it repeats the last one or came too soon after it."""
        now = self._clock()
        last = self._last_progress
        if last is not None and (last[0] == text or now - last[1] < PROGRESS_EVENT_EVERY_S):
            return
        self._last_progress = (text, now)
        self._event(deployment, text)
        self.store.save(deployment)

    def _ask(self, call: Callable[[], _T], *, stoppable: bool = True) -> _T:
        """Run a call to the orchestrator, asking again while it cannot be reached.

        Raises ``OrchestratorUnavailable`` when the retry window is over, or at once for an answer that asking again
        will not change.
        """
        started = self._clock()
        while True:
            try:
                return call()
            except OrchestratorUnavailable as exc:
                if not exc.retryable or self._clock() - started >= self.settings.orchestrator_retry_window_s:
                    raise
                logger.warning("The orchestrator did not answer (%s); asking again", exc)
                if stoppable:
                    self._check_stop()
                self._pause()

    def _pause(self) -> None:
        self._sleep(self.settings.poll_interval_s)

    def _check_stop(self) -> None:
        if self._should_stop():
            raise Interrupted()

    def _seconds_since(self, stamp: str | None) -> float:
        """Seconds from a time saved in a record to now; 0 if there is none or it cannot be read."""
        if not stamp:
            return 0.0
        try:
            return max(0.0, (datetime.fromisoformat(self._now()) - datetime.fromisoformat(stamp)).total_seconds())
        except ValueError:
            return 0.0

    def _release_cordon(self, deployment: Deployment) -> None:
        """Give the cordon back. Every ending passes here; a deployment that never held the cordon does nothing."""
        client = self.orchestrator
        if client is None or deployment.cordoned_at is None or deployment.cordon_released_at is not None:
            return
        try:
            self._ask(lambda: client.release(deployment.id), stoppable=False)
        except OrchestratorUnavailable as exc:
            # The orchestrator lets a cordon go when the manager stops renewing it.
            logger.warning("Deployment %s: the cordon could not be given back (%s); it expires", deployment.id, exc)
        deployment.cordon_released_at = self._now()

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

        self._keep_previous(deployment)
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
            result = self._await_reconnect(deployment)
        if result.ok:
            self._succeed(deployment)
            return
        deployment.failure_logs = self._capture_logs()
        self._fail_over(deployment, FailureKind.VERIFY_FAILED, result.reason)

    def _await_reconnect(self, deployment: Deployment) -> VerifyResult:
        """Wait until the orchestrator sees the new worker: connected through a new session, with its first status.

        Docker cannot show this. A worker that starts and answers on its port but cannot register at the orchestrator
        would otherwise count as a success. Only a deployment that drained the node checks it, because only then the
        manager knows the session of the old worker. If the orchestrator cannot be asked, the check is skipped: not
        seeing the node is no proof that the new container is bad.
        """
        client = self.orchestrator
        if client is None or deployment.cordoned_at is None or deployment.cordon_released_at is not None:
            return VerifyResult(True)
        started = self._clock()
        while True:
            self._check_stop()
            try:
                node = self._ask(lambda: client.status(deployment.id))
            except OrchestratorUnavailable as exc:
                logger.warning("Deployment %s: the connection of the worker was not checked: %s", deployment.id, exc)
                self._event(deployment, f"the connection of the worker to the orchestrator was not checked: {exc}")
                return VerifyResult(True)
            if node.online and node.first_status_received and node.session_id != deployment.session_before:
                self._event(deployment, "the worker is connected to the orchestrator")
                return VerifyResult(True)
            if self._clock() - started >= self.settings.reconnect_timeout_s:
                return VerifyResult(
                    False,
                    f"the worker did not connect to the orchestrator within {int(self.settings.reconnect_timeout_s)} s",
                )
            self._pause()

    def _succeed(self, deployment: Deployment) -> None:
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

    # ------------------------------------------------------------------ Clean-up

    def _clean_up(self, deployment: Deployment) -> None:
        """Remove the images that this deployment leaves without a purpose.

        These are the image that the name ``previous`` pointed to before (now two versions old) and the image that was
        pulled but does not run. An image that a container uses, or that is the previous version, stays. After a failed
        rollback every image stays, because a person may need them to repair the host.

        The record is already saved when this runs. A problem here is logged and does not change the result.
        """
        if deployment.failure is FailureKind.ROLLBACK_FAILED:
            logger.info("Deployment %s: the images stay on the host because the rollback failed", deployment.id)
            return
        removed = []
        try:
            current = self.docker.container()
            needed = {deployment.previous_image_id, current.image_id if current else None}
            for image_id in dict.fromkeys((deployment.stale_image_id, deployment.target_image_id)):
                if image_id and image_id not in needed and self.docker.remove_image(image_id):
                    removed.append(short_id(image_id))
        except Exception:  # noqa: BLE001 - the deployment is over; a clean-up problem must not change its result
            logger.warning(
                "Deployment %s: the clean-up failed; images may stay on the host", deployment.id, exc_info=True
            )
            return
        logger.info(
            "Deployment %s: clean-up finished, %s",
            deployment.id,
            f"removed {', '.join(removed)}" if removed else "nothing removed",
        )
