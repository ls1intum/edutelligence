import asyncio
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

import logos.main as main


# Common stubs ---------------------------------------------------------------

@pytest.fixture(autouse=True)
def stub_auth(monkeypatch):
    """Stub auth and request parsing for all endpoints."""

    async def fake_auth_parse(request: Request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        return dict(request.headers), "lg-test-key", 4242, body or {}, "127.0.0.1", 123

    monkeypatch.setattr(main, "auth_parse_log", fake_auth_parse, raising=False)
    monkeypatch.setattr(main, "authenticate_logos_key", lambda headers: ("lg-test-key", 4242), raising=False)


@pytest.fixture(autouse=True)
def stub_models(monkeypatch):
    """Return a single mock model from request_setup."""
    monkeypatch.setattr(main, "request_setup", lambda headers, logos_key: [{"id": 1, "name": "mock-model"}], raising=False)


@pytest.fixture
def event_loop():
    """Provide a clean event loop for pytest-asyncio (overrides session-scope hook)."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
def stub_db(monkeypatch):
    """Stub DBManager to avoid real DB/psycopg2 for proxy mode and logging."""

    class DummyDB:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def log_usage(self, process_id, client_ip, body, headers):
            return {"log-id": 99}, 200

        def get_providers(self, logos_key):
            return [{"id": 1, "name": "azure", "base_url": "https://example.com"}]

        def get_provider(self, provider):
            if isinstance(provider, dict):
                return provider
            return {"id": provider, "name": "azure", "base_url": "https://example.com"}

        def set_time_at_first_token(self, log_id): ...

        def set_response_timestamp(self, log_id): ...

        def set_response_payload(self, *a, **k): ...

    import logos.responses as responses

    monkeypatch.setattr(main, "DBManager", DummyDB, raising=False)
    monkeypatch.setattr(responses, "DBManager", DummyDB, raising=False)


@pytest.fixture
def client():
    return TestClient(main.app)


# Proxy mode (sync endpoints) -----------------------------------------------

def test_v1_proxy_sync_calls_proxy_sync_response(monkeypatch, client):
    called: Dict[str, Any] = {}

    async def fake_sync_resp(url, headers, body, log_id, provider_id, model_id, policy_id, classified, is_async_job=False):
        called["args"] = (url, headers, body, log_id, provider_id, model_id, policy_id, classified, is_async_job)
        return {"ok": True}

    monkeypatch.setattr(main, "_proxy_sync_response", fake_sync_resp)
    monkeypatch.setattr(main, "_proxy_streaming_response", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not stream")))
    monkeypatch.setattr(main, "proxy_behaviour", lambda headers, providers, path: ({"Authorization": "Bearer x"}, "http://up", 1))

    resp = client.post("/v1/chat/completions", json={"model": "gpt-4o"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    # is_async_job propagated False
    assert called["args"][-1] is False


def test_openai_proxy_stream_calls_streaming_response(monkeypatch, client):
    called: Dict[str, Any] = {}

    def fake_stream_resp(url, headers, body, log_id, provider_id, model_id, policy_id, classified):
        called["args"] = (url, headers, body, log_id, provider_id, model_id, policy_id, classified)
        return {"stream": True}

    monkeypatch.setattr(main, "_proxy_streaming_response", fake_stream_resp)
    monkeypatch.setattr(main, "_proxy_sync_response", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should stream")))
    monkeypatch.setattr(main, "proxy_behaviour", lambda headers, providers, path: ({"Authorization": "Bearer x"}, "http://up", 1))

    resp = client.post("/openai/chat/completions", json={"model": "gpt-4o", "stream": True})
    assert resp.status_code == 200
    assert resp.json() == {"stream": True}
    assert called["args"][2]["stream"] is True


# Resource mode (sync endpoints) --------------------------------------------

@pytest.mark.asyncio
async def test_resource_stream_calls_pipeline_and_stream_response(monkeypatch):
    class Result:
        success = True
        error = None
        execution_context = {"forward_url": "http://fake"}
        provider_id = 2
        model_id = 10
        classification_stats = {"policy": "ok"}
        scheduling_stats = {"request_id": "req-1"}

    async def fake_process(req):
        fake_process.called = req
        return Result()

    def fake_streaming_response(exec_ctx, body, log_id, provider_id, model_id, policy_id, c_stats, s_stats):
        return {"streamed": True, "model_id": model_id, "provider_id": provider_id}

    monkeypatch.setattr(
        main,
        "_pipeline",
        type("P", (), {"process": fake_process, "record_completion": lambda *a, **k: None, "scheduler": None}),
        raising=False,
    )
    monkeypatch.setattr(main, "_extract_policy", lambda headers, logos_key, body: {"p": "ok"})
    monkeypatch.setattr(main, "_streaming_response", fake_streaming_response)

    out = await main._execute_resource_mode(
        models=[{"id": 10}],
        body={"stream": True},
        headers={"h": "v"},
        logos_key="lg-test",
        path="chat/completions",
        log_id=1,
        is_async_job=False,
    )
    assert out["streamed"] is True
    assert out["model_id"] == 10
    assert out["provider_id"] == 2


@pytest.mark.asyncio
async def test_resource_sync_failure_returns_503(monkeypatch):
    class Result:
        success = False
        error = "boom"
        execution_context = None
        provider_id = None
        model_id = None
        classification_stats = {}
        scheduling_stats = {}

    async def fake_process(req):
        return Result()

    monkeypatch.setattr(main, "_pipeline", type("P", (), {"process": fake_process, "record_completion": lambda *a, **k: None}), raising=False)
    monkeypatch.setattr(main, "_extract_policy", lambda headers, logos_key, body: {"p": "ok"})

    with pytest.raises(main.HTTPException) as exc:
        await main._execute_resource_mode(
            models=[{"id": 10}],
            body={},
            headers={"h": "v"},
            logos_key="lg-test",
            path="chat/completions",
            log_id=1,
            is_async_job=False,
        )
    assert exc.value.status_code == 503


# Job (async) endpoints ------------------------------------------------------

def _stub_db_manager(monkeypatch):
    class DummyDB:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def log_usage(self, process_id, client_ip, body, headers):
            return {"log-id": 99}, 200

    monkeypatch.setattr(main, "DBManager", DummyDB, raising=False)
    import logos.responses as responses
    monkeypatch.setattr(responses, "DBManager", DummyDB, raising=False)


@pytest.mark.asyncio
async def test_execute_proxy_job_proxy_mode_sets_async_flag(monkeypatch):
    _stub_db_manager(monkeypatch)
    called = {}

    async def fake_route(models, body, headers, logos_key, path, log_id, is_async_job=False):
        called["args"] = (models, body, headers, logos_key, path, log_id, is_async_job)
        return {"status_code": 200, "data": {"ok": True}}

    monkeypatch.setattr(main, "route_and_execute", fake_route, raising=False)

    result = await main.execute_proxy_job(
        path="chat/completions",
        headers={"h": "v"},
        json_data={"model": "gpt-4o"},
        client_ip="127.0.0.1",
        logos_key="lg-test",
        process_id=4242,
    )
    assert result["status_code"] == 200
    assert called["args"][-1] is True  # is_async_job
    assert called["args"][1]["stream"] is False  # forced non-stream


@pytest.mark.asyncio
async def test_execute_proxy_job_resource_mode(monkeypatch):
    _stub_db_manager(monkeypatch)
    called = {}

    async def fake_route(models, body, headers, logos_key, path, log_id, is_async_job=False):
        called["args"] = (models, body, headers, logos_key, path, log_id, is_async_job)
        return {"status_code": 200, "data": {"ok": True}}

    monkeypatch.setattr(main, "route_and_execute", fake_route, raising=False)

    result = await main.execute_proxy_job(
        path="chat/completions",
        headers={"h": "v"},
        json_data={},  # no model -> resource mode
        client_ip="127.0.0.1",
        logos_key="lg-test",
        process_id=4242,
    )
    assert result["status_code"] == 200
    assert called["args"][-1] is True
    assert "model" not in called["args"][1]


def test_job_submit_and_status(monkeypatch, client):
    _stub_db_manager(monkeypatch)

    job_store = {"created": None, "fetched": None}

    class FakeJobService:
        @staticmethod
        def create_job(payload):
            job_store["created"] = payload
            return 101

        @staticmethod
        def fetch(job_id):
            return job_store["fetched"]

        @staticmethod
        def mark_running(job_id): ...

        @staticmethod
        def mark_success(job_id, result): ...

        @staticmethod
        def mark_failed(job_id, err): ...

    async def fake_process_job(job_id, path, headers, json_data, client_ip, logos_key, process_id):
        return {"status_code": 200, "data": {"ok": True}}

    monkeypatch.setattr(main, "JobService", FakeJobService, raising=False)
    monkeypatch.setattr(main, "process_job", fake_process_job, raising=False)
    monkeypatch.setattr(main, "_background_tasks", set(), raising=False)
    monkeypatch.setattr(asyncio, "create_task", lambda coro: asyncio.get_event_loop().create_task(coro), raising=False)

    resp = client.post("/jobs/v1/chat/completions", json={"prompt": "hi"})
    assert resp.status_code == 202
    assert resp.json()["job_id"] == 101
    assert job_store["created"] is not None

    # unauthorized fetch
    monkeypatch.setattr(main, "authenticate_logos_key", lambda headers: ("lg-test-key", 9999), raising=False)
    job_store["fetched"] = {"process_id": 4242, "status": "success", "result_payload": {"ok": True}, "error_message": None}
    resp_forbidden = client.get("/jobs/101")
    assert resp_forbidden.status_code == 403

    # authorized fetch
    monkeypatch.setattr(main, "authenticate_logos_key", lambda headers: ("lg-test-key", 4242), raising=False)
    job_store["fetched"] = {"process_id": 4242, "status": "success", "result_payload": {"ok": True}, "error_message": None}
    resp_ok = client.get("/jobs/101")
    assert resp_ok.status_code == 200
    assert resp_ok.json()["result"] == {"ok": True}
