"""Queue priority resolution: key > team > policy, plus the role tiebreak.

The classifier bakes the policy's priority into every candidate; the pipeline
then applies the requesting key's default_priority on top of the team's
admin-set priority, so the key owner's explicit choice wins, an unset key (0)
falls back to the team's priority, and an unset team (0, the default) keeps
the historical policy-only behaviour.
"""

from logos import PipelineRequest, RequestPipeline, SchedulingResult
from logos.pipeline.pipeline import queue_role_rank, resolve_queue_priority
from logos.queue import Priority


def test_resolve_queue_priority_key_wins_when_set():
    assert resolve_queue_priority(10, 5, 1) == 10
    # Even a lower key priority is honoured — it is the key owner's choice.
    assert resolve_queue_priority(1, 5, 10) == 1
    # Arbitrary values pass through (Priority.from_int normalises them later).
    assert resolve_queue_priority(7, None, 5) == 7


def test_resolve_queue_priority_unset_key_falls_back_to_team():
    # An unset key takes the team's admin-set priority. Newly provisioned
    # developer keys are created with 0 (ApiKeyFactory, schema default per
    # webservice changelog 036), so this is the case normal developer/app-admin
    # traffic hits; legacy keys may still carry a stored 1, which acts as an
    # explicit override until an admin resets the key.
    assert resolve_queue_priority(0, 5, 10) == 5
    assert resolve_queue_priority(None, 1, 10) == 1
    # The team's choice wins over the policy's.
    assert resolve_queue_priority(0, 1, 10) == 1


def test_resolve_queue_priority_unset_team_falls_back_to_policy():
    assert resolve_queue_priority(0, None, 5) == 5
    assert resolve_queue_priority(0, 0, 10) == 10
    # All unset: resolves to the default level, NORMAL (see the regression
    # below) — not 0, which would rank below explicit NORMAL in the queue.
    assert resolve_queue_priority(0, 0, 0) == int(Priority.NORMAL)
    assert resolve_queue_priority(0, None, None) == int(Priority.NORMAL)


def test_all_unset_resolves_to_normal_raw_not_zero():
    """Regression: with key, team and policy all unset the resolved priority
    must be NORMAL's raw value (5), not 0. 0 lands in the NORMAL bucket via
    ``Priority.from_int`` but, as ``raw_priority=0``, would rank below
    explicit NORMAL (5) traffic inside that bucket and skip the role-rank
    tiebreak between the two."""
    resolved = resolve_queue_priority(0, 0, 0)
    assert resolved == int(Priority.NORMAL)
    # The raw value matches the bucket it maps to — no 0/5 mismatch.
    assert Priority.from_int(resolved) is Priority.NORMAL
    assert resolved == int(Priority.from_int(resolved))


def test_queue_role_rank_application_keys_rank_highest():
    # Application keys rank above everything, whatever user owns them.
    assert queue_role_rank("application", None) == 2
    assert queue_role_rank("application", "app_developer") == 2
    assert queue_role_rank("application", "app_admin") == 2


def test_queue_role_rank_admins_above_developers():
    assert queue_role_rank("developer", "app_admin") == 1
    assert queue_role_rank("developer", "logos_admin") == 1
    assert queue_role_rank("developer", "app_developer") == 0
    assert queue_role_rank("developer", None) == 0


def test_queue_role_rank_unknown_callers_rank_lowest():
    # Service keys, keys without a user, internal/benchmark traffic, and
    # unknown key types all rank 0 — they never jump ahead of interactive
    # developer traffic.
    assert queue_role_rank("service", None) == 0
    assert queue_role_rank("internal", None) == 0
    assert queue_role_rank(None, None) == 0
    assert queue_role_rank("mystery", "app_admin") == 1  # the user role still counts
    assert queue_role_rank("mystery", "app_developer") == 0


class _FakeClassifier:
    """Mimics ClassificationManager: bakes the policy's priority into candidates."""

    def classify(self, user_prompt, policy, allowed=None, system=None, skip_laura=False):  # noqa: ARG002
        priority = policy.get("priority", 0)
        return [(mid, 1.0, priority) for mid in (allowed or [])]


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
    async def resolve_context(
        self, model_id, provider_id, request_path=None, request_id=None, **kwargs
    ):  # noqa: ARG002
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
    assert [prio for _, _, prio in scheduler.last_request.classified_models] == [10]


async def test_key_priority_wins_even_when_lower_than_policy():
    pipeline, scheduler, _monitoring = _build_pipeline()

    await pipeline.process(_request(default_priority=1))

    assert [prio for _, _, prio in scheduler.last_request.classified_models] == [1]


async def test_unset_key_uses_team_priority_over_policy():
    """An unset key takes the team's admin-set priority over the policy's."""
    pipeline, scheduler, _monitoring = _build_pipeline()

    await pipeline.process(_request(default_priority=0, team_priority=1))

    assert [prio for _, _, prio in scheduler.last_request.classified_models] == [1]


async def test_unset_key_and_team_fall_back_to_policy_priority():
    """default_priority=0 and team_priority=0 keep the policy's priority."""
    pipeline, scheduler, _monitoring = _build_pipeline()

    await pipeline.process(_request(default_priority=0, team_priority=0))

    assert [prio for _, _, prio in scheduler.last_request.classified_models] == [5]


async def test_unset_key_and_team_resolve_to_normal_raw():
    """No key, team or policy priority: resolves to NORMAL's raw value (5), so
    the entry's raw_priority matches its bucket and default traffic ranks
    level with explicit NORMAL in the queue (regression)."""
    pipeline, scheduler, _monitoring = _build_pipeline()

    await pipeline.process(_request(policy=None, default_priority=0))

    assert [prio for _, _, prio in scheduler.last_request.classified_models] == [5]


async def test_enqueue_monitoring_uses_effective_priority():
    pipeline, _scheduler, monitoring = _build_pipeline()

    await pipeline.process(_request(default_priority=10))

    assert monitoring.enqueue_kwargs is not None
    assert monitoring.enqueue_kwargs["initial_priority"] == "high"


async def test_classification_stats_report_effective_priority():
    pipeline, _scheduler, _monitoring = _build_pipeline()

    result = await pipeline.process(_request(default_priority=10))

    assert result.classification_stats["candidates"][0]["priority"] == 10


async def test_role_rank_reaches_the_scheduler():
    """The caller's tiebreak rank flows from PipelineRequest to the scheduler,
    which passes it to the queue (application > app admin > developer)."""
    pipeline, scheduler, _monitoring = _build_pipeline()

    await pipeline.process(_request(role_rank=2))

    assert scheduler.last_request.role_rank == 2


async def test_role_rank_defaults_to_lowest():
    pipeline, scheduler, _monitoring = _build_pipeline()

    await pipeline.process(_request())

    assert scheduler.last_request.role_rank == 0
