"""Tests for ClassificationCorrectingScheduler with multi-provider expansion."""

from unittest.mock import MagicMock

import pytest

from logos.pipeline.correcting_scheduler import ClassificationCorrectingScheduler
from logos.pipeline.scheduler_interface import SchedulingRequest
from logos.queue import PriorityQueueManager
from logos.sdi.models import AzureCapacity, LaneSchedulerSignals, ModelSchedulerView


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
        warmest_e2e_latency_p50_seconds=0.5,
        gpu_cache_pressure_max=None,
        lanes=[
            LaneSchedulerSignals(
                lane_id="lane-1",
                model_name=model_name,
                runtime_state=best_lane_state,
                sleep_state="awake" if is_loaded else "unsupported",
                is_vllm=False,
                active_requests=1 if is_loaded else 0,
                queue_waiting=aggregate_queue_waiting,
                requests_running=1.0 if is_loaded else 0.0,
                gpu_cache_usage_percent=None,
                ttft_p95_seconds=warmest_ttft_p95_seconds,
                e2e_latency_p50_seconds=0.5,
                effective_vram_mb=8000.0,
                num_parallel=4,
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
        self._gpu_scores: dict[int, int] = {}  # provider_id -> gpu_performance_score
        self._offline_providers: set[int] = set()

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

    def get_provider_name(self, provider_id):
        return f"worker-{provider_id}"

    def get_all_lane_signals(self, provider_id):
        # No sibling-lane visibility needed for these tests.
        raise KeyError(provider_id)

    def get_gpu_performance_score(self, provider_id):
        return self._gpu_scores.get(provider_id, 100)

    def set_gpu_performance_score(self, provider_id, score):
        self._gpu_scores[provider_id] = score

    def is_provider_online(self, provider_id):
        return provider_id not in self._offline_providers

    def mark_provider_offline(self, provider_id):
        self._offline_providers.add(provider_id)

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
# Scenario E: Azure candidate selected when local is cold
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_candidates_returns_none():
    """No candidates → None."""
    scheduler = _make_scheduler()
    request = _make_request([], [])
    result = await scheduler.schedule(request)
    assert result is None


@pytest.mark.asyncio
async def test_offline_logosnode_provider_is_skipped_in_favor_of_online_one():
    """Regression for prod 2026-06-04: a disconnected worker was still being
    chosen by the correcting scheduler (treated as COLD/UNAVAILABLE fallback),
    which then crashed at execution-context resolution with
    ``LogosNodeOfflineError("No active logosnode worker session")``. The
    scheduler now consults `is_provider_online` and skips offline workers
    entirely so requests for the same model route to a healthy peer instead.
    """
    logosnode = MockLogosNodeFacade()
    offline_provider = 15
    online_provider = 16
    logosnode.set_view(1, online_provider, _make_view(model_id=1, provider_id=online_provider))
    logosnode.set_view(1, offline_provider, _make_view(model_id=1, provider_id=offline_provider))
    logosnode.mark_provider_offline(offline_provider)

    scheduler = _make_scheduler(logosnode=logosnode)
    deployments = [
        {"model_id": 1, "provider_id": offline_provider, "type": "logosnode"},
        {"model_id": 1, "provider_id": online_provider, "type": "logosnode"},
    ]
    request = _make_request([(1, 1.0, 0, 4)], deployments)

    result = await scheduler.schedule(request)

    assert result is not None
    assert result.provider_id == online_provider


@pytest.mark.asyncio
async def test_offline_only_logosnode_provider_returns_no_candidate():
    """If every logosnode candidate for a model is offline, the scheduler
    must not pick any of them — picking an offline provider would lead
    straight to LogosNodeOfflineError in the pipeline. Returning None
    surfaces the failure cleanly (the caller decides how to respond)."""
    logosnode = MockLogosNodeFacade()
    offline_provider = 15
    logosnode.set_view(1, offline_provider, _make_view(model_id=1, provider_id=offline_provider))
    logosnode.mark_provider_offline(offline_provider)

    scheduler = _make_scheduler(logosnode=logosnode)
    deployments = [{"model_id": 1, "provider_id": offline_provider, "type": "logosnode"}]
    request = _make_request([(1, 1.0, 0, 4)], deployments)

    result = await scheduler.schedule(request)
    assert result is None


# ---------------------------------------------------------------------------
# Same model on two logosnode providers: picks loaded over cold
# ---------------------------------------------------------------------------
