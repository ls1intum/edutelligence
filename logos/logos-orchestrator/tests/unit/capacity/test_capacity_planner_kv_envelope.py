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


def test_orchestrator_flags_collapsed_envelope_for_recalibration():
    """A profile whose KV envelope has collapsed (min == max) is flagged as
    needing calibration so the orchestrator picks it up automatically — no
    manual SQL/YAML cleanup needed. This is what catches profiles written
    by the pre-fix calibrator that wrote ``search_lo`` (already mutated up
    to ``best_kv``) into ``min_kv_cache_mb``.
    """
    from unittest.mock import MagicMock

    from logos.capacity.calibration_orchestrator import CalibrationOrchestrator

    profile = ModelProfile(
        model_name="bad/envelope",
        engine="vllm",
        residency_source="calibrated",
        base_residency_mb=47733.0,
        sleeping_residual_mb=1724.0,
        sleep_l1_transient_host_ram_mb=10000.0,
        kv_budget_mb=10240.0,
        min_kv_cache_mb=10240.0,
        max_kv_cache_mb=10240.0,  # collapsed — bug signature
    )
    facade = MagicMock()
    facade.get_configured_models.return_value = ["bad/envelope"]
    facade.get_model_profiles.return_value = {"bad/envelope": profile}

    orch = CalibrationOrchestrator.__new__(CalibrationOrchestrator)
    orch._facade = facade
    assert orch._provider_has_uncalibrated_models(provider_id=42) is True


def test_orchestrator_skips_models_with_proper_envelope():
    """Healthy profiles (min < max) must NOT trigger needless re-calibration."""
    from unittest.mock import MagicMock

    from logos.capacity.calibration_orchestrator import CalibrationOrchestrator

    profile = ModelProfile(
        model_name="good/envelope",
        engine="vllm",
        residency_source="calibrated",
        base_residency_mb=47733.0,
        sleeping_residual_mb=1724.0,
        sleep_l1_transient_host_ram_mb=10000.0,
        kv_budget_mb=10240.0,
        min_kv_cache_mb=1024.0,
        max_kv_cache_mb=30720.0,  # real envelope from a fixed-code calibration
        kv_cache_to_max_model_len_pairs=[
            {"kv_mb": 1024.0, "max_model_len": 1000},
            {"kv_mb": 2048.0, "max_model_len": 2000},
        ],
    )
    facade = MagicMock()
    facade.get_configured_models.return_value = ["good/envelope"]
    facade.get_model_profiles.return_value = {"good/envelope": profile}

    orch = CalibrationOrchestrator.__new__(CalibrationOrchestrator)
    orch._facade = facade
    assert orch._provider_has_uncalibrated_models(provider_id=42) is False


def test_orchestrator_flags_missing_kv_max_model_len_pairs_for_recalibration():
    """Legacy calibrated profiles without the pair curve must be recalibrated."""
    from unittest.mock import MagicMock

    from logos.capacity.calibration_orchestrator import CalibrationOrchestrator

    profile = ModelProfile(
        model_name="missing/pairs",
        engine="vllm",
        residency_source="calibrated",
        base_residency_mb=47733.0,
        sleeping_residual_mb=1724.0,
        sleep_l1_transient_host_ram_mb=10000.0,
        kv_budget_mb=10240.0,
        min_kv_cache_mb=1024.0,
        max_kv_cache_mb=30720.0,
        kv_cache_to_max_model_len_pairs=None,
    )
    facade = MagicMock()
    facade.get_configured_models.return_value = ["missing/pairs"]
    facade.get_model_profiles.return_value = {"missing/pairs": profile}

    orch = CalibrationOrchestrator.__new__(CalibrationOrchestrator)
    orch._facade = facade
    assert orch._provider_has_uncalibrated_models(provider_id=42) is True


def test_select_kv_pair_prefers_smallest_kv_at_best_context():
    """Worked example: free=4G with pairs (1G,1000),(2G,2000),(3G,2000).

    Highest fitting context is 2000 and the planner must choose the smallest
    KV that achieves it (2G), not 3G.
    """
    profile = ModelProfile(
        model_name="pair/model",
        engine="vllm",
        kv_cache_to_max_model_len_pairs=[
            {"kv_mb": 1024.0, "max_model_len": 1000},
            {"kv_mb": 2048.0, "max_model_len": 2000},
            {"kv_mb": 3072.0, "max_model_len": 2000},
        ],
    )
    kv_mb, max_model_len = CapacityPlanner._select_kv_mb_max_model_len_pair(profile, available_for_kv_mb=4096.0)
    assert kv_mb == 2048.0
    assert max_model_len == 2000


def test_select_kv_pair_only_uses_fitting_pairs():
    """Worked examples for free=1G and free=2.5G."""
    profile = ModelProfile(
        model_name="pair/model",
        engine="vllm",
        kv_cache_to_max_model_len_pairs=[
            {"kv_mb": 1024.0, "max_model_len": 1000},
            {"kv_mb": 2048.0, "max_model_len": 2000},
            {"kv_mb": 3072.0, "max_model_len": 2000},
        ],
    )

    kv_mb_1g, max_model_len_1g = CapacityPlanner._select_kv_mb_max_model_len_pair(
        profile,
        available_for_kv_mb=1024.0,
    )
    assert kv_mb_1g == 1024.0
    assert max_model_len_1g == 1000

    kv_mb_25g, max_model_len_25g = CapacityPlanner._select_kv_mb_max_model_len_pair(
        profile,
        available_for_kv_mb=2560.0,
    )
    assert kv_mb_25g == 2048.0
    assert max_model_len_25g == 2000


def test_select_kv_pair_ignores_zero_plateau_entries():
    """Stale 0-max_model_len plateau points must not break selection.

    Qwen-3.6-35B shipped pairs (1G->101376),(2G->205920) plus a 0-plateau for
    3G..10G. With enough KV headroom the planner must still pick (2G, 205920) —
    the 0 entries are never the max, so they are inert.
    """
    profile = ModelProfile(
        model_name="qwen/35b",
        engine="vllm",
        kv_cache_to_max_model_len_pairs=[
            {"kv_mb": 1024.0, "max_model_len": 101376},
            {"kv_mb": 2048.0, "max_model_len": 205920},
            {"kv_mb": 3072.0, "max_model_len": 0},
            {"kv_mb": 4096.0, "max_model_len": 0},
        ],
    )
    kv_mb, max_model_len = CapacityPlanner._select_kv_mb_max_model_len_pair(profile, available_for_kv_mb=5647.0)
    assert (kv_mb, max_model_len) == (2048.0, 205920)


def _planner_for_kv_estimate(available_total_mb: float) -> CapacityPlanner:
    """A CapacityPlanner stub exposing just what _estimate_available_for_kv_mb needs."""
    from unittest.mock import MagicMock

    planner = CapacityPlanner.__new__(CapacityPlanner)
    ledger = MagicMock()
    ledger.get_effective_available_mb.side_effect = lambda _pid, raw: raw
    planner._vram_ledger = ledger
    return planner


def test_estimate_available_for_kv_uses_node_ownership_basis_not_transient_free():
    """KV is sized against the room the lane OWNS post-placement (total VRAM −
    weights), NOT the transient pre-reclaim free VRAM. A large lane must not be
    starved to a floor KV just because idle warmup lanes are briefly co-resident.

    Two unit subtleties also covered:
      * weights = base − kv_budget×tp  (base is TOTAL across TP GPUs; kv_budget
        is PER-RANK). Qwen35B: 94667 − 10240×2 = 74187.
      * basis is total_vram_mb (98280), so even with only 45001MB currently free
        (other models resident) the estimate stays high:
        98280/2 − 74187/2 − 1024 ≈ 11022/GPU  → the (2G, 205920) pair fits.
    """
    from unittest.mock import MagicMock

    profile = ModelProfile(
        model_name="qwen/35b",
        engine="vllm",
        residency_source="calibrated",
        base_residency_mb=94667.0,
        kv_budget_mb=10240.0,
        min_kv_cache_mb=1024.0,
        max_kv_cache_mb=10240.0,
    )
    capacity = MagicMock()
    capacity.total_vram_mb = 98280.0
    capacity.available_vram_mb = 45001.0  # other warmup lanes resident — must be IGNORED
    planner = _planner_for_kv_estimate(45001.0)

    avail = planner._estimate_available_for_kv_mb(profile, capacity, provider_id=1, tp=2)
    assert avail is not None
    assert avail > 2048.0  # the (2G, 205920) pair fits despite tight current-free
    # Node-ownership basis (total, not the 45001 transient free): ~11022/GPU.
    assert 10500.0 < avail < 11500.0


def test_estimate_available_for_kv_falls_back_to_free_when_total_unknown():
    """If the capacity snapshot has no total_vram_mb, fall back to current free."""
    from unittest.mock import MagicMock

    profile = ModelProfile(
        model_name="qwen/35b",
        engine="vllm",
        residency_source="calibrated",
        base_residency_mb=94667.0,
        kv_budget_mb=10240.0,
    )
    capacity = MagicMock()
    capacity.total_vram_mb = 0.0
    capacity.available_vram_mb = 97770.0
    planner = _planner_for_kv_estimate(97770.0)

    avail = planner._estimate_available_for_kv_mb(profile, capacity, provider_id=1, tp=2)
    # Fallback path: 97770/2 − 74187/2 − 1024 ≈ 10767.
    assert 10500.0 < avail < 11000.0


def test_estimate_available_for_kv_uses_full_base_for_uncalibrated():
    """Uncalibrated/measured profiles keep the weights-only base convention —
    no kv_budget to subtract, so the full base is used."""
    from unittest.mock import MagicMock

    profile = ModelProfile(
        model_name="x/y",
        engine="vllm",
        residency_source="measured",
        base_residency_mb=40000.0,
        kv_budget_mb=4096.0,
    )
    capacity = MagicMock()
    capacity.total_vram_mb = 90000.0
    capacity.available_vram_mb = 50000.0  # ignored — node-ownership uses total
    planner = _planner_for_kv_estimate(50000.0)

    avail = planner._estimate_available_for_kv_mb(profile, capacity, provider_id=1, tp=2)
    # node-ownership: per_gpu_total 45000 - per_gpu_base 20000 - 1024 headroom = 23976
    # (measured profile → no kv_budget subtraction from the weights-only base)
    assert abs(avail - 23976.0) < 1.0
