"""Queued-work accounting must follow the dispatched provider.

A model-wide queue can hand a queued request to an eligible peer instead of
the deployment it was enqueued against, so the SDI bookkeeping after dequeue
has to use the result's provider, not the enqueue provider — otherwise
active-request counts drift away from the worker that actually runs the
request (the correcting scheduler already does this; FCFS and utilization
lagged behind)."""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from logos.pipeline.fcfs_scheduler import FcfScheduler
from logos.pipeline.scheduler_interface import SchedulingRequest, SchedulingResult
from logos.pipeline.utilization_scheduler import UtilizationAwareScheduler
from logos.queue import PriorityQueueManager
from logos.queue.priority_queue import Priority

ENQUEUED_PROVIDER = 10
PEER_PROVIDER = 20
MODEL_ID = 1


class _NoCapacityRecordingFacade:
    """Logosnode facade that never has spare capacity (forcing the queue
    path) and records the provider each accounting callback saw."""

    def __init__(self):
        self.calls = []

    def get_model_status(self, model_id, provider_id):
        return SimpleNamespace(is_loaded=True, active_requests=0, queue_depth=0)

    def try_reserve_capacity(self, model_id, provider_id, request_id):
        return False

    def on_request_start(self, request_id, **kwargs):
        self.calls.append(("start", request_id, kwargs))

    def on_request_begin_processing(self, request_id, **kwargs):
        self.calls.append(("begin", request_id, kwargs))


async def _queue_then_dispatch_on_peer(scheduler, queue_mgr):
    """Enqueue via schedule() (no capacity anywhere), then resolve the queued
    future as if the peer provider had dequeued and dispatched it."""
    request = SchedulingRequest(
        request_id="req-1",
        classified_models=[(MODEL_ID, 1.0, 5)],
        deployments=[
            {"model_id": MODEL_ID, "provider_id": ENQUEUED_PROVIDER, "type": "logosnode"},
            {"model_id": MODEL_ID, "provider_id": PEER_PROVIDER, "type": "logosnode"},
        ],
        payload={},
    )
    task = asyncio.create_task(scheduler.schedule(request))
    for _ in range(100):
        await asyncio.sleep(0)
        if queue_mgr.get_total_depth_by_model(MODEL_ID) == 1:
            break
    assert queue_mgr.get_total_depth_by_model(MODEL_ID) == 1, "request did not reach the queue"

    entries = queue_mgr.get_entries_for_priority(MODEL_ID, Priority.NORMAL)
    result = SchedulingResult(
        model_id=MODEL_ID,
        provider_id=PEER_PROVIDER,
        provider_type="logosnode",
        queue_entry_id=None,
        was_queued=True,
        queue_depth_at_schedule=1,
    )
    entries[0].task.set_result(result)
    return await task


@pytest.mark.asyncio
async def test_fcfs_accounts_queued_work_on_the_dispatched_provider():
    queue_mgr = PriorityQueueManager()
    facade = _NoCapacityRecordingFacade()
    scheduler = FcfScheduler(
        queue_manager=queue_mgr,
        logosnode_facade=facade,
        azure_facade=MagicMock(),
    )

    await _queue_then_dispatch_on_peer(scheduler, queue_mgr)

    started = [c[2]["provider_id"] for c in facade.calls if c[0] == "start"]
    begun = [c[2]["provider_id"] for c in facade.calls if c[0] == "begin"]
    # The peer dispatched the work — both callbacks must name it, not the
    # deployment the request was enqueued against.
    assert started == [PEER_PROVIDER]
    assert begun == [PEER_PROVIDER]


@pytest.mark.asyncio
async def test_utilization_accounts_queued_work_on_the_dispatched_provider():
    queue_mgr = PriorityQueueManager()
    facade = _NoCapacityRecordingFacade()
    scheduler = UtilizationAwareScheduler(
        queue_manager=queue_mgr,
        logosnode_facade=facade,
        azure_facade=MagicMock(),
        model_registry={},
    )

    await _queue_then_dispatch_on_peer(scheduler, queue_mgr)

    started = [c[2]["provider_id"] for c in facade.calls if c[0] == "start"]
    begun = [c[2]["provider_id"] for c in facade.calls if c[0] == "begin"]
    assert started == [PEER_PROVIDER]
    assert begun == [PEER_PROVIDER]
