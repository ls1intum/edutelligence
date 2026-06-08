"""Integration tests for OpenAI-spec error handling via FastAPI TestClient.

These tests use a real (in-process) FastAPI app instance with mocked auth and
executor to verify that user-facing endpoints emit properly shaped error
responses per the OpenAI error spec.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import logos.main as main
from logos.errors import UpstreamStreamError
from logos.pipeline.executor import ExecutionResult

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _stub_auth(monkeypatch):
    """Stub auth so every test request passes authentication."""
    from logos.auth import AuthContext

    fake_auth = AuthContext(
        key_value="test-key",
        api_key_id=1,
        api_key_name="test-key-name",
        key_type="developer",
        team_id=10,
        user_id=1,
        environment="-",
        log_level="BILLING",
        settings={},
        default_priority=5,
    )

    def fake_authenticate(headers):
        return fake_auth

    monkeypatch.setattr("logos.auth.authenticate_with_context", fake_authenticate)
    monkeypatch.setattr("logos.auth.authenticate_api_key", fake_authenticate)
    monkeypatch.setattr(main, "authenticate_api_key", fake_authenticate, raising=False)

    monkeypatch.setattr(main, "authenticate_logos_key", lambda h: ("test-key", 1), raising=False)

    with patch(
        "logos.auth.authenticate_with_profile",
        create=True,
        side_effect=fake_authenticate,
    ):
        yield fake_auth


@pytest.fixture(autouse=True)
def _stub_db(monkeypatch):
    """Stub DBManager so no real DB calls are made."""

    class FakeDB:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def log_usage(self, *a, **k):
            return {"log-id": 1}, 200

        def update_log_entry_metrics(self, *a, **k):
            pass

        def set_time_at_first_token(self, *a):
            pass

        def set_response_payload(self, *a, **k):
            pass

        def get_team(self, team_id):
            return {
                "id": team_id,
                "name": "test-team",
                "default_monthly_budget_micro_cents": None,
            }

        def get_api_key_budget_limit(self, api_key_id):
            return None

        def get_api_key_budget_usage(self, api_key_id, start):
            return 0

        def get_team_budget_usage(self, team_id, start):
            return 0

        def get_user_by_api_key(self, key_value):
            return None

        def get_models_for_api_key(self, api_key_id):
            return []

        def get_models_info(self, api_key_id):
            return [(1, "test-model")]

        def get_model(self, model_id):
            return {"id": model_id, "name": "test-model", "parallel": 1}

        def get_provider_deployment_info(self, mid, pid):
            return {
                "model_name": "test",
                "provider_type": "openai",
                "api_key": "x",
                "auth_name": "Authorization",
                "auth_format": "Bearer {}",
            }

    monkeypatch.setattr(main, "DBManager", FakeDB, raising=False)


@pytest.fixture(autouse=True)
def _stub_request_setup(monkeypatch):
    """Return a single fake deployment from request_setup."""
    monkeypatch.setattr(
        main,
        "request_setup",
        lambda headers, api_key_id: (
            [{"model_id": 1, "provider_id": 1, "type": "openai"}],
            [1],
        ),
        raising=False,
    )
    monkeypatch.setattr(
        main,
        "_filter_logosnode_deployments",
        AsyncMock(return_value=[{"model_id": 1, "provider_id": 1, "type": "openai"}]),
        raising=False,
    )


@pytest.fixture(autouse=True)
def _stub_pipeline(monkeypatch):
    """Stub the pipeline with a default successful executor."""
    pipeline = MagicMock()
    pipeline.scheduler = MagicMock()
    pipeline.scheduler.get_total_queue_depth.return_value = 0
    pipeline.record_completion = MagicMock()
    pipeline.record_provider_metrics = MagicMock()
    pipeline.update_provider_stats = MagicMock()

    async def default_execute_sync(*a, **k):
        return ExecutionResult(
            success=True,
            response={"choices": [{"message": {"content": "hi"}}]},
            error=None,
            usage={"total_tokens": 5},
            is_streaming=False,
            headers={},
            status_code=200,
        )

    pipeline.executor = MagicMock()
    pipeline.executor.execute_sync = AsyncMock(side_effect=default_execute_sync)

    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)
    monkeypatch.setattr(
        main,
        "_context_resolver",
        SimpleNamespace(prepare_headers_and_payload=lambda ctx, payload: ({}, payload)),
        raising=False,
    )

    return pipeline


@pytest.fixture
def client():
    """Return a TestClient for the logos FastAPI app."""
    return TestClient(main.app, raise_server_exceptions=False)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _assert_openai_error_shape(body: dict):
    """Assert that *body* has the canonical OpenAI error envelope."""
    assert "error" in body, f"'error' key missing from response body: {body}"
    err = body["error"]
    assert isinstance(err.get("message"), str), "'message' must be a string"
    assert isinstance(err.get("type"), str), "'type' must be a string"
    assert "detail" not in body, "FastAPI 'detail' key must not leak to user"


# ── Exception handler tests ───────────────────────────────────────────────────


class TestExceptionHandlers:
    def test_invalid_json_body_returns_400_openai_shape(self, client):
        """Malformed JSON → HTTP 400, OpenAI error body, no 'detail' leak."""
        resp = client.post(
            "/v1/chat/completions",
            content=b"{invalid json}",
            headers={"content-type": "application/json", "logos_key": "test-key"},
        )
        assert resp.status_code == 400
        body = resp.json()
        _assert_openai_error_shape(body)
        assert body["error"]["type"] == "invalid_request_error"

    def test_missing_auth_header_raises_401(self, client, monkeypatch):
        """Missing key → HTTP 401, OpenAI error body."""
        from fastapi import HTTPException as FE

        def raise_auth(*a, **k):
            raise FE(status_code=401, detail="Missing authentication")

        with (
            patch("logos.auth.authenticate_with_context", side_effect=raise_auth),
            patch("logos.auth.authenticate_api_key", side_effect=raise_auth),
            patch("logos.main.authenticate_api_key", side_effect=raise_auth),
        ):
            resp = client.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "hi"}]},
                headers={"content-type": "application/json"},
            )
        assert resp.status_code == 401
        body = resp.json()
        _assert_openai_error_shape(body)
        assert body["error"]["type"] == "authentication_error"

    def test_non_dict_json_payload_returns_400(self, client):
        """JSON body that is an array (not object) → HTTP 400."""
        resp = client.post(
            "/v1/chat/completions",
            content=b'["not", "an", "object"]',
            headers={"content-type": "application/json", "logos_key": "test-key"},
        )
        assert resp.status_code == 400
        body = resp.json()
        _assert_openai_error_shape(body)


# ── Upstream error forwarding ─────────────────────────────────────────────────


class TestUpstreamErrorForwarding:
    def test_context_length_exceeded_returns_400(self, client, monkeypatch, _stub_pipeline):
        """vLLM context-length error (HTTP 400) → client HTTP 400, correct code."""
        context_error_body = {
            "error": {
                "message": "maximum context length is 4096 tokens, got 8000",
                "type": "invalid_request_error",
                "code": "context_length_exceeded",
            }
        }

        async def error_sync(*a, **k):
            return ExecutionResult(
                success=False,
                response=context_error_body,
                error="context_length_exceeded",
                usage={},
                is_streaming=False,
                headers={},
                status_code=400,
            )

        _stub_pipeline.executor.execute_sync = AsyncMock(side_effect=error_sync)

        # Set up a minimal execution context
        ctx = SimpleNamespace(
            forward_url="http://fake/v1/chat/completions",
            provider_type="openai",
            lane_id=None,
        )

        async def fake_process(req):
            return SimpleNamespace(
                success=True,
                execution_context=ctx,
                provider_id=1,
                model_id=1,
                classification_stats={},
                scheduling_stats={
                    "request_id": "r1",
                    "is_cold_start": False,
                    "provider_type": "openai",
                },
                error=None,
            )

        _stub_pipeline.process = AsyncMock(side_effect=fake_process)

        resp = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
            headers={"logos_key": "test-key"},
        )

        assert resp.status_code == 400
        body = resp.json()
        _assert_openai_error_shape(body)
        assert body["error"]["type"] == "invalid_request_error"
        assert body["error"]["code"] == "context_length_exceeded"

    def test_upstream_500_corrected_to_400_for_context_length(self, client, monkeypatch, _stub_pipeline):
        """vLLM incorrectly returns 500 for context-length → corrected to 400."""
        context_error_body = {
            "error": {
                "message": "maximum context length is 8192 tokens, but got 10000",
                "type": "server_error",
            }
        }

        async def error_sync(*a, **k):
            return ExecutionResult(
                success=False,
                response=context_error_body,
                error="server_error",
                usage={},
                is_streaming=False,
                headers={},
                status_code=500,
            )

        _stub_pipeline.executor.execute_sync = AsyncMock(side_effect=error_sync)

        ctx = SimpleNamespace(
            forward_url="http://fake/v1/chat/completions",
            provider_type="openai",
            lane_id=None,
        )

        async def fake_process(req):
            return SimpleNamespace(
                success=True,
                execution_context=ctx,
                provider_id=1,
                model_id=1,
                classification_stats={},
                scheduling_stats={
                    "request_id": "r2",
                    "is_cold_start": False,
                    "provider_type": "openai",
                },
                error=None,
            )

        _stub_pipeline.process = AsyncMock(side_effect=fake_process)

        resp = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
            headers={"logos_key": "test-key"},
        )

        assert resp.status_code == 400
        body = resp.json()
        _assert_openai_error_shape(body)
        assert body["error"]["type"] == "invalid_request_error"
        assert body["error"]["code"] == "context_length_exceeded"

    def test_upstream_500_non_context_length_stays_500(self, client, _stub_pipeline):
        """Generic 500 upstream error stays 500, provider type preserved, no stack trace."""

        async def error_sync(*a, **k):
            return ExecutionResult(
                success=False,
                response={"error": {"message": "database error", "type": "server_error"}},
                error="database error",
                usage={},
                is_streaming=False,
                headers={},
                status_code=500,
            )

        _stub_pipeline.executor.execute_sync = AsyncMock(side_effect=error_sync)

        ctx = SimpleNamespace(
            forward_url="http://fake/v1/chat/completions",
            provider_type="openai",
            lane_id=None,
        )

        async def fake_process(req):
            return SimpleNamespace(
                success=True,
                execution_context=ctx,
                provider_id=1,
                model_id=1,
                classification_stats={},
                scheduling_stats={
                    "request_id": "r3",
                    "is_cold_start": False,
                    "provider_type": "openai",
                },
                error=None,
            )

        _stub_pipeline.process = AsyncMock(side_effect=fake_process)

        resp = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
            headers={"logos_key": "test-key"},
        )

        assert resp.status_code == 500
        body = resp.json()
        _assert_openai_error_shape(body)
        # Provider-supplied type is preserved; no stack trace leaks
        assert "Traceback" not in json.dumps(body)
        assert "File " not in json.dumps(body)


# ── Streaming pre-stream error ────────────────────────────────────────────────


class TestStreamingErrors:
    def test_upstream_4xx_pre_stream_returns_json_response(self, client, _stub_pipeline):
        """Upstream 4xx before any SSE chunks → JSONResponse with correct status."""

        async def error_streaming(*a, **k) -> AsyncIterator[bytes]:
            raise UpstreamStreamError(
                429,
                {
                    "error": {
                        "message": "rate limit exceeded",
                        "type": "rate_limit_error",
                    }
                },
            )
            # unreachable, but needed to make this an async generator
            yield b""  # noqa: unreachable

        _stub_pipeline.executor.execute_streaming = error_streaming

        ctx = SimpleNamespace(
            forward_url="http://fake/v1/chat/completions",
            provider_type="openai",
            lane_id=None,
        )

        async def fake_process(req):
            return SimpleNamespace(
                success=True,
                execution_context=ctx,
                provider_id=1,
                model_id=1,
                classification_stats={},
                scheduling_stats={
                    "request_id": "r4",
                    "is_cold_start": False,
                    "provider_type": "openai",
                },
                error=None,
            )

        _stub_pipeline.process = AsyncMock(side_effect=fake_process)
        _stub_pipeline.scheduler.release = MagicMock()

        resp = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}], "stream": True},
            headers={"logos_key": "test-key"},
        )

        # The response must NOT be HTTP 200 for a pre-stream 4xx
        assert resp.status_code == 429
        body = resp.json()
        _assert_openai_error_shape(body)
        assert body["error"]["type"] == "rate_limit_error"
