"""Tests for ClassificationCorrectingScheduler."""

import asyncio
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

import pytest

from logos.pipeline.correcting_scheduler import ClassificationCorrectingScheduler
from logos.pipeline.scheduler_interface import SchedulingRequest, SchedulingResult
from logos.pipeline.ettft_estimator import ReadinessTier
from logos.sdi.models import (
    LaneSchedulerSignals,
    ModelSchedulerView,
    AzureCapacity,
)
from logos.queue import PriorityQueueManager
from logos.queue.models import QueueStatePerPriority


def _make_view(
    model_id=1,
    model_name="model-a",
    provider_id=10,
    best_lane_state="loaded",
    is_loaded=True,
    aggregate_queue_waiting=0.0,
    warmest_ttft_p95_seconds=0.1,
):
    return ModelSchedulerView(
        model_id=model_id,
        model_name=model_name,
        provider_id=provider_id,
        is_loaded=is_loaded,
        best_lane_state=best_lane_state,
        best_sleep_state="awake" if is_loaded else "unsupported",
        aggregate_active_requests=1 if is_loaded else 0,
        aggregate_queue_waiting=aggregate_queue_waiting,
        warmest_ttft_p95_seconds=warmest_ttft_p95_seconds,
        gpu_cache_pressure_max=None,
        lanes=[
            LaneSchedulerSignals(
                lane_id="lane-1", model_name=model_name,
                runtime_state=best_lane_state,
                sleep_state="awake" if is_loaded else "unsupported",
                is_vllm=False, active_requests=1 if is_loaded else 0,
                queue_waiting=aggregate_queue_waiting,
                requests_running=1.0 if is_loaded else 0.0,
                gpu_cache_usage_percent=None,
                ttft_p95_seconds=warmest_ttft_p95_seconds,
                effective_vram_mb=8000.0, num_parallel=4,
            )
        ],
    )


def _make_azure_capacity(has_capacity=True, remaining=100):
    return AzureCapacity(
        deployment_name="gpt4o",
        rate_limit_remaining_requests=remaining,
        rate_limit_remaining_tokens=50000,
        rate_limit_total_requests=200,
        rate_limit_total_tokens=100000,
        rate_limit_resets_at=None,
        last_header_age_seconds=2.0,
        has_capacity=has_capacity,
    )


class MockLogosNodeFacade:
    """Mock logosnode facade with controlled scheduler view returns."""

    def __init__(self):
        self._views = {}  # (model_id, provider_id) -> ModelSchedulerView
        self._reserve_results = {}  # (model_id, provider_id) -> bool
        self._tracking = {}
        self.raise_on_request_start = False

    def set_view(self, model_id, provider_id, view):
        self._views[(model_id, provider_id)] = view

    def set_reserve(self, model_id, provider_id, result):
        self._reserve_results[(model_id, provider_id)] = result

    def get_model_scheduler_view(self, model_id, provider_id):
        return self._views.get((model_id, provider_id))

    def get_model_status(self, model_id, provider_id):
        view = self._views.get((model_id, provider_id))
        mock = MagicMock()
        mock.is_loaded = view.is_loaded if view else False
        mock.active_requests = view.aggregate_active_requests if view else 0
        mock.queue_depth = 0
        return mock

    def get_capacity_info(self, provider_id):
        mock = MagicMock()
        mock.available_vram_mb = 32000
        return mock

    def try_reserve_capacity(self, model_id, provider_id, request_id):
        return self._reserve_results.get((model_id, provider_id), True)

    def on_request_start(self, request_id, **kwargs):
        if self.raise_on_request_start:
            raise ValueError("Model not registered")
        self._tracking[request_id] = {"started": True, **kwargs}

    def on_request_begin_processing(self, request_id, **kwargs):
        # No-op in tests: scheduling assertions do not require processing bookkeeping.
        pass

    def on_request_complete(self, request_id, **kwargs):
        self._tracking.pop(request_id, None)


class MockAzureFacade:
    """Mock Azure facade."""

    def __init__(self):
        self._capacities = {}

    def set_capacity(self, model_id, provider_id, capacity):
        self._capacities[(model_id, provider_id)] = capacity

    def get_model_capacity(self, model_id, provider_id):
        return self._capacities.get((model_id, provider_id))

    def get_model_status(self, model_id, provider_id):
        cap = self._capacities.get((model_id, provider_id))
        mock = MagicMock()
        mock.is_loaded = cap.has_capacity if cap else False
        return mock

    def update_model_rate_limits(self, model_id, provider_id, headers):
        # No-op in tests: scheduler selection logic does not mutate Azure rate state.
        pass


def _make_scheduler(logosnode=None, azure=None, ettft_enabled=True):
    queue_mgr = PriorityQueueManager()
    return ClassificationCorrectingScheduler(
        queue_manager=queue_mgr,
        logosnode_facade=logosnode or MockLogosNodeFacade(),
        azure_facade=azure or MockAzureFacade(),
        ettft_enabled=ettft_enabled,
    )


def _make_request(candidates, deployments, request_id="req-1"):
    return SchedulingRequest(
        request_id=request_id,
        classified_models=candidates,
        deployments=deployments,
        payload={},
    )


# ---------------------------------------------------------------------------
# Scenario A: Loaded model (lower weight) beats cold model (higher weight)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loaded_beats_cold_due_to_penalty():
    """Model X (weight=12, loaded) vs Model Y (weight=13, cold) → X wins."""
    logosnode = MockLogosNodeFacade()
    logosnode.set_view(1, 10, _make_view(model_id=1, provider_id=10, best_lane_state="loaded", is_loaded=True))
    logosnode.set_view(2, 10, _make_view(model_id=2, provider_id=10, best_lane_state="cold", is_loaded=False, warmest_ttft_p95_seconds=0.0))
    logosnode.set_reserve(1, 10, True)
    logosnode.set_reserve(2, 10, True)

    scheduler = _make_scheduler(logosnode=logosnode, ettft_enabled=True)

    # (model_id, weight, priority_int, parallel)
    candidates = [(1, 12.0, 1, 4), (2, 13.0, 1, 4)]
    deployments = [
        {"model_id": 1, "provider_id": 10, "type": "logosnode"},
        {"model_id": 2, "provider_id": 10, "type": "logosnode"},
    ]
    request = _make_request(candidates, deployments)

    result = await scheduler.schedule(request)
    assert result is not None
    assert result.model_id == 1  # Loaded wins: 12-0 > 13-20
    assert result.ettft_tier == "warm"


# ---------------------------------------------------------------------------
# Scenario B: Two loaded models → classification ordering preserved
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_loaded_preserves_classification_order():
    """Both loaded → penalty=0 for both → higher weight wins."""
    logosnode = MockLogosNodeFacade()
    logosnode.set_view(1, 10, _make_view(model_id=1, provider_id=10))
    logosnode.set_view(2, 10, _make_view(model_id=2, provider_id=10))
    logosnode.set_reserve(1, 10, True)
    logosnode.set_reserve(2, 10, True)

    scheduler = _make_scheduler(logosnode=logosnode, ettft_enabled=True)

    candidates = [(1, 10.0, 1, 4), (2, 15.0, 1, 4)]
    deployments = [
        {"model_id": 1, "provider_id": 10, "type": "logosnode"},
        {"model_id": 2, "provider_id": 10, "type": "logosnode"},
    ]
    request = _make_request(candidates, deployments)

    result = await scheduler.schedule(request)
    assert result is not None
    assert result.model_id == 2  # Higher weight wins when both warm


# ---------------------------------------------------------------------------
# Scenario C: ettft_enabled=False → pure classification ordering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ettft_disabled_uses_raw_weights():
    """ettft_enabled=False → cold model with higher weight wins."""
    logosnode = MockLogosNodeFacade()
    logosnode.set_view(1, 10, _make_view(model_id=1, provider_id=10, best_lane_state="loaded", is_loaded=True))
    logosnode.set_view(2, 10, _make_view(model_id=2, provider_id=10, best_lane_state="cold", is_loaded=False))
    logosnode.set_reserve(1, 10, True)
    logosnode.set_reserve(2, 10, True)

    scheduler = _make_scheduler(logosnode=logosnode, ettft_enabled=False)

    candidates = [(1, 12.0, 1, 4), (2, 13.0, 1, 4)]
    deployments = [
        {"model_id": 1, "provider_id": 10, "type": "logosnode"},
        {"model_id": 2, "provider_id": 10, "type": "logosnode"},
    ]
    request = _make_request(candidates, deployments)

    result = await scheduler.schedule(request)
    assert result is not None
    assert result.model_id == 2  # Higher weight wins with ETTFT disabled


# ---------------------------------------------------------------------------
# Scenario D: All candidates UNAVAILABLE → returns None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_view_treated_as_cold():
    """No scheduler view → COLD (not UNAVAILABLE), model is still schedulable for cold-load."""
    logosnode = MockLogosNodeFacade()
    # No views set → get_model_scheduler_view returns None → COLD (was UNAVAILABLE)

    scheduler = _make_scheduler(logosnode=logosnode, ettft_enabled=True)

    candidates = [(1, 12.0, 1, 4)]
    deployments = [{"model_id": 1, "provider_id": 10, "type": "logosnode"}]
    request = _make_request(candidates, deployments)

    result = await scheduler.schedule(request)
    # Model is now COLD (penalty=20), not UNAVAILABLE — it can be scheduled
    assert result is not None
    assert result.ettft_tier == "cold"
    assert result.ettft_estimate_ms == pytest.approx(45000.0)


# ---------------------------------------------------------------------------
# Scenario E: Azure candidate selected when local is cold
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_azure_selected_when_local_cold():
    """Azure with capacity selected over cold logosnode model."""
    logosnode = MockLogosNodeFacade()
    logosnode.set_view(1, 10, _make_view(model_id=1, provider_id=10, best_lane_state="cold", is_loaded=False))

    azure = MockAzureFacade()
    azure.set_capacity(2, 20, _make_azure_capacity(has_capacity=True, remaining=100))

    scheduler = _make_scheduler(logosnode=logosnode, azure=azure, ettft_enabled=True)

    # Azure model has lower classification weight but is warm
    candidates = [(1, 15.0, 1, 4), (2, 10.0, 1, 4)]
    deployments = [
        {"model_id": 1, "provider_id": 10, "type": "logosnode"},
        {"model_id": 2, "provider_id": 20, "type": "azure"},
    ]
    request = _make_request(candidates, deployments)

    result = await scheduler.schedule(request)
    assert result is not None
    # Azure: 10-0=10, Logosnode cold: 15-20=-5 → Azure wins
    assert result.model_id == 2
    assert result.ettft_tier == "warm"


# ---------------------------------------------------------------------------
# ETTFT fields populated in result
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ettft_fields_in_result():
    """Verify ettft_estimate_ms and ettft_tier are set on result."""
    logosnode = MockLogosNodeFacade()
    logosnode.set_view(1, 10, _make_view(
        model_id=1, provider_id=10,
        best_lane_state="loaded", is_loaded=True,
        warmest_ttft_p95_seconds=0.15,
    ))
    logosnode.set_reserve(1, 10, True)

    scheduler = _make_scheduler(logosnode=logosnode, ettft_enabled=True)

    candidates = [(1, 12.0, 1, 4)]
    deployments = [{"model_id": 1, "provider_id": 10, "type": "logosnode"}]
    request = _make_request(candidates, deployments)

    result = await scheduler.schedule(request)
    assert result is not None
    assert result.ettft_estimate_ms == pytest.approx(150.0)  # 0.15s * 1000
    assert result.ettft_tier == "warm"


# ---------------------------------------------------------------------------
# Capacity reservation falls through to next candidate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reserve_failure_falls_through():
    """If top candidate can't reserve, fall through to next."""
    logosnode = MockLogosNodeFacade()
    logosnode.set_view(1, 10, _make_view(model_id=1, provider_id=10))
    logosnode.set_view(2, 10, _make_view(model_id=2, provider_id=10))
    logosnode.set_reserve(1, 10, False)  # Can't reserve model 1
    logosnode.set_reserve(2, 10, True)

    scheduler = _make_scheduler(logosnode=logosnode, ettft_enabled=True)

    candidates = [(1, 15.0, 1, 4), (2, 10.0, 1, 4)]
    deployments = [
        {"model_id": 1, "provider_id": 10, "type": "logosnode"},
        {"model_id": 2, "provider_id": 10, "type": "logosnode"},
    ]
    request = _make_request(candidates, deployments)

    result = await scheduler.schedule(request)
    assert result is not None
    assert result.model_id == 2  # Falls through to model 2


# ---------------------------------------------------------------------------
# Empty candidates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_candidates_returns_none():
    """No candidates → None."""
    scheduler = _make_scheduler()
    request = _make_request([], [])
    result = await scheduler.schedule(request)
    assert result is None


# ---------------------------------------------------------------------------
# Sleeping model with moderate weight beats cold model with high weight
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sleeping_beats_cold():
    """Sleeping (penalty=2) beats cold (penalty=20) with similar weights."""
    logosnode = MockLogosNodeFacade()
    logosnode.set_view(1, 10, _make_view(
        model_id=1, provider_id=10,
        best_lane_state="sleeping", is_loaded=False,
    ))
    logosnode.set_view(2, 10, _make_view(
        model_id=2, provider_id=10,
        best_lane_state="cold", is_loaded=False,
    ))
    logosnode.set_reserve(1, 10, True)
    logosnode.set_reserve(2, 10, True)

    scheduler = _make_scheduler(logosnode=logosnode, ettft_enabled=True)

    # Model 1: 10-2=8, Model 2: 12-20=-8
    candidates = [(1, 10.0, 1, 4), (2, 12.0, 1, 4)]
    deployments = [
        {"model_id": 1, "provider_id": 10, "type": "logosnode"},
        {"model_id": 2, "provider_id": 10, "type": "logosnode"},
    ]
    request = _make_request(candidates, deployments)

    result = await scheduler.schedule(request)
    assert result is not None
    assert result.model_id == 1
    assert result.ettft_tier == "sleeping"


@pytest.mark.asyncio
async def test_transient_tracking_failure_does_not_break_scheduling():
    """Registration races in on_request_start should not fail scheduling."""
    logosnode = MockLogosNodeFacade()
    logosnode.set_view(1, 10, _make_view(model_id=1, provider_id=10, best_lane_state="cold", is_loaded=False))
    logosnode.set_reserve(1, 10, True)
    logosnode.raise_on_request_start = True

    scheduler = _make_scheduler(logosnode=logosnode, ettft_enabled=True)

    candidates = [(1, 12.0, 1, 4)]
    deployments = [{"model_id": 1, "provider_id": 10, "type": "logosnode"}]
    request = _make_request(candidates, deployments)

    result = await scheduler.schedule(request)
    assert result is not None
    assert result.model_id == 1
    assert result.ettft_tier == "cold"
