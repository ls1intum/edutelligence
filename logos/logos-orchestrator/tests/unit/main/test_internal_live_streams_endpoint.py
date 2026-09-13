"""The /internal/live_streams endpoints: the token counts of the requests
running right now, pulled by the Spring webservice.

The statistics page shows a request row only once the webservice merges this
view into its feed, so the view here and the shape of the SSE stream that
pushes it are what the page ultimately renders.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from logos.main import _LiveStreamRegistry
from logos.routers import internal as main_mod


def _make_request(authorization: str = "") -> MagicMock:
    request = MagicMock()
    request.headers.get = lambda key, default="": authorization if key == "authorization" else default
    return request


@pytest.fixture
def live_registry(monkeypatch):
    registry = _LiveStreamRegistry()
    monkeypatch.setattr(main_mod, "_live_streams", registry)
    return registry


@pytest.mark.asyncio
async def test_the_snapshot_requires_the_internal_secret(monkeypatch):
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", None)
    with pytest.raises(HTTPException) as exc_info:
        await main_mod.internal_live_streams(_make_request("Bearer anything"))
    assert exc_info.value.status_code == 403

    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", "correct-secret")
    with pytest.raises(HTTPException) as exc_info:
        await main_mod.internal_live_streams(_make_request("Bearer wrong-secret"))
    assert exc_info.value.status_code == 401

    result = await main_mod.internal_live_streams(_make_request("Bearer correct-secret"))
    assert result == {"streams": []}


@pytest.mark.asyncio
async def test_the_snapshot_serves_the_running_requests(live_registry, monkeypatch):
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", "correct-secret")
    live_registry.start("req-1", "qwen-27b", prompt_tokens=1200, prompt_estimated=True)
    live_registry.update("req-1", {"prompt_tokens": 1187, "completion_tokens": 42})

    result = await main_mod.internal_live_streams(_make_request("Bearer correct-secret"))

    (row,) = result["streams"]
    assert row["request_id"] == "req-1"
    assert row["prompt_tokens"] == 1187
    assert row["prompt_estimated"] is False
    assert row["completion_tokens"] == 42


@pytest.mark.asyncio
async def test_the_stream_requires_the_internal_secret(monkeypatch):
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", None)
    with pytest.raises(HTTPException) as exc_info:
        await main_mod.internal_live_streams_stream(_make_request("Bearer anything"))
    assert exc_info.value.status_code == 403

    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", "correct-secret")
    with pytest.raises(HTTPException) as exc_info:
        await main_mod.internal_live_streams_stream(_make_request("Bearer wrong-secret"))
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_the_stream_pushes_the_snapshot_then_every_change(live_registry, monkeypatch):
    """The point of the SSE variant over polling: a change is on the wire on
    the very next tick, and an idle connection only ever hears a ping."""
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", "correct-secret")
    monkeypatch.setattr(main_mod, "_LIVE_STREAMS_SSE_TICK_S", 0.01)
    live_registry.start("req-1", "qwen-27b")

    response = await main_mod.internal_live_streams_stream(_make_request("Bearer correct-secret"))
    assert response.media_type == "text/event-stream"
    iterator = response.body_iterator
    try:
        first = await iterator.__anext__()
        assert first.startswith("data: ")
        payload = json.loads(first.removeprefix("data: ").strip())
        assert [row["request_id"] for row in payload["streams"]] == ["req-1"]

        live_registry.update("req-1", {"prompt_tokens": 7, "completion_tokens": 3})
        second = await iterator.__anext__()
        assert second.startswith("data: ")
        payload = json.loads(second.removeprefix("data: ").strip())
        assert payload["streams"][0]["completion_tokens"] == 3

        # Nothing moved since: a comment line, not a re-send.
        third = await iterator.__anext__()
        assert third == ": ping\n\n"

        live_registry.finish("req-1")
        fourth = await iterator.__anext__()
        payload = json.loads(fourth.removeprefix("data: ").strip())
        assert payload["streams"] == []
    finally:
        aclose = getattr(iterator, "aclose", None)
        if aclose is not None:
            await aclose()
