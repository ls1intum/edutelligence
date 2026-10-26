"""The long-running part of the manager.

The daemon takes the queued deployments from the state directory, oldest first and one at a time. It has no other
trigger: whoever wants a deployment writes a record with the command line, and the daemon finds it on its next pass.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from logos_node_manager import __version__
from logos_node_manager.config import Settings
from logos_node_manager.deployer import Deployer
from logos_node_manager.docker_ops import Docker, describe_registry_login
from logos_node_manager.errors import Interrupted
from logos_node_manager.state import Deployment, StateStore

logger = logging.getLogger(__name__)

# The heartbeat comes from its own thread, so ``ping`` still answers during a deployment that takes many minutes.
HEARTBEAT_INTERVAL_S = 5.0
# A phase is tried this many times in a row when the manager itself fails in it. After the last attempt the deployer
# decides how to end.
MAX_ATTEMPTS = 3
RETRY_DELAY_S = 10.0


class Daemon:
    def __init__(
        self,
        settings: Settings,
        store: StateStore,
        deployer: Deployer,
        stop: threading.Event,
        *,
        docker: Docker | None = None,
        registry_login_file: Path | None = None,
        retry_delay_s: float = RETRY_DELAY_S,
    ) -> None:
        self._settings = settings
        self._store = store
        self._deployer = deployer
        self._stop = stop
        self._docker = docker
        self._registry_login_file = registry_login_file
        self._retry_delay_s = retry_delay_s

    def run(self) -> None:
        """Process deployments until the stop event is set."""
        self._store.ensure()
        self._store.touch_heartbeat()
        beat = threading.Thread(target=self._heartbeat, name="heartbeat", daemon=True)
        beat.start()
        self._log_start()
        try:
            while not self._stop.is_set():
                self._report_endings()
                deployment = self._store.next_unfinished()
                if deployment is None:
                    self._stop.wait(self._settings.loop_interval_s)
                    continue
                self._process(deployment)
        finally:
            self._stop.set()
            beat.join(timeout=2.0)
        logger.info("Node manager stopped")

    def _report_endings(self) -> None:
        """Report the deployments that ended. A problem here never stops the deployments."""
        try:
            self._deployer.report_pending()
        except Interrupted:
            return
        except Exception:  # noqa: BLE001 - a notification must not stop the deployments
            logger.exception("The endings of the deployments could not be reported")

    def _heartbeat(self) -> None:
        while not self._stop.wait(HEARTBEAT_INTERVAL_S):
            try:
                self._store.touch_heartbeat()
            except OSError:
                logger.warning("The heartbeat file could not be written", exc_info=True)

    def _process(self, deployment: Deployment) -> None:
        logger.info(
            "Processing deployment %s (tag %s, phase %s)", deployment.id, deployment.tag, deployment.phase.value
        )
        try:
            self._deployer.process(deployment)
        except Interrupted:
            logger.info("Stopping. Deployment %s continues at the next start.", deployment.id)
            return
        except Exception as exc:  # noqa: BLE001 - one broken deployment must not stop the loop
            self._record_error(deployment, exc)
            return
        self._store.prune()

    def _record_error(self, deployment: Deployment, exc: Exception) -> None:
        """Count an unexpected error. The deployment is tried again, and after the last attempt the deployer ends it."""
        logger.exception("Deployment %s hit an unexpected error", deployment.id)
        record = self._store.load(deployment.id) or deployment
        record.attempts += 1
        if record.attempts >= MAX_ATTEMPTS:
            self._deployer.give_up(record, exc)
        else:
            self._store.save(record)
        if not record.finished:
            self._stop.wait(self._retry_delay_s * record.attempts)

    def _log_start(self) -> None:
        s = self._settings
        logger.info(
            "Node manager %s started: project %s in %s, service %s, container %s",
            __version__,
            s.project_name,
            s.project_dir,
            s.service,
            s.container,
        )
        if self._docker is not None:
            logger.info("Docker: %s", self._docker.versions())
        if self._registry_login_file is not None:
            logger.info("%s", describe_registry_login(self._registry_login_file))
        for path in (s.compose_file, s.env_file):
            if not path.is_file():
                logger.warning("%s does not exist; deployments fail until it does", path)
        if s.orchestrator_url and s.node_key:
            logger.info("The end of a deployment is reported to %s", s.orchestrator_url)
        else:
            logger.info(
                "NODE_MANAGER_ORCHESTRATOR_URL or NODE_MANAGER_NODE_KEY is missing: "
                "the end of a deployment is not reported"
            )
        if not s.drain_enabled:
            logger.info("Draining is switched off: a deployment replaces the container at once")
        elif s.orchestrator_url and s.node_key:
            logger.info(
                "Draining is enabled: the node is cordoned at %s before the container is replaced", s.orchestrator_url
            )
        else:
            logger.warning(
                "Draining is enabled, but NODE_MANAGER_ORCHESTRATOR_URL or NODE_MANAGER_NODE_KEY is missing: "
                "a deployment replaces the container without draining the node"
            )
