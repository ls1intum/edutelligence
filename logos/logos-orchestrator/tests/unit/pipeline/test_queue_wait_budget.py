"""The queue-wait budget caps how long a scheduler waits for a lane.

``SchedulingRequest.queue_wait_budget_s`` carries the client window that is
still left after pre-queue work (auth, worker reconnect wait,
classification). The scheduler waits at most that long, so a request that
spent most of its window before reaching the queue gets only the remainder
— and one whose budget is already spent is answered with a queue-timeout
429 immediately instead of holding a queue slot for minutes.
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from logos import EttftEstimate, ReadinessTier, SchedulingRequest, SchedulingResult
from logos.pipeline.correcting_scheduler import ClassificationCorrectingScheduler
from logos.pipeline.scheduler_interface import QueueTimeoutError
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


def _make_request(request_id: str, queue_wait_budget_s=None) -> SchedulingRequest:
    return SchedulingRequest(
        request_id=request_id,
        payload={"model": "m"},
        deployments=[{"model_id": MODEL_ID, "provider_id": PROVIDER_ID, "type": "logosnode"}],
        classified_models=[(MODEL_ID, 1.0, 5)],
        queue_wait_budget_s=queue_wait_budget_s,
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


async def _queue_request(scheduler, request) -> asyncio.Task:
    """Run the scheduler's queue path as a task and let it reach the wait."""
    task = asyncio.create_task(scheduler._queue_and_wait(CANDIDATE, request))
    for _ in range(100):
        if scheduler._queue_mgr.get_total_depth_all() >= 1:
            return task
        await asyncio.sleep(0)
    raise AssertionError("request never reached the queue")


async def test_exhausted_budget_times_out_immediately():
    scheduler = _make_scheduler()
    wait = await _queue_request(scheduler, _make_request("req-1", queue_wait_budget_s=0.0))
    with pytest.raises(QueueTimeoutError):
        await asyncio.wait_for(wait, timeout=5.0)
    # The entry must not linger in the queue after the timeout.
    assert scheduler._queue_mgr.get_total_depth_all() == 0


async def test_fresh_budget_still_waits_for_the_lane():
    scheduler = _make_scheduler()
    wait = await _queue_request(scheduler, _make_request("req-1", queue_wait_budget_s=60.0))
    entries = scheduler._queue_mgr.get_entries_for_priority(MODEL_ID, Priority.NORMAL)
    assert len(entries) == 1
    entries[0].task.set_result(_dispatched_result())
    assert (await asyncio.wait_for(wait, timeout=5.0)).model_id == MODEL_ID
