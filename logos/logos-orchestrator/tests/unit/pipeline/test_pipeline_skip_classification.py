"""PROXY mode: PipelineRequest(skip_laura=True) skips Laura but still runs policy/token."""

import pytest

from logos import PipelineRequest, RequestPipeline, SchedulingResult


class _RecordingClassifier:
    def __init__(self):
        self.calls = []

    def classify(self, user_prompt, policy, allowed=None, system=None, skip_laura=False):  # noqa: ARG002
        self.calls.append({"skip_laura": skip_laura, "allowed": list(allowed or [])})
        return [(allowed[0], 1.0, 1)] if allowed else []


class _FakeScheduler:
    def __init__(self):
        self.last_request = None

    async def schedule(self, request):
        self.last_request = request
        return SchedulingResult(
            model_id=request.classified_models[0][0],
            provider_id=request.deployments[0]["provider_id"],
            provider_type=request.deployments[0]["type"],
            queue_entry_id=None,
            was_queued=False,
            queue_depth_at_schedule=0,
        )

    def release(self, *args, **kwargs):  # noqa: ARG002
        return None

    def get_total_queue_depth(self):
        return 0

    def update_provider_stats(self, *args, **kwargs):  # noqa: ARG002
        return None


class _StubExecutionContext:
    def __init__(self, model_id, provider_id):
        self.model_id = model_id
        self.provider_id = provider_id


class _FakeContextResolver:
    def __init__(self):
        self.kwargs = None

    async def resolve_context(  # noqa: ARG002
        self, model_id, provider_id, request_path=None, request_id=None, deployment_info=None, wait_for_lane=True
    ):
        self.kwargs = {
            "model_id": model_id,
            "provider_id": provider_id,
            "request_path": request_path,
            "request_id": request_id,
            "deployment_info": deployment_info,
        }
        return _StubExecutionContext(model_id, provider_id)


class _FakeMonitoring:
    def record_enqueue(self, **kwargs):  # noqa: ARG002
        pass

    def record_scheduled(self, **kwargs):  # noqa: ARG002
        pass

    def record_provider(self, *args, **kwargs):  # noqa: ARG002
        pass

    def record_complete(self, **kwargs):  # noqa: ARG002
        pass

    def record_provider_metrics(self, *args, **kwargs):  # noqa: ARG002
        pass


def _build_pipeline():
    classifier = _RecordingClassifier()
    scheduler = _FakeScheduler()
    resolver = _FakeContextResolver()
    pipeline = RequestPipeline(
        classifier=classifier,
        scheduler=scheduler,
        executor=object(),
        context_resolver=resolver,
        monitoring=_FakeMonitoring(),
    )
    return pipeline, classifier, scheduler, resolver


@pytest.mark.asyncio
async def test_skip_laura_propagates_to_classifier():
    """skip_laura=True still calls classify (policy + token), but with skip_laura=True."""
    pipeline, classifier, _scheduler, _resolver = _build_pipeline()

    result = await pipeline.process(
        PipelineRequest(
            payload={"messages": [{"role": "user", "content": "hi"}]},
            headers={},
            allowed_models=[27],
            deployments=[{"model_id": 27, "provider_id": 12, "type": "cloud"}],
            policy=None,
            skip_laura=True,
        )
    )

    assert len(classifier.calls) == 1
    assert classifier.calls[0]["skip_laura"] is True
    assert classifier.calls[0]["allowed"] == [27]
    assert result.success is True


@pytest.mark.asyncio
async def test_default_does_not_skip_laura():
    """Without the flag, classify is called with skip_laura=False."""
    pipeline, classifier, _scheduler, _resolver = _build_pipeline()

    await pipeline.process(
        PipelineRequest(
            payload={"messages": [{"role": "user", "content": "hi"}]},
            headers={},
            allowed_models=[27],
            deployments=[{"model_id": 27, "provider_id": 12, "type": "cloud"}],
            policy=None,
        )
    )

    assert len(classifier.calls) == 1
    assert classifier.calls[0]["skip_laura"] is False


@pytest.mark.asyncio
async def test_request_path_propagates_to_context_resolver():
    """The PipelineRequest.request_path is forwarded to resolve_context."""
    pipeline, _classifier, _scheduler, resolver = _build_pipeline()

    await pipeline.process(
        PipelineRequest(
            payload={"messages": [{"role": "user", "content": "hi"}]},
            headers={},
            allowed_models=[27],
            deployments=[{"model_id": 27, "provider_id": 12, "type": "cloud"}],
            policy=None,
            skip_laura=True,
            request_path="v1/chat/completions",
        )
    )

    assert resolver.kwargs is not None
    assert resolver.kwargs["request_path"] == "v1/chat/completions"
    # The scheduled entry of the request's deployment list rides along so the
    # resolver can skip its database roundtrip for logosnode targets .
    assert resolver.kwargs["deployment_info"] == {"model_id": 27, "provider_id": 12, "type": "cloud"}


@pytest.mark.parametrize("cancel_during_resolve", [True, False])
async def test_cancelled_context_resolution_releases_admission_and_tracking(cancel_during_resolve):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from logos.benchmarks.reservations import benchmark_reservations
    from logos.pipeline.base_scheduler import BaseScheduler
    from logos.sdi.logosnode_facade import LogosNodeSchedulingDataFacade

    pipeline, _, scheduler, resolver = _build_pipeline()
    facade = LogosNodeSchedulingDataFacade(MagicMock())
    provider = MagicMock(provider_id=9040)
    provider._model_id_to_name = {27: "cancel-model"}
    provider.try_reserve_capacity.return_value = True
    provider.get_model_status.return_value = SimpleNamespace(queue_depth=0)
    facade._get_provider_for_model = MagicMock(return_value=provider)
    facade.get_model_name = MagicMock(return_value="cancel-model")
    release_context = SimpleNamespace(
        _logosnode=facade, _check_starvation=MagicMock(), reevaluate_model_queues=MagicMock()
    )
    scheduler.release = MagicMock(side_effect=lambda *args: BaseScheduler.release(release_context, *args))
    original_schedule = scheduler.schedule

    async def admit(request):
        result = await original_schedule(request)
        assert facade.try_reserve_capacity(27, 9040, request.request_id)
        facade.on_request_start(request.request_id, 27, 9040)
        return result

    scheduler.schedule = admit
    resolving = asyncio.Event()

    async def wait_for_lane(**kwargs):
        resolving.set()
        if cancel_during_resolve:
            await asyncio.Future()
        return None

    resolver.resolve_context = AsyncMock(side_effect=wait_for_lane)
    pipeline._CONTEXT_RESOLVE_INTERVAL_S = 60
    task = asyncio.create_task(
        pipeline.process(
            PipelineRequest(
                request_id="disconnected-production",
                payload={"messages": [{"role": "user", "content": "hi"}]},
                headers={},
                allowed_models=[27],
                deployments=[{"model_id": 27, "provider_id": 9040, "type": "logosnode"}],
                policy=None,
                skip_laura=True,
            )
        )
    )
    try:
        await asyncio.wait_for(resolving.wait(), timeout=2)
        assert facade.model_inflight_requests(9040, "cancel-model") == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        scheduler.release.assert_called_once_with(27, 9040, "logosnode", "disconnected-production")
        assert "disconnected-production" not in facade._request_tracking
        assert not benchmark_reservations.admitted_requests(9040, "cancel-model")
        benchmark_reservations.reserve(9040, "cancel-model", 9041)
        assert facade.model_inflight_requests(9040, "cancel-model") == 0
        assert not benchmark_reservations.allows(9040, "cancel-model", "disconnected-production")
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        benchmark_reservations.finish_request("disconnected-production")
        benchmark_reservations.release(9041)
