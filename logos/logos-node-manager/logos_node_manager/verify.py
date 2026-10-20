"""Is the new container up?

The checks use what Docker can see from outside the container: that it runs, that its health check passes, that it
does not restart, and that it runs the image the deployment expects. The health check of the worker only shows that the
worker started and answers on its port. It does not show that the worker connected to the orchestrator or loaded its
models. The manager cannot ask the worker for that yet.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable

from logos_node_manager.config import Settings
from logos_node_manager.docker_ops import ContainerInfo, Docker
from logos_node_manager.errors import Interrupted

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    reason: str = ""


def _problem(info: ContainerInfo | None, expected_image_id: str | None) -> str | None:
    """Why the container is already known to be bad, or None if nothing is wrong yet."""
    if info is None:
        return "the container does not exist"
    if expected_image_id and info.image_id != expected_image_id:
        return "the container runs an unexpected image"
    if info.status in ("exited", "dead"):
        return f"the container exited with code {info.exit_code}"
    # A new container starts with a restart count of 0. The restart policy brings a crashing worker back, so a count
    # above 0 means it crashed during start up, even if it looks fine now.
    if info.restarting or info.restart_count > 0:
        return f"the container restarted {info.restart_count} time(s)"
    if info.health == "unhealthy":
        return "the health check reports the container as unhealthy"
    return None


def verify_container(
    docker: Docker,
    settings: Settings,
    *,
    expected_image_id: str | None,
    timeout_s: float,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    should_stop: Callable[[], bool] = lambda: False,
) -> VerifyResult:
    """Wait until the worker container is healthy, and stays so for the stability window.

    ``timeout_s`` limits the wait for the first healthy state. The stability window that follows is bounded by itself.
    """
    deadline = clock() + timeout_s
    healthy_since: float | None = None
    while True:
        if should_stop():
            raise Interrupted()
        info = docker.container()
        problem = _problem(info, expected_image_id)
        if problem:
            return VerifyResult(False, problem)

        # A container without a health check counts as ready as soon as it runs.
        if info.running and info.health in (None, "healthy"):
            now = clock()
            if healthy_since is None:
                healthy_since = now
            if now - healthy_since >= settings.stability_window_s:
                return VerifyResult(True)
        else:
            # Not ready (again): the stability window starts over once the container is ready.
            healthy_since = None
            if clock() >= deadline:
                return VerifyResult(False, f"the container was not healthy after {int(timeout_s)} s")
        sleep(settings.poll_interval_s)
