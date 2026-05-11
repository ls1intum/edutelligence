"""PROXY mode: PipelineRequest(skip_laura=True) skips Laura but still runs policy/token."""

import pytest

from logos.pipeline.pipeline import PipelineRequest, RequestPipeline
from logos.pipeline.scheduler_interface import SchedulingResult


class _RecordingClassifier:
    def __init__(self):
        self.calls = []

    def classify(self, user_prompt, policy, allowed=None, system=None, skip_laura=False):  # noqa: ARG002
        self.calls.append({"skip_laura": skip_laura, "allowed": list(allowed or [])})
        return [(allowed[0], 1.0, 1, 1)] if allowed else []


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

    async def resolve_context(self, model_id, provider_id, logos_key=None, profile_id=None, request_path=None):  # noqa: ARG002
        self.kwargs = {
            "model_id": model_id,
            "provider_id": provider_id,
            "request_path": request_path,
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
            logos_key="lg-key",
            payload={"messages": [{"role": "user", "content": "hi"}]},
            headers={},
            allowed_models=[27],
            deployments=[{"model_id": 27, "provider_id": 12, "type": "cloud"}],
            policy=None,
            profile_id=1,
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
            logos_key="lg-key",
            payload={"messages": [{"role": "user", "content": "hi"}]},
            headers={},
            allowed_models=[27],
            deployments=[{"model_id": 27, "provider_id": 12, "type": "cloud"}],
            policy=None,
            profile_id=1,
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
            logos_key="lg-key",
            payload={"messages": [{"role": "user", "content": "hi"}]},
            headers={},
            allowed_models=[27],
            deployments=[{"model_id": 27, "provider_id": 12, "type": "cloud"}],
            policy=None,
            profile_id=1,
            skip_laura=True,
            request_path="v1/chat/completions",
        )
    )

    assert resolver.kwargs is not None
    assert resolver.kwargs["request_path"] == "v1/chat/completions"
