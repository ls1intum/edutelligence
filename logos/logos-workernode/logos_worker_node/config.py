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
        _config_path = None
        return _config

    resolved = resolved.resolve()
    logger.info("Loading config from %s", resolved)
    with open(resolved, "r", encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    _config = AppConfig(**raw)
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
