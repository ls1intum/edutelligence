"""Tests for ETTFT estimation, range-scaled correction, and weight span."""

from logos import (
    CLOUD_LOW_HEADROOM_S,
    CLOUD_OVERHEAD_S,
    CORRECTION_STRENGTH,
    MIN_SPAN_FLOOR,
    NORMALIZATION_HORIZON_S,
    AzureCapacity,
    EttftEstimate,
    LaneSchedulerSignals,
    ModelSchedulerView,
    ReadinessTier,
    compute_corrected_score,
    compute_weight_span,
    estimate_ettft_azure,
)
from logos.pipeline.ettft_estimator import estimate_ettft_local


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
        warmest_e2e_latency_p50_seconds=0.0,
        gpu_cache_pressure_max=gpu_cache_pressure_max,
        lanes=lanes
        or [
            LaneSchedulerSignals(
                lane_id="lane-1",
                model_name=model_name,
                runtime_state=best_lane_state,
                sleep_state=best_sleep_state,
                is_vllm=False,
                active_requests=aggregate_active_requests,
                queue_waiting=aggregate_queue_waiting,
                requests_running=float(aggregate_active_requests),
                gpu_cache_usage_percent=gpu_cache_pressure_max,
                ttft_p95_seconds=warmest_ttft_p95_seconds,
                e2e_latency_p50_seconds=0.0,
                effective_vram_mb=8000.0,
                num_parallel=4,
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


# ---------------------------------------------------------------------------
# Warmth-state encoding (-1 cold / 0 warm idle / 1+x running with x queued)
# ---------------------------------------------------------------------------


def test_warmth_state_cold():
    est = estimate_ettft_local(_make_view(best_lane_state="cold", is_loaded=False))
    assert est.tier == ReadinessTier.COLD
    assert est.warmth_state == -1


def test_warmth_state_unavailable_is_cold():
    est = estimate_ettft_local(_make_view(best_lane_state="stopped", is_loaded=False))
    assert est.tier == ReadinessTier.UNAVAILABLE
    assert est.warmth_state == -1


def test_warmth_state_warm_idle():
    est = estimate_ettft_local(_make_view(best_lane_state="loaded", aggregate_active_requests=0))
    assert est.tier == ReadinessTier.WARM
    assert est.warmth_state == 0


def test_warmth_state_sleeping_counts_as_warm_idle():
    """Sleeping = weights resident on GPU → warm but not running."""
    est = estimate_ettft_local(_make_view(best_lane_state="sleeping", best_sleep_state="sleeping", is_loaded=False))
    assert est.tier == ReadinessTier.SLEEPING
    assert est.warmth_state == 0


def test_warmth_state_running_without_queue():
    est = estimate_ettft_local(_make_view(best_lane_state="running", aggregate_active_requests=2))
    assert est.warmth_state == 1


def test_warmth_state_running_with_queue():
    """1 + (scheduler queue + lane backend queue)."""
    est = estimate_ettft_local(
        _make_view(
            best_lane_state="running",
            aggregate_active_requests=1,
            aggregate_queue_waiting=3.0,
        ),
        scheduler_queue_depth=2,
    )
    assert est.warmth_state == 1 + 3 + 2


# ---------------------------------------------------------------------------
# queue_wait: backend backlog must count, not just the orchestrator queue
# ---------------------------------------------------------------------------


def test_queue_wait_counts_backend_waiting():
    """A warm lane with a deep backend queue but an empty orchestrator queue must
    still report a non-trivial wait (the ~35x-underestimate bug: previously this
    returned 0 because only scheduler_queue_depth counted)."""
    est = estimate_ettft_local(
        _make_view(best_lane_state="running", aggregate_active_requests=8, aggregate_queue_waiting=40.0),
        effective_parallel=4,
        generation_time_s=3.0,
        scheduler_queue_depth=0,  # orchestrator queue empty — work is on the lane
    )
    assert est.tier == ReadinessTier.WARM
    # effective_depth = 0 + 40 + max(0, 8-4)=4 → 44; rounds = 44/4 = 11; ×3s = 33s
    assert est.queue_wait_s == 33.0
    assert est.expected_wait_s == 33.0


def test_queue_wait_idle_warm_lane_is_zero():
    """No backlog anywhere → no queue wait (warm lanes still serve immediately)."""
    est = estimate_ettft_local(
        _make_view(best_lane_state="running", aggregate_active_requests=2, aggregate_queue_waiting=0.0),
        effective_parallel=4,
        scheduler_queue_depth=0,
    )
    assert est.queue_wait_s == 0.0
    assert est.expected_wait_s == 0.0


def test_queue_wait_adds_to_cold_overhead():
    """Backend backlog adds on top of the cold-start constant."""
    est = estimate_ettft_local(
        _make_view(best_lane_state="cold", aggregate_active_requests=0, aggregate_queue_waiting=8.0),
        effective_parallel=4,
        generation_time_s=3.0,
    )
    # 8 waiting / 4 parallel = 2 rounds × 3s = 6s queue, plus 45s cold-start
    assert est.queue_wait_s == 6.0
    assert est.state_overhead_s == 45.0
    assert est.expected_wait_s == 51.0
