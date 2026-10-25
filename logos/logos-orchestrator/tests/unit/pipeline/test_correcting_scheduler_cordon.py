"""A cordoned worker takes no new work: a peer serves the request, or it waits for the worker.

A node manager cordons a worker while it replaces the worker's container. The scheduler must neither score the worker
as a normal candidate nor dispatch queued requests onto it. When the worker is the only one that can serve a model, the
request is queued instead of refused, so it is served once the worker is back.
"""

from __future__ import annotations

import asyncio

import pytest

# Reuse the mock infrastructure from the existing scheduler tests
from tests.unit.pipeline.test_correcting_scheduler import (
    MockLogosNodeFacade,
    _make_request,
    _make_scheduler,
    _make_view,
)

from logos.queue.priority_queue import Priority

MODEL_ID = 1
CORDONED = 10
PEER = 20


def _deployments(*provider_ids: int) -> list[dict]:
    return [{"model_id": MODEL_ID, "provider_id": pid, "type": "logosnode"} for pid in provider_ids]


def _facade(*provider_ids: int) -> MockLogosNodeFacade:
    facade = MockLogosNodeFacade()
    for provider_id in provider_ids:
        facade.set_view(MODEL_ID, provider_id, _make_view(model_id=MODEL_ID, provider_id=provider_id))
        facade.set_reserve(MODEL_ID, provider_id, True)
    return facade


@pytest.mark.asyncio
async def test_a_warm_peer_serves_the_request_immediately():
    facade = _facade(CORDONED, PEER)
    facade.mark_provider_cordoned(CORDONED)
    scheduler = _make_scheduler(logosnode=facade)

    result = await scheduler.schedule(_make_request([(MODEL_ID, 1.0, 0)], _deployments(CORDONED, PEER)))

    assert result is not None
    assert result.provider_id == PEER
    assert result.was_queued is False


@pytest.mark.asyncio
async def test_a_cordoned_worker_is_never_reserved_for_a_new_request():
    """Warm lane, free slots, and still no reservation: the node is about to lose its container."""
    reserved: list[int] = []
    facade = _facade(CORDONED, PEER)
    facade.mark_provider_cordoned(CORDONED)
    original = facade.try_reserve_capacity

    def spy(model_id, provider_id, request_id):
        reserved.append(provider_id)
        return original(model_id, provider_id, request_id)

    facade.try_reserve_capacity = spy
    scheduler = _make_scheduler(logosnode=facade)

    for index in range(5):
        await scheduler.schedule(_make_request([(MODEL_ID, 1.0, 0)], _deployments(CORDONED, PEER), f"req-{index}"))

    assert reserved and set(reserved) == {PEER}


@pytest.mark.asyncio
async def test_the_only_worker_for_a_model_queues_the_request_instead_of_refusing_it():
    facade = _facade(CORDONED)
    facade.mark_provider_cordoned(CORDONED)
    scheduler = _make_scheduler(logosnode=facade)
    request = _make_request([(MODEL_ID, 1.0, 0)], _deployments(CORDONED))

    waiting = asyncio.ensure_future(scheduler.schedule(request))
    await asyncio.sleep(0.05)

    assert not waiting.done(), "the request must wait, not be scheduled or refused"
    assert scheduler.get_total_queue_depth() == 1
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    assert scheduler.get_total_queue_depth() == 0


@pytest.mark.asyncio
async def test_a_cordoned_only_worker_does_not_take_a_reservation_either():
    facade = _facade(CORDONED)
    facade.mark_provider_cordoned(CORDONED)
    facade.try_reserve_capacity = lambda *args: pytest.fail("a cordoned worker must not be reserved")
    scheduler = _make_scheduler(logosnode=facade)

    waiting = asyncio.ensure_future(scheduler.schedule(_make_request([(MODEL_ID, 1.0, 0)], _deployments(CORDONED))))
    await asyncio.sleep(0.05)
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting


@pytest.mark.asyncio
async def test_the_request_is_served_by_the_worker_once_the_cordon_ends():
    facade = _facade(CORDONED)
    facade.mark_provider_cordoned(CORDONED)
    facade.is_model_lane_ready = lambda model_id, provider_id: True  # type: ignore[attr-defined]
    scheduler = _make_scheduler(logosnode=facade)
    scheduler.update_model_registry({(MODEL_ID, CORDONED): "logosnode"})

    waiting = asyncio.ensure_future(scheduler.schedule(_make_request([(MODEL_ID, 1.0, 0)], _deployments(CORDONED))))
    await asyncio.sleep(0.05)

    # While the worker is cordoned, a report or a completion must not hand it the queued request.
    scheduler.reevaluate_model_queues("model-a")
    await asyncio.sleep(0.05)
    assert not waiting.done()

    facade._cordoned_providers.clear()
    scheduler.reevaluate_model_queues("model-a")
    result = await asyncio.wait_for(waiting, timeout=2)

    assert result.provider_id == CORDONED
    assert result.was_queued is True


def test_the_queue_does_not_dispatch_onto_a_cordoned_worker():
    facade = _facade(CORDONED)
    facade.mark_provider_cordoned(CORDONED)
    facade.is_model_lane_ready = lambda model_id, provider_id: True  # type: ignore[attr-defined]
    scheduler = _make_scheduler(logosnode=facade)
    scheduler.update_model_registry({(MODEL_ID, CORDONED): "logosnode"})

    loop = asyncio.new_event_loop()
    try:
        future = loop.create_future()
        scheduler._queue_mgr.enqueue(future, MODEL_ID, CORDONED, Priority.NORMAL)
        scheduler.reevaluate_model_queues("model-a")
        loop.run_until_complete(asyncio.sleep(0))
        assert not future.done(), "a queued request was dispatched onto a cordoned worker"
    finally:
        loop.close()


def test_a_peer_takes_the_queued_request_while_the_other_worker_is_cordoned():
    """The queue is per model: the peer's lane picks the request up."""
    facade = _facade(CORDONED, PEER)
    facade.mark_provider_cordoned(CORDONED)
    facade.is_model_lane_ready = lambda model_id, provider_id: True  # type: ignore[attr-defined]
    scheduler = _make_scheduler(logosnode=facade)
    scheduler.update_model_registry({(MODEL_ID, CORDONED): "logosnode", (MODEL_ID, PEER): "logosnode"})

    loop = asyncio.new_event_loop()
    try:
        future = loop.create_future()
        scheduler._queue_mgr.enqueue(future, MODEL_ID, CORDONED, Priority.NORMAL)
        scheduler.reevaluate_model_queues("model-a")
        loop.run_until_complete(asyncio.sleep(0))
        assert future.done()
        assert future.result().provider_id == PEER
    finally:
        loop.close()
