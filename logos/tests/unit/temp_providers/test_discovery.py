"""Tests for model auto-discovery from OpenAI-compatible and Ollama APIs."""

import json

import httpx
import pytest

from logos.temp_providers.discovery import (
    DiscoveredModel,
    discover_models,
    discover_ollama_models,
    discover_openai_models,
)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


class MockResponse:
    """Minimal stand-in for httpx.Response."""

    def __init__(self, status_code, data):
        self.status_code = status_code
        self._data = data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "error", request=httpx.Request("GET", "http://x"), response=self
            )

    def json(self):
        return self._data


class FakeAsyncClient:
    """Drop-in replacement for ``httpx.AsyncClient`` as an async context manager."""

    def __init__(self, response: MockResponse):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def get(self, url, **kwargs):
        return self._response


# ------------------------------------------------------------------
# OpenAI-compatible discovery
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_discover_openai_models_success(monkeypatch):
    payload = {
        "object": "list",
        "data": [
            {"id": "gpt-4o", "object": "model", "owned_by": "openai"},
            {"id": "llama3", "object": "model", "owned_by": "meta"},
        ],
    }
    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda **kw: FakeAsyncClient(MockResponse(200, payload)),
    )

    models = await discover_openai_models("http://localhost:1234")
    assert len(models) == 2
    assert models[0].id == "gpt-4o"
    assert models[1].owned_by == "meta"


@pytest.mark.asyncio
async def test_discover_openai_models_empty_data(monkeypatch):
    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda **kw: FakeAsyncClient(MockResponse(200, {"data": []})),
    )
    models = await discover_openai_models("http://localhost:1234")
    assert models == []


@pytest.mark.asyncio
async def test_discover_openai_models_error(monkeypatch):
    """Network error should return empty list, not raise."""

    class FailClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def get(self, *a, **kw):
            raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: FailClient())
    models = await discover_openai_models("http://localhost:1234")
    assert models == []


# ------------------------------------------------------------------
# Ollama discovery
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_discover_ollama_models_success(monkeypatch):
    payload = {
        "models": [
            {"name": "deepseek-r1:latest", "model": "deepseek-r1:latest"},
            {"name": "llama3.2:latest", "model": "llama3.2:latest"},
        ]
    }
    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda **kw: FakeAsyncClient(MockResponse(200, payload)),
    )
    models = await discover_ollama_models("http://localhost:11434")
    assert len(models) == 2
    assert models[0].id == "deepseek-r1:latest"
    assert models[1].owned_by == "ollama"


@pytest.mark.asyncio
async def test_discover_ollama_models_error(monkeypatch):
    class FailClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def get(self, *a, **kw):
            raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: FailClient())
    models = await discover_ollama_models("http://localhost:11434")
    assert models == []


# ------------------------------------------------------------------
# Combined discovery (fallback logic)
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_discover_models_openai_first(monkeypatch):
    """If OpenAI endpoint succeeds, Ollama is not tried."""
    openai_payload = {"data": [{"id": "mymodel", "owned_by": "x"}]}

    call_log = []

    original_get = None

    class TrackingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def get(self, url, **kw):
            call_log.append(url)
            if "/v1/models" in url:
                return MockResponse(200, openai_payload)
            return MockResponse(404, {})

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: TrackingClient())

    models = await discover_models("http://localhost:1234")
    assert len(models) == 1
    assert models[0].id == "mymodel"
    # Should only have called /v1/models
    assert any("/v1/models" in u for u in call_log)


@pytest.mark.asyncio
async def test_discover_models_fallback_to_ollama(monkeypatch):
    """If OpenAI fails, fall back to Ollama."""
    ollama_payload = {"models": [{"name": "llama3:latest"}]}

    class FallbackClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def get(self, url, **kw):
            if "/v1/models" in url:
                raise httpx.ConnectError("refused")
            if "/api/tags" in url:
                return MockResponse(200, ollama_payload)
            return MockResponse(404, {})

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: FallbackClient())
    models = await discover_models("http://localhost:11434")
    assert len(models) == 1
    assert models[0].id == "llama3:latest"


@pytest.mark.asyncio
async def test_discover_models_both_fail(monkeypatch):
    class FailClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def get(self, *a, **kw):
            raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: FailClient())
    models = await discover_models("http://localhost:9999")
    assert models == []


@pytest.mark.asyncio
async def test_discover_openai_with_auth_key(monkeypatch):
    """Auth key should be passed as Bearer token."""
    captured_headers = {}

    class CapturingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def get(self, url, headers=None, **kw):
            captured_headers.update(headers or {})
            return MockResponse(200, {"data": [{"id": "m1"}]})

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: CapturingClient())
    await discover_openai_models("http://localhost:1234", auth_key="secret123")
    assert captured_headers.get("Authorization") == "Bearer secret123"
