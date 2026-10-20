"""Ending the in-flight requests of one client by its tag.

The agent runner freezes a session and cuts its network; the frozen client
neither reads nor closes its connection, so without this the generation it
started runs to its end on a GPU lane while the runner believes it has
handed that lane back.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import StreamingResponse
from starlette.routing import Route

from logos.client_tags import ClientTagCancellationMiddleware, cancel, in_flight
from logos.dbutils.dbrequest import CancelClientTagRequest
from logos.routers import internal as internal_mod


def _scope(tag: str | None) -> dict:
    headers = [(b"content-type", b"application/json")]
    if tag is not None:
        headers.append((b"x-logos-client-tag", tag.encode()))
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/v1/chat/completions",
        "raw_path": b"/v1/chat/completions",
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("172.30.0.5", 40000),
        "server": ("logos-orchestrator", 8080),
    }


def _client_that_never_leaves():
    """The body, then silence: a frozen client never reports a disconnect."""
    delivered = False

    async def receive():
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": b"{}", "more_body": False}
        await asyncio.Event().wait()

    return receive


async def _discard(message):
    return None


async def _until(condition, timeout: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not condition():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not reached")
        await asyncio.sleep(0.01)


def _streaming_app(events: list[str]):
    async def endless(request):
        async def chunks():
            try:
                while True:
                    yield b"data: token\n\n"
                    await asyncio.sleep(0.01)
            finally:
                events.append("upstream closed")

        return StreamingResponse(chunks(), media_type="text/event-stream")

    return Starlette(routes=[Route("/v1/chat/completions", endless, methods=["POST"])])


async def test_cancelling_a_tag_ends_its_streaming_request():
    """The stream is torn down as for a client that left, so the generator's
    cleanup — closing the upstream, releasing the slot — runs at once."""
    events: list[str] = []
    app = ClientTagCancellationMiddleware(_streaming_app(events))

    serving = asyncio.create_task(app(_scope("agent:172.30.0.5"), _client_that_never_leaves(), _discard))
    await _until(lambda: in_flight("agent:172.30.0.5") == 1)

    assert cancel("agent:172.30.0.5") == 1
    await asyncio.wait_for(serving, timeout=2.0)

    assert events == ["upstream closed"]
    assert in_flight("agent:172.30.0.5") == 0


async def test_another_tag_is_left_alone():
    events: list[str] = []
    app = ClientTagCancellationMiddleware(_streaming_app(events))

    serving = asyncio.create_task(app(_scope("agent:172.30.0.6"), _client_that_never_leaves(), _discard))
    await _until(lambda: in_flight("agent:172.30.0.6") == 1)

    assert cancel("agent:172.30.0.7") == 0
    await asyncio.sleep(0.05)
    assert not serving.done()

    cancel("agent:172.30.0.6")
    await asyncio.wait_for(serving, timeout=2.0)


async def test_an_untagged_request_passes_through_untouched():
    seen = {}

    async def app(scope, receive, send):
        seen["receive"] = receive

    receive = _client_that_never_leaves()
    await ClientTagCancellationMiddleware(app)(_scope(None), receive, _discard)

    assert seen["receive"] is receive


async def test_a_cancelled_request_reports_the_disconnect_without_waiting():
    """`Request.is_disconnected()` asks inside an already-cancelled scope; the
    answer must not need an await to arrive."""
    answers = []

    async def app(scope, receive, send):
        await receive()  # the body
        cancel("agent:172.30.0.8")
        answers.append(await receive())

    await ClientTagCancellationMiddleware(app)(_scope("agent:172.30.0.8"), _client_that_never_leaves(), _discard)

    assert answers == [{"type": "http.disconnect"}]


async def test_a_client_that_leaves_on_its_own_is_still_noticed():
    """The disconnect watcher polls `Request.is_disconnected()`, which gives
    up at its first await. A read cut short by one probe must hand what it
    brings back to the next, or a tagged request outlives its client."""
    left = asyncio.Event()
    delivered = False

    async def receive():
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": b"{}", "more_body": False}
        await left.wait()
        return {"type": "http.disconnect"}

    noticed = []

    async def app(scope, receive, send):
        request = Request(scope, receive)
        await request.body()
        while not await request.is_disconnected():
            left.set()
            await asyncio.sleep(0.01)
        noticed.append(True)

    await asyncio.wait_for(
        ClientTagCancellationMiddleware(app)(_scope("agent:172.30.0.9"), receive, _discard), timeout=2.0
    )

    assert noticed == [True]
    assert in_flight("agent:172.30.0.9") == 0


def _request(authorization: str = "") -> MagicMock:
    request = MagicMock()
    request.headers.get = lambda key, default="": authorization if key == "authorization" else default
    return request


async def test_the_cancel_endpoint_requires_the_internal_secret(monkeypatch):
    monkeypatch.setattr(internal_mod, "_INTERNAL_SECRET", "correct-secret")
    with pytest.raises(HTTPException) as exc_info:
        await internal_mod.internal_cancel_client_tag(CancelClientTagRequest(tag="t"), _request("Bearer wrong"))
    assert exc_info.value.status_code == 401


async def test_the_cancel_endpoint_reports_how_many_it_ended(monkeypatch):
    monkeypatch.setattr(internal_mod, "_INTERNAL_SECRET", "correct-secret")
    monkeypatch.setattr(internal_mod, "cancel_client_tag", lambda tag: 3 if tag == "agent:10.0.0.2" else 0)

    response = await internal_mod.internal_cancel_client_tag(
        CancelClientTagRequest(tag="agent:10.0.0.2"), _request("Bearer correct-secret")
    )

    assert json.loads(response.body) == {"cancelled": 3}
