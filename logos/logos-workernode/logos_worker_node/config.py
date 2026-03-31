"""Configuration loading and persistence for LogosWorkerNode."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml

from logos_worker_node.models import AppConfig, LaneConfig

logger = logging.getLogger("logos_worker_node.config")

_config: AppConfig | None = None
_config_path: Path | None = None


def get_config() -> AppConfig:
    if _config is None:
        raise RuntimeError("Configuration not loaded — call load_config() first")
    return _config


def get_config_path() -> Path | None:
    """Return the resolved path of the loaded config file, or None."""
    return _config_path


def _apply_env_overrides(cfg: AppConfig) -> None:
    """Apply LOGOS_* environment variable overrides to the logos bridge config.

    Environment variables take precedence over config.yml values.  Set these
    in .env (see .env.example) so that connection credentials are never stored
    in the config file:

      LOGOS_URL              — Logos server base URL, e.g. https://logos.example.com
      LOGOS_PROVIDER_ID      — Numeric provider ID issued during registration
      LOGOS_API_KEY          — Provider API key (shared_key) issued during registration
      LOGOS_WORKER_NODE_ID   — Optional worker identifier (defaults to worker-<id>)
    """
    logos_url = os.getenv("LOGOS_URL", "").strip()
    if logos_url:
        cfg.logos.logos_url = logos_url
        cfg.logos.enabled = True

    provider_id_str = os.getenv("LOGOS_PROVIDER_ID", "").strip()
    if provider_id_str:
        try:
            cfg.logos.provider_id = int(provider_id_str)
        except ValueError as exc:
            raise RuntimeError(
                f"LOGOS_PROVIDER_ID must be an integer, got: {provider_id_str!r}"
            ) from exc

    api_key = os.getenv("LOGOS_API_KEY", "").strip()
    if api_key:
        cfg.logos.shared_key = api_key

    worker_id = os.getenv("LOGOS_WORKER_NODE_ID", "").strip()
    if worker_id:
        cfg.logos.worker_id = worker_id

    if os.getenv("LOGOS_ALLOW_INSECURE_HTTP", "").strip().lower() in {"1", "true", "yes"}:
        cfg.logos.allow_insecure_http = True


def load_config(path: str | Path | None = None) -> AppConfig:
    global _config, _config_path

    if path is not None:
        resolved = Path(path)
    elif env := os.environ.get("LOGOS_WORKER_NODE_CONFIG"):
        resolved = Path(env)
    elif Path("config.yml").exists():
        resolved = Path("config.yml")
    elif Path("../config.yml").exists():
        resolved = Path("../config.yml")
    else:
        logger.warning("No config file found — using defaults")
        _config = AppConfig()
        _apply_env_overrides(_config)
        _config_path = None
        return _config

    resolved = resolved.resolve()
    logger.info("Loading config from %s", resolved)
    with open(resolved, "r", encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    _config = AppConfig(**raw)
    _apply_env_overrides(_config)
    _config_path = resolved
    return _config


def save_config(config: AppConfig | None = None) -> None:
    global _config

    if config is not None:
        _config = config

    cfg = get_config()
    if _config_path is None:
        raise RuntimeError("Cannot save — config was never loaded from a file")

    data = cfg.model_dump(mode="json", exclude_none=True)
    with open(_config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)
        f.flush()
        os.fsync(f.fileno())

    logger.info("Config saved to %s", _config_path)


def save_lanes_config(lanes: list[LaneConfig]) -> None:
    cfg = get_config()
    cfg.lanes = lanes
    save_config(cfg)
