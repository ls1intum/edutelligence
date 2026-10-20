"""A request whose reserved lane is not ready never waits in vain.

Reproduces the situation where the scheduler reserved a lane as warm while the
planner put it to sleep: the context lookup then finds no ready lane. The
pipeline must (a) register the request with the capacity planner so a lane is
woken for it, and (b) move the request to another deployment of the same model
that can serve it now, instead of waiting for the sleeping lane.
"""

import asyncio
from types import SimpleNamespace

import pytest

from logos.pipeline.context_resolver import ContextResolver
from logos.pipeline.pipeline import RequestPipeline, _ClassificationResult
from logos.pipeline.scheduler_interface import SchedulingRequest, SchedulingResult

MODEL_ID = 31
ASLEEP = 1
WARM = 2


def _result(provider_id):
    return SchedulingResult(
        model_id=MODEL_ID,
        provider_id=provider_id,
        provider_type="logosnode",
        queue_entry_id=None,
        was_queued=False,
        queue_depth_at_schedule=0,
    )


class _Planner:
    """The capacity planner as the context resolver sees it."""

    def __init__(self):
        self.waiters = {}
        self.registered = []

    async def prepare_lane_for_request(self, provider_id, model_name):  # noqa: ARG002
        return None

    def register_lane_waiter(self, request_id, provider_id, model_name):
        self.waiters[request_id] = (provider_id, model_name)
        self.registered.append((request_id, provider_id, model_name))

    def clear_lane_waiter(self, request_id):
        self.waiters.pop(request_id, None)


class _Registry:
    """Worker lanes: provider ASLEEP has none ready until ``wake_after`` lookups."""

    def __init__(self, wake_after=None):
        self.lookups = {ASLEEP: 0, WARM: 0}
        self.wake_after = wake_after

    async def select_lane_for_model(self, provider_id, model_name, *, request_id=None):  # noqa: ARG002
        self.lookups[provider_id] += 1
        if provider_id == WARM:
            return {"lane_id": "warm-lane"}
        if self.wake_after is not None and self.lookups[provider_id] > self.wake_after:
            return {"lane_id": "woken-lane"}
        return None


class _Scheduler:
    def __init__(self, reroute_to=None):
        self.reroute_to = reroute_to
        self.released = []
        self.reroute_calls = []

    def try_reroute(self, request, model_id, exclude_provider_id):
        self.reroute_calls.append((request.request_id, model_id, exclude_provider_id))
        if self.reroute_to is None:
            return None
        # The real scheduler releases the old reservation itself on success.
        self.released.append((model_id, exclude_provider_id))
        return _result(self.reroute_to)

    def release(self, model_id, provider_id, provider_type, request_id):  # noqa: ARG002
        self.released.append((model_id, provider_id))


class _SchedulerWithoutReroute:
    def release(self, model_id, provider_id, provider_type, request_id):  # noqa: ARG002
        pass


def _deployment(provider_id):
    return {
        "model_id": MODEL_ID,
        "provider_id": provider_id,
        "model_name": "intfloat/multilingual-e5-large",
        "provider_name": f"worker-{provider_id}",
        "type": "logosnode",
    }


def _pipeline(scheduler, registry, planner):
    pipeline = RequestPipeline.__new__(RequestPipeline)
    pipeline._scheduler = scheduler
    pipeline._context_resolver = ContextResolver(logosnode_registry=registry, lane_preparer=planner)
    pipeline._monitoring = SimpleNamespace(record_scheduled=lambda **kw: None)
    # Keep the test fast: no real sleeping between polls.
    pipeline._CONTEXT_RESOLVE_FAST_INTERVAL_S = 0.0
    pipeline._CONTEXT_RESOLVE_INTERVAL_S = 0.0
    return pipeline


def _requests(request_id="req-1"):
    deployments = [_deployment(ASLEEP), _deployment(WARM)]
    scheduling_request = SchedulingRequest(
        request_id=request_id,
        payload={"input": "hello"},
        deployments=deployments,
        classified_models=[(MODEL_ID, 1.0, 1)],
    )
    pipeline_request = SimpleNamespace(deployments=deployments)
    return pipeline_request, scheduling_request


async def _resolve(pipeline, scheduling_result, request_id="req-1"):
    pipeline_request, scheduling_request = _requests(request_id)
    return await pipeline._resolve_context_with_retry(
        scheduling_result=scheduling_result,
        classification_result=_ClassificationResult(candidates=[(MODEL_ID, 1.0, 1)], stats={}),
        request_id=request_id,
        deployment_info=RequestPipeline._scheduled_deployment(pipeline_request, scheduling_result),
        pipeline_request=pipeline_request,
        scheduling_request=scheduling_request,
    )


async def test_a_request_on_a_sleeping_lane_moves_to_a_warm_deployment():
    planner = _Planner()
    registry = _Registry()
    scheduler = _Scheduler(reroute_to=WARM)
    pipeline = _pipeline(scheduler, registry, planner)

    result = await _resolve(pipeline, _result(ASLEEP))

    assert result.success is True
    assert result.provider_id == WARM
    assert result.execution_context.forward_url.endswith("/lane/warm-lane")
    # It did not sit on the sleeping lane: one lookup there, then it moved.
    assert registry.lookups[ASLEEP] == 1
    assert scheduler.reroute_calls == [("req-1", MODEL_ID, ASLEEP)]
    # The planner was told about the waiting request, and the entry is gone
    # once the request has a lane.
    assert planner.registered == [("req-1", ASLEEP, "intfloat/multilingual-e5-large")]
    assert planner.waiters == {}


async def test_cancellation_after_rerouting_releases_the_current_deployment(monkeypatch):
    planner = _Planner()
    registry = _Registry()
    scheduler = _Scheduler(reroute_to=WARM)
    pipeline = _pipeline(scheduler, registry, planner)
    resolve_context = pipeline._context_resolver.resolve_context

    async def cancel_at_new_provider(**kwargs):
        if kwargs["provider_id"] == WARM:
            raise asyncio.CancelledError
        return await resolve_context(**kwargs)

    monkeypatch.setattr(pipeline._context_resolver, "resolve_context", cancel_at_new_provider)

    with pytest.raises(asyncio.CancelledError):
        await _resolve(pipeline, _result(ASLEEP))

    assert scheduler.released == [(MODEL_ID, ASLEEP), (MODEL_ID, WARM)]
    assert planner.waiters == {}


async def test_without_an_alternative_the_request_registers_and_gets_the_woken_lane():
    planner = _Planner()
    registry = _Registry(wake_after=3)
    scheduler = _Scheduler(reroute_to=None)
    pipeline = _pipeline(scheduler, registry, planner)

    result = await _resolve(pipeline, _result(ASLEEP))

    assert result.success is True
    assert result.provider_id == ASLEEP
    assert result.execution_context.forward_url.endswith("/lane/woken-lane")
    # Registered as a waiter so the planner wakes the lane, and checked for an
    # alternative on every poll while it waited.
    assert planner.registered
    assert len(scheduler.reroute_calls) == 3
    assert planner.waiters == {}


async def test_a_scheduler_without_reroute_still_waits_for_the_lane():
    planner = _Planner()
    registry = _Registry(wake_after=1)
    pipeline = _pipeline(_SchedulerWithoutReroute(), registry, planner)

    result = await _resolve(pipeline, _result(ASLEEP))

    assert result.success is True
    assert result.provider_id == ASLEEP
    assert planner.waiters == {}


async def test_the_waiter_is_cleared_when_the_wait_times_out():
    planner = _Planner()
    registry = _Registry()
    scheduler = _Scheduler(reroute_to=None)
    pipeline = _pipeline(scheduler, registry, planner)
    pipeline._CONTEXT_RESOLVE_TIMEOUT_S = 0.0
    pipeline.record_completion = lambda **kw: None

    result = await _resolve(pipeline, _result(ASLEEP))

    assert result.success is False
    assert planner.registered
    assert planner.waiters == {}
    assert (MODEL_ID, ASLEEP) in scheduler.released
