"""Ending a paused session's model requests on the orchestrator."""

from __future__ import annotations

from dataclasses import replace

from app import upstream

# Taken at import: the suite stubs the module attribute for every test that
# is not about it.
from app.upstream import cancel_client_requests


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def _client(calls: list, response=None, error: Exception | None = None):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, **kwargs):
            calls.append((url, kwargs))
            if error is not None:
                raise error
            return response

    return FakeClient


async def test_the_tag_matches_what_the_gateway_sets():
    # agent-gateway/nginx.conf: proxy_set_header X-Logos-Client-Tag "agent:$remote_addr"
    assert upstream.client_tag("172.30.0.5") == "agent:172.30.0.5"


async def test_the_requests_are_ended_by_the_gateways_tag(monkeypatch):
    calls: list = []
    monkeypatch.setattr(upstream.httpx, "AsyncClient", _client(calls, _FakeResponse(200, {"cancelled": 3})))
    monkeypatch.setattr(
        upstream, "settings", replace(upstream.settings, internal_secret="tok", orchestrator_url="http://orch:8080/")
    )

    assert await cancel_client_requests("172.30.0.5") == 3

    ((url, kwargs),) = calls
    assert url == "http://orch:8080/internal/client_tags/cancel"
    assert kwargs["json"] == {"tag": "agent:172.30.0.5"}
    assert kwargs["headers"] == {"Authorization": "Bearer tok"}


async def test_without_the_internal_secret_nothing_is_asked(monkeypatch):
    calls: list = []
    monkeypatch.setattr(upstream.httpx, "AsyncClient", _client(calls))
    monkeypatch.setattr(upstream, "settings", replace(upstream.settings, internal_secret=""))

    assert await cancel_client_requests("172.30.0.5") is None
    assert calls == []


async def test_a_refusal_is_not_a_count(monkeypatch):
    calls: list = []
    monkeypatch.setattr(upstream.httpx, "AsyncClient", _client(calls, _FakeResponse(401, {})))
    monkeypatch.setattr(upstream, "settings", replace(upstream.settings, internal_secret="tok"))

    assert await cancel_client_requests("172.30.0.5") is None


async def test_an_unreachable_orchestrator_does_not_raise(monkeypatch):
    calls: list = []
    monkeypatch.setattr(upstream.httpx, "AsyncClient", _client(calls, error=ConnectionError()))
    monkeypatch.setattr(upstream, "settings", replace(upstream.settings, internal_secret="tok"))

    assert await cancel_client_requests("172.30.0.5") is None
