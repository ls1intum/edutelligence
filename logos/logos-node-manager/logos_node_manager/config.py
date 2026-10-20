"""Settings of the node manager.

Everything comes from environment variables with the prefix ``NODE_MANAGER_``. The defaults match the layout the
deploy workflows create on a worker host: the compose project in ``/opt/logos-workernode`` with the worker service
and container ``logos-workernode``.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
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

    # Reserved for the drain phase. The phase exists in the record, but this version only logs that it is skipped.
    drain_enabled: bool
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
            log_level=_text(env, "LOG_LEVEL", "INFO").upper(),
        )
