"""Tests for readiness classification (classify_local / classify_azure)."""

from logos.pipeline.ettft_estimator import (
    ReadinessTier,
    ReadinessSignal,
    classify_local,
    classify_azure,
)
from logos.sdi.models import (
    LaneSchedulerSignals,
    ModelSchedulerView,
    AzureCapacity,
)


def _make_lane(
    runtime_state="loaded",
    sleep_state="unsupported",
    queue_waiting=0.0,
    requests_running=0.0,
    active_requests=0,
    model_name="test-model",
):
    return LaneSchedulerSignals(
        lane_id="lane-1",
        model_name=model_name,
        runtime_state=runtime_state,
        sleep_state=sleep_state,
        is_vllm=True,
        active_requests=active_requests,
        queue_waiting=queue_waiting,
        requests_running=requests_running,
        gpu_cache_usage_percent=None,
        ttft_p95_seconds=0.0,
        effective_vram_mb=8000.0,
        num_parallel=4,
    )


def _make_view(
    best_lane_state="loaded",
    best_sleep_state="unsupported",
    is_loaded=True,
    aggregate_queue_waiting=0.0,
    aggregate_active_requests=0,
    lanes=None,
):
    return ModelSchedulerView(
        model_id=1,
        model_name="test-model",
        provider_id=10,
        is_loaded=is_loaded,
        best_lane_state=best_lane_state,
        best_sleep_state=best_sleep_state,
        aggregate_active_requests=aggregate_active_requests,
        aggregate_queue_waiting=aggregate_queue_waiting,
        warmest_ttft_p95_seconds=0.0,
        gpu_cache_pressure_max=None,
        lanes=lanes if lanes is not None else [_make_lane(runtime_state=best_lane_state)],
    )


# ---------------------------------------------------------------------------
# classify_local tests
# ---------------------------------------------------------------------------


def test_classify_local_ready():
    """Loaded model with queue_waiting==0 -> READY."""
    signal = classify_local(_make_view(best_lane_state="loaded", aggregate_queue_waiting=0.0))
    assert signal.tier == ReadinessTier.READY
    assert isinstance(signal, ReadinessSignal)


def test_classify_local_running_ready():
    """Running model with queue_waiting==0 -> READY."""
    signal = classify_local(_make_view(best_lane_state="running", aggregate_queue_waiting=0.0))
    assert signal.tier == ReadinessTier.READY


def test_classify_local_queueing():
    """Loaded model with queue_waiting>0 -> QUEUEING."""
    signal = classify_local(_make_view(best_lane_state="loaded", aggregate_queue_waiting=3.0))
    assert signal.tier == ReadinessTier.QUEUEING
    assert "queue_waiting" in signal.reasoning


def test_classify_local_sleeping():
    """Sleeping lane -> SLEEPING tier."""
    signal = classify_local(
        _make_view(
            best_lane_state="sleeping",
            best_sleep_state="sleeping",
            is_loaded=False,
            lanes=[_make_lane(runtime_state="sleeping", sleep_state="sleeping")],
        )
    )
    assert signal.tier == ReadinessTier.SLEEPING


def test_classify_local_cold():
    """Cold lane -> COLD tier."""
    signal = classify_local(
        _make_view(
            best_lane_state="cold",
            is_loaded=False,
            lanes=[_make_lane(runtime_state="cold")],
        )
    )
    assert signal.tier == ReadinessTier.COLD


def test_classify_local_starting():
    """Starting lane treated as cold -> COLD tier."""
    signal = classify_local(
        _make_view(
            best_lane_state="starting",
            is_loaded=False,
            lanes=[_make_lane(runtime_state="starting")],
        )
    )
    assert signal.tier == ReadinessTier.COLD


def test_classify_local_unavailable_no_lanes():
    """No lanes -> UNAVAILABLE."""
    view = ModelSchedulerView(
        model_id=1,
        model_name="test",
        provider_id=10,
        is_loaded=False,
        best_lane_state="error",
        best_sleep_state="unsupported",
        aggregate_active_requests=0,
        aggregate_queue_waiting=0.0,
        warmest_ttft_p95_seconds=0.0,
        gpu_cache_pressure_max=None,
        lanes=[],
    )
    signal = classify_local(view)
    assert signal.tier == ReadinessTier.UNAVAILABLE


def test_classify_local_unavailable_all_stopped():
    """All stopped/error lanes -> UNAVAILABLE."""
    lanes = [
        _make_lane(runtime_state="stopped"),
        _make_lane(runtime_state="error"),
    ]
    view = _make_view(best_lane_state="stopped", lanes=lanes)
    signal = classify_local(view)
    assert signal.tier == ReadinessTier.UNAVAILABLE


def test_classify_local_reasoning_not_empty():
    """Reasoning string is always non-empty."""
    for state, queue in [("loaded", 0.0), ("loaded", 5.0), ("sleeping", 0.0), ("cold", 0.0)]:
        view = _make_view(
            best_lane_state=state,
            aggregate_queue_waiting=queue,
            lanes=[_make_lane(runtime_state=state)],
        )
        signal = classify_local(view)
        assert signal.reasoning, f"Empty reasoning for state={state} queue={queue}"


# ---------------------------------------------------------------------------
# classify_azure tests
# ---------------------------------------------------------------------------


def test_classify_azure_ready():
    """Azure with has_capacity=True -> READY."""
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
    signal = classify_azure(cap)
    assert signal.tier == ReadinessTier.READY
    assert "remaining_requests" in signal.reasoning


def test_classify_azure_unavailable_no_capacity():
    """Azure with has_capacity=False -> UNAVAILABLE."""
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
    signal = classify_azure(cap)
    assert signal.tier == ReadinessTier.UNAVAILABLE


def test_classify_azure_unavailable_none():
    """None capacity -> UNAVAILABLE."""
    signal = classify_azure(None)
    assert signal.tier == ReadinessTier.UNAVAILABLE


def test_readiness_signal_is_frozen():
    """ReadinessSignal is a frozen dataclass - mutation raises."""
    signal = ReadinessSignal(tier=ReadinessTier.READY, reasoning="ok")
    raised = False
    try:
        signal.tier = ReadinessTier.COLD  # type: ignore[misc]
    except Exception:
        raised = True
    assert raised, "Expected FrozenInstanceError"
