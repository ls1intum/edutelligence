"""A client that vanishes mid-request must not leave the worker generating.

Uvicorn does not tear the handler down when the connection breaks, so a
non-streaming call kept a GPU lane busy producing a response nobody would read.
Cancelling the task unwinds the executor's httpx context, which closes the
upstream connection so vLLM aborts the sequence.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

import logos as main


class _Client:
    """Stand-in for the disconnect probe Starlette exposes on Request."""

    def __init__(self, *, leaves: bool):
        self._leaves = leaves
        self.probes = 0

    async def is_disconnected(self) -> bool:
        self.probes += 1
        return self._leaves


@pytest.fixture(autouse=True)
def _fast_polling(monkeypatch):
    monkeypatch.setattr(main, "_CLIENT_DISCONNECT_POLL_SECONDS", 0.001)


@pytest.fixture
def recorded_failures(monkeypatch):
    calls = []
    monkeypatch.setattr(
        main,
        "_record_log_failure",
        lambda log_id, request_id, message, **kwargs: calls.append((log_id, request_id, message)),
    )
    return calls


@pytest.mark.asyncio
async def test_result_is_returned_while_the_client_stays(monkeypatch):
    async def fake_route_and_execute(**kwargs):
        return "the response"

    monkeypatch.setattr(main, "route_and_execute", fake_route_and_execute)

    result = await main._execute_cancelling_on_disconnect(_Client(leaves=False), log_id=1, request_id="req-1")

    assert result == "the response"


@pytest.mark.asyncio
async def test_upstream_work_is_cancelled_when_the_client_leaves(monkeypatch, recorded_failures):
    cancelled = asyncio.Event()

    async def fake_route_and_execute(**kwargs):
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    monkeypatch.setattr(main, "route_and_execute", fake_route_and_execute)

    response = await main._execute_cancelling_on_disconnect(_Client(leaves=True), log_id=7, request_id="req-2")

    assert cancelled.is_set(), "the upstream request kept running"
    assert response.status_code == 499
    assert [(log_id, request_id) for log_id, request_id, _ in recorded_failures] == [(7, "req-2")]


@pytest.mark.asyncio
async def test_errors_from_the_pipeline_still_propagate(monkeypatch):
    async def fake_route_and_execute(**kwargs):
        raise HTTPException(status_code=404, detail="no deployments")

    monkeypatch.setattr(main, "route_and_execute", fake_route_and_execute)

    with pytest.raises(HTTPException) as excinfo:
        await main._execute_cancelling_on_disconnect(_Client(leaves=False), log_id=None, request_id="req-3")

    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_streaming_requests_keep_starlettes_own_disconnect_watcher(monkeypatch):
    """Polling the receive channel here would race Starlette for the disconnect."""
    guarded = []
    direct = []

    async def fake_auth_parse_log(request, use_profile_auth=False):
        auth = MagicMock()
        auth.api_key_id = 88
        return {}, auth, {"model": "some-model", "stream": True}, "127.0.0.1", None

    async def fake_filter(deployments):
        return deployments

    monkeypatch.setattr(main, "auth_parse_log", fake_auth_parse_log)
    monkeypatch.setattr(main, "request_setup", lambda headers, api_key_id: ([{"model_id": 1}], ["m"]))
    monkeypatch.setattr(main, "_filter_logosnode_deployments", fake_filter)
    monkeypatch.setattr(main, "route_and_execute", lambda **kwargs: direct.append(kwargs) or _done())
    monkeypatch.setattr(
        main,
        "_execute_cancelling_on_disconnect",
        lambda request, **kwargs: guarded.append(kwargs) or _done(),
    )

    await main.handle_sync_request("chat/completions", _Client(leaves=False))

    assert direct and not guarded


async def _done():
    return "streamed"
