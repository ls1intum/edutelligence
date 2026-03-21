"""Auto-calibrating model VRAM profiles.

Records observed lane reservation after model load and sleeping_residual_mb after
sleep. Logos uses these observations as calibration input, but may derive a
different planning budget for vLLM based on current gpu_memory_utilization.
Uses exponential moving average after the first measurement. Persists in
config.yml.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

logger = logging.getLogger(__name__)

_EMA_ALPHA = 0.3  # weight for new measurement vs historical average
_MODEL_SCALE_RE = re.compile(r"(?i)(\d+(?:\.\d+)?)([bm])")


def _ema(previous: float | None, current: float) -> float:
    if previous is None:
        return current
    return (_EMA_ALPHA * current) + ((1 - _EMA_ALPHA) * previous)


def _estimated_disk_size_bytes_from_model_name(model_name: str) -> int | None:
    lowered = (model_name or "").lower()
    match = _MODEL_SCALE_RE.search(lowered)
    if match is None:
        return None

    magnitude = float(match.group(1))
    unit = match.group(2).lower()
    params = magnitude * (1_000_000_000 if unit == "b" else 1_000_000)

    bytes_per_param = 2.0
    if any(token in lowered for token in ("q2", "2bit")):
        bytes_per_param = 0.35
    elif any(token in lowered for token in ("q3", "3bit")):
        bytes_per_param = 0.45
    elif any(token in lowered for token in ("q4", "4bit", "int4", "awq", "gptq")):
        bytes_per_param = 0.60
    elif any(token in lowered for token in ("q5", "5bit")):
        bytes_per_param = 0.70
    elif any(token in lowered for token in ("q6", "6bit")):
        bytes_per_param = 0.80
    elif any(token in lowered for token in ("q8", "8bit", "int8")):
        bytes_per_param = 1.00

    return int(params * bytes_per_param)


def _base_residency_from_bytes(disk_size_bytes: int | None) -> float | None:
    if disk_size_bytes is None or disk_size_bytes <= 0:
        return None
    return (disk_size_bytes / (1024 * 1024)) * 1.1


@dataclass
class ModelProfileRecord:
    loaded_vram_mb: float | None = None
    sleeping_residual_mb: float | None = None
    disk_size_bytes: int | None = None
    base_residency_mb: float | None = None
    kv_budget_mb: float | None = None
    engine: str | None = None
    observed_gpu_memory_utilization: float | None = None
    min_gpu_memory_utilization_to_load: float | None = None
    tensor_parallel_size: int | None = None
    measurement_count: int = 0
    last_measured_epoch: float = 0.0

    def estimate_vram_mb(self) -> float:
        """Best estimate of model footprint (not GPU reservation).

        For vLLM, loaded_vram_mb is the full GPU reservation (gpu_util × device_vram),
        which vastly overestimates the actual model size. Prefer base_residency_mb
        (model weights + runtime overhead) for vLLM engines.
        """
        if self.engine == "vllm":
            base = self.estimate_base_residency_mb()
            if base is not None:
                return base
        if self.loaded_vram_mb is not None:
            return self.loaded_vram_mb
        base = self.estimate_base_residency_mb()
        if base is not None:
            return base
        return 4096.0

    def estimate_base_residency_mb(self, model_name: str | None = None) -> float | None:
        if self.base_residency_mb is not None:
            return self.base_residency_mb
        disk_size_bytes = self.disk_size_bytes
        if (disk_size_bytes is None or disk_size_bytes <= 0) and model_name:
            disk_size_bytes = _estimated_disk_size_bytes_from_model_name(model_name)
        return _base_residency_from_bytes(disk_size_bytes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "loaded_vram_mb": self.loaded_vram_mb,
            "sleeping_residual_mb": self.sleeping_residual_mb,
            "disk_size_bytes": self.disk_size_bytes,
            "base_residency_mb": self.base_residency_mb,
            "kv_budget_mb": self.kv_budget_mb,
            "engine": self.engine,
            "observed_gpu_memory_utilization": self.observed_gpu_memory_utilization,
            "min_gpu_memory_utilization_to_load": self.min_gpu_memory_utilization_to_load,
            "tensor_parallel_size": self.tensor_parallel_size,
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

    def _update_metadata(
        self,
        profile: ModelProfileRecord,
        *,
        engine: str | None = None,
        observed_gpu_memory_utilization: float | None = None,
        tensor_parallel_size: int | None = None,
    ) -> None:
        if isinstance(engine, str) and engine.strip():
            profile.engine = engine.strip()
        if observed_gpu_memory_utilization is not None and observed_gpu_memory_utilization > 0:
            profile.observed_gpu_memory_utilization = observed_gpu_memory_utilization
        if tensor_parallel_size is not None and tensor_parallel_size > 0:
            profile.tensor_parallel_size = tensor_parallel_size

    def record_loaded_vram(
        self,
        model_name: str,
        effective_vram_mb: float,
        *,
        engine: str | None = None,
        observed_gpu_memory_utilization: float | None = None,
        tensor_parallel_size: int | None = None,
    ) -> None:
        """Called after lane reaches loaded/running with measured effective_vram_mb > 0.

        First measurement sets value. Subsequent measurements update via EMA.
        """
        if effective_vram_mb <= 0:
            return

        with self._lock:
            profile = self._profiles.setdefault(model_name, ModelProfileRecord())
            self._update_metadata(
                profile,
                engine=engine,
                observed_gpu_memory_utilization=observed_gpu_memory_utilization,
                tensor_parallel_size=tensor_parallel_size,
            )
            base_estimate = profile.estimate_base_residency_mb(model_name)
            if base_estimate is not None:
                profile.base_residency_mb = _ema(profile.base_residency_mb, base_estimate)
                if engine == "vllm":
                    profile.kv_budget_mb = _ema(
                        profile.kv_budget_mb,
                        max(effective_vram_mb - profile.base_residency_mb, 0.0),
                    )
            if profile.loaded_vram_mb is None:
                profile.loaded_vram_mb = effective_vram_mb
            else:
                profile.loaded_vram_mb = _ema(profile.loaded_vram_mb, effective_vram_mb)
            profile.measurement_count += 1
            profile.last_measured_epoch = time.time()
            logger.debug(
                "Model profile updated: %s loaded_vram_mb=%.1f (count=%d)",
                model_name, profile.loaded_vram_mb, profile.measurement_count,
            )
        self._persist()

    def record_successful_load_util(self, model_name: str, gpu_memory_utilization: float) -> None:
        """Record the lowest known-good gpu_memory_utilization that reached loaded/running."""
        if gpu_memory_utilization <= 0:
            return

        with self._lock:
            profile = self._profiles.setdefault(model_name, ModelProfileRecord())
            if (
                profile.min_gpu_memory_utilization_to_load is None
                or gpu_memory_utilization < profile.min_gpu_memory_utilization_to_load
            ):
                profile.min_gpu_memory_utilization_to_load = gpu_memory_utilization
                profile.last_measured_epoch = time.time()
        self._persist()

    def record_sleeping_vram(
        self,
        model_name: str,
        residual_vram_mb: float,
        *,
        engine: str | None = None,
        observed_gpu_memory_utilization: float | None = None,
        tensor_parallel_size: int | None = None,
    ) -> None:
        """Called after successful sleep. residual_vram_mb is the lane's effective_vram_mb
        while in sleeping state."""
        if residual_vram_mb < 0:
            return

        with self._lock:
            profile = self._profiles.setdefault(model_name, ModelProfileRecord())
            self._update_metadata(
                profile,
                engine=engine,
                observed_gpu_memory_utilization=observed_gpu_memory_utilization,
                tensor_parallel_size=tensor_parallel_size,
            )
            base_estimate = profile.estimate_base_residency_mb(model_name)
            if base_estimate is not None:
                profile.base_residency_mb = _ema(profile.base_residency_mb, base_estimate)
            if profile.sleeping_residual_mb is None:
                profile.sleeping_residual_mb = residual_vram_mb
            else:
                profile.sleeping_residual_mb = _ema(profile.sleeping_residual_mb, residual_vram_mb)
            profile.last_measured_epoch = time.time()
        self._persist()

    def record_disk_size(self, model_name: str, disk_size_bytes: int) -> None:
        """Called from Ollama /api/tags response."""
        if disk_size_bytes <= 0:
            return

        with self._lock:
            profile = self._profiles.setdefault(model_name, ModelProfileRecord())
            profile.disk_size_bytes = disk_size_bytes
            base_estimate = profile.estimate_base_residency_mb(model_name)
            if base_estimate is not None:
                profile.base_residency_mb = _ema(profile.base_residency_mb, base_estimate)
                if profile.engine == "vllm" and profile.loaded_vram_mb is not None:
                    profile.kv_budget_mb = _ema(
                        profile.kv_budget_mb,
                        max(profile.loaded_vram_mb - profile.base_residency_mb, 0.0),
                    )
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
                    base_residency_mb=profile_data.get("base_residency_mb"),
                    kv_budget_mb=profile_data.get("kv_budget_mb"),
                    engine=profile_data.get("engine"),
                    observed_gpu_memory_utilization=profile_data.get("observed_gpu_memory_utilization"),
                    min_gpu_memory_utilization_to_load=profile_data.get("min_gpu_memory_utilization_to_load"),
                    tensor_parallel_size=profile_data.get("tensor_parallel_size"),
                    measurement_count=int(profile_data.get("measurement_count", 0) or 0),
                    last_measured_epoch=float(profile_data.get("last_measured_epoch", 0.0) or 0.0),
                )
            logger.info("Loaded %d model profiles from %s", len(self._profiles), self._config_path)
        except Exception:  # noqa: BLE001
            logger.debug("Failed to load persisted model profiles", exc_info=True)
