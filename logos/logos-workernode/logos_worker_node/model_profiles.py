"""Model VRAM profiles — observation-only, no estimation.

Sources of truth, in priority order:
  1. "calibrated"  — pre-measured by tools/calibrate_vram_profiles.py
  2. "measured"    — derived from live observations (loaded_vram - kv_cache_sent)
  3. "override"    — operator-provided values in config.yml
  4. "cached"      — any of the above, reloaded from model_profiles.yml on restart

There is no HF API fetch and no name-based heuristic. If base_residency_mb is
unknown, placement returns 0 (no estimate) and the lane manager skips auto-
placement rather than guessing. The calibration script must be run once before
the worker is expected to make placement decisions for uncalibrated models.

Persists in the state directory as model_profiles.yml.
"""

from __future__ import annotations

import logging
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


def _ema(previous: float | None, current: float) -> float:
    if previous is None:
        return current
    return (_EMA_ALPHA * current) + ((1 - _EMA_ALPHA) * previous)


@dataclass
class ModelProfileRecord:
    loaded_vram_mb: float | None = None
    sleeping_residual_mb: float | None = None
    disk_size_bytes: int | None = None       # informational; from Ollama /api/tags
    base_residency_mb: float | None = None   # model weights + CUDA runtime (no KV)
    kv_budget_mb: float | None = None        # last observed kv_cache_sent (informational)
    engine: str | None = None
    observed_gpu_memory_utilization: float | None = None
    min_gpu_memory_utilization_to_load: float | None = None
    tensor_parallel_size: int | None = None
    kv_per_token_bytes: int | None = None    # manual override only
    max_context_length: int | None = None    # manual override only
    measurement_count: int = 0
    last_measured_epoch: float = 0.0
    # Where base_residency_mb came from:
    #   "calibrated" — pre-measured by calibrate_vram_profiles.py (most trusted)
    #   "measured"   — derived from live observation: loaded_vram - kv_cache_sent
    #   "override"   — operator-provided value in config.yml
    #   "cached"     — loaded from persisted model_profiles.yml on restart
    residency_source: str | None = None

    def known_base_residency_mb(self) -> float | None:
        """Return base_residency_mb only if it came from a real source, else None."""
        return self.base_residency_mb

    def estimate_vram_mb(self) -> float:
        """Best estimate of full model footprint for placement.

        For vLLM: base_residency_mb (model weights only, no KV).
        The caller adds kv_cache_memory_bytes separately.
        Falls back to loaded_vram_mb for non-vLLM engines.
        Returns 0.0 when nothing is known — caller must handle this.
        """
        if self.engine == "vllm":
            if self.base_residency_mb is not None:
                return self.base_residency_mb
            return 0.0
        if self.loaded_vram_mb is not None:
            return self.loaded_vram_mb
        if self.base_residency_mb is not None:
            return self.base_residency_mb
        return 0.0

    def estimate_base_residency_mb(self, model_name: str | None = None) -> float | None:
        """Return base_residency_mb if known. No estimation fallback."""
        return self.base_residency_mb

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
            "kv_per_token_bytes": self.kv_per_token_bytes,
            "max_context_length": self.max_context_length,
            "measurement_count": self.measurement_count,
            "last_measured_epoch": self.last_measured_epoch,
            "residency_source": self.residency_source,
        }


class ModelProfileRegistry:
    """Model VRAM profiles persisted in state directory."""

    def __init__(
        self,
        state_dir: Path | None = None,
        model_profile_overrides: dict[str, dict] | None = None,
    ) -> None:
        self._profiles: dict[str, ModelProfileRecord] = {}
        self._state_dir = state_dir
        self._lock = threading.Lock()
        self._manual_overrides: dict[str, dict[str, Any]] = {}
        if model_profile_overrides:
            for model_name, ov in model_profile_overrides.items():
                if isinstance(ov, dict):
                    self._manual_overrides[str(model_name)] = dict(ov)
            if self._manual_overrides:
                logger.info(
                    "Loaded manual profile overrides for %d model(s): %s",
                    len(self._manual_overrides),
                    ", ".join(sorted(self._manual_overrides)),
                )
        self._load_persisted()

    def _update_metadata(
        self,
        profile: ModelProfileRecord,
        *,
        engine: str | None = None,
        observed_gpu_memory_utilization: float | None = None,
        tensor_parallel_size: int | None = None,
    ) -> bool:
        """Update metadata fields. Returns True if tensor_parallel_size changed."""
        tp_changed = False
        if isinstance(engine, str) and engine.strip():
            profile.engine = engine.strip()
        if observed_gpu_memory_utilization is not None and observed_gpu_memory_utilization > 0:
            profile.observed_gpu_memory_utilization = observed_gpu_memory_utilization
        if tensor_parallel_size is not None and tensor_parallel_size > 0:
            if (
                profile.tensor_parallel_size is not None
                and profile.tensor_parallel_size != tensor_parallel_size
            ):
                tp_changed = True
            profile.tensor_parallel_size = tensor_parallel_size
        return tp_changed

    def add_overrides(self, overrides: dict[str, dict[str, Any]]) -> None:
        """Merge additional manual overrides (e.g. from capabilities_overrides)."""
        for model_name, ov in overrides.items():
            if not isinstance(ov, dict) or not ov:
                continue
            existing = self._manual_overrides.get(model_name)
            if existing is not None:
                existing.update(ov)
            else:
                self._manual_overrides[model_name] = dict(ov)
        if overrides:
            logger.info(
                "Added inline profile overrides for %d model(s): %s",
                len(overrides), ", ".join(sorted(overrides)),
            )

    def _apply_manual_overrides(self, model_name: str, profile: ModelProfileRecord) -> bool:
        """Apply operator-provided overrides from config.yml."""
        overrides = self._manual_overrides.get(model_name)
        if overrides is None:
            return False

        applied = []
        if "base_residency_mb" in overrides:
            profile.base_residency_mb = float(overrides["base_residency_mb"])
            profile.residency_source = "override"
            applied.append(f"base_residency={profile.base_residency_mb:.0f}MB")
        if "sleeping_residual_mb" in overrides:
            profile.sleeping_residual_mb = float(overrides["sleeping_residual_mb"])
            applied.append(f"sleeping_residual={profile.sleeping_residual_mb:.0f}MB")
        if "loaded_vram_mb" in overrides:
            profile.loaded_vram_mb = float(overrides["loaded_vram_mb"])
            applied.append(f"loaded_vram={profile.loaded_vram_mb:.0f}MB")
        if "kv_budget_mb" in overrides:
            profile.kv_budget_mb = float(overrides["kv_budget_mb"])
            applied.append(f"kv_budget={profile.kv_budget_mb:.0f}MB")
        if "kv_per_token_bytes" in overrides:
            profile.kv_per_token_bytes = int(overrides["kv_per_token_bytes"])
            applied.append(f"kv_per_token={profile.kv_per_token_bytes}")
        if "max_context_length" in overrides:
            profile.max_context_length = int(overrides["max_context_length"])
            applied.append(f"max_ctx={profile.max_context_length}")
        if "engine" in overrides:
            profile.engine = str(overrides["engine"])
            applied.append(f"engine={profile.engine}")
        if "tensor_parallel_size" in overrides:
            profile.tensor_parallel_size = int(overrides["tensor_parallel_size"])
            applied.append(f"tp={profile.tensor_parallel_size}")

        if applied:
            logger.info("Applied manual overrides for %s: %s", model_name, ", ".join(applied))
        return bool(applied)

    def seed_capabilities(self, model_names: list[str], engine: str = "vllm") -> None:
        """Pre-create profile stubs for capabilities models before any lane is loaded.

        If a profile already exists (loaded from model_profiles.yml — e.g. from a
        prior calibration run) it is left untouched. Only applies manual overrides
        for genuinely new entries.
        """
        for model_name in model_names:
            with self._lock:
                if model_name in self._profiles:
                    profile = self._profiles[model_name]
                    if profile.engine is None:
                        profile.engine = engine
                    src = profile.residency_source or "unknown"
                    logger.info(
                        "Capability [%s] %s — base_residency=%.0f MB | engine=%s (pre-existing)",
                        src.upper(), model_name,
                        profile.base_residency_mb or 0, profile.engine,
                    )
                    continue
                profile = ModelProfileRecord(engine=engine)
                self._profiles[model_name] = profile

            # New profile — apply any config overrides, nothing else
            self._apply_manual_overrides(model_name, profile)
            src = profile.residency_source or "unknown"
            if profile.base_residency_mb is not None:
                logger.info(
                    "Capability [%s] %s — base_residency=%.0f MB | engine=%s",
                    src.upper(), model_name, profile.base_residency_mb, engine,
                )
            else:
                logger.warning(
                    "Capability [UNCALIBRATED] %s — no base_residency_mb known. "
                    "Run tools/calibrate_vram_profiles.py before starting the worker "
                    "to enable accurate placement decisions.",
                    model_name,
                )
        self._persist()

    @staticmethod
    def _parse_kv_cache_to_mb(value: str) -> float:
        """Parse kv_cache_memory_bytes string to MB. E.g. '4G' → 4096.0."""
        if not value:
            return 0.0
        v = value.strip().upper()
        if v.endswith("G"):
            return float(v[:-1]) * 1024
        if v.endswith("M"):
            return float(v[:-1])
        if v.endswith("K"):
            return float(v[:-1]) / 1024
        return float(v) / (1024 * 1024)

    def record_loaded_vram(
        self,
        model_name: str,
        effective_vram_mb: float,
        *,
        engine: str | None = None,
        observed_gpu_memory_utilization: float | None = None,
        tensor_parallel_size: int | None = None,
        kv_cache_sent_mb: float = 0.0,
    ) -> None:
        """Called after lane reaches loaded/running with measured effective_vram_mb > 0.

        When kv_cache_sent_mb > 0 (vLLM with explicit --kv-cache-memory-bytes),
        derives base_residency exactly:
            base_residency = effective_vram - kv_cache_sent

        Without kv_cache_sent_mb, only loaded_vram_mb is updated.
        base_residency_mb is never touched if it already has a calibrated/override value.
        """
        if effective_vram_mb <= 0:
            return

        with self._lock:
            profile = self._profiles.setdefault(model_name, ModelProfileRecord())
            tp_changed = self._update_metadata(
                profile,
                engine=engine,
                observed_gpu_memory_utilization=observed_gpu_memory_utilization,
                tensor_parallel_size=tensor_parallel_size,
            )

            if tp_changed:
                logger.info(
                    "TP size changed for %s — resetting VRAM measurements "
                    "(old loaded=%.0f, new=%.0f)",
                    model_name, profile.loaded_vram_mb or 0, effective_vram_mb,
                )
                # Reset sleeping residual too — it's invalid with a new TP
                profile.sleeping_residual_mb = None

            if engine == "vllm" and kv_cache_sent_mb > 0:
                measured_base = max(effective_vram_mb - kv_cache_sent_mb, 0.0)
                if measured_base > 0:
                    # Never let runtime measurements overwrite a calibrated
                    # base_residency — calibration measures on a clean GPU and
                    # is authoritative.  Runtime measurements can be lower when
                    # multiple models share GPU memory.
                    if profile.residency_source == "calibrated":
                        pass  # keep calibrated value
                    elif tp_changed or profile.base_residency_mb is None:
                        profile.base_residency_mb = measured_base
                        profile.residency_source = "measured"
                    else:
                        profile.base_residency_mb = _ema(profile.base_residency_mb, measured_base)
                        profile.residency_source = "measured"
                profile.kv_budget_mb = _ema(profile.kv_budget_mb, kv_cache_sent_mb)

            if tp_changed or profile.loaded_vram_mb is None:
                profile.loaded_vram_mb = effective_vram_mb
            else:
                profile.loaded_vram_mb = _ema(profile.loaded_vram_mb, effective_vram_mb)
            profile.measurement_count += 1
            profile.last_measured_epoch = time.time()
            src = profile.residency_source or "unknown"
            logger.info(
                "Model profile [%s] %s — "
                "base_residency=%.0f MB | kv_budget=%.0f MB | "
                "total_vram=%.0f MB | kv_sent=%.0f MB | observations=%d",
                src.upper(), model_name,
                profile.base_residency_mb or 0,
                profile.kv_budget_mb or 0,
                profile.loaded_vram_mb or 0,
                kv_cache_sent_mb,
                profile.measurement_count,
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
        """Called after successful sleep with the lane's measured residual VRAM."""
        if residual_vram_mb < 0:
            return

        with self._lock:
            profile = self._profiles.setdefault(model_name, ModelProfileRecord())
            tp_changed = self._update_metadata(
                profile,
                engine=engine,
                observed_gpu_memory_utilization=observed_gpu_memory_utilization,
                tensor_parallel_size=tensor_parallel_size,
            )
            if tp_changed or profile.sleeping_residual_mb is None:
                # TP change invalidates old measurements — reset instead of EMA
                if tp_changed:
                    logger.info(
                        "TP size changed for %s — resetting sleeping_residual_mb "
                        "(old=%.0f, new=%.0f)",
                        model_name, profile.sleeping_residual_mb or 0, residual_vram_mb,
                    )
                profile.sleeping_residual_mb = residual_vram_mb
            else:
                profile.sleeping_residual_mb = _ema(profile.sleeping_residual_mb, residual_vram_mb)
            profile.last_measured_epoch = time.time()
        self._persist()

    def record_disk_size(self, model_name: str, disk_size_bytes: int) -> None:
        """Store disk size reported by Ollama /api/tags. Informational only."""
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
        """Save model profiles to state directory as YAML."""
        if self._state_dir is None or yaml is None:
            return
        try:
            with self._lock:
                data = {name: profile.to_dict() for name, profile in self._profiles.items()}
            if not data:
                return

            self._state_dir.mkdir(parents=True, exist_ok=True)
            state_path = self._state_dir / "model_profiles.yml"
            with state_path.open("w") as f:
                yaml.safe_dump({"model_profiles": data}, f, default_flow_style=False)
        except Exception:  # noqa: BLE001
            logger.debug("Failed to persist model profiles", exc_info=True)

    def _load_persisted(self) -> None:
        """Read persisted model profiles from state file on startup."""
        if self._state_dir is None or yaml is None:
            return
        state_path = self._state_dir / "model_profiles.yml"
        if not state_path.exists():
            return
        try:
            with state_path.open() as f:
                data = yaml.safe_load(f) or {}

            profiles = data.get("model_profiles")
            if not isinstance(profiles, dict):
                return
            for model_name, profile_data in profiles.items():
                if not isinstance(profile_data, dict):
                    continue
                persisted_source = profile_data.get("residency_source")
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
                    kv_per_token_bytes=profile_data.get("kv_per_token_bytes"),
                    max_context_length=profile_data.get("max_context_length"),
                    measurement_count=int(profile_data.get("measurement_count", 0) or 0),
                    last_measured_epoch=float(profile_data.get("last_measured_epoch", 0.0) or 0.0),
                    residency_source=persisted_source or "cached",
                )
            logger.info(
                "Loaded %d model profile(s) from %s", len(self._profiles), state_path,
            )
            for name, prof in self._profiles.items():
                src = prof.residency_source or "unknown"
                logger.info(
                    "  [%s] %s — base_residency=%.0f MB | sleeping=%.0f MB | observations=%d",
                    src.upper(), name,
                    prof.base_residency_mb or 0,
                    prof.sleeping_residual_mb or 0,
                    prof.measurement_count,
                )
        except Exception:  # noqa: BLE001
            logger.debug("Failed to load persisted model profiles", exc_info=True)
