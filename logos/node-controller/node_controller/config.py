"""
Configuration loading, saving, and runtime management.

Loads from config.yml, supports partial updates with file writes,
and determines whether a config change requires a process restart.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml

from node_controller.models import AppConfig, LaneConfig, OllamaConfig

logger = logging.getLogger("node_controller.config")

# Fields that require Ollama process restart when changed
# (all of these become environment variables or process-level settings)
_RESTART_FIELDS: frozenset[str] = frozenset({
    "num_parallel",
    "max_loaded_models",
    "keep_alive",
    "max_queue",
    "context_length",
    "flash_attention",
    "kv_cache_type",
    "gpu_devices",
    "port",
    "env_overrides",
    "sched_spread",
    "multiuser_cache",
    "gpu_overhead_bytes",
    "load_timeout",
    "origins",
    "noprune",
    "llm_library",
})

# Global singleton — set by load_config()
_config: AppConfig | None = None
_config_path: Path | None = None


def get_config() -> AppConfig:
    """Return the current application config.  Raises if not loaded."""
    if _config is None:
        raise RuntimeError("Configuration not loaded — call load_config() first")
    return _config


def load_config(path: str | Path | None = None) -> AppConfig:
    """
    Load configuration from a YAML file.

    Resolution order:
      1. Explicit *path* argument
      2. ``NODE_CONTROLLER_CONFIG`` environment variable
      3. ``./config.yml`` (relative to cwd)
      4. ``../config.yml`` (for running inside ``node_controller/``)
    """
    global _config, _config_path

    if path is not None:
        resolved = Path(path)
    elif env := os.environ.get("NODE_CONTROLLER_CONFIG"):
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

    with open(resolved, "r") as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    _config = AppConfig(**raw)
    _config_path = resolved
    return _config


def save_config(config: AppConfig | None = None) -> None:
    """
    Persist the current (or provided) config to disk atomically.

    Uses a temp-file + rename to prevent corruption on crash.
    """
    global _config

    if config is not None:
        _config = config

    cfg = get_config()

    if _config_path is None:
        raise RuntimeError("Cannot save — config was never loaded from a file")

    data = cfg.model_dump(mode="json")

    with open(_config_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
        f.flush()
        os.fsync(f.fileno())

    logger.info("Config saved to %s", _config_path)


def apply_reconfigure(
    updates: dict[str, Any],
) -> tuple[OllamaConfig, bool, list[str]]:
    """
    Apply partial updates to the Ollama config section.

    Returns:
        (new_ollama_config, needs_restart, actually_changed_fields)

    *actually_changed_fields* only contains keys whose values actually
    differ from the current config — prevents confusing no-op reports.
    """
    cfg = get_config()
    current = cfg.ollama.model_dump()

    needs_restart = False
    changed: list[str] = []
    for key, value in updates.items():
        if value is None:
            continue
        if key in current and current[key] != value:
            changed.append(key)
            if key in _RESTART_FIELDS:
                needs_restart = True
            current[key] = value

    new_ollama = OllamaConfig(**current)

    cfg.ollama = new_ollama

    # Only persist if something actually changed
    if changed:
        save_config(cfg)

    return new_ollama, needs_restart, changed


def get_lanes_config() -> list[LaneConfig]:
    """Return the current lanes configuration."""
    return get_config().lanes


def save_lanes_config(lanes: list[LaneConfig]) -> None:
    """Update the lanes section in config and persist."""
    cfg = get_config()
    cfg.lanes = lanes
    save_config(cfg)
