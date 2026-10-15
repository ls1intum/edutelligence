"""Tests for the best-effort notification emission client.

The client must never raise into the caller, must no-op cleanly when no
application server is configured, and must ship the event to the internal
endpoint with the shared-secret bearer.
"""

from __future__ import annotations

from typing import Any, List

import pytest

from logos.notifications import client as notifications_client
from logos.notifications.client import emit_notification


class FakeResponse:
    def raise_for_status(self):
        pass


class FakeClientFactory:
    """Stands in for httpx.AsyncClient: records posts, plays back results."""

    def __init__(self, results: List[Any]):
        self.results = list(results)
        self.created = 0
        self.posts: List[Any] = []

    def __call__(self, *args, **kwargs):
        self.created += 1
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


@pytest.mark.asyncio
async def test_no_application_server_configured_is_a_noop(monkeypatch):
    factory = FakeClientFactory([])
    monkeypatch.setattr(notifications_client.httpx, "AsyncClient", factory)
    monkeypatch.delenv("LOGOS_WEBSERVICE_URL", raising=False)
    monkeypatch.delenv("LOGOS_INTERNAL_SECRET", raising=False)

    result = await emit_notification("budget_hit", "Budget hit", targets=[{"kind": "role", "role": "app_admin"}])

    assert result is False
    assert factory.created == 0


@pytest.mark.asyncio
async def test_successful_emit_posts_to_internal_endpoint(monkeypatch):
    factory = FakeClientFactory([FakeResponse()])
    monkeypatch.setattr(notifications_client.httpx, "AsyncClient", factory)
    monkeypatch.setenv("LOGOS_WEBSERVICE_URL", "http://webservice:8081")
    monkeypatch.setenv("LOGOS_INTERNAL_SECRET", "s3cret")

    result = await emit_notification(
        "batch_job_finished",
        "Batch finished",
        body="done",
        payload={"job_id": 7},
        targets=[{"kind": "team", "id": 2001}],
        actor_user_id=1001,
    )

    assert result is True
    url, kwargs = factory.posts[0]
    assert url == "http://webservice:8081/internal/notifications"
    assert kwargs["headers"]["Authorization"] == "Bearer s3cret"
    assert kwargs["json"] == {
        "type": "batch_job_finished",
        "title": "Batch finished",
        "body": "done",
        "payload": {"job_id": 7},
        "targets": [{"kind": "team", "id": 2001}],
        "actor_user_id": 1001,
    }


@pytest.mark.asyncio
async def test_failed_emit_returns_false_and_does_not_raise(monkeypatch):
    factory = FakeClientFactory([ConnectionError("webservice down")])
    monkeypatch.setattr(notifications_client.httpx, "AsyncClient", factory)
    monkeypatch.setenv("LOGOS_WEBSERVICE_URL", "http://webservice:8081")
    monkeypatch.setenv("LOGOS_INTERNAL_SECRET", "s3cret")

    result = await emit_notification("budget_hit", "Budget hit")

    assert result is False


@pytest.mark.asyncio
async def test_omitted_targets_and_payload_default_safely(monkeypatch):
    factory = FakeClientFactory([FakeResponse()])
    monkeypatch.setattr(notifications_client.httpx, "AsyncClient", factory)
    monkeypatch.setenv("LOGOS_WEBSERVICE_URL", "http://webservice:8081/")
    monkeypatch.setenv("LOGOS_INTERNAL_SECRET", "s3cret")

    await emit_notification("deployment", "Deployed")

    url, kwargs = factory.posts[0]
    # Trailing slash on the configured base URL must not double up.
    assert url == "http://webservice:8081/internal/notifications"
    assert kwargs["json"]["targets"] == []
    assert kwargs["json"]["payload"] is None
