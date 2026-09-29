"""Keepalive bytes while a streaming request is still being processed.

A streaming client sees no bytes until the first token: the scheduling wait,
the context resolution and the upstream's pre-token silence all sit behind
zero bytes. A reverse proxy in front of Logos (Traefik's default 180 s respond
timeout) 504s the client long before a queued or cold-loading request produces
its first token. The fix commits the response early and dribbles keepalive
bytes through the whole wait. These tests cover that wrapper in isolation,
driving a controlled ``route_and_execute``.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

import logos as main

KEEPALIVE = b": keepalive\n\n"


class _Client:
    """Stand-in for the disconnect probe Starlette exposes on Request."""

    def __init__(self, *, leaves: bool):
        self._leaves = leaves

    async def is_disconnected(self) -> bool:
        return self._leaves


async def _collect(response) -> bytes:
    """Drain a StreamingResponse body and return the raw bytes the client sees."""
    out = bytearray()
    async for chunk in response.body_iterator:
        out += chunk
    return bytes(out)


@pytest.fixture(autouse=True)
def _fast_intervals(monkeypatch):
    """Keepalive and disconnect polling fast enough for the tests to be quick."""
    monkeypatch.setattr(main, "_KEEPALIVE_INTERVAL_S", 0.05)
    monkeypatch.setattr(main, "_CLIENT_DISCONNECT_POLL_SECONDS", 0.001)


@pytest.mark.asyncio
async def test_keepalive_during_a_slow_pipeline(monkeypatch):
    """The pipeline (scheduling + context) can take minutes; keepalives must
    flow across that silence, before the first content byte."""

    async def fast_stream():
        yield b"data: hello\n\n"

    response_obj = StreamingResponse(fast_stream(), media_type="text/event-stream")

    async def fake_route_and_execute(**kwargs):
        await asyncio.sleep(0.2)  # slower than the 0.05 s keepalive interval
        return response_obj

    monkeypatch.setattr(main, "route_and_execute", fake_route_and_execute)

    response = await main._keepalive_streaming_response(
        _Client(leaves=False), log_id=1, request_id="req-1", path="chat/completions"
    )
    raw = await _collect(response)

    assert KEEPALIVE in raw
    assert raw.index(KEEPALIVE) < raw.index(b"data: hello")


@pytest.mark.asyncio
async def test_keepalive_during_a_slow_first_token(monkeypatch):
    """The response is ready but the upstream is silent before its first token;
    keepalives must flow across that silence too."""

    async def slow_stream():
        await asyncio.sleep(0.2)  # the pre-token silence
        yield b"data: hello\n\n"
        yield b"data: [DONE]\n\n"

    response_obj = StreamingResponse(slow_stream(), media_type="text/event-stream")

    async def fake_route_and_execute(**kwargs):
        return response_obj  # ready immediately; the silence is inside the body

    monkeypatch.setattr(main, "route_and_execute", fake_route_and_execute)

    response = await main._keepalive_streaming_response(
        _Client(leaves=False), log_id=1, request_id="req-2", path="chat/completions"
    )
    raw = await _collect(response)

    assert KEEPALIVE in raw
    assert raw.index(KEEPALIVE) < raw.index(b"data: hello")


@pytest.mark.asyncio
async def test_keepalives_never_reach_the_content_log(monkeypatch):
    """Keepalives are yielded by the wrapper, not the streamer, so the bytes the
    streamer logs and bills hold only real content."""
    logged: list[bytes] = []

    async def content_stream():
        await asyncio.sleep(0.15)  # force keepalives from the wrapper
        for chunk in (b"data: one\n\n", b"data: two\n\n"):
            logged.append(chunk)  # the streamer's log sees what it yields
            yield chunk

    response_obj = StreamingResponse(content_stream(), media_type="text/event-stream")

    async def fake_route_and_execute(**kwargs):
        return response_obj

    monkeypatch.setattr(main, "route_and_execute", fake_route_and_execute)

    response = await main._keepalive_streaming_response(
        _Client(leaves=False), log_id=1, request_id="req-3", path="chat/completions"
    )
    raw = await _collect(response)

    assert KEEPALIVE in raw, "the client should see keepalives"
    assert b"".join(logged) == b"data: one\n\ndata: two\n\n"
    assert KEEPALIVE not in b"".join(logged), "keepalives must not be logged or billed"


@pytest.mark.asyncio
async def test_pipeline_failure_becomes_an_openai_instream_error(monkeypatch):
    """A scheduling timeout used to be an HTTP 503; once the response has
    committed it must ride in the stream as an OpenAI error frame."""

    async def fake_route_and_execute(**kwargs):
        await asyncio.sleep(0.1)
        raise HTTPException(status_code=503, detail="scheduling timed out")

    monkeypatch.setattr(main, "route_and_execute", fake_route_and_execute)

    response = await main._keepalive_streaming_response(
        _Client(leaves=False), log_id=1, request_id="req-4", path="chat/completions"
    )
    raw = await _collect(response)

    assert b"scheduling timed out" in raw
    assert b'"error"' in raw
    assert b"data: [DONE]" in raw


@pytest.mark.asyncio
async def test_pipeline_failure_becomes_an_anthropic_instream_error(monkeypatch):
    """A Messages client gets an ``error`` SSE event, not an OpenAI data frame."""

    async def fake_route_and_execute(**kwargs):
        raise HTTPException(status_code=503, detail="overloaded")

    monkeypatch.setattr(main, "route_and_execute", fake_route_and_execute)

    response = await main._keepalive_streaming_response(
        _Client(leaves=False), log_id=1, request_id="req-5", path="v1/messages"
    )
    raw = await _collect(response)

    assert b"event: error" in raw
    assert b"overloaded" in raw
    assert b"data: [DONE]" not in raw


@pytest.mark.asyncio
async def test_pre_stream_non2xx_becomes_an_instream_error(monkeypatch):
    """A pre-stream upstream 4xx used to be a JSONResponse with the status; it
    must now ride in the committed stream as an error frame."""
    error_response = JSONResponse(
        status_code=400,
        content={"error": {"message": "bad request", "type": "invalid_request_error"}},
    )

    async def fake_route_and_execute(**kwargs):
        return error_response

    monkeypatch.setattr(main, "route_and_execute", fake_route_and_execute)

    response = await main._keepalive_streaming_response(
        _Client(leaves=False), log_id=1, request_id="req-6", path="chat/completions"
    )
    raw = await _collect(response)

    assert b"bad request" in raw
    assert b"data: [DONE]" in raw


@pytest.mark.asyncio
async def test_a_sync_200_answer_is_carried_through(monkeypatch):
    """A stream:true request the pipeline answered synchronously (Whisper) still
    delivers its body through the committed response."""
    sync_response = JSONResponse(status_code=200, content={"text": "hello"})

    async def fake_route_and_execute(**kwargs):
        return sync_response

    monkeypatch.setattr(main, "route_and_execute", fake_route_and_execute)

    response = await main._keepalive_streaming_response(
        _Client(leaves=False), log_id=1, request_id="req-7", path="chat/completions"
    )
    raw = await _collect(response)

    assert b"hello" in raw


@pytest.mark.asyncio
async def test_scheduling_decision_rides_in_the_stream(monkeypatch):
    """The ETTFT estimate and warmth state are only known once the pipeline has
    run — after the keepalive response is committed — so they cannot ride the
    response headers. The wrapper emits them as an SSE comment (under the same
    names the headers used) for the benchmark client that correlates the
    scheduler's view with the observed TTFT."""

    async def fast_stream():
        yield b"data: hello\n\n"

    response_obj = StreamingResponse(
        fast_stream(),
        media_type="text/event-stream",
        headers={"X-Logos-ETTFT-Ms": "123", "X-Logos-Warmth-State": "1"},
    )

    async def fake_route_and_execute(**kwargs):
        return response_obj

    monkeypatch.setattr(main, "route_and_execute", fake_route_and_execute)

    response = await main._keepalive_streaming_response(
        _Client(leaves=False), log_id=1, request_id="req-9", path="chat/completions"
    )
    raw = await _collect(response)

    assert b": logos-schedule" in raw
    assert b"x-logos-ettft-ms=123" in raw
    assert b"x-logos-warmth-state=1" in raw
    # The scheduling comment precedes the content.
    assert raw.index(b"logos-schedule") < raw.index(b"data: hello")


@pytest.mark.asyncio
async def test_no_scheduling_comment_without_scheduling_headers(monkeypatch):
    """A response that carries no scheduling values emits no comment."""

    async def fast_stream():
        yield b"data: hello\n\n"

    response_obj = StreamingResponse(fast_stream(), media_type="text/event-stream")

    async def fake_route_and_execute(**kwargs):
        return response_obj

    monkeypatch.setattr(main, "route_and_execute", fake_route_and_execute)

    response = await main._keepalive_streaming_response(
        _Client(leaves=False), log_id=1, request_id="req-10", path="chat/completions"
    )
    raw = await _collect(response)

    assert b"logos-schedule" not in raw
    assert b"data: hello" in raw


@pytest.mark.asyncio
async def test_disconnect_cancels_the_pipeline_work(monkeypatch):
    """A client that is already gone must not leave the pipeline running: the
    watcher fires, the work is cancelled, and no content is delivered."""
    cancelled = asyncio.Event()

    async def fake_route_and_execute(**kwargs):
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    monkeypatch.setattr(main, "route_and_execute", fake_route_and_execute)

    response = await main._keepalive_streaming_response(
        _Client(leaves=True), log_id=1, request_id="req-8", path="chat/completions"
    )
    raw = await _collect(response)

    assert cancelled.is_set(), "the upstream request kept running after the client left"
    assert b"data:" not in raw


@pytest.mark.asyncio
async def test_no_deployment_still_404s_for_a_streaming_request(monkeypatch):
    """The fast no-deployment 404 is raised before the keepalive branch, so it
    keeps its proper HTTP status instead of becoming an in-stream error."""

    async def fake_auth_parse_log(request, use_profile_auth=False, request_id=None):
        auth = MagicMock()
        auth.api_key_id = 88
        return {}, auth, {"stream": True}, "127.0.0.1", None, []

    async def fake_filter(deployments, payload=None):
        return deployments

    monkeypatch.setattr(main, "auth_parse_log", fake_auth_parse_log)
    monkeypatch.setattr(main, "_filter_logosnode_deployments", fake_filter)

    with pytest.raises(HTTPException) as exc:
        await main.handle_sync_request("chat/completions", _Client(leaves=False))

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_non_streaming_requests_stay_on_the_sync_path(monkeypatch):
    """A stream:false request must not early-commit a keepalive stream; it keeps
    the plain execution path and its proper HTTP statuses."""
    guarded = []

    async def fake_auth_parse_log(request, use_profile_auth=False, request_id=None):
        auth = MagicMock()
        auth.api_key_id = 88
        return {}, auth, {"stream": False}, "127.0.0.1", None, [{"model_id": 1}]

    async def fake_filter(deployments, payload=None):
        return deployments

    async def fake_guard(request, **kwargs):
        guarded.append(kwargs)
        return "guarded"

    async def fail_keepalive(request, **kwargs):
        raise AssertionError("the keepalive path must not be used for a non-streaming request")

    monkeypatch.setattr(main, "auth_parse_log", fake_auth_parse_log)
    monkeypatch.setattr(main, "_filter_logosnode_deployments", fake_filter)
    monkeypatch.setattr(main, "_execute_cancelling_on_disconnect", fake_guard)
    monkeypatch.setattr(main, "_keepalive_streaming_response", fail_keepalive)

    result = await main.handle_sync_request("chat/completions", _Client(leaves=False))

    assert result == "guarded"
    assert len(guarded) == 1
