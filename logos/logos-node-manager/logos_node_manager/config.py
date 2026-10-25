"""Settings of the node manager.

Everything comes from environment variables with the prefix ``NODE_MANAGER_``. The defaults match the layout the
deploy workflows create on a worker host: the compose project in ``/opt/logos-workernode`` with the worker service
and container ``logos-workernode``.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

PREFIX = "NODE_MANAGER_"

_TRUE = {"1", "true", "yes", "on"}


def _seconds(environ: Mapping[str, str], name: str, default: float, *, allow_zero: bool = False) -> float:
    """A number of seconds from the environment.

    A missing, malformed or out-of-range value falls back to ``default``: a bad override must neither stop the manager
    at start nor silently switch a timeout off.
    """
    raw = environ.get(PREFIX + name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    if value > 0 or (allow_zero and value == 0):
        return value
    return default


def _text(environ: Mapping[str, str], name: str, default: str) -> str:
    raw = environ.get(PREFIX + name)
    return raw.strip() if raw and raw.strip() else default


def _flag(environ: Mapping[str, str], name: str, default: bool) -> bool:
    raw = environ.get(PREFIX + name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in _TRUE


def compose_project_name(project_dir: Path) -> str:
    """The project name Compose derives from the directory of the compose file.

    The manager passes it explicitly, so it finds the containers that a plain ``docker compose`` on the host created.
    """
    name = re.sub(r"[^a-z0-9_-]", "", project_dir.name.lower())
    return name or "logos-workernode"


@dataclass(frozen=True)
class Settings:
    """What the manager needs to know about its host."""

    # The compose project of the worker. The directory is mounted at the same path as on the host, because Compose
    # turns relative bind mounts into absolute host paths before it sends them to the Docker engine.
    project_dir: Path
    compose_file: Path
    env_file: Path
    project_name: str
    service: str
    container: str
    state_dir: Path

    # Timeouts in seconds.
    pull_timeout_s: float
    swap_timeout_s: float
    verify_timeout_s: float
    rollback_verify_timeout_s: float
    # How long the container must stay healthy, without a restart, before a deployment counts as done.
    stability_window_s: float
    poll_interval_s: float
    loop_interval_s: float

    # Whether a deployment drains the node before it replaces the container. Off switches the whole drain phase off,
    # so it is also the way to deploy as before if the orchestrator misbehaves.
    drain_enabled: bool
    # The orchestrator cordons the node and says when its requests are done. The node authenticates with the key of the
    # worker, so it can only cordon itself. Without both values a deployment cannot drain and swaps at once.
    orchestrator_url: str
    node_key: str = field(repr=False)
    # Time limits of the drain, in seconds. The drain limit starts when the cordon is granted. The turn limit covers the
    # wait for the cordon while another node is being replaced. The retry window is how long an unreachable
    # orchestrator is asked again before the drain is skipped. The reconnect limit is how long the replaced worker may
    # take to show up at the orchestrator.
    drain_timeout_s: float
    turn_timeout_s: float
    orchestrator_retry_window_s: float
    orchestrator_timeout_s: float
    reconnect_timeout_s: float
    log_level: str

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if environ is None else environ
        project_dir = Path(_text(env, "PROJECT_DIR", "/opt/logos-workernode"))
        return cls(
            project_dir=project_dir,
            compose_file=Path(_text(env, "COMPOSE_FILE", str(project_dir / "docker-compose.yml"))),
            env_file=Path(_text(env, "ENV_FILE", str(project_dir / ".env"))),
            project_name=_text(env, "PROJECT_NAME", compose_project_name(project_dir)),
            service=_text(env, "SERVICE", "logos-workernode"),
            container=_text(env, "CONTAINER", "logos-workernode"),
            state_dir=Path(_text(env, "STATE_DIR", str(project_dir / "node-manager"))),
            pull_timeout_s=_seconds(env, "PULL_TIMEOUT_S", 1800.0),
            swap_timeout_s=_seconds(env, "SWAP_TIMEOUT_S", 300.0),
            verify_timeout_s=_seconds(env, "VERIFY_TIMEOUT_S", 600.0),
            rollback_verify_timeout_s=_seconds(env, "ROLLBACK_VERIFY_TIMEOUT_S", 300.0),
            stability_window_s=_seconds(env, "STABILITY_WINDOW_S", 60.0, allow_zero=True),
            poll_interval_s=_seconds(env, "POLL_INTERVAL_S", 5.0),
            loop_interval_s=_seconds(env, "LOOP_INTERVAL_S", 2.0),
            drain_enabled=_flag(env, "DRAIN_ENABLED", False),
            orchestrator_url=_text(env, "ORCHESTRATOR_URL", "").rstrip("/"),
            node_key=_text(env, "NODE_KEY", ""),
            drain_timeout_s=_seconds(env, "DRAIN_TIMEOUT_S", 900.0),
            turn_timeout_s=_seconds(env, "TURN_TIMEOUT_S", 7200.0),
            orchestrator_retry_window_s=_seconds(env, "ORCHESTRATOR_RETRY_WINDOW_S", 120.0),
            orchestrator_timeout_s=_seconds(env, "ORCHESTRATOR_TIMEOUT_S", 15.0),
            reconnect_timeout_s=_seconds(env, "RECONNECT_TIMEOUT_S", 300.0),
            log_level=_text(env, "LOG_LEVEL", "INFO").upper(),
        )
