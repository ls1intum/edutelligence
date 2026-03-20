"""Tests for ETTFT estimation and tier classification."""

from logos.pipeline.ettft_estimator import (
    ReadinessTier,
    EttftEstimate,
    TIER_THRESHOLDS,
    classify_tier,
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
# classify_tier tests
# ---------------------------------------------------------------------------


def test_classify_tier_warm():
    tier, penalty = classify_tier(200.0)
    assert tier == ReadinessTier.WARM
    assert penalty == 0.0


def test_classify_tier_warm_boundary():
    tier, penalty = classify_tier(500.0)
    assert tier == ReadinessTier.WARM


def test_classify_tier_sleeping():
    tier, penalty = classify_tier(501.0)
    assert tier == ReadinessTier.SLEEPING
    assert penalty == TIER_THRESHOLDS[ReadinessTier.SLEEPING]["penalty"]


def test_classify_tier_busy():
    tier, penalty = classify_tier(5000.0)
    assert tier == ReadinessTier.BUSY
    assert penalty == 8.0


def test_classify_tier_cold():
    tier, penalty = classify_tier(45000.0)
    assert tier == ReadinessTier.COLD
    assert penalty == 20.0


def test_classify_tier_unavailable():
    tier, penalty = classify_tier(100000.0)
    assert tier == ReadinessTier.UNAVAILABLE
    assert penalty == float("inf")


# ---------------------------------------------------------------------------
# compute_corrected_score tests
# ---------------------------------------------------------------------------


def test_corrected_score_basic():
    assert compute_corrected_score(12.0, 2.0) == 10.0


def test_corrected_score_zero_penalty():
    assert compute_corrected_score(15.0, 0.0) == 15.0


def test_corrected_score_inf_penalty():
    result = compute_corrected_score(15.0, float("inf"))
    assert result == float("-inf")


# ---------------------------------------------------------------------------
# estimate_ettft_local tests
# ---------------------------------------------------------------------------


def test_local_warm_loaded_no_queue():
    """Loaded model with no queue pressure → WARM."""
    view = _make_view(
        best_lane_state="loaded",
        is_loaded=True,
        aggregate_queue_waiting=0.0,
        warmest_ttft_p95_seconds=0.15,
    )
    est = estimate_ettft_local(view)
    assert est.tier == ReadinessTier.WARM
    assert est.penalty == 0.0
    assert est.ettft_ms == 150.0  # 0.15s * 1000


def test_local_warm_default_ttft():
    """Loaded model with no measured TTFT → uses 200ms default."""
    view = _make_view(
        best_lane_state="running",
        is_loaded=True,
        aggregate_queue_waiting=0.0,
        warmest_ttft_p95_seconds=0.0,
    )
    est = estimate_ettft_local(view)
    assert est.tier == ReadinessTier.WARM
    assert est.ettft_ms == 200.0


def test_local_sleeping():
    """Sleeping lane → SLEEPING tier."""
    view = _make_view(
        best_lane_state="sleeping",
        best_sleep_state="sleeping",
        is_loaded=False,
    )
    est = estimate_ettft_local(view)
    assert est.tier == ReadinessTier.SLEEPING
    assert est.penalty == TIER_THRESHOLDS[ReadinessTier.SLEEPING]["penalty"]
    assert est.ettft_ms == 2000.0


def test_local_busy_high_queue():
    """Loaded model with queue pressure → BUSY tier."""
    view = _make_view(
        best_lane_state="loaded",
        is_loaded=True,
        aggregate_queue_waiting=5.0,
        warmest_ttft_p95_seconds=0.2,
    )
    est = estimate_ettft_local(view)
    # base=200ms, queue_delay=5*200=1000ms, total=1200ms → SLEEPING tier (501-3000)
    assert est.ettft_ms == 1200.0
    assert est.tier == ReadinessTier.SLEEPING

    # With higher queue
    view2 = _make_view(
        best_lane_state="loaded",
        is_loaded=True,
        aggregate_queue_waiting=20.0,
        warmest_ttft_p95_seconds=0.3,
    )
    est2 = estimate_ettft_local(view2)
    # base=300ms, delay=20*300=6000ms, total=6300ms → BUSY tier (3001-10000)
    assert est2.tier == ReadinessTier.BUSY
    assert est2.penalty == 8.0


def test_local_cold():
    """Cold model → COLD tier."""
    view = _make_view(
        best_lane_state="cold",
        is_loaded=False,
    )
    est = estimate_ettft_local(view)
    assert est.tier == ReadinessTier.COLD
    assert est.penalty == 20.0
    assert est.ettft_ms == 45000.0


def test_local_starting():
    """Starting model treated same as cold."""
    view = _make_view(
        best_lane_state="starting",
        is_loaded=False,
    )
    est = estimate_ettft_local(view)
    assert est.tier == ReadinessTier.COLD


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
    assert est.penalty == float("inf")


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
    assert est.penalty == 0.0
    assert est.ettft_ms == 300.0


def test_azure_busy_low_headroom():
    """Azure with low remaining requests → BUSY."""
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
    assert est.tier == ReadinessTier.BUSY
    assert est.penalty == 8.0


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
# Tier boundary tests
# ---------------------------------------------------------------------------


def test_tier_boundary_warm_sleeping():
    """500ms → WARM, 501ms → SLEEPING."""
    tier_500, _ = classify_tier(500.0)
    tier_501, _ = classify_tier(500.1)
    assert tier_500 == ReadinessTier.WARM
    assert tier_501 == ReadinessTier.SLEEPING


def test_tier_boundary_sleeping_busy():
    """3000ms → SLEEPING, 3001ms → BUSY."""
    tier_3000, _ = classify_tier(3000.0)
    tier_3001, _ = classify_tier(3000.1)
    assert tier_3000 == ReadinessTier.SLEEPING
    assert tier_3001 == ReadinessTier.BUSY
