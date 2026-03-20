"""Auto-calibrating model VRAM profiles.

Records effective_vram_mb after model load and sleeping_residual_mb after sleep.
Uses exponential moving average after the first measurement. Persists in config.yml.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

logger = logging.getLogger(__name__)

_EMA_ALPHA = 0.3  # weight for new measurement vs historical average


@dataclass
class ModelProfileRecord:
    loaded_vram_mb: float | None = None
    sleeping_residual_mb: float | None = None
    disk_size_bytes: int | None = None
    measurement_count: int = 0
    last_measured_epoch: float = 0.0

    def estimate_vram_mb(self) -> float:
        """Best estimate: measured > disk heuristic > conservative fallback."""
        if self.loaded_vram_mb is not None:
            return self.loaded_vram_mb
        if self.disk_size_bytes is not None and self.disk_size_bytes > 0:
            return (self.disk_size_bytes / (1024 * 1024)) * 1.1
        return 4096.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "loaded_vram_mb": self.loaded_vram_mb,
            "sleeping_residual_mb": self.sleeping_residual_mb,
            "disk_size_bytes": self.disk_size_bytes,
            "measurement_count": self.measurement_count,
            "last_measured_epoch": self.last_measured_epoch,
        }


class ModelProfileRegistry:
    """Auto-calibrating model VRAM profiles. Optionally persisted in config.yml."""

    def __init__(self, config_path: Path | None = None) -> None:
        self._profiles: dict[str, ModelProfileRecord] = {}
        self._config_path = config_path
        self._lock = threading.Lock()
        self._load_persisted()

    def record_loaded_vram(self, model_name: str, effective_vram_mb: float) -> None:
        """Called after lane reaches loaded/running with measured effective_vram_mb > 0.

        First measurement sets value. Subsequent measurements update via EMA.
        """
        if effective_vram_mb <= 0:
            return

        with self._lock:
            profile = self._profiles.setdefault(model_name, ModelProfileRecord())
            if profile.loaded_vram_mb is None:
                profile.loaded_vram_mb = effective_vram_mb
            else:
                profile.loaded_vram_mb = (
                    _EMA_ALPHA * effective_vram_mb
                    + (1 - _EMA_ALPHA) * profile.loaded_vram_mb
                )
            profile.measurement_count += 1
            profile.last_measured_epoch = time.time()
            logger.debug(
                "Model profile updated: %s loaded_vram_mb=%.1f (count=%d)",
                model_name, profile.loaded_vram_mb, profile.measurement_count,
            )
        self._persist()

    def record_sleeping_vram(self, model_name: str, residual_vram_mb: float) -> None:
        """Called after successful sleep. residual_vram_mb is the lane's effective_vram_mb
        while in sleeping state."""
        if residual_vram_mb < 0:
            return

        with self._lock:
            profile = self._profiles.setdefault(model_name, ModelProfileRecord())
            if profile.sleeping_residual_mb is None:
                profile.sleeping_residual_mb = residual_vram_mb
            else:
                profile.sleeping_residual_mb = (
                    _EMA_ALPHA * residual_vram_mb
                    + (1 - _EMA_ALPHA) * profile.sleeping_residual_mb
                )
            profile.last_measured_epoch = time.time()
        self._persist()

    def record_disk_size(self, model_name: str, disk_size_bytes: int) -> None:
        """Called from Ollama /api/tags response."""
        if disk_size_bytes <= 0:
            return

        with self._lock:
            profile = self._profiles.setdefault(model_name, ModelProfileRecord())
            profile.disk_size_bytes = disk_size_bytes
        self._persist()

    def get_profile(self, model_name: str) -> ModelProfileRecord | None:
        with self._lock:
            return self._profiles.get(model_name)

    def get_all_profiles(self) -> dict[str, dict[str, Any]]:
        """Return all profiles as serializable dicts for websocket payload."""
        with self._lock:
            return {name: profile.to_dict() for name, profile in self._profiles.items()}

    def _persist(self) -> None:
        """Append model_profiles section to config.yml."""
        if self._config_path is None or yaml is None:
            return
        try:
            with self._lock:
                data = {name: profile.to_dict() for name, profile in self._profiles.items()}
            if not data:
                return

            existing: dict = {}
            if self._config_path.exists():
                try:
                    with self._config_path.open() as f:
                        existing = yaml.safe_load(f) or {}
                except Exception:  # noqa: BLE001
                    existing = {}

            existing["model_profiles"] = data
            with self._config_path.open("w") as f:
                yaml.safe_dump(existing, f, default_flow_style=False)
        except Exception:  # noqa: BLE001
            logger.debug("Failed to persist model profiles", exc_info=True)

    def _load_persisted(self) -> None:
        """Read model_profiles from config.yml on startup."""
        if self._config_path is None or yaml is None:
            return
        if not self._config_path.exists():
            return
        try:
            with self._config_path.open() as f:
                data = yaml.safe_load(f) or {}
            profiles = data.get("model_profiles")
            if not isinstance(profiles, dict):
                return
            for model_name, profile_data in profiles.items():
                if not isinstance(profile_data, dict):
                    continue
                self._profiles[str(model_name)] = ModelProfileRecord(
                    loaded_vram_mb=profile_data.get("loaded_vram_mb"),
                    sleeping_residual_mb=profile_data.get("sleeping_residual_mb"),
                    disk_size_bytes=profile_data.get("disk_size_bytes"),
                    measurement_count=int(profile_data.get("measurement_count", 0) or 0),
                    last_measured_epoch=float(profile_data.get("last_measured_epoch", 0.0) or 0.0),
                )
            logger.info("Loaded %d model profiles from %s", len(self._profiles), self._config_path)
        except Exception:  # noqa: BLE001
            logger.debug("Failed to load persisted model profiles", exc_info=True)
