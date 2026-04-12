"""Tests for ETTFT estimation, range-scaled correction, and weight span."""

import math

from logos.pipeline.ettft_estimator import (
    ReadinessTier,
    EttftEstimate,
    NORMALIZATION_HORIZON_S,
    CORRECTION_STRENGTH,
    OVERHEAD_WARM_S,
    OVERHEAD_SLEEPING_S,
    OVERHEAD_COLD_S,
    OVERHEAD_RECLAIM_S,
    CLOUD_OVERHEAD_S,
    CLOUD_LOW_HEADROOM_S,
    DEFAULT_GENERATION_TIME_S,
    MIN_SPAN_FLOOR,
    compute_weight_span,
    compute_corrected_score,
    estimate_ettft_local,
    estimate_ettft_azure,
)
from logos.sdi.models import (
    LaneSchedulerSignals,
    ModelSchedulerView,
    AzureCapacity,
)


def _make_view(
    model_id=1,
    model_name="test-model",
    provider_id=10,
    best_lane_state="loaded",
    best_sleep_state="unsupported",
    is_loaded=True,
    aggregate_active_requests=0,
    aggregate_queue_waiting=0.0,
    warmest_ttft_p95_seconds=0.0,
    gpu_cache_pressure_max=None,
    lanes=None,
):
    return ModelSchedulerView(
        model_id=model_id,
        model_name=model_name,
        provider_id=provider_id,
        is_loaded=is_loaded,
        best_lane_state=best_lane_state,
        best_sleep_state=best_sleep_state,
        aggregate_active_requests=aggregate_active_requests,
        aggregate_queue_waiting=aggregate_queue_waiting,
        warmest_ttft_p95_seconds=warmest_ttft_p95_seconds,
        gpu_cache_pressure_max=gpu_cache_pressure_max,
        lanes=lanes or [
            LaneSchedulerSignals(
                lane_id="lane-1", model_name=model_name,
                runtime_state=best_lane_state, sleep_state=best_sleep_state,
                is_vllm=False, active_requests=aggregate_active_requests,
                queue_waiting=aggregate_queue_waiting,
                requests_running=float(aggregate_active_requests),
                gpu_cache_usage_percent=gpu_cache_pressure_max,
                ttft_p95_seconds=warmest_ttft_p95_seconds,
                effective_vram_mb=8000.0, num_parallel=4,
            )
        ],
    )


# ---------------------------------------------------------------------------
# compute_weight_span tests
# ---------------------------------------------------------------------------


def test_weight_span_empty():
    assert compute_weight_span([]) == MIN_SPAN_FLOOR


def test_weight_span_single():
    """Single weight: spread=0, floor from abs value."""
    span = compute_weight_span([5.0])
    # max(0, 5*0.2, 1.0) = max(0, 1.0, 1.0) = 1.0
    assert span == 1.0


def test_weight_span_single_large():
    """Single large weight: abs_floor dominates."""
    span = compute_weight_span([20.0])
    # max(0, 20*0.2, 1.0) = max(0, 4.0, 1.0) = 4.0
    assert span == 4.0


def test_weight_span_spread_dominates():
    """When spread > abs_floor, spread wins."""
    span = compute_weight_span([5.0, 10.0])
    # max(5, 10*0.2, 1.0) = max(5, 2.0, 1.0) = 5.0
    assert span == 5.0


def test_weight_span_abs_floor_dominates():
    """When weights are close but large, abs_floor wins."""
    span = compute_weight_span([12.0, 13.0])
    # max(1, 13*0.2, 1.0) = max(1, 2.6, 1.0) = 2.6
    assert span == 2.6


def test_weight_span_negative_weights():
    """Handles negative weights correctly."""
    span = compute_weight_span([-3.0, 5.0])
    # max(8, max(3,5)*0.2, 1.0) = max(8, 1.0, 1.0) = 8.0
    assert span == 8.0


def test_weight_span_all_negative():
    """All negative weights."""
    span = compute_weight_span([-3.0, -1.0])
    # max(2, max(3,1)*0.2, 1.0) = max(2, 0.6, 1.0) = 2.0
    assert span == 2.0


def test_weight_span_identical():
    """Identical weights: spread=0, abs_floor applies."""
    span = compute_weight_span([7.0, 7.0])
    # max(0, 7*0.2, 1.0) = max(0, 1.4, 1.0) = 1.4
    assert abs(span - 1.4) < 1e-9


def test_weight_span_zeros():
    """All zeros: falls to MIN_SPAN_FLOOR."""
    span = compute_weight_span([0.0, 0.0])
    assert span == MIN_SPAN_FLOOR


# ---------------------------------------------------------------------------
# compute_corrected_score tests
# ---------------------------------------------------------------------------


def test_corrected_score_no_wait():
    """Zero wait → no penalty."""
    assert compute_corrected_score(10.0, 0.0, 5.0) == 10.0


def test_corrected_score_negative_wait():
    """Negative wait → no penalty."""
    assert compute_corrected_score(10.0, -1.0, 5.0) == 10.0


def test_corrected_score_zero_span():
    """Zero span → no penalty."""
    assert compute_corrected_score(10.0, 30.0, 0.0) == 10.0


def test_corrected_score_half_horizon():
    """Wait = half horizon → 50% of max penalty."""
    half = NORMALIZATION_HORIZON_S / 2
    score = compute_corrected_score(10.0, half, 5.0)
    expected = 10.0 - 0.5 * 5.0 * CORRECTION_STRENGTH
    assert abs(score - expected) < 1e-9


def test_corrected_score_full_horizon():
    """Wait = full horizon → 100% of max penalty."""
    score = compute_corrected_score(10.0, NORMALIZATION_HORIZON_S, 5.0)
    expected = 10.0 - 1.0 * 5.0 * CORRECTION_STRENGTH
    assert abs(score - expected) < 1e-9


def test_corrected_score_beyond_horizon():
    """Wait > horizon → clamped to max penalty."""
    score = compute_corrected_score(10.0, NORMALIZATION_HORIZON_S * 2, 5.0)
    expected = 10.0 - 1.0 * 5.0 * CORRECTION_STRENGTH
    assert abs(score - expected) < 1e-9


def test_corrected_score_inf_wait():
    """Infinite wait → full-span penalty."""
    score = compute_corrected_score(10.0, float("inf"), 5.0)
    expected = 10.0 - 5.0 * CORRECTION_STRENGTH
    assert abs(score - expected) < 1e-9


def test_corrected_score_negative_weight():
    """Negative classification weight: penalty still subtracts."""
    score = compute_corrected_score(-3.0, 45.0, 8.0)
    penalty = min(45.0 / NORMALIZATION_HORIZON_S, 1.0) * 8.0 * CORRECTION_STRENGTH
    expected = -3.0 - penalty
    assert abs(score - expected) < 1e-9


def test_corrected_score_same_state_ordering():
    """Two models with same wait: classification ordering preserved."""
    score_a = compute_corrected_score(12.0, 2.5, 5.0)
    score_b = compute_corrected_score(10.0, 2.5, 5.0)
    # Both get identical penalty, so 12 > 10 holds
    assert score_a > score_b


def test_corrected_score_cold_vs_warm():
    """Cold model (45s) penalized more than warm model (0s)."""
    warm_score = compute_corrected_score(10.0, 0.0, 5.0)
    cold_score = compute_corrected_score(13.0, 45.0, 5.0)
    # Warm: 10, Cold: 13 - (0.75 × 5 × 1.5) = 13 - 5.625 = 7.375
    assert warm_score > cold_score


# ---------------------------------------------------------------------------
# EttftEstimate dataclass tests
# ---------------------------------------------------------------------------


def test_ettft_ms_property():
    est = EttftEstimate(expected_wait_s=45.0, tier=ReadinessTier.COLD, reasoning="test")
    assert est.ettft_ms == 45000.0


def test_ettft_ms_zero():
    est = EttftEstimate(expected_wait_s=0.0, tier=ReadinessTier.WARM, reasoning="test")
    assert est.ettft_ms == 0.0


def test_ettft_ms_inf():
    est = EttftEstimate(expected_wait_s=float("inf"), tier=ReadinessTier.UNAVAILABLE, reasoning="test")
    assert est.ettft_ms == float("inf")


def test_ettft_estimate_fields():
    est = EttftEstimate(
        expected_wait_s=53.0,
        tier=ReadinessTier.COLD_RECLAIM,
        reasoning="test",
        state_overhead_s=53.0,
        queue_wait_s=0.0,
        needs_reclaim=True,
    )
    assert est.needs_reclaim is True
    assert est.state_overhead_s == 53.0
    assert est.queue_wait_s == 0.0


# ---------------------------------------------------------------------------
# estimate_ettft_local: WARM tier
# ---------------------------------------------------------------------------


def test_local_warm_loaded_no_queue():
    """Loaded model with no queue → WARM, 0s wait."""
    view = _make_view(
        best_lane_state="loaded",
        is_loaded=True,
        warmest_ttft_p95_seconds=0.15,
    )
    est = estimate_ettft_local(view, effective_parallel=4)
    assert est.tier == ReadinessTier.WARM
    assert est.expected_wait_s == 0.0
    assert est.state_overhead_s == 0.0
    assert est.queue_wait_s == 0.0


def test_local_warm_running():
    """Running model → WARM."""
    view = _make_view(
        best_lane_state="running",
        is_loaded=True,
    )
    est = estimate_ettft_local(view, effective_parallel=4)
    assert est.tier == ReadinessTier.WARM
    assert est.expected_wait_s == 0.0


def test_local_warm_with_queue():
    """Loaded model with scheduler queue → WARM + queue penalty."""
    view = _make_view(
        best_lane_state="loaded",
        is_loaded=True,
    )
    # 8 requests in queue, 4 parallel, 3s per generation
    est = estimate_ettft_local(
        view, effective_parallel=4, generation_time_s=3.0,
        scheduler_queue_depth=8,
    )
    assert est.tier == ReadinessTier.WARM
    assert est.state_overhead_s == 0.0
    # queue_wait = (8/4) × 3.0 = 6.0
    assert est.queue_wait_s == 6.0
    assert est.expected_wait_s == 6.0


# ---------------------------------------------------------------------------
# estimate_ettft_local: SLEEPING tier
# ---------------------------------------------------------------------------


def test_local_sleeping():
    """Sleeping lane → SLEEPING tier, ~2.5s overhead."""
    view = _make_view(
        best_lane_state="sleeping",
        best_sleep_state="sleeping",
        is_loaded=False,
    )
    est = estimate_ettft_local(view)
    assert est.tier == ReadinessTier.SLEEPING
    assert est.state_overhead_s == OVERHEAD_SLEEPING_S
    assert est.expected_wait_s == OVERHEAD_SLEEPING_S
    assert est.needs_reclaim is False


def test_local_sleeping_with_queue():
    """Sleeping + queue → overhead + queue penalty."""
    view = _make_view(
        best_lane_state="sleeping",
        best_sleep_state="sleeping",
        is_loaded=False,
    )
    est = estimate_ettft_local(
        view, effective_parallel=4, generation_time_s=3.0,
        scheduler_queue_depth=4,
    )
    assert est.tier == ReadinessTier.SLEEPING
    # overhead=2.5 + queue=(4/4)*3.0=3.0 = 5.5
    assert abs(est.expected_wait_s - 5.5) < 1e-9


def test_local_sleeping_reclaim():
    """Sleeping but KV cache needs more VRAM than available → SLEEPING_RECLAIM."""
    view = _make_view(
        best_lane_state="sleeping",
        best_sleep_state="sleeping",
        is_loaded=False,
    )
    est = estimate_ettft_local(
        view, available_vram_mb=1000.0, kv_budget_mb=2000.0,
    )
    assert est.tier == ReadinessTier.SLEEPING_RECLAIM
    assert est.state_overhead_s == OVERHEAD_SLEEPING_S + OVERHEAD_RECLAIM_S
    assert est.needs_reclaim is True
    assert est.expected_wait_s == OVERHEAD_SLEEPING_S + OVERHEAD_RECLAIM_S


def test_local_sleeping_no_reclaim_when_vram_sufficient():
    """Sleeping with sufficient VRAM for KV cache → plain SLEEPING."""
    view = _make_view(
        best_lane_state="sleeping",
        best_sleep_state="sleeping",
        is_loaded=False,
    )
    est = estimate_ettft_local(
        view, available_vram_mb=5000.0, kv_budget_mb=2000.0,
    )
    assert est.tier == ReadinessTier.SLEEPING
    assert est.needs_reclaim is False


# ---------------------------------------------------------------------------
# estimate_ettft_local: COLD tier
# ---------------------------------------------------------------------------


def test_local_cold():
    """Cold model → COLD tier, ~45s overhead."""
    view = _make_view(
        best_lane_state="cold",
        is_loaded=False,
    )
    est = estimate_ettft_local(view)
    assert est.tier == ReadinessTier.COLD
    assert est.state_overhead_s == OVERHEAD_COLD_S
    assert est.expected_wait_s == OVERHEAD_COLD_S
    assert est.ettft_ms == OVERHEAD_COLD_S * 1000


def test_local_starting():
    """Starting model treated same as cold."""
    view = _make_view(
        best_lane_state="starting",
        is_loaded=False,
    )
    est = estimate_ettft_local(view)
    assert est.tier == ReadinessTier.COLD


def test_local_cold_reclaim():
    """Cold model needs more VRAM than available → COLD_RECLAIM."""
    view = _make_view(
        best_lane_state="cold",
        is_loaded=False,
    )
    est = estimate_ettft_local(
        view, available_vram_mb=3000.0, model_vram_mb=5000.0,
    )
    assert est.tier == ReadinessTier.COLD_RECLAIM
    assert est.state_overhead_s == OVERHEAD_COLD_S + OVERHEAD_RECLAIM_S
    assert est.needs_reclaim is True
    assert est.expected_wait_s == OVERHEAD_COLD_S + OVERHEAD_RECLAIM_S


def test_local_cold_no_reclaim_when_vram_sufficient():
    """Cold with sufficient VRAM → plain COLD."""
    view = _make_view(
        best_lane_state="cold",
        is_loaded=False,
    )
    est = estimate_ettft_local(
        view, available_vram_mb=10000.0, model_vram_mb=5000.0,
    )
    assert est.tier == ReadinessTier.COLD
    assert est.needs_reclaim is False


def test_local_cold_with_queue():
    """Cold + queue → overhead + queue penalty."""
    view = _make_view(
        best_lane_state="cold",
        is_loaded=False,
    )
    est = estimate_ettft_local(
        view, effective_parallel=2, generation_time_s=3.0,
        scheduler_queue_depth=6,
    )
    assert est.tier == ReadinessTier.COLD
    # overhead=45 + queue=(6/2)*3=9 = 54
    assert abs(est.expected_wait_s - 54.0) < 1e-9


# ---------------------------------------------------------------------------
# estimate_ettft_local: UNAVAILABLE tier
# ---------------------------------------------------------------------------


def test_local_unavailable_no_lanes():
    """Empty lanes → UNAVAILABLE."""
    view = ModelSchedulerView(
        model_id=1, model_name="test", provider_id=10,
        is_loaded=False, best_lane_state="error", best_sleep_state="unsupported",
        aggregate_active_requests=0, aggregate_queue_waiting=0.0,
        warmest_ttft_p95_seconds=0.0, gpu_cache_pressure_max=None,
        lanes=[],
    )
    est = estimate_ettft_local(view)
    assert est.tier == ReadinessTier.UNAVAILABLE
    assert est.expected_wait_s == float("inf")


def test_local_unavailable_all_stopped():
    """All stopped/error lanes → UNAVAILABLE."""
    lanes = [
        LaneSchedulerSignals(
            lane_id="l1", model_name="m", runtime_state="stopped",
            sleep_state="unsupported", is_vllm=False, active_requests=0,
            queue_waiting=0.0, requests_running=0.0, gpu_cache_usage_percent=None,
            ttft_p95_seconds=0.0, effective_vram_mb=0.0, num_parallel=0,
        ),
        LaneSchedulerSignals(
            lane_id="l2", model_name="m", runtime_state="error",
            sleep_state="unsupported", is_vllm=False, active_requests=0,
            queue_waiting=0.0, requests_running=0.0, gpu_cache_usage_percent=None,
            ttft_p95_seconds=0.0, effective_vram_mb=0.0, num_parallel=0,
        ),
    ]
    view = _make_view(best_lane_state="stopped", lanes=lanes)
    est = estimate_ettft_local(view)
    assert est.tier == ReadinessTier.UNAVAILABLE


# ---------------------------------------------------------------------------
# estimate_ettft_local: queue penalty scaling
# ---------------------------------------------------------------------------


def test_queue_penalty_scales_with_depth():
    """Queue penalty increases linearly with depth."""
    view = _make_view(best_lane_state="loaded", is_loaded=True)
    est_4 = estimate_ettft_local(view, effective_parallel=4, scheduler_queue_depth=4)
    est_8 = estimate_ettft_local(view, effective_parallel=4, scheduler_queue_depth=8)
    assert est_8.queue_wait_s == 2 * est_4.queue_wait_s


def test_queue_penalty_inversely_proportional_to_parallel():
    """Higher parallelism reduces queue wait."""
    view = _make_view(best_lane_state="loaded", is_loaded=True)
    est_2p = estimate_ettft_local(view, effective_parallel=2, scheduler_queue_depth=8)
    est_4p = estimate_ettft_local(view, effective_parallel=4, scheduler_queue_depth=8)
    assert est_2p.queue_wait_s == 2 * est_4p.queue_wait_s


def test_queue_penalty_zero_depth():
    """Zero queue depth → zero queue wait."""
    view = _make_view(best_lane_state="loaded", is_loaded=True)
    est = estimate_ettft_local(view, scheduler_queue_depth=0)
    assert est.queue_wait_s == 0.0


def test_queue_penalty_with_custom_generation_time():
    """Custom generation time affects queue wait."""
    view = _make_view(best_lane_state="loaded", is_loaded=True)
    est = estimate_ettft_local(
        view, effective_parallel=1, generation_time_s=5.0,
        scheduler_queue_depth=3,
    )
    # (3/1) × 5.0 = 15.0
    assert est.queue_wait_s == 15.0


# ---------------------------------------------------------------------------
# estimate_ettft_local: VRAM-aware warm ignores VRAM constraints
# ---------------------------------------------------------------------------


def test_warm_ignores_vram_constraints():
    """Warm (loaded) model is not affected by VRAM limits."""
    view = _make_view(best_lane_state="loaded", is_loaded=True)
    est = estimate_ettft_local(
        view, available_vram_mb=0.0, model_vram_mb=99999.0,
    )
    assert est.tier == ReadinessTier.WARM
    assert est.expected_wait_s == 0.0


# ---------------------------------------------------------------------------
# estimate_ettft_azure tests
# ---------------------------------------------------------------------------


def test_azure_warm_healthy():
    """Azure with ample capacity → WARM."""
    cap = AzureCapacity(
        deployment_name="gpt4o",
        rate_limit_remaining_requests=100,
        rate_limit_remaining_tokens=50000,
        rate_limit_total_requests=200,
        rate_limit_total_tokens=100000,
        rate_limit_resets_at=None,
        last_header_age_seconds=2.0,
        has_capacity=True,
    )
    est = estimate_ettft_azure(cap)
    assert est.tier == ReadinessTier.WARM
    assert est.expected_wait_s == CLOUD_OVERHEAD_S
    assert est.ettft_ms == CLOUD_OVERHEAD_S * 1000


def test_azure_low_headroom():
    """Azure with low remaining requests → WARM with higher wait."""
    cap = AzureCapacity(
        deployment_name="gpt4o",
        rate_limit_remaining_requests=5,
        rate_limit_remaining_tokens=1000,
        rate_limit_total_requests=200,
        rate_limit_total_tokens=100000,
        rate_limit_resets_at=None,
        last_header_age_seconds=2.0,
        has_capacity=True,
    )
    est = estimate_ettft_azure(cap)
    assert est.tier == ReadinessTier.WARM
    assert est.expected_wait_s == CLOUD_LOW_HEADROOM_S


def test_azure_unavailable_no_capacity():
    """Azure with no capacity → UNAVAILABLE."""
    cap = AzureCapacity(
        deployment_name="gpt4o",
        rate_limit_remaining_requests=0,
        rate_limit_remaining_tokens=0,
        rate_limit_total_requests=200,
        rate_limit_total_tokens=100000,
        rate_limit_resets_at=None,
        last_header_age_seconds=2.0,
        has_capacity=False,
    )
    est = estimate_ettft_azure(cap)
    assert est.tier == ReadinessTier.UNAVAILABLE


def test_azure_unavailable_none():
    """None capacity → UNAVAILABLE."""
    est = estimate_ettft_azure(None)
    assert est.tier == ReadinessTier.UNAVAILABLE


# ---------------------------------------------------------------------------
# Integration: same-state ordering invariant
# ---------------------------------------------------------------------------


def test_same_state_ordering_two_warm():
    """Two warm models: higher weight wins (identical penalty=0)."""
    view_a = _make_view(model_id=1, best_lane_state="loaded", is_loaded=True)
    view_b = _make_view(model_id=2, best_lane_state="loaded", is_loaded=True)

    est_a = estimate_ettft_local(view_a, effective_parallel=4)
    est_b = estimate_ettft_local(view_b, effective_parallel=4)

    span = compute_weight_span([10.0, 15.0])
    score_a = compute_corrected_score(10.0, est_a.expected_wait_s, span)
    score_b = compute_corrected_score(15.0, est_b.expected_wait_s, span)

    assert score_b > score_a  # Higher weight wins


def test_same_state_ordering_two_cold():
    """Two cold models: higher weight wins (identical penalty)."""
    view_a = _make_view(model_id=1, best_lane_state="cold", is_loaded=False)
    view_b = _make_view(model_id=2, best_lane_state="cold", is_loaded=False)

    est_a = estimate_ettft_local(view_a)
    est_b = estimate_ettft_local(view_b)

    # Same state → same expected_wait → same penalty → classification preserved
    assert est_a.expected_wait_s == est_b.expected_wait_s

    span = compute_weight_span([10.0, 15.0])
    score_a = compute_corrected_score(10.0, est_a.expected_wait_s, span)
    score_b = compute_corrected_score(15.0, est_b.expected_wait_s, span)

    assert score_b > score_a  # Higher weight wins


def test_cross_state_warm_beats_cold():
    """Warm model (lower weight) beats cold model (higher weight)."""
    view_warm = _make_view(best_lane_state="loaded", is_loaded=True)
    view_cold = _make_view(best_lane_state="cold", is_loaded=False)

    est_warm = estimate_ettft_local(view_warm, effective_parallel=4)
    est_cold = estimate_ettft_local(view_cold)

    span = compute_weight_span([12.0, 13.0])
    score_warm = compute_corrected_score(12.0, est_warm.expected_wait_s, span)
    score_cold = compute_corrected_score(13.0, est_cold.expected_wait_s, span)

    assert score_warm > score_cold


def test_sleeping_beats_cold():
    """Sleeping (2.5s) beats cold (45s) when weights are close."""
    view_sleep = _make_view(best_lane_state="sleeping", is_loaded=False)
    view_cold = _make_view(best_lane_state="cold", is_loaded=False)

    est_sleep = estimate_ettft_local(view_sleep)
    est_cold = estimate_ettft_local(view_cold)

    span = compute_weight_span([10.0, 12.0])
    score_sleep = compute_corrected_score(10.0, est_sleep.expected_wait_s, span)
    score_cold = compute_corrected_score(12.0, est_cold.expected_wait_s, span)

    # Sleeping penalty ≈ 0.15, Cold penalty ≈ 2.7
    # sleep: 10-0.15=9.85, cold: 12-2.7=9.3 → sleep wins
    assert score_sleep > score_cold
