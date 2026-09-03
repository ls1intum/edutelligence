"""The queue-wait budget caps how long a scheduler waits for a lane.

``SchedulingRequest.ingress_at`` carries the request's ingress stamp, and the
scheduler recomputes the client window that is still left from it immediately
before the queue wait (``remaining_queue_wait_s``). Pre-queue work (auth,
worker reconnect wait, classification) and the synchronous scheduling phase in
between all count against the window, so a request that spent most of it
before reaching the queue gets only the remainder — and one whose budget is
already spent is answered with a queue-timeout 429 immediately instead of
holding a queue slot for minutes.
"""

import asyncio
import time
from unittest.mock import MagicMock

import pytest

from logos import EttftEstimate, ReadinessTier, SchedulingRequest, SchedulingResult
from logos.pipeline.correcting_scheduler import ClassificationCorrectingScheduler
from logos.pipeline.scheduler_interface import QueueTimeoutError
from logos.queue import PriorityQueueManager
from logos.queue.priority_queue import Priority
from logos.timeouts import DEFAULT_QUEUE_WAIT_TIMEOUT_S

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


def _make_request(request_id: str, ingress_at=None, timeout_s=None) -> SchedulingRequest:
    return SchedulingRequest(
        request_id=request_id,
        payload={"model": "m"},
        deployments=[{"model_id": MODEL_ID, "provider_id": PROVIDER_ID, "type": "logosnode"}],
        classified_models=[(MODEL_ID, 1.0, 5)],
        ingress_at=ingress_at,
        timeout_s=timeout_s,
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
    # Ingress already past the whole window: nothing is left to wait.
    wait = await _queue_request(
        scheduler, _make_request("req-1", ingress_at=time.monotonic() - DEFAULT_QUEUE_WAIT_TIMEOUT_S - 5.0)
    )
    with pytest.raises(QueueTimeoutError):
        await asyncio.wait_for(wait, timeout=5.0)
    # The entry must not linger in the queue after the timeout.
    assert scheduler._queue_mgr.get_total_depth_all() == 0


async def test_fresh_budget_still_waits_for_the_lane():
    scheduler = _make_scheduler()
    wait = await _queue_request(scheduler, _make_request("req-1", ingress_at=time.monotonic()))
    entries = scheduler._queue_mgr.get_entries_for_priority(MODEL_ID, Priority.NORMAL)
    assert len(entries) == 1
    entries[0].task.set_result(_dispatched_result())
    assert (await asyncio.wait_for(wait, timeout=5.0)).model_id == MODEL_ID


async def test_synchronous_scheduling_time_counts_against_the_budget(monkeypatch):
    """The wait cap must be the budget left at wait time, not at construction.

    The correcting scheduler scores candidates synchronously before the queue
    wait, and a stale candidate's SDI refresh blocks on an HTTP fetch with a
    5s timeout — so that phase alone can spend most of the client window
    after the request was constructed. A budget fixed at construction time
    would let the 429 land past the client's watchdog; recomputing it
    immediately before the wait keeps the whole request inside the window.
    """
    monkeypatch.setenv("LOGOS_TIMEOUT_S", "5")  # small window keeps the test fast
    ingress_at = time.monotonic() - 1.5  # ~3.5s of the 5s window left at construction

    def slow_scheduler_view(*_args, **_kwargs):
        # Stand-in for the blocking /api/ps refresh a stale candidate triggers.
        time.sleep(2.5)
        return None  # no lanes visible → COLD estimate → queue path

    facade = MagicMock()
    facade.get_model_name.return_value = "model-a"
    facade.get_model_scheduler_view.side_effect = slow_scheduler_view
    scheduler = ClassificationCorrectingScheduler(
        queue_manager=PriorityQueueManager(),
        logosnode_facade=facade,
        azure_facade=MagicMock(),
    )
    scheduler.update_model_registry({(MODEL_ID, PROVIDER_ID): "logosnode"})

    request = _make_request("req-1", ingress_at=ingress_at)

    with pytest.raises(QueueTimeoutError) as excinfo:
        await scheduler.schedule(request)

    # The cap must be the ~1s left at wait time (5 - 1.5 - 2.5), not the
    # ~3.5s that were still left when the request was constructed.
    assert excinfo.value.timeout_s < 2.5
    # And end to end the 429 still lands inside the client window.
    assert time.monotonic() - ingress_at <= 5.0 + 1.5


async def test_short_request_timeout_binds_the_remaining_budget():
    """A request timeout shorter than the default window is the client budget.

    The client waits ``timeout_s`` seconds in total, not ``timeout_s`` on top
    of whatever it already spent on auth, reconnect and scoring: with a 4s
    timeout and 2.5s already spent, the scheduler may only wait the ~1.5s
    left, not the full 4s again (which would deliver the 429 ~6.5s after
    ingress, after the client gave up at 4s).
    """
    scheduler = _make_scheduler()
    ingress_at = time.monotonic() - 2.5  # pre-queue work already spent 2.5s
    wait = await _queue_request(scheduler, _make_request("req-1", ingress_at=ingress_at, timeout_s=4.0))
    with pytest.raises(QueueTimeoutError) as excinfo:
        await asyncio.wait_for(wait, timeout=10.0)
    # The cap must be the ~1.5s left of the 4s request budget at wait time,
    # not the full 4s request timeout.
    assert excinfo.value.timeout_s < 3.0
    # And end to end the 429 still lands at or before the client's own
    # timeout, not after it.
    assert time.monotonic() - ingress_at <= 4.0 + 1.5
    # The entry must not linger in the queue after the timeout.
    assert scheduler._queue_mgr.get_total_depth_all() == 0
