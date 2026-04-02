"""Configuration loading for LogosWorkerNode.

Two sources, zero overlap:
  config.yml  — hardware & tuning (managed by Ansible, mounted read-only)
  .env        — identity & credentials (managed by GitHub secrets/variables)

Runtime state (lanes, model profiles) persists in a separate data volume.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import yaml

from logos_worker_node.models import AppConfig, LaneConfig

logger = logging.getLogger("logos_worker_node.config")

_config: AppConfig | None = None

# Directory for runtime state (lane config, model profiles).
STATE_DIR = Path(os.getenv("LOGOS_STATE_DIR", "/app/data"))


def get_config() -> AppConfig:
    if _config is None:
        raise RuntimeError("Configuration not loaded — call load_config() first")
    return _config


def get_state_dir() -> Path:
    """Return the state directory, creating it if needed."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return STATE_DIR


# ── Env helpers ──────────────────────────────────────────────────────────────

def _getenv(name: str) -> str:
    return os.getenv(name, "").strip()


def _getenv_int(name: str) -> int | None:
    val = _getenv(name)
    if not val:
        return None
    try:
        return int(val)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer, got: {val!r}") from exc


def _getenv_bool(name: str) -> bool:
    return _getenv(name).lower() in {"1", "true", "yes"}


# ── Config loading ───────────────────────────────────────────────────────────

def _load_config_yml() -> AppConfig:
    """Load config.yml if present, otherwise return defaults."""
    config_path = os.environ.get("LOGOS_WORKER_NODE_CONFIG", "").strip()
    candidates = (
        [Path(config_path)] if config_path
        else [Path("/app/config.yml"), Path("config.yml")]
    )

    for path in candidates:
        resolved = path.resolve()
        if resolved.is_file():
            logger.info("Loading config from %s", resolved)
            with open(resolved, "r", encoding="utf-8") as f:
                raw: dict[str, Any] = yaml.safe_load(f) or {}
            return AppConfig(**raw)

    logger.info("No config.yml found — using defaults (all tuning via env or defaults)")
    return AppConfig()


def _apply_env_overrides(cfg: AppConfig) -> None:
    """Apply .env overrides — credentials only.

    These are the ONLY values that come from .env (GitHub secrets/variables).
    Hardware and tuning settings live in config.yml (Ansible).
    Identity (provider_id, worker_id) is resolved by the server from the API key.
    """
    logos_url = _getenv("LOGOS_URL")
    if logos_url:
        cfg.logos.logos_url = logos_url
        cfg.logos.enabled = True

    api_key = _getenv("LOGOS_API_KEY")
    if api_key:
        cfg.logos.shared_key = api_key

    if _getenv_bool("LOGOS_ALLOW_INSECURE_HTTP"):
        cfg.logos.allow_insecure_http = True


def load_config() -> AppConfig:
    """Load config.yml (hardware/tuning), then apply .env overrides (credentials)."""
    global _config

    _config = _load_config_yml()
    _apply_env_overrides(_config)

    # Restore persisted lanes from state file if present
    lanes_path = get_state_dir() / "lanes.json"
    if lanes_path.exists() and not _config.lanes:
        try:
            with lanes_path.open("r", encoding="utf-8") as f:
                lanes_data = json.load(f)
            _config.lanes = [LaneConfig(**item) for item in lanes_data]
            logger.info("Restored %d lane(s) from %s", len(_config.lanes), lanes_path)
        except Exception:
            logger.debug("Failed to restore lanes from %s", lanes_path, exc_info=True)

    return _config


def save_lanes_state(lanes: list[LaneConfig]) -> None:
    """Persist lane configuration to the state directory."""
    try:
        state_dir = get_state_dir()
        lanes_path = state_dir / "lanes.json"
        data = [lane.model_dump(mode="json", exclude_none=True) for lane in lanes]
        with lanes_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        logger.info("Lane state saved to %s", lanes_path)
    except OSError:
        logger.debug("Could not persist lane state", exc_info=True)
