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
    disk_size_bytes: int | None = None  # informational; from Ollama /api/tags
    base_residency_mb: float | None = (
        None  # full awake footprint; semantics depend on residency_source (see below)
    )
    kv_budget_mb: float | None = None  # last observed kv_cache_sent (informational)
    # KV cache envelope discovered by calibration on this hardware. The planner
    # picks a runtime kv_cache_memory_bytes value inside [min, max] based on
    # how much VRAM is free at load time — small enough to coexist with other
    # lanes when memory is tight, large enough for healthy concurrency when it
    # isn't. Both None on legacy profiles written before this envelope existed;
    # callers fall back to kv_budget_mb in that case.
    min_kv_cache_mb: float | None = None
    max_kv_cache_mb: float | None = None
    engine: str | None = None
    observed_gpu_memory_utilization: float | None = None
    min_gpu_memory_utilization_to_load: float | None = None
    tensor_parallel_size: int | None = None
    kv_per_token_bytes: int | None = None  # manual override only
    max_context_length: int | None = None  # manual override only
    measurement_count: int = 0
    last_measured_epoch: float = 0.0
    # Where base_residency_mb came from — also determines its semantics:
    #   "calibrated" — pre-measured by calibrate_vram_profiles.py; value is
    #                  loaded_vram_mb = full awake footprint with the
    #                  configured KV cap already in effect. KV is INCLUDED;
    #                  callers must NOT add kv_cache_memory_bytes on top.
    #   "measured"   — derived from live observation: loaded_vram − kv_cache_sent.
    #                  Value is weights-only; callers DO add KV separately.
    #   "override"   — operator-provided value in config.yml.
    #   "cached"     — any of the above, loaded from persisted yml on restart.
    residency_source: str | None = None
    # Provenance: what enforce_eager mode the calibration ran under.
    # When None on a "calibrated" profile, treat as legacy = True (the prior
    # auto-calibrator hard-forced eager mode). Matched against the production
    # override when deciding whether a cached profile is still valid.
    enforce_eager_at_calibration: bool | None = None
    # Host-RAM footprint of the lane process tree once loaded. The master's
    # capacity planner uses this to reason about host RAM as a resource axis
    # parallel to VRAM — necessary because vLLM sleep_l1/sleep_l2 free VRAM
    # but retain weights in host RAM. EMA-updated from worker telemetry.
    host_ram_mb: float | None = None
    # Host-RAM still held when the lane is sleeping (level 1). Approximately
    # equal to host_ram_mb in practice — sleep_l1 moves weights from VRAM to
    # host RAM rather than freeing them — but tracked separately so the
    # planner can use the right value depending on the candidate's state.
    host_ram_residual_mb: float | None = None
    # Peak transient host-RAM allocation observed during the calibrated
    # sleep call (level 1 / level 2). Distinct from host_ram_residual_mb,
    # which is steady-state after the sleep settles. The planner uses these
    # to gate sleep dispatch on swap-saturated workers — without enough
    # transient headroom vLLM's sleep cancels mid-flight and kills
    # EngineCore. None on profiles calibrated before this field existed.
    sleep_l1_transient_host_ram_mb: float | None = None
    sleep_l2_transient_host_ram_mb: float | None = None
    # True when this worker's effective config forbids sleep mode for this
    # model (engines.vllm.disable_sleep_mode worker kill switch, or a
    # per-model enable_sleep_mode=false override under engines.vllm or
    # logos.capabilities). The server's nightly calibration orchestrator
    # treats this as "sleep_l1_transient_host_ram_mb is N/A by design" so
    # it stops re-requesting calibration of a sleep field that can never
    # be measured here. None on legacy profiles written before this flag
    # existed (interpret as "unknown — assume sleep is possible").
    sleep_mode_disabled: bool | None = None
    # True when calibration has classified this model as permanently
    # unsupported on this worker — bad repo id, gated repo without token,
    # vLLM architecture mismatch, etc. (see FatalLoadErrorPattern in
    # calibration.py). The master's calibration orchestrator skips models
    # flagged this way so it doesn't burn a maintenance window each night
    # watching the same identity-level error reproduce. Cleared by an
    # operator (delete the entry from calibration_unsupported_models.txt
    # and restart, or set this flag to False) after fixing the underlying
    # cause. None on profiles written before this flag existed.
    calibration_unsupported: bool | None = None
    # Reason code matching FatalLoadErrorPattern.reason_code, for diagnostics.
    # Surfaced to ops in master logs alongside `calibration_unsupported=True`.
    calibration_unsupported_reason: str | None = None

    def known_base_residency_mb(self) -> float | None:
        """Return base_residency_mb only if it came from a real source, else None."""
        return self.base_residency_mb

    def estimate_vram_mb(self) -> float:
        """Best estimate of full model footprint for placement.

        For vLLM: returns base_residency_mb. The value's meaning depends on
        residency_source — "calibrated" is the full awake footprint (KV
        included); "measured" is weights-only. Callers that add KV on top
        must gate on residency_source to avoid double-counting.
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
            "min_kv_cache_mb": self.min_kv_cache_mb,
            "max_kv_cache_mb": self.max_kv_cache_mb,
            "engine": self.engine,
            "observed_gpu_memory_utilization": self.observed_gpu_memory_utilization,
            "min_gpu_memory_utilization_to_load": self.min_gpu_memory_utilization_to_load,
            "tensor_parallel_size": self.tensor_parallel_size,
            "kv_per_token_bytes": self.kv_per_token_bytes,
            "max_context_length": self.max_context_length,
            "measurement_count": self.measurement_count,
            "last_measured_epoch": self.last_measured_epoch,
            "residency_source": self.residency_source,
            "enforce_eager_at_calibration": self.enforce_eager_at_calibration,
            "host_ram_mb": self.host_ram_mb,
            "host_ram_residual_mb": self.host_ram_residual_mb,
            "sleep_l1_transient_host_ram_mb": self.sleep_l1_transient_host_ram_mb,
            "sleep_l2_transient_host_ram_mb": self.sleep_l2_transient_host_ram_mb,
            "sleep_mode_disabled": self.sleep_mode_disabled,
            "calibration_unsupported": self.calibration_unsupported,
            "calibration_unsupported_reason": self.calibration_unsupported_reason,
        }

    def estimate_host_ram_mb(self) -> float:
        """Best estimate of awake host-RAM footprint for the lane process tree.

        Returns host_ram_mb when known. Otherwise falls back to disk_size_bytes
        (the safetensors total is a tight lower bound on the loaded footprint —
        the weights are mmapped/copied into host RAM at load time, plus
        tokenizer, compile cache, etc. add ~1–4 GiB overhead). Returns 0.0
        when nothing is known.
        """
        if self.host_ram_mb is not None and self.host_ram_mb > 0:
            return self.host_ram_mb
        if self.disk_size_bytes and self.disk_size_bytes > 0:
            return self.disk_size_bytes / (1024 * 1024)
        return 0.0

    def estimate_sleeping_host_ram_mb(self) -> float:
        """Host-RAM still held when sleeping (level 1).

        Sleep_l1 retains weights in host RAM, so the residual ≈ the awake
        footprint. Falls back to estimate_host_ram_mb() when no measurement
        has been recorded.
        """
        if self.host_ram_residual_mb is not None and self.host_ram_residual_mb > 0:
            return self.host_ram_residual_mb
        return self.estimate_host_ram_mb()


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
        if (
            observed_gpu_memory_utilization is not None
            and observed_gpu_memory_utilization > 0
        ):
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
                len(overrides),
                ", ".join(sorted(overrides)),
            )

    def _apply_manual_overrides(
        self, model_name: str, profile: ModelProfileRecord
    ) -> bool:
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
        if "min_kv_cache_mb" in overrides:
            profile.min_kv_cache_mb = float(overrides["min_kv_cache_mb"])
            applied.append(f"min_kv={profile.min_kv_cache_mb:.0f}MB")
        if "max_kv_cache_mb" in overrides:
            profile.max_kv_cache_mb = float(overrides["max_kv_cache_mb"])
            applied.append(f"max_kv={profile.max_kv_cache_mb:.0f}MB")
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
        if "host_ram_mb" in overrides:
            profile.host_ram_mb = float(overrides["host_ram_mb"])
            applied.append(f"host_ram={profile.host_ram_mb:.0f}MB")
        if "host_ram_residual_mb" in overrides:
            profile.host_ram_residual_mb = float(overrides["host_ram_residual_mb"])
            applied.append(f"host_ram_residual={profile.host_ram_residual_mb:.0f}MB")

        if applied:
            logger.info(
                "Applied manual overrides for %s: %s", model_name, ", ".join(applied)
            )
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
                        src.upper(),
                        model_name,
                        profile.base_residency_mb or 0,
                        profile.engine,
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
                    src.upper(),
                    model_name,
                    profile.base_residency_mb,
                    engine,
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
                    model_name,
                    profile.loaded_vram_mb or 0,
                    effective_vram_mb,
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
                        profile.base_residency_mb = _ema(
                            profile.base_residency_mb, measured_base
                        )
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
                src.upper(),
                model_name,
                profile.base_residency_mb or 0,
                profile.kv_budget_mb or 0,
                profile.loaded_vram_mb or 0,
                kv_cache_sent_mb,
                profile.measurement_count,
            )
        self._persist()

    def record_successful_load_util(
        self, model_name: str, gpu_memory_utilization: float
    ) -> None:
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
                        model_name,
                        profile.sleeping_residual_mb or 0,
                        residual_vram_mb,
                    )
                profile.sleeping_residual_mb = residual_vram_mb
            else:
                profile.sleeping_residual_mb = _ema(
                    profile.sleeping_residual_mb, residual_vram_mb
                )
            profile.last_measured_epoch = time.time()
        self._persist()

    def record_host_ram(
        self,
        model_name: str,
        host_ram_mb: float,
        *,
        sleeping: bool = False,
    ) -> None:
        """Record measured host-RAM footprint for the lane process tree.

        *sleeping* selects which field is updated: when False, host_ram_mb
        (awake footprint); when True, host_ram_residual_mb (level-1 sleep).
        EMA-blended with prior measurements.
        """
        if host_ram_mb <= 0:
            return
        with self._lock:
            profile = self._profiles.setdefault(model_name, ModelProfileRecord())
            if sleeping:
                profile.host_ram_residual_mb = (
                    host_ram_mb
                    if profile.host_ram_residual_mb is None
                    else _ema(profile.host_ram_residual_mb, host_ram_mb)
                )
            else:
                profile.host_ram_mb = (
                    host_ram_mb
                    if profile.host_ram_mb is None
                    else _ema(profile.host_ram_mb, host_ram_mb)
                )
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

    def mark_sleep_mode_disabled(self, model_name: str, disabled: bool) -> bool:
        """Persist whether sleep mode is forbidden for this model on this worker.

        Returns True when the stored value changed. Used by the
        server-orchestrated calibration path to tell the master "stop
        asking — sleep_l1_transient_host_ram_mb is N/A for this model
        because the worker config forbids sleeping it."

        Setting ``disabled=False`` is treated as a clearing operation:
        it never creates a new profile entry, only updates an existing
        one. This keeps the registry from filling up with empty stubs
        for models that were never calibrated.
        """
        with self._lock:
            if not disabled and model_name not in self._profiles:
                return False
            profile = self._profiles.setdefault(model_name, ModelProfileRecord())
            if profile.sleep_mode_disabled == disabled:
                return False
            profile.sleep_mode_disabled = disabled
        self._persist()
        return True

    def mark_calibration_unsupported(
        self, model_name: str, unsupported: bool, reason_code: str | None = None
    ) -> bool:
        """Persist whether this model is permanently uncalibratable on this worker.

        Returns True when the stored value changed. Used by the
        server-orchestrated calibration path to tell the master "stop
        scheduling this model for calibration — it cannot succeed here
        until an operator removes the matching line from
        ``calibration_unsupported_models.txt``."

        Setting ``unsupported=False`` is treated as a clearing operation:
        it never creates a new profile entry, only updates an existing
        one — same convention as :meth:`mark_sleep_mode_disabled`. When
        clearing, ``reason_code`` is also nulled out.
        """
        with self._lock:
            if not unsupported and model_name not in self._profiles:
                return False
            profile = self._profiles.setdefault(model_name, ModelProfileRecord())
            changed = (
                profile.calibration_unsupported != unsupported
                or profile.calibration_unsupported_reason
                != (reason_code if unsupported else None)
            )
            if not changed:
                return False
            profile.calibration_unsupported = unsupported
            profile.calibration_unsupported_reason = (
                reason_code if unsupported else None
            )
        self._persist()
        return True

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
                data = {
                    name: profile.to_dict() for name, profile in self._profiles.items()
                }
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
                eager_at_cal = profile_data.get("enforce_eager_at_calibration")
                # Legacy profiles predating provenance tracking were always
                # measured with the hard-forced eager=True path. Carry that
                # assumption forward so the reuse check doesn't false-mismatch.
                if eager_at_cal is None and persisted_source == "calibrated":
                    eager_at_cal = True
                self._profiles[str(model_name)] = ModelProfileRecord(
                    loaded_vram_mb=profile_data.get("loaded_vram_mb"),
                    sleeping_residual_mb=profile_data.get("sleeping_residual_mb"),
                    disk_size_bytes=profile_data.get("disk_size_bytes"),
                    base_residency_mb=profile_data.get("base_residency_mb"),
                    kv_budget_mb=profile_data.get("kv_budget_mb"),
                    min_kv_cache_mb=profile_data.get("min_kv_cache_mb"),
                    max_kv_cache_mb=profile_data.get("max_kv_cache_mb"),
                    engine=profile_data.get("engine"),
                    observed_gpu_memory_utilization=profile_data.get(
                        "observed_gpu_memory_utilization"
                    ),
                    min_gpu_memory_utilization_to_load=profile_data.get(
                        "min_gpu_memory_utilization_to_load"
                    ),
                    tensor_parallel_size=profile_data.get("tensor_parallel_size"),
                    kv_per_token_bytes=profile_data.get("kv_per_token_bytes"),
                    max_context_length=profile_data.get("max_context_length"),
                    measurement_count=int(
                        profile_data.get("measurement_count", 0) or 0
                    ),
                    last_measured_epoch=float(
                        profile_data.get("last_measured_epoch", 0.0) or 0.0
                    ),
                    residency_source=persisted_source or "cached",
                    enforce_eager_at_calibration=eager_at_cal,
                    host_ram_mb=profile_data.get("host_ram_mb"),
                    host_ram_residual_mb=profile_data.get("host_ram_residual_mb"),
                    sleep_l1_transient_host_ram_mb=profile_data.get(
                        "sleep_l1_transient_host_ram_mb"
                    ),
                    sleep_l2_transient_host_ram_mb=profile_data.get(
                        "sleep_l2_transient_host_ram_mb"
                    ),
                    sleep_mode_disabled=profile_data.get("sleep_mode_disabled"),
                    calibration_unsupported=profile_data.get("calibration_unsupported"),
                    calibration_unsupported_reason=profile_data.get(
                        "calibration_unsupported_reason"
                    ),
                )
            logger.info(
                "Loaded %d model profile(s) from %s",
                len(self._profiles),
                state_path,
            )
            for name, prof in self._profiles.items():
                src = prof.residency_source or "unknown"
                logger.info(
                    "  [%s] %s — base_residency=%.0f MB | sleeping=%.0f MB | observations=%d",
                    src.upper(),
                    name,
                    prof.base_residency_mb or 0,
                    prof.sleeping_residual_mb or 0,
                    prof.measurement_count,
                )
        except Exception:  # noqa: BLE001
            logger.debug("Failed to load persisted model profiles", exc_info=True)
