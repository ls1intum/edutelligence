"""Start the previous version again.

The manager notes the image of the running container when a deployment starts, and keeps it under the name
``<image>:previous`` just before it replaces the container. A pull moves a tag such as ``latest`` to the new image, so
without this the old image would have no name once its container is gone. The rollback does not need the registry: the
old image is already on the host, and the record holds its ID.
"""

from __future__ import annotations

import logging
import time
from typing import Callable

from logos_node_manager.config import Settings
from logos_node_manager.docker_ops import Docker, split_image_ref
from logos_node_manager.errors import DockerError, Interrupted
from logos_node_manager.state import Deployment
from logos_node_manager.verify import VerifyResult, verify_container

logger = logging.getLogger(__name__)

# A replacement of the container that was cut off, for example by a timeout, can leave containers behind that make the
# next ``up`` fail with a name conflict. That attempt already clears part of them, so a new attempt after a short pause
# usually works. The pause grows with each attempt.
ROLLBACK_ATTEMPTS = 3
ROLLBACK_PAUSE_S = 5.0


def restore_previous(
    docker: Docker,
    settings: Settings,
    deployment: Deployment,
    *,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    should_stop: Callable[[], bool] = lambda: False,
) -> VerifyResult:
    """Recreate the container from the image that ran before, and check that it runs.

    Every step can be repeated, so a rollback that was cut short can run again from the start. If the recreation
    fails, it is tried again, up to ``ROLLBACK_ATTEMPTS`` attempts in all.
    """
    if not deployment.previous_image_id:
        return VerifyResult(False, "there is no previous version to restore")

    # Compose starts the image that its own reference names. Point that reference at the old image again, then let
    # Compose recreate the container without a pull, which would fetch the new image again.
    _, previous_tag = split_image_ref(deployment.previous_image_ref or "")
    tag = previous_tag or "latest"
    problem = ""
    for attempt in range(1, ROLLBACK_ATTEMPTS + 1):
        if attempt > 1:
            if should_stop():
                raise Interrupted()
            sleep(ROLLBACK_PAUSE_S * (attempt - 1))
        try:
            reference = docker.image_ref(tag)
            docker.tag(deployment.previous_image_id, reference)
        except DockerError as exc:
            problem = str(exc)
        else:
            result = docker.up(tag, recreate=True, pull_never=True)
            if result.ok:
                break
            problem = f"docker compose up failed: {result.tail()}"
        logger.warning(
            "Deployment %s: attempt %d of %d to restore the previous version failed: %s",
            deployment.id,
            attempt,
            ROLLBACK_ATTEMPTS,
            problem,
        )
    else:
        return VerifyResult(False, f"{problem} (after {ROLLBACK_ATTEMPTS} attempts)")

    return verify_container(
        docker,
        settings,
        expected_image_id=deployment.previous_image_id,
        timeout_s=settings.rollback_verify_timeout_s,
        clock=clock,
        sleep=sleep,
        should_stop=should_stop,
    )
