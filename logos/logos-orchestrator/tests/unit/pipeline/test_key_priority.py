"""API-key default_priority drives queue ordering.

The classifier bakes the policy's priority into every candidate; the pipeline
then applies the requesting key's default_priority on top, so the key owner's
explicit choice wins and an unset key (0) keeps the policy's priority.
"""

from logos import PipelineRequest, RequestPipeline, SchedulingResult
from logos.pipeline.pipeline import resolve_queue_priority


def test_resolve_queue_priority_key_wins_when_set():
    assert resolve_queue_priority(10, 5) == 10
    # Even a lower key priority is honoured — it is the key owner's choice.
    assert resolve_queue_priority(1, 10) == 1
    # Arbitrary values pass through (Priority.from_int normalises them later).
    assert resolve_queue_priority(7, 5) == 7


def test_resolve_queue_priority_unset_key_falls_back_to_policy():
    assert resolve_queue_priority(0, 5) == 5
    assert resolve_queue_priority(None, 10) == 10
    # Both unset: 0 (ProxyPolicy default), which Priority.from_int maps to NORMAL.
    assert resolve_queue_priority(0, 0) == 0
    assert resolve_queue_priority(0, None) == 0


class _FakeClassifier:
    """Mimics ClassificationManager: bakes the policy's priority into candidates."""

    def classify(self, user_prompt, policy, allowed=None, system=None, skip_laura=False):  # noqa: ARG002
        priority = policy.get("priority", 0)
        return [(mid, 1.0, priority, 1) for mid in (allowed or [])]


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
    async def resolve_context(self, model_id, provider_id, request_path=None):  # noqa: ARG002
        return _StubExecutionContext(model_id, provider_id)


class _RecordingMonitoring:
    def __init__(self):
        self.enqueue_kwargs = None

    def record_enqueue(self, **kwargs):
        self.enqueue_kwargs = kwargs

    def record_scheduled(self, **kwargs):  # noqa: ARG002
        pass

    def record_provider(self, *args, **kwargs):  # noqa: ARG002
        pass

    def record_complete(self, **kwargs):  # noqa: ARG002
        pass

    def record_provider_metrics(self, *args, **kwargs):  # noqa: ARG002
        pass


def _build_pipeline():
    scheduler = _FakeScheduler()
    monitoring = _RecordingMonitoring()
    pipeline = RequestPipeline(
        classifier=_FakeClassifier(),
        scheduler=scheduler,
        executor=object(),
        context_resolver=_FakeContextResolver(),
        monitoring=monitoring,
    )
    return pipeline, scheduler, monitoring


def _request(**overrides):
    kwargs = dict(
        payload={"messages": [{"role": "user", "content": "hi"}]},
        headers={},
        allowed_models=[27],
        deployments=[{"model_id": 27, "provider_id": 12, "type": "cloud"}],
        policy={"priority": 5},
    )
    kwargs.update(overrides)
    return PipelineRequest(**kwargs)


async def test_key_priority_overrides_policy_priority():
    """A key with a set default_priority queues at that priority, not the policy's."""
    pipeline, scheduler, _monitoring = _build_pipeline()

    result = await pipeline.process(_request(default_priority=10))

    assert result.success is True
    assert [prio for _, _, prio, _ in scheduler.last_request.classified_models] == [10]


async def test_key_priority_wins_even_when_lower_than_policy():
    pipeline, scheduler, _monitoring = _build_pipeline()

    await pipeline.process(_request(default_priority=1))

    assert [prio for _, _, prio, _ in scheduler.last_request.classified_models] == [1]


async def test_unset_key_falls_back_to_policy_priority():
    """default_priority=0 (webservice/UI default) keeps the policy's priority."""
    pipeline, scheduler, _monitoring = _build_pipeline()

    await pipeline.process(_request(default_priority=0))

    assert [prio for _, _, prio, _ in scheduler.last_request.classified_models] == [5]


async def test_unset_key_without_policy_keeps_prior_behavior():
    """No key priority and no policy: priority stays 0 (→ NORMAL) as before."""
    pipeline, scheduler, _monitoring = _build_pipeline()

    await pipeline.process(_request(policy=None, default_priority=0))

    assert [prio for _, _, prio, _ in scheduler.last_request.classified_models] == [0]


async def test_enqueue_monitoring_uses_effective_priority():
    pipeline, _scheduler, monitoring = _build_pipeline()

    await pipeline.process(_request(default_priority=10))

    assert monitoring.enqueue_kwargs is not None
    assert monitoring.enqueue_kwargs["initial_priority"] == "high"


async def test_classification_stats_report_effective_priority():
    pipeline, _scheduler, _monitoring = _build_pipeline()

    result = await pipeline.process(_request(default_priority=10))

    assert result.classification_stats["candidates"][0]["priority"] == 10
