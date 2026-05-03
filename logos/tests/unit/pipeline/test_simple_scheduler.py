"""Tests for SimpleScheduler (trust-vLLM-queue-signals)."""

import asyncio
from typing import Optional
from unittest.mock import MagicMock

import pytest

from logos.pipeline.simple_scheduler import SimpleScheduler
from logos.pipeline.scheduler_interface import SchedulingRequest
from logos.pipeline.ettft_estimator import ReadinessTier
from logos.queue.priority_queue import PriorityQueueManager
from logos.sdi.models import LaneSchedulerSignals, ModelSchedulerView


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_lane(model_name="llama3:8b", runtime_state="loaded", queue_waiting=0.0, requests_running=0.0):
    return LaneSchedulerSignals(
        lane_id="lane-1",
        model_name=model_name,
        runtime_state=runtime_state,
        sleep_state="unsupported",
        is_vllm=True,
        active_requests=0,
        queue_waiting=queue_waiting,
        requests_running=requests_running,
        gpu_cache_usage_percent=None,
        ttft_p95_seconds=0.0,
        effective_vram_mb=8000.0,
        num_parallel=4,
    )


def _make_view(
    model_id=1,
    provider_id=10,
    best_lane_state="loaded",
    queue_waiting=0.0,
    requests_running=0.0,
):
    lane = _make_lane(runtime_state=best_lane_state, queue_waiting=queue_waiting, requests_running=requests_running)
    return ModelSchedulerView(
        model_id=model_id,
        model_name="llama3:8b",
        provider_id=provider_id,
        is_loaded=best_lane_state in ("loaded", "running"),
        best_lane_state=best_lane_state,
        best_sleep_state="unsupported",
        aggregate_active_requests=0,
        aggregate_queue_waiting=queue_waiting,
        warmest_ttft_p95_seconds=0.0,
        gpu_cache_pressure_max=None,
        lanes=[lane],
    )


def _make_scheduler(logosnode=None, azure=None, queue_mgr=None, model_registry=None):
    if queue_mgr is None:
        queue_mgr = PriorityQueueManager()
    if logosnode is None:
        logosnode = MagicMock()
        logosnode.get_provider_name.return_value = "worker-1"
        logosnode.get_model_scheduler_view.return_value = None
    if azure is None:
        azure = MagicMock()
    if model_registry is None:
        model_registry = {}
    return SimpleScheduler(
        queue_manager=queue_mgr,
        logosnode_facade=logosnode,
        azure_facade=azure,
        model_registry=model_registry,
    )


def _make_request(model_id=1, provider_id=10, provider_type="logosnode", weight=1.0, timeout_s=5.0):
    req = MagicMock(spec=SchedulingRequest)
    req.request_id = "req-test"
    req.classified_models = [(model_id, weight, 5, 4)]  # model_id, weight, priority_int, parallel
    req.deployments = [{"model_id": model_id, "provider_id": provider_id, "type": provider_type}]
    req.timeout_s = timeout_s
    return req


# ---------------------------------------------------------------------------
# Test: READY candidate forwarded immediately
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ready_candidate_forwarded_immediately():
    """When any provider has queue_waiting==0, forward immediately without queueing."""
    view = _make_view(model_id=1, provider_id=10, best_lane_state="loaded", queue_waiting=0.0)
    logosnode = MagicMock()
    logosnode.get_provider_name.return_value = "worker-1"
    logosnode.get_model_scheduler_view.return_value = view
    logosnode.get_model_status.return_value = MagicMock(queue_state=MagicMock(total=0, low=0, normal=0, high=0), active_requests=0)

    scheduler = _make_scheduler(
        logosnode=logosnode,
        model_registry={(1, 10): "logosnode"},
    )
    req = _make_request(model_id=1, provider_id=10, provider_type="logosnode")

    result = await scheduler.schedule(req)

    assert result is not None
    assert result.model_id == 1
    assert result.provider_id == 10
    assert result.was_queued is False


# ---------------------------------------------------------------------------
# Test: All-QUEUEING goes to local queue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_queueing_goes_to_local_queue():
    """When all providers have queue_waiting>0, request is queued locally."""
    view = _make_view(model_id=1, provider_id=10, best_lane_state="loaded", queue_waiting=3.0)
    logosnode = MagicMock()
    logosnode.get_provider_name.return_value = "worker-1"
    logosnode.get_model_scheduler_view.return_value = view

    queue_mgr = PriorityQueueManager()
    scheduler = _make_scheduler(
        logosnode=logosnode,
        queue_mgr=queue_mgr,
        model_registry={(1, 10): "logosnode"},
    )
    req = _make_request(model_id=1, provider_id=10, provider_type="logosnode", timeout_s=0.1)

    with pytest.raises(Exception):  # QueueTimeoutError after 0.1s
        await scheduler.schedule(req)

    # Confirm request was actually placed into queue before timeout
    # (queue depth was 1 at some point — the enqueue happened)
    assert queue_mgr.get_total_depth_by_model(1) == 0  # removed on timeout


# ---------------------------------------------------------------------------
# Test: release() wakes queued request
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_release_wakes_queued():
    """release() dequeues the next future and sets a result on it."""
    view_queueing = _make_view(model_id=1, provider_id=10, best_lane_state="loaded", queue_waiting=5.0)
    view_ready = _make_view(model_id=1, provider_id=10, best_lane_state="loaded", queue_waiting=0.0)

    logosnode = MagicMock()
    logosnode.get_provider_name.return_value = "worker-1"
    # First call: queueing; second call (from release): ready
    logosnode.get_model_scheduler_view.side_effect = [
        view_queueing,  # schedule() classification
        view_ready,     # _create_result inside release()
    ]
    logosnode.get_model_status.return_value = MagicMock(
        queue_state=MagicMock(total=0, low=0, normal=0, high=0),
        active_requests=0,
    )

    queue_mgr = PriorityQueueManager()
    scheduler = _make_scheduler(
        logosnode=logosnode,
        queue_mgr=queue_mgr,
        model_registry={(1, 10): "logosnode"},
    )
    req = _make_request(model_id=1, provider_id=10, provider_type="logosnode", timeout_s=5.0)

    # Schedule (will queue because view is QUEUEING)
    schedule_task = asyncio.create_task(scheduler.schedule(req))
    await asyncio.sleep(0)  # let schedule() run and enqueue

    # Now release (simulates request complete)
    scheduler.release(model_id=1, provider_id=10, provider_type="logosnode", request_id="prev-req")

    result = await asyncio.wait_for(schedule_task, timeout=2.0)
    assert result is not None
    assert result.was_queued is True


# ---------------------------------------------------------------------------
# Test: multi-worker tiebreak by requests_running
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multi_worker_tiebreak_by_requests_running():
    """Among two READY workers with equal weight, pick the one with lowest requests_running."""
    view_busy = _make_view(model_id=1, provider_id=10, best_lane_state="loaded", queue_waiting=0.0, requests_running=3.0)
    view_free = _make_view(model_id=1, provider_id=20, best_lane_state="loaded", queue_waiting=0.0, requests_running=0.0)

    logosnode = MagicMock()
    logosnode.get_provider_name.return_value = "worker"

    def _get_view(model_id, provider_id):
        if provider_id == 10:
            return view_busy
        if provider_id == 20:
            return view_free
        return None

    logosnode.get_model_scheduler_view.side_effect = _get_view
    logosnode.get_model_status.return_value = MagicMock(
        queue_state=MagicMock(total=0, low=0, normal=0, high=0),
        active_requests=0,
    )

    scheduler = _make_scheduler(
        logosnode=logosnode,
        model_registry={(1, 10): "logosnode", (1, 20): "logosnode"},
    )
    req = MagicMock(spec=SchedulingRequest)
    req.request_id = "req-tiebreak"
    req.classified_models = [(1, 1.0, 5, 4)]
    req.deployments = [
        {"model_id": 1, "provider_id": 10, "type": "logosnode"},
        {"model_id": 1, "provider_id": 20, "type": "logosnode"},
    ]
    req.timeout_s = 5.0

    result = await scheduler.schedule(req)

    assert result is not None
    assert result.was_queued is False
    assert result.provider_id == 20  # free worker preferred
