"""Central model-profile store: field ownership and profile resolution.

model_profiles.profile holds each node's full record, model_calibrations
immutable snapshots of successful calibrations.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from typing import Any, Mapping

SYNC_MODEL_PROFILES_ACTION = "sync_model_profiles"

# Fields a calibration run measures; snapshotted into model_calibrations.
CALIBRATION_FIELDS = frozenset(
    {
        "base_residency_mb",
        "loaded_vram_mb",
        "kv_budget_mb",
        "min_kv_cache_mb",
        "max_kv_cache_mb",
        "kv_cache_to_max_model_len_pairs",
        "calibration_max_model_len",
        "calibration_max_num_seqs",
        "tensor_parallel_size",
        "enforce_eager_at_calibration",
        "sleep_mode_disabled",
        "engine",
        "sleeping_residual_mb",
        "sleep_l1_transient_host_ram_mb",
        "sleep_l2_transient_host_ram_mb",
        "host_ram_residual_mb",
        "cold_load_time_s",
        "wake_from_sleep_time_s",
        "residency_source",
        "last_measured_epoch",
    }
)

# Sync bookkeeping the worker echoes; derived or owned centrally, never stored.
SYNC_METADATA_FIELDS = frozenset(
    {
        "sync_revision",
        "calibration_id",
        "calibration_origin",
        "calibration_stale",
        "calibration_key",
        "calibration_key_hash",
        "calibration_duration_s",
        "overridden_fields",
    }
)


def shared_profiles_enabled() -> bool:
    """Whether a node may take over another node's calibration."""
    return os.environ.get("LOGOS_SHARED_PROFILES", "1").strip().lower() not in ("0", "false", "no", "off")


def shared_profile_max_age_days() -> int:
    try:
        return max(1, int(os.environ.get("LOGOS_SHARED_PROFILE_MAX_AGE_DAYS", "30")))
    except ValueError:
        return 30


def is_central_profile_payload(profiles: Mapping[str, Any]) -> bool:
    """True when the worker keeps no local store and syncs with the database."""
    return any(isinstance(p, dict) and "sync_revision" in p for p in profiles.values())


def reported_profile(profile: Mapping[str, Any]) -> dict[str, Any]:
    """What the node runs with, operator overrides included."""
    return {key: value for key, value in profile.items() if key not in SYNC_METADATA_FIELDS}


def overridden_fields(profile: Mapping[str, Any]) -> list[str]:
    """Fields the worker's config.yml overrides; they are no measurement."""
    overridden = profile.get("overridden_fields")
    return sorted({str(field) for field in overridden}) if isinstance(overridden, list) else []


def persistable_profile(profile: Mapping[str, Any]) -> dict[str, Any]:
    """The part of a worker echo that belongs in ``model_profiles.profile``."""
    skip = set(overridden_fields(profile))
    return {key: value for key, value in reported_profile(profile).items() if key not in skip}


def calibration_snapshot(profile: Mapping[str, Any]) -> dict[str, Any]:
    return {key: profile[key] for key in CALIBRATION_FIELDS if key in profile}


def is_new_local_calibration(profile: Mapping[str, Any]) -> bool:
    """A calibration this node just ran and the database has no snapshot of."""
    try:
        epoch = float(profile.get("last_measured_epoch") or 0.0)
    except (TypeError, ValueError):
        epoch = 0.0
    return (
        profile.get("residency_source") == "calibrated"
        and profile.get("calibration_origin") == "local"
        and not profile.get("calibration_id")
        and bool(profile.get("calibration_key_hash"))
        and epoch > 0
    )


def profile_digest(sync_revision: int, profile: Mapping[str, Any]) -> str:
    payload = json.dumps([sync_revision, profile], sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# Every status of a loaded lane bumps these and nudges the EMA floats, so
# a digest over them changes each time; such changes are written lazily.
VOLATILE_FIELDS = frozenset({"last_measured_epoch", "measurement_count"})
VOLATILE_FLUSH_SECONDS = 300.0


def _coarse(value: Any) -> Any:
    if isinstance(value, float):
        return float(f"{value:.3g}")
    if isinstance(value, dict):
        return {key: _coarse(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_coarse(item) for item in value]
    return value


def material_profile(profile: Mapping[str, Any]) -> dict[str, Any]:
    """The part of an echo whose change is written at once.

    Floats keep three significant digits, so EMA jitter does not count.
    """
    return {key: _coarse(value) for key, value in profile.items() if key not in VOLATILE_FIELDS}


def effective_profile(provider_id: int, row: Mapping[str, Any]) -> dict[str, Any]:
    """The profile a worker runs with, built from one model_profiles row.

    ``row`` also carries the joined ``cal_*`` columns of its calibration.
    """
    stored = row.get("profile")
    profile = dict(stored) if isinstance(stored, dict) else {}
    profile["sync_revision"] = int(row.get("sync_revision") or 0)
    cal_id = row.get("cal_id")
    if cal_id is None or row.get("cal_invalidated_at") is not None:
        return profile
    cal_key_hash = row.get("cal_key_hash")
    if cal_key_hash is None:
        origin = "legacy"
    elif row.get("cal_source_provider_id") == provider_id:
        origin = "local"
    else:
        origin = "shared"
    reported = row.get("calibration_key_hash")
    # A key change (vLLM bump, config edit) keeps the old result serving
    # until the next calibration window replaces it.
    stale = cal_key_hash is None or (bool(reported) and reported != cal_key_hash)
    profile["calibration_id"] = int(cal_id)
    profile["calibration_origin"] = origin
    profile["calibration_stale"] = stale
    return profile


def base_residency_agrees(previous: Any, current: Any, tolerance: float = 0.05) -> bool | None:
    """Whether two calibrations of one key measured the same footprint."""
    try:
        prev, cur = float(previous), float(current)
    except (TypeError, ValueError):
        return None
    if prev <= 0 or cur <= 0:
        return None
    return abs(cur - prev) <= tolerance * prev


class ProfileWriteCache:
    """Skips database writes for profiles a worker echoes unchanged.

    Statuses persist in worker threads while endpoints forget entries.
    """

    def __init__(self, flush_seconds: float = VOLATILE_FLUSH_SECONDS) -> None:
        # (provider, model) -> (digest, material digest, monotonic write time)
        self._entries: dict[tuple[int, str], tuple[str, str | None, float]] = {}
        # Bumped by forget(): a write that started before must not repopulate.
        self._model_generations: dict[tuple[int, str], int] = {}
        self._provider_generations: dict[int, int] = {}
        self._flush_seconds = flush_seconds
        self._lock = threading.Lock()

    def generation(self, provider_id: int, model_name: str) -> tuple[int, int]:
        """Read before a database write; pass it to remember() afterwards."""
        with self._lock:
            return (
                self._provider_generations.get(provider_id, 0),
                self._model_generations.get((provider_id, model_name), 0),
            )

    def unchanged(
        self,
        provider_id: int,
        model_name: str,
        digest: str,
        material: str | None = None,
        now: float | None = None,
    ) -> bool:
        """True when the stored row is current enough to skip this write.

        With ``material``, volatile-only changes wait for the flush interval.
        """
        with self._lock:
            entry = self._entries.get((provider_id, model_name))
        if entry is None:
            return False
        stored, stored_material, written_at = entry
        if stored == digest:
            return True
        if material is None or stored_material != material:
            return False
        return (time.monotonic() if now is None else now) - written_at < self._flush_seconds

    def remember(
        self,
        provider_id: int,
        model_name: str,
        digest: str,
        material: str | None = None,
        now: float | None = None,
        generation: tuple[int, int] | None = None,
    ) -> None:
        written_at = time.monotonic() if now is None else now
        key = (provider_id, model_name)
        with self._lock:
            current = (self._provider_generations.get(provider_id, 0), self._model_generations.get(key, 0))
            if generation is not None and generation != current:
                return
            self._entries[key] = (digest, material, written_at)

    def forget(self, provider_id: int, model_name: str | None = None) -> None:
        with self._lock:
            if model_name is not None:
                key = (provider_id, model_name)
                self._entries.pop(key, None)
                self._model_generations[key] = self._model_generations.get(key, 0) + 1
                return
            for key in [k for k in self._entries if k[0] == provider_id]:
                del self._entries[key]
            # The provider generation alone invalidates older reads now.
            for key in [k for k in self._model_generations if k[0] == provider_id]:
                del self._model_generations[key]
            self._provider_generations[provider_id] = self._provider_generations.get(provider_id, 0) + 1
