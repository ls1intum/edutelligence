import pytest
from unittest.mock import AsyncMock, MagicMock
import logos.main as main
from logos.pipeline.pipeline import PipelineRequest, RequestPipeline
from logos.pipeline.scheduler_interface import SchedulingResult


async def test_execute_proxy_mode_requires_model_in_body(monkeypatch):
    """_execute_proxy_mode raises 400 when body has no 'model' key."""
    # Stub DBManager so no real DB call is attempted
    class DummyDB:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    monkeypatch.setattr(main, "DBManager", DummyDB)

    with pytest.raises(main.HTTPException) as exc:
        await main._execute_proxy_mode(
            body={"stream": True},          # no "model" key
            headers={"Authorization": "Bearer x"},
            auth=MagicMock(key_value="lg-key", api_key_id=1),
            deployments=[{"model_id": 1, "provider_id": 1}],
            log_id=None,
            is_async_job=False,
        )
    assert exc.value.status_code == 400


async def test_execute_resource_mode_failure_records_error(monkeypatch):
    """_execute_resource_mode returns 503 when the pipeline fails."""

    class Result:
        success = False
        error = "boom"
        execution_context = None
        provider_id = None
        model_id = None
        classification_stats = {}
        scheduling_stats = {"request_id": "req-1"}

    monkeypatch.setattr(
        main,
        "_pipeline",
        type("P", (), {"process": AsyncMock(return_value=Result()), "record_completion": lambda *a, **k: None}),
        raising=False,
    )
    monkeypatch.setattr(main, "_extract_policy", lambda *args, **kwargs: {"p": "ok"})

    with pytest.raises(main.HTTPException) as exc:
        await main._execute_resource_mode(
            deployments=[{"model_id": 10, "provider_id": 1}],
            body={},
            headers={"h": "v"},
            auth=MagicMock(key_value="lg-test", api_key_id=1),
            log_id=1,
            is_async_job=False,
        )
    assert exc.value.status_code == 503


async def test_execute_proxy_mode_routes_through_resource_mode(monkeypatch):
    """_execute_proxy_mode keeps classification/scheduling but narrows deployments to one model."""

    class DummyDB:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        @staticmethod
        def get_models_info(api_key_id=None):
            return [{"id": 27, "name": "gemma2:2b"}]

    called = {}

    async def fake_resource_mode(  # noqa: ARG001
        deployments,
        body,
        headers,
        auth,
        log_id,
        is_async_job,
        allowed_models_override=None,
        request_id=None,
        request_path=None,
        skip_laura=False,
        priority=1,
    ):
        called["deployments"] = deployments
        called["body"] = body
        called["allowed_models_override"] = allowed_models_override
        called["request_id"] = request_id
        return {"status": "resource"}

    monkeypatch.setattr(main, "DBManager", DummyDB)
    monkeypatch.setattr(main, "_execute_resource_mode", fake_resource_mode)

    result = await main._execute_proxy_mode(
        body={"model": "gemma2:2b", "stream": False},
        headers={"Authorization": "Bearer x"},
        auth=MagicMock(key_value="lg-key", api_key_id=1),
        deployments=[
            {"model_id": 27, "provider_id": 12},
            {"model_id": 99, "provider_id": 1},
        ],
        log_id=None,
        is_async_job=False,
    )

    assert result == {"status": "resource"}
    assert called["deployments"] == [{"model_id": 27, "provider_id": 12}]
    assert called["body"]["model"] == "gemma2:2b"
    assert called["allowed_models_override"] == [27]
    assert called["request_id"] is None


async def test_execute_proxy_mode_resolves_planner_sanitized_alias(monkeypatch):
    """Planner-safe underscore aliases resolve to canonical DB model names."""

    class DummyDB:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        @staticmethod
        def get_models_info(api_key_id=None):
            return [{"id": 32, "name": "Qwen/Qwen2.5-0.5B-Instruct"}]

    called = {}

    async def fake_resource_mode(  # noqa: ARG001
        deployments,
        body,
        headers,
        auth,
        log_id,
        is_async_job,
        allowed_models_override=None,
        request_id=None,
        request_path=None,
        skip_laura=False,
        priority=1,
    ):
        called["deployments"] = deployments
        called["body"] = body
        called["allowed_models_override"] = allowed_models_override
        return {"status": "resource"}

    monkeypatch.setattr(main, "DBManager", DummyDB)
    monkeypatch.setattr(main, "_execute_resource_mode", fake_resource_mode)

    result = await main._execute_proxy_mode(
        body={"model": "Qwen_Qwen2.5-0.5B-Instruct", "stream": True},
        headers={"Authorization": "Bearer x"},
        auth=MagicMock(key_value="lg-key", api_key_id=1),
        deployments=[
            {"model_id": 32, "provider_id": 13},
            {"model_id": 99, "provider_id": 1},
        ],
        log_id=None,
        is_async_job=False,
    )

    assert result == {"status": "resource"}
    assert called["deployments"] == [{"model_id": 32, "provider_id": 13}]
    assert called["body"]["model"] == "Qwen/Qwen2.5-0.5B-Instruct"
    assert called["allowed_models_override"] == [32]


async def test_pipeline_releases_capacity_when_context_resolution_fails():
    """A scheduled reservation is released if context resolution fails afterwards."""

    class FakeClassifier:
        def classify(self, user_prompt, policy, allowed=None, system=None, skip_laura=False):  # noqa: ARG002
            return [(27, 1.0, 1, 1)]

    class FakeScheduler:
        def __init__(self):
            self.released = []

        async def schedule(self, request):
            return SchedulingResult(
                model_id=27,
                provider_id=12,
                provider_type="cloud",
                queue_entry_id=None,
                was_queued=False,
                queue_depth_at_schedule=0,
            )

        def release(self, model_id, provider_id, provider_type, request_id):
            self.released.append((model_id, provider_id, provider_type, request_id))

        def get_total_queue_depth(self):
            return 0

        def update_provider_stats(self, model_id, provider_id, headers):  # noqa: ARG002
            return None

    class FakeContextResolver:
        async def resolve_context(self, *args, **kwargs):
            return None

    scheduler = FakeScheduler()
    pipeline = RequestPipeline(
        classifier=FakeClassifier(),
        scheduler=scheduler,
        executor=MagicMock(),
        context_resolver=FakeContextResolver(),
        monitoring=MagicMock(),
    )

    result = await pipeline.process(
        PipelineRequest(
            payload={"messages": [{"role": "user", "content": "hi"}]},
            headers={},
            allowed_models=[27],
            deployments=[{"model_id": 27, "provider_id": 12, "type": "cloud"}],
            policy=None,
            request_id="1",
        )
    )

    assert result.success is False
    assert result.provider_id == 12
    assert len(scheduler.released) == 1
    assert scheduler.released[0][0:3] == (27, 12, "cloud")


async def test_pipeline_releases_capacity_when_context_resolution_raises():
    """A scheduled reservation is released if context resolution raises."""

    class FakeClassifier:
        def classify(self, user_prompt, policy, allowed=None, system=None, skip_laura=False):  # noqa: ARG002
            return [(27, 1.0, 1, 1)]

    class FakeScheduler:
        def __init__(self):
            self.released = []

        async def schedule(self, request):
            return SchedulingResult(
                model_id=27,
                provider_id=12,
                provider_type="logosnode",
                queue_entry_id=None,
                was_queued=False,
                queue_depth_at_schedule=0,
            )

        def release(self, model_id, provider_id, provider_type, request_id):
            self.released.append((model_id, provider_id, provider_type, request_id))

        def get_total_queue_depth(self):
            return 0

        def update_provider_stats(self, model_id, provider_id, headers):  # noqa: ARG002
            return None

    class FakeContextResolver:
        async def resolve_context(self, *args, **kwargs):
            raise RuntimeError("worker offline")

    scheduler = FakeScheduler()
    pipeline = RequestPipeline(
        classifier=FakeClassifier(),
        scheduler=scheduler,
        executor=MagicMock(),
        context_resolver=FakeContextResolver(),
        monitoring=MagicMock(),
    )

    result = await pipeline.process(
        PipelineRequest(
            payload={"messages": [{"role": "user", "content": "hi"}]},
            headers={},
            allowed_models=[27],
            deployments=[{"model_id": 27, "provider_id": 12, "type": "logosnode"}],
            policy=None,
            request_id="1",
        )
    )

    assert result.success is False
    assert result.provider_id == 12
    assert "worker offline" in (result.error or "")
    assert len(scheduler.released) == 1
    assert scheduler.released[0][0:3] == (27, 12, "logosnode")
