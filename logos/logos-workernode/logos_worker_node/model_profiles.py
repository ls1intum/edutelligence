"""Model VRAM profiles.

Sources of truth, in priority order:
  1. "calibrated"  — measured by a calibration session
  2. "measured"    — derived from live observations (loaded_vram - kv_cache_sent)
  3. "override"    — operator-provided values in config.yml
  4. "hf"          — best-effort estimate from the model's Hugging Face
                     config.json + safetensors sizes, applied by the
                     calibration compatibility pre-check (hf_model_info.py)
                     before a probe has ever run. Below "measured"/"calibrated"
                     in authority — a real measurement always overwrites it.
  5. "cached"      — any of the above, restored from the central store

If base_residency_mb is unknown (no override, no HF estimate, never
calibrated), placement returns 0 (no estimate) and the lane manager skips
auto-placement rather than guessing.

Profiles live only in memory. Logos' database is their store: the worker
receives them at startup and through sync_model_profiles, and reports every
change back in its runtime status.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, fields
from typing import Any

logger = logging.getLogger(__name__)

_EMA_ALPHA = 0.3  # weight for new measurement vs historical average


def reconfigured_vram_mb(profile: Any, measured_mb: float, gpu_count: int, cache_per_gpu_mb: float) -> float:
    """Adjust a calibrated total for a different number/size of per-rank KV caches.

    Keep measured weights and overhead; replace only the known KV allocation.
    Unknown or inconsistent metadata retains the conservative measured total.
    """
    old_count = getattr(profile, "tensor_parallel_size", None)
    old_cache = getattr(profile, "kv_budget_mb", None)
    if (
        getattr(profile, "residency_source", None) != "calibrated"
        or not old_count
        or old_count <= 0
        or not old_cache
        or old_cache <= 0
        or cache_per_gpu_mb <= 0
        or gpu_count <= 0
        or measured_mb <= old_count * old_cache
    ):
        return measured_mb
    return measured_mb - old_count * old_cache + gpu_count * cache_per_gpu_mb


def _ema(previous: float | None, current: float) -> float:
    if previous is None:
        return current
    return (_EMA_ALPHA * current) + ((1 - _EMA_ALPHA) * previous)


@dataclass
class ModelProfileRecord:
    loaded_vram_mb: float | None = None
    sleeping_residual_mb: float | None = None
    disk_size_bytes: int | None = None  # informational; legacy field — still read from persisted profiles
    base_residency_mb: float | None = None  # full awake footprint; semantics depend on residency_source (see below)
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
    kv_per_token_bytes: int | None = None  # manual override or HF precheck
    # KV heads in the whole model (config's own dtype geometry) — kv_per_token_bytes
    # above is the WHOLE-MODEL footprint (every head), but vLLM's TP shards KV heads
    # across ranks (max(1, heads // tp)), so a per-rank budget needs this to scale
    # kv_per_token_bytes down for the selected tp. None on legacy profiles that
    # predate this field, or when HF config.json didn't expose enough to derive it.
    num_key_value_heads: int | None = None
    max_context_length: int | None = None  # manual override or HF precheck
    # Smallest share of this model's own context length a lane here may serve,
    # as a fraction in [0, 1]. Operator-set per model under
    # logos.capabilities_models; the master's capacity planner refuses to place
    # a lane below it.
    #
    # It exists because a lane's context window comes from whatever KV cache
    # fits at load time, while the API can only promise the smallest window
    # across the cluster — so one narrow lane defines what every client is told
    # the model can do. 1.0 means "full context or nothing", 0 (or unset) means
    # place it at any width. Manual override only; calibration never sets it.
    min_context_fraction: float | None = None
    measurement_count: int = 0
    last_measured_epoch: float = 0.0
    # Where base_residency_mb came from — also determines its semantics:
    #   "calibrated" — measured by a calibration session; value is
    #                  loaded_vram_mb = full awake footprint with the
    #                  configured KV cap already in effect. KV is INCLUDED;
    #                  callers must NOT add kv_cache_memory_bytes on top.
    #   "measured"   — derived from live observation: loaded_vram − kv_cache_sent.
    #                  Value is weights-only; callers DO add KV separately.
    #   "override"   — operator-provided value in config.yml.
    #   "hf"         — best-effort estimate from HF config.json +
    #                  safetensors sizes (pre-calibration precheck).
    #                  Weights-only, same semantics as "measured";
    #                  a real calibration always replaces it.
    #   "cached"     — any of the above, restored without a source label.
    residency_source: str | None = None
    # Provenance: what enforce_eager mode the calibration ran under.
    # When None on a "calibrated" profile, treat as legacy = True (the prior
    # auto-calibrator hard-forced eager mode). Matched against the production
    # override when deciding whether a cached profile is still valid.
    enforce_eager_at_calibration: bool | None = None
    # Host-RAM footprint of the lane process tree once loaded. The master's
    # capacity planner uses this to reason about host RAM as a resource axis
    # parallel to VRAM — necessary because vLLM sleep_l1/sleep_l2 free VRAM
    # but retain weights in host RAM. Updated as a high-water mark from
    # worker telemetry: long-lived EngineCores accumulate sticky host
    # shared-memory that sleep→wake does not clear, so averaging fresh lean
    # replicas with heavy ones would understate lasting pressure.
    host_ram_mb: float | None = None
    # Host-RAM still held when the lane is sleeping (level 1). Approximately
    # equal to host_ram_mb in practice — sleep_l1 moves weights from VRAM to
    # host RAM rather than freeing them — but tracked separately so the
    # planner can use the right value depending on the candidate's state.
    # Also a high-water mark: sticky shm that survives sleep/wake is part of
    # the lasting residency the host must afford.
    host_ram_residual_mb: float | None = None
    # Peak transient host-RAM allocation observed during the calibrated
    # sleep call (level 1 / level 2). Distinct from host_ram_residual_mb,
    # which is steady-state after the sleep settles. The planner uses these
    # to gate sleep dispatch on swap-saturated workers — without enough
    # transient headroom vLLM's sleep cancels mid-flight and kills
    # EngineCore. None on profiles calibrated before this field existed.
    sleep_l1_transient_host_ram_mb: float | None = None
    sleep_l2_transient_host_ram_mb: float | None = None
    # Wall-clock seconds the calibration measured from the final probe spawn
    # to the first request it served (the warmup 1-token completion) — the
    # cold start a client pays when a lane has to load for its request (vLLM
    # startup + weight load + first-request CUDA-graph/JIT overhead). None
    # when the calibrating run's warmup did not serve, or on profiles that
    # predate the field.
    cold_load_time_s: float | None = None
    # Wall-clock seconds from the calibrated /wake_up trigger to the
    # post-wake test request being served — the wait a request queued on a
    # sleeping lane pays for the wake. None when the sleep phases were
    # skipped, the post-wake request did not serve, or the profile predates
    # the field.
    wake_from_sleep_time_s: float | None = None
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
    # vllm_compat.py). The master's calibration orchestrator skips models
    # flagged this way so it doesn't burn a maintenance window each night
    # watching the same identity-level error reproduce. Cleared by an
    # operator through Logos' clear-unsupported endpoint after fixing the
    # underlying cause. None on profiles written before this flag existed.
    calibration_unsupported: bool | None = None
    # Reason code matching FatalLoadErrorPattern.reason_code, for diagnostics.
    # Surfaced to ops in master logs alongside `calibration_unsupported=True`.
    calibration_unsupported_reason: str | None = None
    # Metal only: this node's working-set budget (MB) when this model last
    # failed calibration with a capacity-like error. The orchestrator
    # compares this across nodes to skip retrying on any node no bigger.
    # Clear a false positive: set this key to null under
    # capabilities_overrides.<model> in config.yml.
    metal_capacity_floor_mb: float | None = None
    # --max-model-len that calibration auto-injected because the operator's
    # pinned kv_cache_memory_bytes couldn't hold one request at the model's
    # default max_seq_len (see vllm_compat.py's _extract_vllm_max_model_len_suggestion).
    # None = the model fit at default and no flag was passed during calibration.
    # The lane spawner reuses this so production matches the configuration that
    # actually passed the binary search.
    calibration_max_model_len: int | None = None
    # --max-num-seqs that calibration auto-injected for a hybrid Mamba/SSM
    # model whose state-cache block pool was smaller than vLLM's default 1024
    # (see vllm_compat.py's _extract_vllm_max_num_seqs_suggestion). None = no
    # cap was needed. The lane spawner reuses this so production runs with the
    # same ceiling that passed calibration — otherwise the lane reverts to
    # 1024 and aborts CUDA-graph capture at startup.
    calibration_max_num_seqs: int | None = None
    # Per-KV max_model_len sweep captured by calibration, ordered by ascending
    # kv_mb. None for legacy profiles.
    kv_cache_to_max_model_len_pairs: list[dict[str, Any]] | None = None
    # Central-store bookkeeping, echoed back in the runtime status.
    # sync_revision is the orchestrator's revision this record reflects; a
    # local calibration carries calibration_origin="local", no
    # calibration_id and its calibration_key until the snapshot is linked.
    sync_revision: int = 0
    calibration_id: int | None = None
    calibration_origin: str | None = None
    calibration_stale: bool | None = None
    calibration_key: dict[str, Any] | None = None

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
            "num_key_value_heads": self.num_key_value_heads,
            "max_context_length": self.max_context_length,
            "min_context_fraction": self.min_context_fraction,
            "measurement_count": self.measurement_count,
            "last_measured_epoch": self.last_measured_epoch,
            "residency_source": self.residency_source,
            "enforce_eager_at_calibration": self.enforce_eager_at_calibration,
            "host_ram_mb": self.host_ram_mb,
            "host_ram_residual_mb": self.host_ram_residual_mb,
            "sleep_l1_transient_host_ram_mb": self.sleep_l1_transient_host_ram_mb,
            "sleep_l2_transient_host_ram_mb": self.sleep_l2_transient_host_ram_mb,
            "cold_load_time_s": self.cold_load_time_s,
            "wake_from_sleep_time_s": self.wake_from_sleep_time_s,
            "sleep_mode_disabled": self.sleep_mode_disabled,
            "calibration_unsupported": self.calibration_unsupported,
            "calibration_unsupported_reason": self.calibration_unsupported_reason,
            "metal_capacity_floor_mb": self.metal_capacity_floor_mb,
            "calibration_max_model_len": self.calibration_max_model_len,
            "calibration_max_num_seqs": self.calibration_max_num_seqs,
            "kv_cache_to_max_model_len_pairs": self.kv_cache_to_max_model_len_pairs,
            "sync_revision": self.sync_revision,
            "calibration_id": self.calibration_id,
            "calibration_origin": self.calibration_origin,
            "calibration_stale": self.calibration_stale,
            "calibration_key": self.calibration_key,
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
    """Model VRAM profiles, held in memory and synced with Logos."""

    def __init__(
        self,
        model_profile_overrides: dict[str, dict] | None = None,
    ) -> None:
        self._profiles: dict[str, ModelProfileRecord] = {}
        self._lock = threading.Lock()
        # model -> (calibration key this node computes for it now, its hash)
        self._calibration_keys: dict[str, tuple[dict[str, Any], str]] = {}
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

    @staticmethod
    def _calibrated_tp_conflicts(profile: ModelProfileRecord, tensor_parallel_size: int | None) -> bool:
        """True when a runtime lane ran at a TP the calibrated profile did not record.

        A calibrated profile's tensor_parallel_size is the single source of
        truth: its base_residency, KV envelope, and max_model_len pairs were
        all measured under that TP. A lane that ran at a different TP
        (re-inferred at spawn time, a stale value from upstream) produces
        measurements that describe a different configuration — recording
        them, or letting the runtime TP overwrite the calibrated one, would
        leave a split-brain profile.
        """
        return (
            tensor_parallel_size is not None
            and tensor_parallel_size > 0
            and profile.residency_source == "calibrated"
            and profile.tensor_parallel_size is not None
            and profile.tensor_parallel_size != tensor_parallel_size
        )

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
            if profile.tensor_parallel_size is not None and profile.tensor_parallel_size != tensor_parallel_size:
                tp_changed = True
            profile.tensor_parallel_size = tensor_parallel_size
        return tp_changed

    def add_overrides(self, overrides: dict[str, dict[str, Any]]) -> None:
        """Merge additional manual overrides (e.g. from capabilities_overrides).

        Re-applies the merged overrides to profile records that already exist:
        records restored from Logos are otherwise never revisited after
        startup, so an override that arrives late — this
        method is also called from the lane-spawn path for profile-level keys
        routed out of engines.vllm.model_overrides — would be missing from the
        live record and from the runtime snapshot the server planner reads.
        """
        if not overrides:
            return
        with self._lock:
            for model_name, ov in overrides.items():
                if not isinstance(ov, dict) or not ov:
                    continue
                existing = self._manual_overrides.get(model_name)
                if existing is not None:
                    existing.update(ov)
                else:
                    self._manual_overrides[model_name] = dict(ov)
            for model_name in overrides:
                profile = self._profiles.get(model_name)
                if profile is not None:
                    self._apply_manual_overrides(model_name, profile)
        logger.info(
            "Added inline profile overrides for %d model(s): %s",
            len(overrides),
            ", ".join(sorted(overrides)),
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
        if "calibration_max_model_len" in overrides:
            profile.calibration_max_model_len = int(overrides["calibration_max_model_len"])
            applied.append(f"calibration_max_model_len={profile.calibration_max_model_len}")
        if "calibration_max_num_seqs" in overrides:
            profile.calibration_max_num_seqs = int(overrides["calibration_max_num_seqs"])
            applied.append(f"calibration_max_num_seqs={profile.calibration_max_num_seqs}")
        if "kv_cache_to_max_model_len_pairs" in overrides:
            raw_pairs = overrides["kv_cache_to_max_model_len_pairs"]
            if isinstance(raw_pairs, list):
                parsed_pairs: list[dict[str, Any]] = []
                for item in raw_pairs:
                    if not isinstance(item, dict):
                        continue
                    try:
                        kv_mb = float(item.get("kv_mb"))
                        max_model_len = int(item.get("max_model_len"))
                    except (TypeError, ValueError):
                        continue
                    if kv_mb <= 0 or max_model_len <= 0:
                        continue
                    entry: dict[str, Any] = {"kv_mb": kv_mb, "max_model_len": max_model_len}
                    # Preserve the achievable concurrency (parallelity factor) when present.
                    raw_par = item.get("parallelity")
                    if raw_par is not None:
                        try:
                            par = float(raw_par)
                        except (TypeError, ValueError):
                            par = 0.0
                        if par > 0:
                            entry["parallelity"] = par
                    parsed_pairs.append(entry)
                profile.kv_cache_to_max_model_len_pairs = parsed_pairs or None
                applied.append(
                    "kv_cache_to_max_model_len_pairs=" f"{len(profile.kv_cache_to_max_model_len_pairs or [])}"
                )
        if "min_context_fraction" in overrides:
            try:
                fraction = float(overrides["min_context_fraction"])
            except (TypeError, ValueError):
                logger.warning(
                    "%s: min_context_fraction=%r is not a number — ignoring it",
                    model_name,
                    overrides["min_context_fraction"],
                )
            else:
                profile.min_context_fraction = max(0.0, min(1.0, fraction))
                applied.append(f"min_context_fraction={profile.min_context_fraction:.2f}")
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
        if "metal_capacity_floor_mb" in overrides:
            # null clears a floor a false-positive capacity failure set
            # (see mark_capacity_floor) — the only way to undo it, since
            # that method only ever raises the stored value.
            value = overrides["metal_capacity_floor_mb"]
            if value is None:
                profile.metal_capacity_floor_mb = None
                applied.append("metal_capacity_floor=cleared")
            else:
                profile.metal_capacity_floor_mb = float(value)
                applied.append(f"metal_capacity_floor={profile.metal_capacity_floor_mb:.0f}MB")

        if applied:
            logger.info("Applied manual overrides for %s: %s", model_name, ", ".join(applied))
        return bool(applied)

    def seed_capabilities(self, model_names: list[str], engine: str = "vllm") -> None:
        """Pre-create profile stubs for capabilities models before any lane is loaded.

        If a profile already exists (restored from Logos — e.g. from a prior
        calibration run) it is left untouched. Only applies manual overrides
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
                    "Logos calibrates it in its next calibration window.",
                    model_name,
                )

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
        A lane that ran at a TP different from the calibrated profile's TP
        records nothing: the calibrated TP is authoritative, and the
        measurement would describe a different configuration.
        """
        if effective_vram_mb <= 0:
            return

        with self._lock:
            profile = self._profiles.setdefault(model_name, ModelProfileRecord())
            if self._calibrated_tp_conflicts(profile, tensor_parallel_size):
                logger.warning(
                    "Model profile [%s] %s — discarding loaded-VRAM measurement: "
                    "lane ran at tensor_parallel_size=%d but the calibrated profile says %d. "
                    "The calibrated TP is the source of truth; the profile is left untouched.",
                    (profile.residency_source or "unknown").upper(),
                    model_name,
                    tensor_parallel_size,
                    profile.tensor_parallel_size,
                )
                return
            tp_changed = self._update_metadata(
                profile,
                engine=engine,
                observed_gpu_memory_utilization=observed_gpu_memory_utilization,
                tensor_parallel_size=tensor_parallel_size,
            )

            if tp_changed:
                logger.info(
                    "TP size changed for %s — resetting VRAM measurements " "(old loaded=%.0f, new=%.0f)",
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
                    elif tp_changed or profile.base_residency_mb is None or profile.residency_source == "hf":
                        # "hf" is a best-effort guess, not a prior real
                        # measurement — the first live one replaces it
                        # exactly instead of blending through it via EMA.
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
                src.upper(),
                model_name,
                profile.base_residency_mb or 0,
                profile.kv_budget_mb or 0,
                profile.loaded_vram_mb or 0,
                kv_cache_sent_mb,
                profile.measurement_count,
            )

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

    def record_sleeping_vram(
        self,
        model_name: str,
        residual_vram_mb: float,
        *,
        engine: str | None = None,
        observed_gpu_memory_utilization: float | None = None,
        tensor_parallel_size: int | None = None,
    ) -> None:
        """Called after successful sleep with the lane's measured residual VRAM.

        Like record_loaded_vram, a lane that ran at a TP different from the
        calibrated profile's TP records nothing — the calibrated TP is
        authoritative and the measurement would describe a different
        configuration.
        """
        if residual_vram_mb < 0:
            return

        with self._lock:
            profile = self._profiles.setdefault(model_name, ModelProfileRecord())
            if self._calibrated_tp_conflicts(profile, tensor_parallel_size):
                logger.warning(
                    "Model profile [%s] %s — discarding sleeping-VRAM measurement: "
                    "lane ran at tensor_parallel_size=%d but the calibrated profile says %d. "
                    "The calibrated TP is the source of truth; the profile is left untouched.",
                    (profile.residency_source or "unknown").upper(),
                    model_name,
                    tensor_parallel_size,
                    profile.tensor_parallel_size,
                )
                return
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
                        "TP size changed for %s — resetting sleeping_residual_mb " "(old=%.0f, new=%.0f)",
                        model_name,
                        profile.sleeping_residual_mb or 0,
                        residual_vram_mb,
                    )
                profile.sleeping_residual_mb = residual_vram_mb
            else:
                profile.sleeping_residual_mb = _ema(profile.sleeping_residual_mb, residual_vram_mb)
            profile.last_measured_epoch = time.time()

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

        Both fields are high-water marks, not EMA averages. Long-lived
        EngineCores accumulate sticky host shared-memory that sleep→wake does
        not clear; blending a heavy observation with a fresh lean replica
        would understate the lasting ceiling the planner needs for cold-load
        and sleep-vs-stop gates.
        """
        if host_ram_mb <= 0:
            return
        with self._lock:
            profile = self._profiles.setdefault(model_name, ModelProfileRecord())
            if sleeping:
                prior = profile.host_ram_residual_mb
                profile.host_ram_residual_mb = host_ram_mb if prior is None else max(prior, host_ram_mb)
            else:
                prior = profile.host_ram_mb
                profile.host_ram_mb = host_ram_mb if prior is None else max(prior, host_ram_mb)
            profile.last_measured_epoch = time.time()

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
        return True

    def mark_calibration_unsupported(self, model_name: str, unsupported: bool, reason_code: str | None = None) -> bool:
        """Record whether this model is permanently uncalibratable on this worker.

        Returns True when the stored value changed. Used by the
        server-orchestrated calibration path to tell the master "stop
        scheduling this model for calibration — it cannot succeed here
        until an operator clears the verdict in Logos."

        Setting ``unsupported=False`` is treated as a clearing operation:
        it never creates a new profile entry, only updates an existing
        one — same convention as :meth:`mark_sleep_mode_disabled`. When
        clearing, ``reason_code`` is also nulled out.
        """
        with self._lock:
            if not unsupported and model_name not in self._profiles:
                return False
            profile = self._profiles.setdefault(model_name, ModelProfileRecord())
            changed = profile.calibration_unsupported != unsupported or profile.calibration_unsupported_reason != (
                reason_code if unsupported else None
            )
            if not changed:
                return False
            profile.calibration_unsupported = unsupported
            profile.calibration_unsupported_reason = reason_code if unsupported else None
        return True

    def mark_capacity_floor(self, model_name: str, floor_mb: float) -> bool:
        """Record that this model failed to fit under *floor_mb* on this node.

        Only ever raises the stored value — see the config.yml override in
        _apply_manual_overrides to undo a false positive instead.
        """
        with self._lock:
            profile = self._profiles.setdefault(model_name, ModelProfileRecord())
            current = profile.metal_capacity_floor_mb
            new_floor = floor_mb if current is None else max(current, floor_mb)
            if new_floor == current:
                return False
            profile.metal_capacity_floor_mb = new_floor
        return True

    def apply_hf_precheck(
        self,
        model_name: str,
        *,
        disk_size_bytes: int | None = None,
        base_residency_mb: float | None = None,
        kv_per_token_bytes: int | None = None,
        num_key_value_heads: int | None = None,
        max_context_length: int | None = None,
    ) -> bool:
        """Persist HF-derived compatibility-precheck estimates.

        Returns True when the stored value changed. Never overwrites an
        operator-provided config.yml override for the same field. Only sets
        base_residency_mb + residency_source="hf" when the profile has no
        higher-priority source yet (None, "hf", or "cached") — a real
        "measured"/"calibrated"/"override" value always wins.
        kv_per_token_bytes/max_context_length/disk_size_bytes have no
        higher-priority writer to conflict with, so they're set unconditionally
        (subject only to the manual-override check).

        ``num_key_value_heads`` has no manual-override key of its own — it is
        pure geometry, not a tunable — so it is set unconditionally whenever
        HF provides it. The master's capacity planner needs it alongside
        kv_per_token_bytes to derive a per-rank KV budget for the selected
        tp; kv_per_token_bytes alone is the whole-model (every-head) figure.
        """
        with self._lock:
            # Read under the lock too — add_overrides also runs under it, and
            # reading this beforehand risks a stale empty dict racing a
            # just-added override, letting the HF value overwrite it below.
            overrides = self._manual_overrides.get(model_name) or {}
            profile = self._profiles.setdefault(model_name, ModelProfileRecord())
            changed = False

            if "disk_size_bytes" not in overrides and disk_size_bytes and profile.disk_size_bytes != disk_size_bytes:
                profile.disk_size_bytes = disk_size_bytes
                changed = True
            if (
                "kv_per_token_bytes" not in overrides
                and kv_per_token_bytes
                and profile.kv_per_token_bytes != kv_per_token_bytes
            ):
                profile.kv_per_token_bytes = kv_per_token_bytes
                changed = True
            if num_key_value_heads and profile.num_key_value_heads != num_key_value_heads:
                profile.num_key_value_heads = num_key_value_heads
                changed = True
            if (
                "max_context_length" not in overrides
                and max_context_length
                and profile.max_context_length != max_context_length
            ):
                profile.max_context_length = max_context_length
                changed = True
            if (
                "base_residency_mb" not in overrides
                and base_residency_mb
                and base_residency_mb > 0
                and profile.residency_source in (None, "hf", "cached")
            ):
                if profile.base_residency_mb != base_residency_mb:
                    profile.base_residency_mb = base_residency_mb
                    changed = True
                if profile.residency_source != "hf":
                    profile.residency_source = "hf"
                    changed = True

        return changed

    def get_profile(self, model_name: str) -> ModelProfileRecord | None:
        with self._lock:
            return self._profiles.get(model_name)

    def get_all_profiles(self) -> dict[str, dict[str, Any]]:
        """All profiles as the runtime status reports them to Logos.

        Each carries the calibration key this node computes for the model
        right now and the fields its config.yml overrides, so Logos can tell
        configuration from measurement.
        """
        with self._lock:
            result = {}
            for name, profile in self._profiles.items():
                entry = profile.to_dict()
                entry["calibration_key_hash"] = self._calibration_keys.get(name, (None, None))[1]
                entry["overridden_fields"] = self._overridden_fields(name)
                result[name] = entry
            return result

    def _overridden_fields(self, model_name: str) -> list[str]:
        overrides = self._manual_overrides.get(model_name) or {}
        return sorted(key for key in overrides if key in _RECORD_FIELDS)

    def set_calibration_keys(self, keys: dict[str, dict[str, Any]]) -> None:
        from logos_worker_node.profile_fingerprint import key_hash  # noqa: PLC0415

        with self._lock:
            self._calibration_keys = {name: (key, key_hash(key)) for name, key in keys.items()}

    def calibration_key(self, model_name: str) -> dict[str, Any] | None:
        with self._lock:
            entry = self._calibration_keys.get(model_name)
        return entry[0] if entry is not None else None

    def calibration_key_hashes(self) -> dict[str, str]:
        with self._lock:
            return {name: digest for name, (_, digest) in self._calibration_keys.items()}

    def replace_from_sync(self, profiles: dict[str, Any], skip: frozenset[str] = frozenset()) -> list[str]:
        """Adopt profiles Logos sent; returns the models that were replaced.

        Models absent from ``profiles`` keep their record. ``skip`` protects
        a model whose calibration is running: its result must not be
        overwritten by a sync that predates it.
        """
        replaced: list[str] = []
        with self._lock:
            for model_name, data in profiles.items():
                if model_name in skip or not isinstance(data, dict):
                    continue
                self._profiles[str(model_name)] = _record_from_dict(data)
                self._apply_manual_overrides(str(model_name), self._profiles[str(model_name)])
                replaced.append(str(model_name))
        return replaced

    def apply_calibration_result(self, model_name: str, measured: dict[str, Any]) -> None:
        """Layer a fresh local calibration over the model's record.

        Logos snapshots it from the next runtime status and replies with the
        snapshot's calibration_id.
        """
        from logos_worker_node.calibration import merge_profile  # noqa: PLC0415

        with self._lock:
            prior = self._profiles.get(model_name)
            merged = merge_profile(prior.to_dict() if prior is not None else None, measured)
            record = _record_from_dict(merged)
            record.calibration_id = None
            record.calibration_origin = "local"
            record.calibration_stale = False
            key = self._calibration_keys.get(model_name)
            record.calibration_key = dict(key[0]) if key is not None else None
            self._profiles[model_name] = record
            self._apply_manual_overrides(model_name, record)


_RECORD_FIELDS = frozenset(field.name for field in fields(ModelProfileRecord))


def _optional_int(value: Any) -> int | None:
    return int(value) if value else None


def _record_from_dict(data: dict[str, Any]) -> ModelProfileRecord:
    """Build a record from a stored profile dict, tolerating legacy shapes."""
    persisted_source = data.get("residency_source")
    eager_at_cal = data.get("enforce_eager_at_calibration")
    # Profiles predating provenance tracking were always measured with the
    # hard-forced eager=True path; carrying that forward keeps the reuse
    # check from false-mismatching.
    if eager_at_cal is None and persisted_source == "calibrated":
        eager_at_cal = True
    pairs = data.get("kv_cache_to_max_model_len_pairs")
    key = data.get("calibration_key")
    return ModelProfileRecord(
        loaded_vram_mb=data.get("loaded_vram_mb"),
        sleeping_residual_mb=data.get("sleeping_residual_mb"),
        disk_size_bytes=data.get("disk_size_bytes"),
        base_residency_mb=data.get("base_residency_mb"),
        kv_budget_mb=data.get("kv_budget_mb"),
        min_kv_cache_mb=data.get("min_kv_cache_mb"),
        max_kv_cache_mb=data.get("max_kv_cache_mb"),
        engine=data.get("engine"),
        observed_gpu_memory_utilization=data.get("observed_gpu_memory_utilization"),
        min_gpu_memory_utilization_to_load=data.get("min_gpu_memory_utilization_to_load"),
        tensor_parallel_size=data.get("tensor_parallel_size"),
        kv_per_token_bytes=data.get("kv_per_token_bytes"),
        num_key_value_heads=data.get("num_key_value_heads"),
        max_context_length=data.get("max_context_length"),
        min_context_fraction=data.get("min_context_fraction"),
        measurement_count=int(data.get("measurement_count", 0) or 0),
        last_measured_epoch=float(data.get("last_measured_epoch", 0.0) or 0.0),
        residency_source=persisted_source or "cached",
        enforce_eager_at_calibration=eager_at_cal,
        host_ram_mb=data.get("host_ram_mb"),
        host_ram_residual_mb=data.get("host_ram_residual_mb"),
        sleep_l1_transient_host_ram_mb=data.get("sleep_l1_transient_host_ram_mb"),
        sleep_l2_transient_host_ram_mb=data.get("sleep_l2_transient_host_ram_mb"),
        cold_load_time_s=data.get("cold_load_time_s"),
        wake_from_sleep_time_s=data.get("wake_from_sleep_time_s"),
        sleep_mode_disabled=data.get("sleep_mode_disabled"),
        calibration_unsupported=data.get("calibration_unsupported"),
        calibration_unsupported_reason=data.get("calibration_unsupported_reason"),
        metal_capacity_floor_mb=data.get("metal_capacity_floor_mb"),
        calibration_max_model_len=_optional_int(data.get("calibration_max_model_len")),
        calibration_max_num_seqs=_optional_int(data.get("calibration_max_num_seqs")),
        kv_cache_to_max_model_len_pairs=pairs if isinstance(pairs, list) else None,
        sync_revision=int(data.get("sync_revision", 0) or 0),
        calibration_id=_optional_int(data.get("calibration_id")),
        calibration_origin=data.get("calibration_origin"),
        calibration_stale=data.get("calibration_stale"),
        calibration_key=key if isinstance(key, dict) else None,
    )
