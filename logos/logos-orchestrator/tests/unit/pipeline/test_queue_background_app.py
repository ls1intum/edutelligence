"""The background-app flag travels from the request headers to the queue.

Claude Code's background agents mark their traffic with the ``x-app: cli-bg``
header. The pipeline derives ``SchedulingRequest.background_app`` from it and
the queue gives flagged entries bounded precedence at the same priority
level — a 1-flagged : 2-regular dispatch interleave, so a latency-sensitive
call (an agent's auto-permission classifier) does not wait out a full queue
of interactive traffic, but a steady flagged stream cannot starve it either
— while unrecognised traffic keeps plain arrival order.
"""

import asyncio
from unittest.mock import MagicMock

from logos import EttftEstimate, ReadinessTier, SchedulingRequest, SchedulingResult
from logos.pipeline.correcting_scheduler import ClassificationCorrectingScheduler
from logos.pipeline.pipeline import is_background_app
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


def _make_request(request_id: str, payload: dict, background_app: bool = False) -> SchedulingRequest:
    return SchedulingRequest(
        request_id=request_id,
        payload=payload,
        deployments=[{"model_id": MODEL_ID, "provider_id": PROVIDER_ID, "type": "logosnode"}],
        classified_models=[(MODEL_ID, 1.0, 5)],
        background_app=background_app,
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


def test_is_background_app_only_flags_the_cli_bg_header():
    assert is_background_app({"x-app": "cli-bg"}) is True
    # HTTP headers are case-insensitive in name; compare the value the same
    # way.
    assert is_background_app({"X-App": "CLI-BG"}) is True
    # Interactive Claude Code sessions and anything unrecognised stay plain.
    assert is_background_app({"x-app": "cli"}) is False
    assert is_background_app({"x-app": "other-app"}) is False
    assert is_background_app({"user-agent": "claude-cli/1.0"}) is False
    assert is_background_app({}) is False


async def test_background_app_flag_reaches_the_queue():
    scheduler = _make_scheduler()
    wait = await _queue_request(scheduler, _make_request("req-1", {"model": "m"}, background_app=True))

    entries = scheduler._queue_mgr.get_entries_for_priority(MODEL_ID, Priority.NORMAL)
    assert len(entries) == 1
    assert entries[0].background_app is True

    entries[0].task.set_result(_dispatched_result())
    assert (await wait).model_id == MODEL_ID


async def test_unflagged_request_queues_as_plain_traffic():
    scheduler = _make_scheduler()
    wait = await _queue_request(scheduler, _make_request("req-1", {"model": "m"}))

    entries = scheduler._queue_mgr.get_entries_for_priority(MODEL_ID, Priority.NORMAL)
    assert len(entries) == 1
    assert entries[0].background_app is False

    entries[0].task.set_result(_dispatched_result())
    await wait


async def test_the_dispatcher_hands_out_background_app_first():
    """An interactive request that arrived first must not be dispatched ahead
    of a flagged one: capacity going free goes to the background call, not
    the old wait."""
    scheduler = _make_scheduler()
    interactive_wait = await _queue_request(
        scheduler, _make_request("req-interactive", {"messages": [{"role": "user", "content": "x" * 10_000}]})
    )
    bg_wait = await _queue_request(
        scheduler,
        _make_request("req-bg", {"messages": [{"role": "user", "content": "x" * 500}]}, background_app=True),
        min_depth=2,
    )

    # What the release/dispatch path pops next:
    _task, first_out = scheduler._queue_mgr.dequeue_with_entry(MODEL_ID, PROVIDER_ID)
    assert first_out.background_app is True

    first_out.task.set_result(_dispatched_result())
    _task, second_out = scheduler._queue_mgr.dequeue_with_entry(MODEL_ID, PROVIDER_ID)
    assert second_out.background_app is False
    second_out.task.set_result(_dispatched_result())

    assert (await bg_wait).model_id == MODEL_ID
    assert (await interactive_wait).model_id == MODEL_ID
