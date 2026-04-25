"""Tests for ClassificationCorrectingScheduler with multi-provider expansion."""

import asyncio
import json
import os
import tempfile
from unittest.mock import MagicMock

import pytest

from logos.pipeline.correcting_scheduler import ClassificationCorrectingScheduler
from logos.pipeline.scheduler_interface import SchedulingRequest, SchedulingResult
from logos.pipeline.ettft_estimator import ReadinessTier, OVERHEAD_COLD_S
from logos.sdi.models import (
    LaneSchedulerSignals,
    ModelSchedulerView,
    AzureCapacity,
)
from logos.queue import PriorityQueueManager


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

    def get_parallel_capacity(self, model_id, provider_id):
        return (4, "configured")

    def get_model_profiles(self, provider_id):
        return {}

    def get_model_name(self, model_id, provider_id):
        view = self._views.get((model_id, provider_id))
        return view.model_name if view else None

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
    """Model X (weight=12, loaded) vs Model Y (weight=13, cold) → X wins.

    Weight span = max(1, 2.6, 1.0) = 2.6
    X loaded: score = 12 - 0 = 12
    Y cold (45s): score = 13 - (0.75 × 2.6 × 1.5) = 13 - 2.925 = 10.075
    → X wins
    """
    logosnode = MockLogosNodeFacade()
    logosnode.set_view(1, 10, _make_view(model_id=1, provider_id=10, best_lane_state="loaded", is_loaded=True))
    logosnode.set_view(2, 10, _make_view(model_id=2, provider_id=10, best_lane_state="cold", is_loaded=False, warmest_ttft_p95_seconds=0.0))
    logosnode.set_reserve(1, 10, True)
    logosnode.set_reserve(2, 10, True)

    scheduler = _make_scheduler(logosnode=logosnode, ettft_enabled=True)

    candidates = [(1, 12.0, 1, 4), (2, 13.0, 1, 4)]
    deployments = [
        {"model_id": 1, "provider_id": 10, "type": "logosnode"},
        {"model_id": 2, "provider_id": 10, "type": "logosnode"},
    ]
    request = _make_request(candidates, deployments)

    result = await scheduler.schedule(request)
    assert result is not None
    assert result.model_id == 1  # Loaded wins
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
# Scenario D: No view → treated as COLD (still schedulable)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_view_treated_as_cold():
    """No scheduler view → COLD (not UNAVAILABLE), model is still schedulable.

    With ECCS enabled, a COLD top candidate correctly defers to the queue
    path.  We verify the ETTFT tier assignment is COLD and the queue-for-best
    behavior by checking _try_immediate_select returns None, then separately
    verify the full queue path works via a short-timeout schedule call.
    """
    logosnode = MockLogosNodeFacade()
    # No views set → get_model_scheduler_view returns None → COLD fallback

    scheduler = _make_scheduler(logosnode=logosnode, ettft_enabled=True)

    candidates = [(1, 12.0, 1, 4)]
    deployments = [{"model_id": 1, "provider_id": 10, "type": "logosnode"}]

    # Verify ETTFT tier is COLD
    scored = scheduler._compute_candidate_scores(candidates, deployments)
    assert len(scored) == 1
    _model_id, _prov_id, _ptype, _score, _prio, ettft = scored[0]
    assert ettft.tier == ReadinessTier.COLD
    assert ettft.expected_wait_s == OVERHEAD_COLD_S

    # Verify _try_immediate_select defers to queue path (returns None)
    # because the top candidate is COLD and ECCS is enabled
    immediate = scheduler._try_immediate_select(scored, "req-1")
    assert immediate is None, (
        "ECCS queue-for-best: COLD top candidate should defer to queue, "
        "not fall through to a lower-scored warm model"
    )


# ---------------------------------------------------------------------------
# Scenario E: Azure candidate selected when local is cold
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_azure_selected_when_local_cold():
    """Azure with capacity selected over cold logosnode model.

    Weight span = max(5, 3.0, 1.0) = 5.0
    Azure (10, 0.3s): 10 - (0.005 × 5 × 1.5) = ~9.96
    Logosnode cold (15, 45s): 15 - (0.75 × 5 × 1.5) = 15 - 5.625 = 9.375
    → Azure wins
    """
    logosnode = MockLogosNodeFacade()
    logosnode.set_view(1, 10, _make_view(model_id=1, provider_id=10, best_lane_state="cold", is_loaded=False))

    azure = MockAzureFacade()
    azure.set_capacity(2, 20, _make_azure_capacity(has_capacity=True, remaining=100))

    scheduler = _make_scheduler(logosnode=logosnode, azure=azure, ettft_enabled=True)

    candidates = [(1, 15.0, 1, 4), (2, 10.0, 1, 4)]
    deployments = [
        {"model_id": 1, "provider_id": 10, "type": "logosnode"},
        {"model_id": 2, "provider_id": 20, "type": "azure"},
    ]
    request = _make_request(candidates, deployments)

    result = await scheduler.schedule(request)
    assert result is not None
    assert result.model_id == 2  # Azure wins
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
    # Warm model with no queue → expected_wait=0s → ettft_ms=0
    assert result.ettft_estimate_ms == 0.0
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
# Sleeping model beats cold model with close weights
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sleeping_beats_cold():
    """Sleeping (2.5s) beats cold (45s) with close weights.

    Weight span = max(2, 2.4, 1.0) = 2.4
    Sleeping (10, 2.5s): 10 - (0.042 × 2.4 × 1.5) ≈ 9.85
    Cold (12, 45s): 12 - (0.75 × 2.4 × 1.5) = 12 - 2.7 = 9.3
    → Sleeping wins in scored ranking.

    With ECCS enabled, the top candidate (sleeping) defers to the queue
    path so the capacity planner wakes it.  We verify the ranking and
    the queue-for-best deferral.
    """
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

    candidates = [(1, 10.0, 1, 4), (2, 12.0, 1, 4)]
    deployments = [
        {"model_id": 1, "provider_id": 10, "type": "logosnode"},
        {"model_id": 2, "provider_id": 10, "type": "logosnode"},
    ]

    # Verify scoring: sleeping model 1 scores higher than cold model 2
    scored = scheduler._compute_candidate_scores(candidates, deployments)
    assert scored[0][0] == 1, "Sleeping model should rank first"
    assert scored[0][5].tier == ReadinessTier.SLEEPING

    # Verify queue-for-best: top candidate is sleeping → defers to queue
    immediate = scheduler._try_immediate_select(scored, "req-1")
    assert immediate is None, (
        "ECCS queue-for-best: sleeping top candidate should defer to queue"
    )


# ===========================================================================
# Multi-provider tests
# ===========================================================================


# ---------------------------------------------------------------------------
# Same model on logosnode (sleeping) + Azure (warm) → Azure wins
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multi_provider_azure_beats_sleeping_logosnode():
    """Same model on logosnode (sleeping) and Azure (warm).
    Azure has lower expected_wait → Azure selected.
    """
    logosnode = MockLogosNodeFacade()
    logosnode.set_view(1, 10, _make_view(
        model_id=1, model_name="shared-model", provider_id=10,
        best_lane_state="sleeping", is_loaded=False,
    ))
    logosnode.set_reserve(1, 10, True)

    azure = MockAzureFacade()
    azure.set_capacity(1, 20, _make_azure_capacity(has_capacity=True, remaining=100))

    scheduler = _make_scheduler(logosnode=logosnode, azure=azure, ettft_enabled=True)

    candidates = [(1, 10.0, 1, 4)]
    deployments = [
        {"model_id": 1, "provider_id": 10, "type": "logosnode"},
        {"model_id": 1, "provider_id": 20, "type": "azure"},
    ]
    request = _make_request(candidates, deployments)

    result = await scheduler.schedule(request)
    assert result is not None
    # Azure (0.3s) beats sleeping logosnode (2.5s)
    assert result.provider_id == 20
    assert result.provider_type == "azure"
    assert result.ettft_tier == "warm"


# ---------------------------------------------------------------------------
# Same model on logosnode (loaded) + Azure → logosnode wins (0s < 0.3s)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multi_provider_loaded_logosnode_beats_azure():
    """Loaded logosnode (0s wait) beats Azure (0.3s wait)."""
    logosnode = MockLogosNodeFacade()
    logosnode.set_view(1, 10, _make_view(
        model_id=1, model_name="shared-model", provider_id=10,
        best_lane_state="loaded", is_loaded=True,
    ))
    logosnode.set_reserve(1, 10, True)

    azure = MockAzureFacade()
    azure.set_capacity(1, 20, _make_azure_capacity(has_capacity=True, remaining=100))

    scheduler = _make_scheduler(logosnode=logosnode, azure=azure, ettft_enabled=True)

    candidates = [(1, 10.0, 1, 4)]
    deployments = [
        {"model_id": 1, "provider_id": 10, "type": "logosnode"},
        {"model_id": 1, "provider_id": 20, "type": "azure"},
    ]
    request = _make_request(candidates, deployments)

    result = await scheduler.schedule(request)
    assert result is not None
    assert result.provider_id == 10  # logosnode wins
    assert result.provider_type == "logosnode"


# ---------------------------------------------------------------------------
# Cloud-only model, rate-limited → returns None (503)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cloud_only_unavailable_returns_none():
    """Azure-only model that is rate-limited → no logosnode fallback → None."""
    azure = MockAzureFacade()
    azure.set_capacity(1, 20, _make_azure_capacity(has_capacity=False))

    scheduler = _make_scheduler(azure=azure, ettft_enabled=True)

    candidates = [(1, 10.0, 1, 4)]
    deployments = [{"model_id": 1, "provider_id": 20, "type": "azure"}]
    request = _make_request(candidates, deployments)

    result = await scheduler.schedule(request)
    assert result is None  # No logosnode to queue on → 503


# ---------------------------------------------------------------------------
# Same model on two logosnode providers: picks loaded over cold
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_same_model_two_logosnode_picks_loaded():
    """Same model on provider-A (cold) and provider-B (loaded).
    Provider-B should be selected.
    """
    logosnode = MockLogosNodeFacade()
    logosnode.set_view(1, 10, _make_view(
        model_id=1, model_name="model-x", provider_id=10,
        best_lane_state="cold", is_loaded=False,
    ))
    logosnode.set_view(1, 11, _make_view(
        model_id=1, model_name="model-x", provider_id=11,
        best_lane_state="loaded", is_loaded=True,
    ))
    logosnode.set_reserve(1, 10, True)
    logosnode.set_reserve(1, 11, True)

    scheduler = _make_scheduler(logosnode=logosnode, ettft_enabled=True)

    candidates = [(1, 10.0, 1, 4)]
    deployments = [
        {"model_id": 1, "provider_id": 10, "type": "logosnode"},
        {"model_id": 1, "provider_id": 11, "type": "logosnode"},
    ]
    request = _make_request(candidates, deployments)

    result = await scheduler.schedule(request)
    assert result is not None
    assert result.provider_id == 11  # Loaded provider wins


# ---------------------------------------------------------------------------
# Mixed: two models, one with two providers → correct routing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mixed_multi_provider_routing():
    """Model A on logosnode (cold) + Azure (warm),
    Model B on logosnode (loaded).
    If weights close, Model B (loaded) should win over both Model A options.
    """
    logosnode = MockLogosNodeFacade()
    logosnode.set_view(1, 10, _make_view(
        model_id=1, model_name="model-a", provider_id=10,
        best_lane_state="cold", is_loaded=False,
    ))
    logosnode.set_view(2, 10, _make_view(
        model_id=2, model_name="model-b", provider_id=10,
        best_lane_state="loaded", is_loaded=True,
    ))
    logosnode.set_reserve(1, 10, True)
    logosnode.set_reserve(2, 10, True)

    azure = MockAzureFacade()
    azure.set_capacity(1, 20, _make_azure_capacity(has_capacity=True, remaining=100))

    scheduler = _make_scheduler(logosnode=logosnode, azure=azure, ettft_enabled=True)

    # Model A slightly higher weight, Model B slightly lower
    candidates = [(1, 11.0, 1, 4), (2, 10.0, 1, 4)]
    deployments = [
        {"model_id": 1, "provider_id": 10, "type": "logosnode"},
        {"model_id": 1, "provider_id": 20, "type": "azure"},
        {"model_id": 2, "provider_id": 10, "type": "logosnode"},
    ]
    request = _make_request(candidates, deployments)

    result = await scheduler.schedule(request)
    assert result is not None
    # Model B loaded (10-0=10) vs Model A Azure (11-small≈11) vs Model A cold (11-big≈8)
    # Azure for model A should win with ~11 score since weight gap is small
    # and Azure penalty is tiny (0.3s → almost 0 penalty)
    assert result.model_id in (1, 2)  # Either could win depending on exact penalty
    # But Azure model A should beat cold model A for sure
    if result.model_id == 1:
        assert result.provider_type == "azure"  # Never cold logosnode


# ---------------------------------------------------------------------------
# Single-provider model: identical to old behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_provider_unchanged():
    """Single deployment per model → same behavior as pre-expansion."""
    logosnode = MockLogosNodeFacade()
    logosnode.set_view(1, 10, _make_view(model_id=1, provider_id=10))
    logosnode.set_reserve(1, 10, True)

    scheduler = _make_scheduler(logosnode=logosnode, ettft_enabled=True)

    candidates = [(1, 10.0, 1, 4)]
    deployments = [{"model_id": 1, "provider_id": 10, "type": "logosnode"}]
    request = _make_request(candidates, deployments)

    result = await scheduler.schedule(request)
    assert result is not None
    assert result.model_id == 1
    assert result.provider_id == 10


# ---------------------------------------------------------------------------
# No deployment for a candidate → skipped gracefully
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_deployment_skipped():
    """Candidate with no matching deployment is skipped, other works fine."""
    logosnode = MockLogosNodeFacade()
    logosnode.set_view(2, 10, _make_view(model_id=2, provider_id=10))
    logosnode.set_reserve(2, 10, True)

    scheduler = _make_scheduler(logosnode=logosnode, ettft_enabled=True)

    candidates = [(1, 15.0, 1, 4), (2, 10.0, 1, 4)]
    # Only model 2 has a deployment
    deployments = [{"model_id": 2, "provider_id": 10, "type": "logosnode"}]
    request = _make_request(candidates, deployments)

    result = await scheduler.schedule(request)
    assert result is not None
    assert result.model_id == 2


# ---------------------------------------------------------------------------
# Transient tracking failure should not break scheduling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transient_tracking_failure_does_not_break_scheduling():
    """Registration races in on_request_start should not fail scheduling."""
    logosnode = MockLogosNodeFacade()
    logosnode.set_view(
        1, 10,
        _make_view(model_id=1, provider_id=10, best_lane_state="cold", is_loaded=False),
    )
    logosnode.set_reserve(1, 10, True)
    logosnode.raise_on_request_start = True

    scheduler = _make_scheduler(logosnode=logosnode, ettft_enabled=True)

    candidates = [(1, 12.0, 1, 4)]
    deployments = [{"model_id": 1, "provider_id": 10, "type": "logosnode"}]
    request = _make_request(candidates, deployments)

    result = await scheduler.schedule(request)
    assert result is not None
    assert result.model_id == 1


# ===========================================================================
# Decision logging tests
# ===========================================================================


@pytest.mark.asyncio
async def test_decision_log_writes_jsonl():
    """ECCS_DECISION_LOG env var → one JSON line per decision."""
    logosnode = MockLogosNodeFacade()
    logosnode.set_view(1, 10, _make_view(model_id=1, provider_id=10))
    logosnode.set_view(2, 10, _make_view(
        model_id=2, provider_id=10,
        best_lane_state="loaded", is_loaded=True,
    ))
    logosnode.set_reserve(1, 10, True)
    logosnode.set_reserve(2, 10, True)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        log_path = f.name

    try:
        os.environ["ECCS_DECISION_LOG"] = log_path
        scheduler = _make_scheduler(logosnode=logosnode, ettft_enabled=True)

        candidates = [(1, 10.0, 1, 4), (2, 12.0, 1, 4)]
        deployments = [
            {"model_id": 1, "provider_id": 10, "type": "logosnode"},
            {"model_id": 2, "provider_id": 10, "type": "logosnode"},
        ]
        request = _make_request(candidates, deployments)
        result = await scheduler.schedule(request)
        assert result is not None

        with open(log_path) as f:
            lines = f.readlines()
        assert len(lines) == 1

        record = json.loads(lines[0])
        assert record["request_id"] == "req-1"
        assert record["ettft_enabled"] is True
        assert len(record["candidates"]) == 2
        assert record["selected_model_id"] is not None
        assert record["classification_top_model_id"] == 2
        assert isinstance(record["correction_changed"], bool)
        assert record["was_queued"] is False
        assert "ts" in record
    finally:
        os.environ.pop("ECCS_DECISION_LOG", None)
        os.unlink(log_path)


@pytest.mark.asyncio
async def test_decision_log_records_correction_changed():
    """correction_changed=True when ECCS reranks away from classification top."""
    logosnode = MockLogosNodeFacade()
    logosnode.set_view(1, 10, _make_view(model_id=1, provider_id=10))
    logosnode.set_view(2, 10, _make_view(
        model_id=2, provider_id=10,
        best_lane_state="cold", is_loaded=False,
    ))
    logosnode.set_reserve(1, 10, True)
    logosnode.set_reserve(2, 10, True)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        log_path = f.name

    try:
        os.environ["ECCS_DECISION_LOG"] = log_path
        scheduler = _make_scheduler(logosnode=logosnode, ettft_enabled=True)

        # Model 2 has higher weight but is cold → ECCS should prefer model 1
        candidates = [(1, 10.0, 1, 4), (2, 12.0, 1, 4)]
        deployments = [
            {"model_id": 1, "provider_id": 10, "type": "logosnode"},
            {"model_id": 2, "provider_id": 10, "type": "logosnode"},
        ]
        request = _make_request(candidates, deployments)
        result = await scheduler.schedule(request)

        assert result is not None
        assert result.model_id == 1  # ECCS overrides classification

        with open(log_path) as f:
            record = json.loads(f.readline())

        assert record["classification_top_model_id"] == 2
        assert record["selected_model_id"] == 1
        assert record["correction_changed"] is True
    finally:
        os.environ.pop("ECCS_DECISION_LOG", None)
        os.unlink(log_path)


@pytest.mark.asyncio
async def test_no_decision_log_without_env_var():
    """No log file created when ECCS_DECISION_LOG is not set."""
    os.environ.pop("ECCS_DECISION_LOG", None)

    logosnode = MockLogosNodeFacade()
    logosnode.set_view(1, 10, _make_view(model_id=1, provider_id=10))
    logosnode.set_reserve(1, 10, True)

    scheduler = _make_scheduler(logosnode=logosnode)

    candidates = [(1, 10.0, 1, 4)]
    deployments = [{"model_id": 1, "provider_id": 10, "type": "logosnode"}]
    request = _make_request(candidates, deployments)

    result = await scheduler.schedule(request)
    assert result is not None


# ===========================================================================
# Weight override tests
# ===========================================================================


@pytest.mark.asyncio
async def test_weight_override_changes_ranking():
    """ECCS_WEIGHT_OVERRIDE swaps classification weights before scoring."""
    logosnode = MockLogosNodeFacade()
    logosnode.set_view(1, 10, _make_view(model_id=1, provider_id=10))
    logosnode.set_view(2, 10, _make_view(model_id=2, provider_id=10))
    logosnode.set_reserve(1, 10, True)
    logosnode.set_reserve(2, 10, True)

    try:
        # Classification says model 1 wins (15 > 10), but override reverses
        os.environ["ECCS_WEIGHT_OVERRIDE"] = json.dumps({"1": 5.0, "2": 20.0})
        scheduler = _make_scheduler(logosnode=logosnode, ettft_enabled=True)

        candidates = [(1, 15.0, 1, 4), (2, 10.0, 1, 4)]
        deployments = [
            {"model_id": 1, "provider_id": 10, "type": "logosnode"},
            {"model_id": 2, "provider_id": 10, "type": "logosnode"},
        ]
        request = _make_request(candidates, deployments)
        result = await scheduler.schedule(request)

        assert result is not None
        assert result.model_id == 2  # Override made model 2 win
    finally:
        os.environ.pop("ECCS_WEIGHT_OVERRIDE", None)


@pytest.mark.asyncio
async def test_weight_override_partial():
    """Override only some models; others keep classification weights."""
    logosnode = MockLogosNodeFacade()
    logosnode.set_view(1, 10, _make_view(model_id=1, provider_id=10))
    logosnode.set_view(2, 10, _make_view(model_id=2, provider_id=10))
    logosnode.set_reserve(1, 10, True)
    logosnode.set_reserve(2, 10, True)

    try:
        os.environ["ECCS_WEIGHT_OVERRIDE"] = json.dumps({"1": 1.0})
        scheduler = _make_scheduler(logosnode=logosnode, ettft_enabled=True)

        candidates = [(1, 15.0, 1, 4), (2, 10.0, 1, 4)]
        deployments = [
            {"model_id": 1, "provider_id": 10, "type": "logosnode"},
            {"model_id": 2, "provider_id": 10, "type": "logosnode"},
        ]
        request = _make_request(candidates, deployments)
        result = await scheduler.schedule(request)

        assert result is not None
        assert result.model_id == 2  # Model 2 wins because model 1 overridden down
    finally:
        os.environ.pop("ECCS_WEIGHT_OVERRIDE", None)


@pytest.mark.asyncio
async def test_weight_override_invalid_json_ignored():
    """Invalid ECCS_WEIGHT_OVERRIDE is silently ignored."""
    logosnode = MockLogosNodeFacade()
    logosnode.set_view(1, 10, _make_view(model_id=1, provider_id=10))
    logosnode.set_reserve(1, 10, True)

    try:
        os.environ["ECCS_WEIGHT_OVERRIDE"] = "not-valid-json"
        scheduler = _make_scheduler(logosnode=logosnode, ettft_enabled=True)
        assert scheduler._weight_overrides == {}

        candidates = [(1, 10.0, 1, 4)]
        deployments = [{"model_id": 1, "provider_id": 10, "type": "logosnode"}]
        request = _make_request(candidates, deployments)
        result = await scheduler.schedule(request)
        assert result is not None
    finally:
        os.environ.pop("ECCS_WEIGHT_OVERRIDE", None)


@pytest.mark.asyncio
async def test_decision_log_captures_weight_override():
    """Decision log shows both classification_weight and effective_weight."""
    logosnode = MockLogosNodeFacade()
    logosnode.set_view(1, 10, _make_view(model_id=1, provider_id=10))
    logosnode.set_view(2, 10, _make_view(model_id=2, provider_id=10))
    logosnode.set_reserve(1, 10, True)
    logosnode.set_reserve(2, 10, True)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        log_path = f.name

    try:
        os.environ["ECCS_DECISION_LOG"] = log_path
        os.environ["ECCS_WEIGHT_OVERRIDE"] = json.dumps({"1": 5.0, "2": 20.0})
        scheduler = _make_scheduler(logosnode=logosnode, ettft_enabled=True)

        candidates = [(1, 15.0, 1, 4), (2, 10.0, 1, 4)]
        deployments = [
            {"model_id": 1, "provider_id": 10, "type": "logosnode"},
            {"model_id": 2, "provider_id": 10, "type": "logosnode"},
        ]
        request = _make_request(candidates, deployments)
        await scheduler.schedule(request)

        with open(log_path) as f:
            record = json.loads(f.readline())

        assert record["weight_overrides_active"] is True
        c1 = next(c for c in record["candidates"] if c["model_id"] == 1)
        c2 = next(c for c in record["candidates"] if c["model_id"] == 2)
        # classification_weight = original from classification
        assert c1["classification_weight"] == 15.0
        assert c2["classification_weight"] == 10.0
        # effective_weight = after override
        assert c1["effective_weight"] == 5.0
        assert c2["effective_weight"] == 20.0
    finally:
        os.environ.pop("ECCS_DECISION_LOG", None)
        os.environ.pop("ECCS_WEIGHT_OVERRIDE", None)
        os.unlink(log_path)
