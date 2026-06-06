"""Unit tests for the capacity planner's KV cache envelope selection.

These cover the static decision logic (``_select_kv_mb_from_envelope``) and
its interaction with ``_compute_kv_cache_bytes`` without spinning up a full
planner — both helpers operate purely on a ``ModelProfile`` dataclass plus an
optional available-VRAM scalar, so they can be exercised in isolation.

The behaviour we encode:

* No envelope on the profile → return None (caller falls back to the legacy
  ``kv_budget_mb`` estimate).
* Envelope present, no ``available_for_kv_mb`` provided → return the maximum
  (the planner has already passed a feasibility check by the time it asks).
* Envelope present, plenty of available VRAM → return the maximum (clamp is a
  no-op).
* Envelope present, tight available VRAM → return ``available`` (lowered from
  max but still above min).
* Envelope present, available below min → return min (the floor at which
  calibration confirmed the model still loads; going lower would mean the
  caller should fail feasibility instead).
"""

from __future__ import annotations

from logos.capacity.capacity_planner import CapacityPlanner
from logos.sdi.models import ModelProfile


def _profile_with_envelope(min_mb: float | None, max_mb: float | None) -> ModelProfile:
    return ModelProfile(
        model_name="test/model",
        engine="vllm",
        base_residency_mb=4000.0,
        kv_budget_mb=4096.0,  # legacy field, ignored by envelope path
        min_kv_cache_mb=min_mb,
        max_kv_cache_mb=max_mb,
    )


def test_select_returns_none_when_no_envelope():
    """Profiles predating the envelope feature use the legacy path."""
    profile = _profile_with_envelope(min_mb=None, max_mb=None)
    assert CapacityPlanner._select_kv_mb_from_envelope(profile, available_for_kv_mb=None) is None
    assert CapacityPlanner._select_kv_mb_from_envelope(profile, available_for_kv_mb=10000.0) is None


def test_select_returns_none_when_max_is_zero():
    """A zero max is the calibration's "I never wrote one" sentinel — fall back."""
    profile = _profile_with_envelope(min_mb=1024.0, max_mb=0.0)
    assert CapacityPlanner._select_kv_mb_from_envelope(profile, available_for_kv_mb=None) is None


def test_select_uses_max_when_no_available_hint():
    """No live VRAM signal → prefer the calibrated max; caller has already
    cleared feasibility before reaching this point."""
    profile = _profile_with_envelope(min_mb=1024.0, max_mb=8192.0)
    assert CapacityPlanner._select_kv_mb_from_envelope(profile, available_for_kv_mb=None) == 8192.0


def test_select_uses_max_when_available_exceeds_max():
    """Plenty of room → clamp is a no-op, return the calibrated max."""
    profile = _profile_with_envelope(min_mb=1024.0, max_mb=8192.0)
    assert CapacityPlanner._select_kv_mb_from_envelope(profile, available_for_kv_mb=40000.0) == 8192.0


def test_select_lowers_to_available_when_tight():
    """Tight available VRAM → spawn smaller, but still inside the envelope."""
    profile = _profile_with_envelope(min_mb=1024.0, max_mb=8192.0)
    # Available falls between min and max — caller spawns at "available".
    assert CapacityPlanner._select_kv_mb_from_envelope(profile, available_for_kv_mb=4096.0) == 4096.0


def test_select_clamps_to_min_when_available_below_floor():
    """Available below the calibrated floor → still return min, never go lower.

    The min is the smallest KV at which the model was *proven* to load and
    serve. Spawning below that would risk a load failure the calibrator
    already ruled out. The caller is expected to recognise the (min > true
    available) case via its own feasibility check and abandon the load.
    """
    profile = _profile_with_envelope(min_mb=1024.0, max_mb=8192.0)
    assert CapacityPlanner._select_kv_mb_from_envelope(profile, available_for_kv_mb=512.0) == 1024.0


def test_select_collapses_when_min_equals_max():
    """Operator-pinned ``kv_cache_memory_bytes`` makes min == max — both ends
    of the envelope are the same value, so the choice is invariant."""
    profile = _profile_with_envelope(min_mb=4096.0, max_mb=4096.0)
    assert CapacityPlanner._select_kv_mb_from_envelope(profile, available_for_kv_mb=None) == 4096.0
    assert CapacityPlanner._select_kv_mb_from_envelope(profile, available_for_kv_mb=10000.0) == 4096.0
    assert CapacityPlanner._select_kv_mb_from_envelope(profile, available_for_kv_mb=1024.0) == 4096.0
