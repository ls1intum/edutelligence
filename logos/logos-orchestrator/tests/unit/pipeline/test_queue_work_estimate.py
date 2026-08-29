"""Queued requests carry their payload's work estimate into the queue.

The queue orders by priority, then by estimated work (short first), so a
small latency-sensitive request is not made to wait for every long-running
request that arrived before it when the queue fills under load — the failure
mode behind Claude Code auto-classifier timeouts (#828). The estimate is
derived from the payload itself (prompt plus reserved output) and never from
anything the client claims.
"""

import asyncio
from unittest.mock import MagicMock

from logos import EttftEstimate, ReadinessTier, SchedulingRequest, SchedulingResult
from logos.context_budget import estimated_work_tokens
from logos.pipeline.correcting_scheduler import ClassificationCorrectingScheduler
from logos.queue import PriorityQueueManager
from logos.queue.priority_queue import Priority

MODEL_ID = 7
PROVIDER_ID = 3
CANDIDATE = (
    MODEL_ID,
    PROVIDER_ID,
    "logosnode",
    1.0,
    5,
    EttftEstimate(expected_wait_s=0.0, tier=ReadinessTier.WARM, reasoning="test"),
)


def _make_scheduler():
    facade = MagicMock()
    facade.get_model_name.return_value = "model-a"
    scheduler = ClassificationCorrectingScheduler(
        queue_manager=PriorityQueueManager(),
        logosnode_facade=facade,
        azure_facade=MagicMock(),
    )
    scheduler.update_model_registry({(MODEL_ID, PROVIDER_ID): "logosnode"})
    return scheduler


def _make_request(request_id: str, payload: dict) -> SchedulingRequest:
    return SchedulingRequest(
        request_id=request_id,
        payload=payload,
        deployments=[{"model_id": MODEL_ID, "provider_id": PROVIDER_ID, "type": "logosnode"}],
        classified_models=[(MODEL_ID, 1.0, 5)],
    )


def _dispatched_result() -> SchedulingResult:
    return SchedulingResult(
        model_id=MODEL_ID,
        provider_id=PROVIDER_ID,
        provider_type="logosnode",
        queue_entry_id=None,
        was_queued=True,
        queue_depth_at_schedule=1,
    )


async def _queue_request(scheduler, request, min_depth: int = 1) -> asyncio.Task:
    """Run the scheduler's queue path as a task and let it reach the wait.

    min_depth: wait until the queue has at least this many entries. This is
    required when you stack multiple queued requests in one test — otherwise
    the helper returns at the moment the first request is in the queue, not
    once yours is."""
    task = asyncio.create_task(scheduler._queue_and_wait(CANDIDATE, request))
    for _ in range(100):
        if scheduler._queue_mgr.get_total_depth_all() >= min_depth:
            return task
        await asyncio.sleep(0)
    raise AssertionError("request never reached the queue")


async def test_queued_entry_carries_the_payload_work_estimate():
    scheduler = _make_scheduler()
    payload = {"messages": [{"role": "user", "content": "x" * 3000}], "max_tokens": 1000}
    wait = await _queue_request(scheduler, _make_request("req-1", payload))

    entries = scheduler._queue_mgr.get_entries_for_priority(MODEL_ID, Priority.NORMAL)
    assert len(entries) == 1
    assert entries[0].work_estimate == estimated_work_tokens(payload) > 0

    entries[0].task.set_result(_dispatched_result())
    assert (await wait).model_id == MODEL_ID


async def test_unreadable_payload_queues_with_no_work_estimate():
    """0 = no opinion: audio-style payloads keep the arrival order."""
    scheduler = _make_scheduler()
    wait = await _queue_request(scheduler, _make_request("req-1", {"model": "whisper-1"}))

    entries = scheduler._queue_mgr.get_entries_for_priority(MODEL_ID, Priority.NORMAL)
    assert len(entries) == 1
    assert entries[0].work_estimate == 0

    entries[0].task.set_result(_dispatched_result())
    await wait


async def test_the_dispatcher_hands_out_small_requests_first():
    """A big request that arrived first must not be dispatched ahead of a
    small one: capacity going free goes to the short wait, not the old wait."""
    scheduler = _make_scheduler()
    small_payload = {"messages": [{"role": "user", "content": "x" * 100}], "max_tokens": 50}
    big_payload = {"messages": [{"role": "user", "content": "x" * 60_000}], "max_tokens": 8000}

    big_wait = await _queue_request(scheduler, _make_request("req-big", big_payload))
    small_wait = await _queue_request(scheduler, _make_request("req-small", small_payload), min_depth=2)

    # What the release/dispatch path pops next:
    _task, first_out = scheduler._queue_mgr.dequeue_with_entry(MODEL_ID, PROVIDER_ID)
    assert first_out.work_estimate == estimated_work_tokens(small_payload)

    first_out.task.set_result(_dispatched_result())
    _task, second_out = scheduler._queue_mgr.dequeue_with_entry(MODEL_ID, PROVIDER_ID)
    assert second_out.work_estimate == estimated_work_tokens(big_payload)
    second_out.task.set_result(_dispatched_result())

    assert (await small_wait).model_id == MODEL_ID
    assert (await big_wait).model_id == MODEL_ID
