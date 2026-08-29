"""
Tests for temporary provider admin endpoints, model listing, and routing.

The registry's HTTP probe and the request executor are faked; the DB is a
stub with user/model lookups and log-write recording.
"""

import json
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

import logos as main
from logos.pipeline.executor import ExecutionResult
from logos.temp_providers import STATUS_UNHEALTHY, TempProviderError, TempProviderRegistry

ADMIN_KEY = "lg-admin"
OWNER_KEY = "lg-owner"
OTHER_KEY = "lg-other"

USERS = {
    ADMIN_KEY: {"role": "logos_admin", "api_key_id": 100},
    OWNER_KEY: {"role": "app_developer", "api_key_id": 1},
    OTHER_KEY: {"role": "app_developer", "api_key_id": 2},
}


class DummyDB:
    """In-memory DBManager stub: user/model lookups plus log-write recording."""

    def __init__(self, users=None, models=None):
        self._users = users if users is not None else {}
        self._models = models if models is not None else []
        self.log_calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get_user_by_api_key(self, key_value):
        return self._users.get(key_value)

    def get_models_for_api_key(self, api_key_id):
        return self._models

    def get_model_for_api_key(self, api_key_id, model_name):
        return next((m for m in self._models if m["name"] == model_name), None)

    def get_models_info(self, key_value):
        return [{"id": m["id"], "name": m["name"]} for m in self._models]

    def update_log_entry_metrics(self, **fields):
        self.log_calls.append(("update_log_entry_metrics", fields))

    def set_response_payload(self, log_id, payload, provider_id, model_id, usage, policy_id, classified, **kw):
        self.log_calls.append(("set_response_payload", (log_id, provider_id, model_id)))

    def set_time_at_first_token(self, log_id):
        self.log_calls.append(("set_time_at_first_token", log_id))


class FakeExecutor:
    """Stands in for _pipeline.executor: records calls, returns canned results."""

    def __init__(self):
        self.calls = []
        self.sync_result = None
        self.stream_chunks: list[bytes] = []

    async def execute_sync(self, url, headers, payload):
        self.calls.append(("sync", url, headers, payload))
        return self.sync_result

    async def execute_streaming(self, url, headers, payload, on_headers=None, on_response_start=None, status=None):
        self.calls.append(("stream", url, headers, payload))
        for chunk in self.stream_chunks:
            yield chunk


@pytest.fixture
def registry(monkeypatch):
    reg = TempProviderRegistry(health_interval_s=3600.0, unhealthy_after=3, expiry_s=86400.0, probe_timeout_s=5.0)
    monkeypatch.setattr(main, "_temp_providers", reg)
    return reg


async def _register(
    registry, owner_api_key_id=1, models=("llama-3.1-8b", "mistral-7b"), base_url="http://mac.example.com/v1"
):
    async def probe(base_url_, api_key_):
        return list(models)

    registry._probe = probe
    return await registry.add_provider(base_url=base_url, api_key="lm-key", owner_api_key_id=owner_api_key_id)


def _patch_db(monkeypatch, users=None, models=None):
    db = DummyDB(users=users if users is not None else USERS, models=models)
    monkeypatch.setattr(main, "DBManager", lambda: db)
    return db


def _patch_auth(monkeypatch, key_value):
    monkeypatch.setattr(
        main,
        "authenticate_api_key",
        lambda headers: MagicMock(api_key_id=USERS[key_value]["api_key_id"], key_value=key_value),
    )


def _request(headers=None):
    req = MagicMock()
    req.headers = headers if headers is not None else {"authorization": f"Bearer {OWNER_KEY}"}
    return req


# ---------------------------------------------------------------------------
# POST /logosdb/temp_providers
# ---------------------------------------------------------------------------


async def test_add_temp_provider_admin(registry, monkeypatch):
    _patch_db(monkeypatch)

    async def probe(base_url, api_key):
        assert api_key == "lm-key"
        return ["llama-3.1-8b"]

    registry._probe = probe
    data = main.AddTempProviderRequest(logos_key=ADMIN_KEY, base_url="http://mac.example.com", api_key="lm-key")
    response = await main.add_temp_provider(data)

    assert isinstance(response, JSONResponse)
    assert response.status_code == 201
    body = json.loads(response.body)
    assert body["base_url"] == "http://mac.example.com/v1"
    assert body["models"] == ["llama-3.1-8b"]
    assert body["owner_api_key_id"] == 100  # defaults to the registering admin key
    assert len(registry) == 1


async def test_add_temp_provider_non_admin_forbidden(registry, monkeypatch):
    _patch_db(monkeypatch)
    data = main.AddTempProviderRequest(logos_key=OWNER_KEY, base_url="http://mac.example.com", api_key="lm-key")
    with pytest.raises(HTTPException) as exc:
        await main.add_temp_provider(data)
    assert exc.value.status_code == 403
    assert len(registry) == 0


async def test_add_temp_provider_owner_binding(registry, monkeypatch):
    """owner_api_key ties the provider to that user: only they (and admins) may use it."""
    _patch_db(monkeypatch)

    async def probe(base_url, api_key):
        return ["llama-3.1-8b"]

    registry._probe = probe
    data = main.AddTempProviderRequest(
        logos_key=ADMIN_KEY, base_url="http://mac.example.com", api_key="lm-key", owner_api_key=OWNER_KEY
    )
    response = await main.add_temp_provider(data)
    body = json.loads(response.body)
    assert body["owner_api_key_id"] == 1  # OWNER_KEY's api key id


async def test_add_temp_provider_unknown_owner(registry, monkeypatch):
    _patch_db(monkeypatch)
    data = main.AddTempProviderRequest(
        logos_key=ADMIN_KEY, base_url="http://mac.example.com", api_key="lm-key", owner_api_key="lg-unknown"
    )
    with pytest.raises(HTTPException) as exc:
        await main.add_temp_provider(data)
    assert exc.value.status_code == 400


async def test_add_temp_provider_discovery_failure(registry, monkeypatch):
    _patch_db(monkeypatch)

    async def dead_probe(base_url, api_key):
        raise TempProviderError("ConnectError: connection refused")

    registry._probe = dead_probe
    data = main.AddTempProviderRequest(logos_key=ADMIN_KEY, base_url="http://gone.example.com", api_key="lm-key")
    with pytest.raises(HTTPException) as exc:
        await main.add_temp_provider(data)
    assert exc.value.status_code == 502
    assert len(registry) == 0


# ---------------------------------------------------------------------------
# GET /logosdb/temp_providers
# ---------------------------------------------------------------------------


async def test_list_temp_providers_owner_sees_own(registry, monkeypatch):
    _patch_db(monkeypatch)
    await _register(registry, owner_api_key_id=1)
    await _register(registry, owner_api_key_id=2, base_url="http://other.example.com/v1")
    _patch_auth(monkeypatch, OWNER_KEY)

    response = await main.list_temp_providers(_request())
    body = json.loads(response.body)
    assert len(body["temp_providers"]) == 1
    assert body["temp_providers"][0]["base_url"] == "http://mac.example.com/v1"


async def test_list_temp_providers_admin_sees_all(registry, monkeypatch):
    _patch_db(monkeypatch)
    await _register(registry, owner_api_key_id=1)
    await _register(registry, owner_api_key_id=2, base_url="http://other.example.com/v1")
    _patch_auth(monkeypatch, ADMIN_KEY)

    response = await main.list_temp_providers(_request())
    body = json.loads(response.body)
    assert len(body["temp_providers"]) == 2


async def test_list_temp_providers_other_key_sees_none(registry, monkeypatch):
    _patch_db(monkeypatch)
    await _register(registry, owner_api_key_id=1)
    _patch_auth(monkeypatch, OTHER_KEY)

    response = await main.list_temp_providers(_request())
    assert json.loads(response.body)["temp_providers"] == []


# ---------------------------------------------------------------------------
# POST /logosdb/temp_providers/delete
# ---------------------------------------------------------------------------


async def test_delete_temp_provider_admin(registry, monkeypatch):
    _patch_db(monkeypatch)
    entry = await _register(registry, owner_api_key_id=1)
    data = main.DeleteTempProviderRequest(logos_key=ADMIN_KEY, provider_id=entry.provider_id)
    response = await main.delete_temp_provider(data)
    assert json.loads(response.body)["result"] == "Temporary provider removed."
    assert len(registry) == 0


async def test_delete_temp_provider_owner(registry, monkeypatch):
    _patch_db(monkeypatch)
    entry = await _register(registry, owner_api_key_id=1)
    data = main.DeleteTempProviderRequest(logos_key=OWNER_KEY, provider_id=entry.provider_id)
    await main.delete_temp_provider(data)
    assert len(registry) == 0


async def test_delete_temp_provider_other_key_forbidden(registry, monkeypatch):
    _patch_db(monkeypatch)
    entry = await _register(registry, owner_api_key_id=1)
    data = main.DeleteTempProviderRequest(logos_key=OTHER_KEY, provider_id=entry.provider_id)
    with pytest.raises(HTTPException) as exc:
        await main.delete_temp_provider(data)
    assert exc.value.status_code == 403
    assert len(registry) == 1


async def test_delete_temp_provider_not_found(registry, monkeypatch):
    _patch_db(monkeypatch)
    data = main.DeleteTempProviderRequest(logos_key=ADMIN_KEY, provider_id="tmp-doesnotexist")
    with pytest.raises(HTTPException) as exc:
        await main.delete_temp_provider(data)
    assert exc.value.status_code == 404


async def test_delete_temp_provider_invalid_key(registry, monkeypatch):
    _patch_db(monkeypatch)
    data = main.DeleteTempProviderRequest(logos_key="lg-unknown", provider_id="tmp-x")
    with pytest.raises(HTTPException) as exc:
        await main.delete_temp_provider(data)
    assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# /v1/models and /v1/models/{id} include temp provider models
# ---------------------------------------------------------------------------


async def test_list_models_includes_temp_models_for_owner(registry, monkeypatch):
    _patch_db(monkeypatch, models=[{"id": 5, "name": "gpt-4o", "description": None}])
    await _register(registry, owner_api_key_id=1)
    _patch_auth(monkeypatch, OWNER_KEY)

    response = await main.list_models(_request())
    ids = [entry["id"] for entry in json.loads(response.body)["data"]]

    assert "gpt-4o" in ids  # DB models still listed
    assert "llama-3.1-8b" in ids
    assert "mistral-7b" in ids


async def test_list_models_temp_models_hidden_from_other_keys(registry, monkeypatch):
    _patch_db(monkeypatch, models=[])
    await _register(registry, owner_api_key_id=1)
    _patch_auth(monkeypatch, OTHER_KEY)

    response = await main.list_models(_request())
    ids = [entry["id"] for entry in json.loads(response.body)["data"]]
    assert "llama-3.1-8b" not in ids


async def test_list_models_db_model_of_same_name_wins(registry, monkeypatch):
    """A persistent DB model shadows a same-named temporary provider model."""
    _patch_db(monkeypatch, models=[{"id": 5, "name": "llama-3.1-8b", "description": None}])
    await _register(registry, owner_api_key_id=1)
    _patch_auth(monkeypatch, OWNER_KEY)

    response = await main.list_models(_request())
    entries = json.loads(response.body)["data"]
    matches = [e for e in entries if e["id"] == "llama-3.1-8b"]
    assert len(matches) == 1
    assert "logos_temp_provider" not in matches[0]  # the DB entry, not the temp one


async def test_retrieve_model_temp_model(registry, monkeypatch):
    _patch_db(monkeypatch, models=[])
    await _register(registry, owner_api_key_id=1)
    _patch_auth(monkeypatch, OWNER_KEY)

    response = await main.retrieve_model("llama-3.1-8b", _request())
    body = json.loads(response.body)
    assert body["id"] == "llama-3.1-8b"
    assert body["logos_temp_provider_status"] == "healthy"


async def test_retrieve_model_temp_model_no_access(registry, monkeypatch):
    _patch_db(monkeypatch, models=[])
    await _register(registry, owner_api_key_id=1)
    _patch_auth(monkeypatch, OTHER_KEY)

    with pytest.raises(HTTPException) as exc:
        await main.retrieve_model("llama-3.1-8b", _request())
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Routing: _try_execute_temp_provider
# ---------------------------------------------------------------------------


def _patch_pipeline(monkeypatch, executor):
    pipeline = MagicMock()
    pipeline.executor = executor
    # _pipeline only exists once start_pipeline() has run; create it if absent.
    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)


def _auth(key_value):
    return MagicMock(api_key_id=USERS[key_value]["api_key_id"], key_value=key_value)


async def test_try_temp_provider_routes_sync_for_owner(registry, monkeypatch):
    _patch_db(monkeypatch, models=[])
    entry = await _register(registry, owner_api_key_id=1)
    executor = FakeExecutor()
    executor.sync_result = ExecutionResult(
        success=True,
        response={
            "id": "cmpl-1",
            "choices": [{"message": {"content": "hi"}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2},
        },
        error=None,
        usage={"prompt_tokens": 3, "completion_tokens": 2},
        is_streaming=False,
        status_code=200,
    )
    _patch_pipeline(monkeypatch, executor)
    db = main.DBManager()

    response = await main._try_execute_temp_provider(
        "v1/chat/completions",
        {"model": "llama-3.1-8b", "messages": [{"role": "user", "content": "hi"}]},
        _auth(OWNER_KEY),
        log_id=42,
        is_async_job=False,
        request_id="req-1",
    )

    assert isinstance(response, JSONResponse)
    assert response.status_code == 200
    assert json.loads(response.body)["choices"][0]["message"]["content"] == "hi"

    # Forwarded to the temp provider with its auth, model name pinned,
    # like-for-like on the inbound path (no duplicated /v1).
    kind, url, headers, payload = executor.calls[0]
    assert kind == "sync"
    assert url == "http://mac.example.com/v1/chat/completions"
    assert headers["Authorization"] == "Bearer lm-key"
    assert payload["model"] == "llama-3.1-8b"

    # Usage logged without DB model/provider references (in-memory only).
    assert ("set_response_payload", (42, None, None)) in db.log_calls
    assert (
        "update_log_entry_metrics",
        {"log_id": 42, "result_status": "success", "error_message": None},
    ) in db.log_calls


async def test_try_temp_provider_admin_can_route_to_others_provider(registry, monkeypatch):
    _patch_db(monkeypatch, models=[])
    await _register(registry, owner_api_key_id=1)
    executor = FakeExecutor()
    executor.sync_result = ExecutionResult(
        success=True, response={"ok": True}, error=None, usage={}, is_streaming=False, status_code=200
    )
    _patch_pipeline(monkeypatch, executor)

    response = await main._try_execute_temp_provider(
        "v1/chat/completions", {"model": "llama-3.1-8b"}, _auth(ADMIN_KEY), log_id=None, is_async_job=False
    )
    assert isinstance(response, JSONResponse)
    assert response.status_code == 200


async def test_try_temp_provider_other_key_gets_none(registry, monkeypatch):
    _patch_db(monkeypatch, models=[])
    await _register(registry, owner_api_key_id=1)
    result = await main._try_execute_temp_provider(
        "v1/chat/completions", {"model": "llama-3.1-8b"}, _auth(OTHER_KEY), log_id=None, is_async_job=False
    )
    assert result is None  # normal flow continues → 404 as usual


async def test_try_temp_provider_no_model_in_body(registry, monkeypatch):
    _patch_db(monkeypatch, models=[])
    await _register(registry, owner_api_key_id=1)
    result = await main._try_execute_temp_provider(
        "v1/chat/completions", {"messages": []}, _auth(OWNER_KEY), log_id=None, is_async_job=False
    )
    assert result is None


async def test_try_temp_provider_unhealthy_fails_fast_sync(registry, monkeypatch):
    _patch_db(monkeypatch, models=[])
    entry = await _register(registry, owner_api_key_id=1)
    entry.status = STATUS_UNHEALTHY
    executor = FakeExecutor()
    _patch_pipeline(monkeypatch, executor)

    response = await main._try_execute_temp_provider(
        "v1/chat/completions", {"model": "llama-3.1-8b"}, _auth(OWNER_KEY), log_id=None, is_async_job=False
    )

    assert isinstance(response, JSONResponse)
    assert response.status_code == 503
    body = json.loads(response.body)
    assert body["error"]["code"] == "temp_provider_unavailable"
    assert executor.calls == []  # no upstream request was even attempted


async def test_try_temp_provider_unhealthy_async_job(registry, monkeypatch):
    _patch_db(monkeypatch, models=[])
    entry = await _register(registry, owner_api_key_id=1)
    entry.status = STATUS_UNHEALTHY

    result = await main._try_execute_temp_provider(
        "v1/chat/completions", {"model": "llama-3.1-8b"}, _auth(OWNER_KEY), log_id=None, is_async_job=True
    )
    assert result["status_code"] == 503
    assert "unreachable" in result["data"]["error"]


async def test_try_temp_provider_upstream_error_relays_status(registry, monkeypatch):
    """A 400 from the temp host is relayed with its status (OpenAI shape)."""
    _patch_db(monkeypatch, models=[])
    await _register(registry, owner_api_key_id=1)
    executor = FakeExecutor()
    executor.sync_result = ExecutionResult(
        success=False,
        response={"error": {"message": "model not loaded", "type": "invalid_request_error"}},
        error="model not loaded",
        usage={},
        is_streaming=False,
        status_code=400,
    )
    _patch_pipeline(monkeypatch, executor)

    response = await main._try_execute_temp_provider(
        "v1/chat/completions", {"model": "llama-3.1-8b"}, _auth(OWNER_KEY), log_id=None, is_async_job=False
    )
    assert response.status_code == 400
    assert json.loads(response.body)["error"]["message"] == "model not loaded"


async def test_try_temp_provider_streaming(registry, monkeypatch):
    _patch_db(monkeypatch, models=[])
    await _register(registry, owner_api_key_id=1)
    executor = FakeExecutor()
    executor.stream_chunks = [
        b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n',
        b'data: {"choices":[],"usage":{"prompt_tokens":3,"completion_tokens":2}}\n\ndata: [DONE]\n\n',
    ]
    _patch_pipeline(monkeypatch, executor)

    response = await main._try_execute_temp_provider(
        "v1/chat/completions",
        {"model": "llama-3.1-8b", "stream": True, "messages": [{"role": "user", "content": "hi"}]},
        _auth(OWNER_KEY),
        log_id=7,
        is_async_job=False,
        request_id="req-stream",
    )

    assert isinstance(response, StreamingResponse)
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk)
    assert b'"hi"' in b"".join(chunks)
    assert b"data: [DONE]" in b"".join(chunks)

    # The streamer ends the live-view entry.
    assert main._live_streams.snapshot() == []


async def test_route_and_execute_falls_back_to_temp_provider(registry, monkeypatch):
    """A key without any DB deployment gets its temp provider model routed."""
    _patch_db(monkeypatch, models=[])
    await _register(registry, owner_api_key_id=1)
    executor = FakeExecutor()
    executor.sync_result = ExecutionResult(
        success=True, response={"ok": True}, error=None, usage={}, is_streaming=False, status_code=200
    )
    _patch_pipeline(monkeypatch, executor)

    response = await main.route_and_execute(
        deployments=[],
        body={"model": "llama-3.1-8b"},
        headers={},
        auth=_auth(OWNER_KEY),
        path="v1/chat/completions",
        log_id=None,
        is_async_job=False,
        request_id="req-route",
    )
    assert isinstance(response, JSONResponse)
    assert response.status_code == 200


async def test_route_and_execute_still_404_without_temp_match(registry, monkeypatch):
    _patch_db(monkeypatch, models=[])
    await _register(registry, owner_api_key_id=1)

    with pytest.raises(HTTPException) as exc:
        await main.route_and_execute(
            deployments=[],
            body={"model": "unknown-model"},
            headers={},
            auth=_auth(OWNER_KEY),
            path="v1/chat/completions",
            log_id=None,
            is_async_job=False,
            request_id="req-404",
        )
    assert exc.value.status_code == 404
