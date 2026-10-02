"""Tests for the retriable discovery notification delivery.

The queue (model_discovery_notifications) must be cleared only after the
webservice acknowledged the notification; on failure the IDs stay queued
and are retried in full on the next sync pass.
"""

from __future__ import annotations

from typing import Any, List

import pytest

from logos.sdi import model_discovery_notifier
from logos.sdi.model_discovery_notifier import deliver_discovery_notifications, notify_models_discovered


class DummyDB:
    def __init__(self, pending: List[int]):
        self.pending = list(pending)
        self.marked: List[int] = []

    def get_pending_discovery_model_ids(self):
        return list(self.pending)

    def mark_discovery_notified(self, model_ids):
        self.marked.extend(model_ids)


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
async def test_empty_queue_sends_nothing(monkeypatch):
    factory = FakeClientFactory([])
    monkeypatch.setattr(model_discovery_notifier.httpx, "AsyncClient", factory)

    db = DummyDB([])
    await deliver_discovery_notifications(db)

    assert factory.created == 0
    assert db.marked == []


@pytest.mark.asyncio
async def test_successful_delivery_clears_the_queue(monkeypatch):
    factory = FakeClientFactory([FakeResponse()])
    monkeypatch.setattr(model_discovery_notifier.httpx, "AsyncClient", factory)
    monkeypatch.setenv("LOGOS_WEBSERVICE_URL", "http://webservice:8081")
    monkeypatch.setenv("LOGOS_INTERNAL_SECRET", "s3cret")

    db = DummyDB([5, 6])
    await deliver_discovery_notifications(db)

    url, kwargs = factory.posts[0]
    assert url == "http://webservice:8081/internal/models_discovered"
    assert kwargs["json"] == {"model_ids": [5, 6]}
    assert kwargs["headers"]["Authorization"] == "Bearer s3cret"
    assert db.marked == [5, 6]


@pytest.mark.asyncio
async def test_failed_delivery_keeps_the_queue(monkeypatch):
    factory = FakeClientFactory([ConnectionError("webservice down")])
    monkeypatch.setattr(model_discovery_notifier.httpx, "AsyncClient", factory)
    monkeypatch.setenv("LOGOS_WEBSERVICE_URL", "http://webservice:8081")
    monkeypatch.setenv("LOGOS_INTERNAL_SECRET", "s3cret")

    db = DummyDB([5, 6])
    await deliver_discovery_notifications(db)

    # Nothing was acknowledged — the IDs stay queued for the next pass.
    assert db.marked == []
    assert db.pending == [5, 6]


@pytest.mark.asyncio
async def test_no_webservice_configured_drains_the_queue(monkeypatch):
    factory = FakeClientFactory([])
    monkeypatch.setattr(model_discovery_notifier.httpx, "AsyncClient", factory)
    monkeypatch.delenv("LOGOS_WEBSERVICE_URL", raising=False)
    monkeypatch.delenv("LOGOS_INTERNAL_SECRET", raising=False)

    # Without a webservice there is nothing to retry against — the queue
    # must not accumulate forever for a nonexistent endpoint.
    db = DummyDB([5, 6])
    await deliver_discovery_notifications(db)

    assert factory.created == 0
    assert db.marked == [5, 6]


@pytest.mark.asyncio
async def test_notify_empty_list_succeeds_without_http(monkeypatch):
    factory = FakeClientFactory([])
    monkeypatch.setattr(model_discovery_notifier.httpx, "AsyncClient", factory)
    monkeypatch.setenv("LOGOS_WEBSERVICE_URL", "http://webservice:8081")
    monkeypatch.setenv("LOGOS_INTERNAL_SECRET", "s3cret")

    assert await notify_models_discovered([]) is True
    assert factory.created == 0
