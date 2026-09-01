"""Internal retry / stream resume (#815): pinned PipelineRequests keep the
model, may change the node, and honour priority overrides."""

import pytest

from logos import PipelineRequest, RequestPipeline, SchedulingResult
from logos.queue.models import Priority


class _RecordingClassifier:
    def __init__(self):
        self.calls = []

    def classify(self, user_prompt, policy, allowed=None, system=None, skip_laura=False):  # noqa: ARG002
        self.calls.append({"allowed": list(allowed or [])})
        return [(27, 1.0, 5)]


class _RecordingScheduler:
    def __init__(self, pick_provider_id: int | None = None):
        self.requests = []
        self._pick_provider_id = pick_provider_id

    async def schedule(self, request):
        self.requests.append(request)
        if self._pick_provider_id is not None:
            deployment = next(d for d in request.deployments if d["provider_id"] == self._pick_provider_id)
        else:
            deployment = request.deployments[0]
        return SchedulingResult(
            model_id=deployment["model_id"],
            provider_id=deployment["provider_id"],
            provider_type=deployment["type"],
            queue_entry_id=None,
            was_queued=False,
            queue_depth_at_schedule=0,
            priority_when_scheduled=Priority.from_resolved(request.classified_models[0][2]).name.lower(),
        )

    def release(self, *args, **kwargs):  # noqa: ARG002
        return None

    def get_total_queue_depth(self):
        return 0

    def update_provider_stats(self, *args, **kwargs):  # noqa: ARG002
        return None


class _StubExecutionContext:
    def __init__(self, model_id, provider_id, provider_type="logosnode", lane_id="lane-1"):
        self.model_id = model_id
        self.provider_id = provider_id
        self.provider_type = provider_type
        self.lane_id = lane_id
        self.forward_url = "http://stub"
        self.model_name = "stub-model"


class _FakeContextResolver:
    def __init__(self):
        self.last = None

    async def resolve_context(self, model_id, provider_id, request_path=None):  # noqa: ARG002
        self.last = (model_id, provider_id)
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


_DEPLOYMENTS = [
    {"model_id": 27, "provider_id": 1, "type": "logosnode"},
    {"model_id": 27, "provider_id": 2, "type": "logosnode"},
    {"model_id": 28, "provider_id": 3, "type": "cloud"},
]


def _build_pipeline(pick_provider_id: int | None = None):
    classifier = _RecordingClassifier()
    scheduler = _RecordingScheduler(pick_provider_id=pick_provider_id)
    pipeline = RequestPipeline(
        classifier=classifier,
        scheduler=scheduler,
        executor=object(),
        context_resolver=_FakeContextResolver(),
        monitoring=_FakeMonitoring(),
    )
    return pipeline, classifier, scheduler


def _pinned_request(**overrides) -> PipelineRequest:
    base = dict(
        payload={"messages": [{"role": "user", "content": "hi"}]},
        headers={},
        allowed_models=[27, 28],
        deployments=_DEPLOYMENTS,
        policy=None,
        request_id="req-pinned",
        default_priority=0,
        pinned_model_id=27,
    )
    base.update(overrides)
    return PipelineRequest(**base)


@pytest.mark.asyncio
async def test_pinned_request_skips_classification_and_keeps_model():
    pipeline, classifier, scheduler = _build_pipeline()

    result = await pipeline.process(_pinned_request())

    assert result.success is True
    assert classifier.calls == []  # classification did not run at all
    assert scheduler.requests[0].classified_models == [(27, 1.0, 0)]
    assert result.model_id == 27


@pytest.mark.asyncio
async def test_pinned_request_excludes_failed_providers():
    pipeline, _classifier, scheduler = _build_pipeline(pick_provider_id=2)

    result = await pipeline.process(_pinned_request(exclude_provider_ids=frozenset({1})))

    assert result.success is True
    seen = [d["provider_id"] for d in scheduler.requests[0].deployments]
    assert seen == [2]  # failed node 1 filtered out, only its peer remains
    assert result.provider_id == 2


@pytest.mark.asyncio
async def test_pinned_request_lifts_exclusion_when_no_peer_remains():
    """Single-node model: the exclusion is lifted so the same node is retried
    (the redeploy case — the answer comes back from the node that dropped)."""
    pipeline, _classifier, scheduler = _build_pipeline()

    single_node = [d for d in _DEPLOYMENTS if d["provider_id"] == 1]
    result = await pipeline.process(_pinned_request(deployments=single_node, exclude_provider_ids=frozenset({1})))

    assert result.success is True
    seen = [d["provider_id"] for d in scheduler.requests[0].deployments]
    assert seen == [1]
    assert result.provider_id == 1


@pytest.mark.asyncio
async def test_pinned_priority_override_feeds_scheduling():
    """Stream resumes queue at Priority.RESUME; plain retries keep the
    original priority (override unset → resolved default)."""
    pipeline, _classifier, scheduler = _build_pipeline()

    await pipeline.process(_pinned_request(priority_override=Priority.RESUME.value))
    assert scheduler.requests[0].classified_models == [(27, 1.0, int(Priority.RESUME))]

    await pipeline.process(_pinned_request(default_priority=int(Priority.HIGH)))
    assert scheduler.requests[1].classified_models == [(27, 1.0, int(Priority.HIGH))]


@pytest.mark.asyncio
async def test_pinned_payload_timeout_reaches_scheduling_request():
    """The retry loop clamps payload['timeout_s']; the scheduler must see it
    as the queue-wait bound."""
    pipeline, _classifier, scheduler = _build_pipeline()

    await pipeline.process(_pinned_request(payload={"messages": [], "timeout_s": 42.0}))

    assert scheduler.requests[0].timeout_s == 42.0


@pytest.mark.asyncio
async def test_pinned_retry_carries_eligible_provider_set_to_queue():
    """The queue is model-wide, so the failed-node exclusion must travel with
    the scheduling request — otherwise the failed node dequeues and executes
    its own retry."""
    pipeline, _classifier, scheduler = _build_pipeline(pick_provider_id=2)

    await pipeline.process(_pinned_request(exclude_provider_ids=frozenset({1})))

    assert scheduler.requests[0].eligible_provider_ids == frozenset({2})


@pytest.mark.asyncio
async def test_pinned_resume_carries_eligible_provider_set_to_queue():
    """Stream resumes queue at RESUME priority and carry the same set, so the
    resume stays on an eligible provider."""
    pipeline, _classifier, scheduler = _build_pipeline(pick_provider_id=2)

    await pipeline.process(
        _pinned_request(exclude_provider_ids=frozenset({1}), priority_override=Priority.RESUME.value)
    )

    assert scheduler.requests[0].eligible_provider_ids == frozenset({2})


@pytest.mark.asyncio
async def test_pinned_redeploy_lifted_exclusion_carries_single_node_set():
    """Single-node model: the lifted exclusion leaves the failed node as the
    only deployment — the set must keep the entry on that node, not open it
    up model-wide."""
    pipeline, _classifier, scheduler = _build_pipeline()

    single_node = [d for d in _DEPLOYMENTS if d["provider_id"] == 1]
    await pipeline.process(_pinned_request(deployments=single_node, exclude_provider_ids=frozenset({1})))

    assert scheduler.requests[0].eligible_provider_ids == frozenset({1})


@pytest.mark.asyncio
async def test_non_pinned_request_stays_model_wide():
    """Normal requests carry no eligibility set — model-wide queueing is
    unchanged for them."""
    pipeline, _classifier, scheduler = _build_pipeline()

    await pipeline.process(_pinned_request(pinned_model_id=None))

    assert scheduler.requests[0].eligible_provider_ids is None
