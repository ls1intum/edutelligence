"""A client that vanishes mid-request must not leave the worker generating.

Uvicorn does not tear the handler down when the connection breaks, so the call
kept a GPU lane busy producing a response nobody would read. Cancelling the task
unwinds the executor's httpx context, which closes the upstream connection so
vLLM aborts the sequence.
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


class _Body:
    """Async iterator stand-in that records being closed."""

    def __init__(self):
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


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
async def test_pipeline_cleanup_finishes_before_the_wrapper_returns(monkeypatch, recorded_failures):
    """The scheduler slot is released in a finally block, so it has to be awaited."""
    released = []

    async def fake_route_and_execute(**kwargs):
        try:
            await asyncio.sleep(30)
        finally:
            await asyncio.sleep(0)
            released.append("scheduler slot")

    monkeypatch.setattr(main, "route_and_execute", fake_route_and_execute)

    await main._execute_cancelling_on_disconnect(_Client(leaves=True), log_id=1, request_id="req-3")

    assert released == ["scheduler slot"]


@pytest.mark.asyncio
async def test_a_response_finished_as_the_client_left_is_closed(monkeypatch, recorded_failures):
    """The disconnect probe consumes the message Starlette's watcher would need."""
    body = _Body()
    streamed = MagicMock()
    streamed.body_iterator = body

    async def fake_route_and_execute(**kwargs):
        return streamed

    monkeypatch.setattr(main, "route_and_execute", fake_route_and_execute)

    response = await main._execute_cancelling_on_disconnect(_Client(leaves=True), log_id=2, request_id="req-4")

    assert response.status_code == 499
    assert body.closed, "the upstream stream was left open"


@pytest.mark.asyncio
async def test_discarding_a_plain_response_is_a_no_op():
    await main._discard_response(MagicMock(spec=[]))
    await main._discard_response(None)


@pytest.mark.asyncio
async def test_errors_from_the_pipeline_still_propagate(monkeypatch):
    async def fake_route_and_execute(**kwargs):
        raise HTTPException(status_code=404, detail="no deployments")

    monkeypatch.setattr(main, "route_and_execute", fake_route_and_execute)

    with pytest.raises(HTTPException) as excinfo:
        await main._execute_cancelling_on_disconnect(_Client(leaves=False), log_id=None, request_id="req-5")

    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_streaming_requests_take_the_keepalive_path(monkeypatch):
    """A stream request commits early and keepalives while it is processed; the
    disconnect guard now lives in the keepalive wrapper rather than the plain
    execution guard."""
    keepalive = []

    async def fake_auth_parse_log(request, use_profile_auth=False, request_id=None):
        auth = MagicMock()
        auth.api_key_id = 88
        return {}, auth, {"stream": True, "model": "gpt-4o"}, "127.0.0.1", None, [{"model_id": 1}]

    async def fake_filter(deployments, payload=None):
        return deployments

    async def fake_keepalive(request, **kwargs):
        keepalive.append(kwargs)
        return "keepalive-guarded"

    monkeypatch.setattr(main, "auth_parse_log", fake_auth_parse_log)
    monkeypatch.setattr(main, "_filter_logosnode_deployments", fake_filter)
    monkeypatch.setattr(main, "_keepalive_streaming_response", fake_keepalive)

    result = await main.handle_sync_request("chat/completions", _Client(leaves=False))

    assert result == "keepalive-guarded"
    assert len(keepalive) == 1


@pytest.mark.asyncio
async def test_whisper_stream_requests_keep_the_sync_guard(monkeypatch):
    """Whisper ignores ``stream`` and keeps the upstream content type, so it must
    stay on the synchronous path instead of committing a keepalive SSE stream."""
    guarded = []

    async def fake_auth_parse_log(request, use_profile_auth=False, request_id=None):
        auth = MagicMock()
        auth.api_key_id = 88
        return {}, auth, {"stream": True, "model": "whisper-1"}, "127.0.0.1", None, [{"model_id": 1}]

    async def fake_filter(deployments, payload=None):
        return deployments

    async def fake_guard(request, **kwargs):
        guarded.append(kwargs)
        return "guarded"

    monkeypatch.setattr(main, "auth_parse_log", fake_auth_parse_log)
    monkeypatch.setattr(main, "_filter_logosnode_deployments", fake_filter)
    monkeypatch.setattr(main, "_execute_cancelling_on_disconnect", fake_guard)

    result = await main.handle_sync_request("chat/completions", _Client(leaves=False))

    assert result == "guarded"
    assert len(guarded) == 1


@pytest.mark.asyncio
async def test_whisper_alias_stream_requests_keep_the_sync_guard(monkeypatch):
    """A logical alias that resolves to Whisper keeps the synchronous path even
    though the requested name does not mention Whisper."""
    guarded = []

    async def fake_auth_parse_log(request, use_profile_auth=False, request_id=None):
        auth = MagicMock()
        auth.api_key_id = 88
        auth.resolved_proxy_model = (7, "whisper-1")  # the alias resolves to Whisper
        return {}, auth, {"stream": True, "model": "transcription-production"}, "127.0.0.1", None, [{"model_id": 1}]

    async def fake_filter(deployments, payload=None):
        return deployments

    async def fake_guard(request, **kwargs):
        guarded.append(kwargs)
        return "guarded"

    monkeypatch.setattr(main, "auth_parse_log", fake_auth_parse_log)
    monkeypatch.setattr(main, "_filter_logosnode_deployments", fake_filter)
    monkeypatch.setattr(main, "_execute_cancelling_on_disconnect", fake_guard)

    result = await main.handle_sync_request("chat/completions", _Client(leaves=False))

    assert result == "guarded"
    assert len(guarded) == 1


@pytest.mark.asyncio
async def test_audio_upload_stream_requests_keep_the_sync_guard(monkeypatch):
    """An audio transcription ignores stream and keeps its upstream content
    type, so it must stay on the synchronous path even on the audio route."""
    guarded = []

    async def fake_auth_parse_log(request, use_profile_auth=False, request_id=None):
        auth = MagicMock()
        auth.api_key_id = 88
        return {}, auth, {"stream": True, "model": "whisper-1"}, "127.0.0.1", None, [{"model_id": 1}]

    async def fake_filter(deployments, payload=None):
        return deployments

    async def fake_guard(request, **kwargs):
        guarded.append(kwargs)
        return "guarded"

    monkeypatch.setattr(main, "auth_parse_log", fake_auth_parse_log)
    monkeypatch.setattr(main, "_filter_logosnode_deployments", fake_filter)
    monkeypatch.setattr(main, "_execute_cancelling_on_disconnect", fake_guard)

    # The audio upload path, not the chat path.
    result = await main.handle_sync_request("audio/transcriptions", _Client(leaves=False))

    assert result == "guarded"
    assert len(guarded) == 1


@pytest.mark.asyncio
async def test_model_free_stream_requests_keep_the_sync_guard(monkeypatch):
    """A stream:true request without a model enters resource mode; classification
    may still pick Whisper later. Keep the sync path so SSE is not committed
    before the selected model is known."""
    guarded = []

    async def fake_auth_parse_log(request, use_profile_auth=False, request_id=None):
        auth = MagicMock()
        auth.api_key_id = 88
        return {}, auth, {"stream": True}, "127.0.0.1", None, [{"model_id": 1}]

    async def fake_filter(deployments, payload=None):
        return deployments

    async def fake_guard(request, **kwargs):
        guarded.append(kwargs)
        return "guarded"

    async def fail_keepalive(request, **kwargs):
        raise AssertionError("model-free streaming must not commit the keepalive SSE path")

    monkeypatch.setattr(main, "auth_parse_log", fake_auth_parse_log)
    monkeypatch.setattr(main, "_filter_logosnode_deployments", fake_filter)
    monkeypatch.setattr(main, "_execute_cancelling_on_disconnect", fake_guard)
    monkeypatch.setattr(main, "_keepalive_streaming_response", fail_keepalive)

    result = await main.handle_sync_request("chat/completions", _Client(leaves=False))

    assert result == "guarded"
    assert len(guarded) == 1


@pytest.mark.asyncio
async def test_local_stream_requests_keep_the_sync_guard(monkeypatch):
    """Local HTTP providers may stream NDJSON rather than SSE; they must not
    commit the keepalive wrapper's text/event-stream content type."""
    guarded = []

    async def fake_auth_parse_log(request, use_profile_auth=False, request_id=None):
        auth = MagicMock()
        auth.api_key_id = 88
        return (
            {},
            auth,
            {"stream": True, "model": "local-model"},
            "127.0.0.1",
            None,
            [{"model_id": 1, "type": "local"}],
        )

    async def fake_filter(deployments, payload=None):
        return deployments

    async def fake_guard(request, **kwargs):
        guarded.append(kwargs)
        return "guarded"

    async def fail_keepalive(request, **kwargs):
        raise AssertionError("local streaming must not commit the keepalive SSE path")

    monkeypatch.setattr(main, "auth_parse_log", fake_auth_parse_log)
    monkeypatch.setattr(main, "_filter_logosnode_deployments", fake_filter)
    monkeypatch.setattr(main, "_execute_cancelling_on_disconnect", fake_guard)
    monkeypatch.setattr(main, "_keepalive_streaming_response", fail_keepalive)

    result = await main.handle_sync_request("chat/completions", _Client(leaves=False))

    assert result == "guarded"
    assert len(guarded) == 1


@pytest.mark.asyncio
async def test_unrelated_local_deployment_does_not_block_keepalive(monkeypatch):
    """A key that can also reach an unrelated local model must still keepalive
    when the requested model itself is SSE-safe."""
    keepalive = []

    async def fake_auth_parse_log(request, use_profile_auth=False, request_id=None):
        auth = MagicMock()
        auth.api_key_id = 88
        auth.resolved_proxy_model = (1, "gpt-4o")
        return (
            {},
            auth,
            {"stream": True, "model": "gpt-4o"},
            "127.0.0.1",
            None,
            [
                {"model_id": 1, "type": "openai", "model_name": "gpt-4o"},
                {"model_id": 2, "type": "local", "model_name": "local-model"},
            ],
        )

    async def fake_filter(deployments, payload=None):
        return deployments

    async def fake_keepalive(request, **kwargs):
        keepalive.append(kwargs)
        return "keepalive-guarded"

    monkeypatch.setattr(main, "auth_parse_log", fake_auth_parse_log)
    monkeypatch.setattr(main, "_filter_logosnode_deployments", fake_filter)
    monkeypatch.setattr(main, "_keepalive_streaming_response", fake_keepalive)

    result = await main.handle_sync_request("chat/completions", _Client(leaves=False))

    assert result == "keepalive-guarded"
    assert len(keepalive) == 1
