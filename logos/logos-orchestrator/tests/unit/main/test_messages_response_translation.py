"""End-to-end shape of a /v1/messages response from an OpenAI-shaped upstream.

The translation runs at the very end of the response path on purpose: logging,
billing and the rate-limit accounting all read the upstream's own
(OpenAI-shaped) body, and only the bytes on the wire change shape. These tests
pin both halves of that — the client gets Anthropic, the ledger gets OpenAI.
"""

import json
from types import SimpleNamespace

import pytest

import logos as main
from logos import ExecutionResult
from logos.anthropic_compat import UpstreamDialect
from logos.errors import UpstreamStreamError

from .test_request_logging import _make_dummy_db, _make_pipeline, _read_stream_response

CLOUD_CONTEXT = SimpleNamespace(
    provider_type="cloud",
    forward_url="https://provider.test/v1/chat/completions",
    model_name="gpt-4.1-nano",
    lane_id=None,
    anthropic_dialect=UpstreamDialect.CHAT_COMPLETIONS,
)

MESSAGES_BODY = {"model": "gpt-4.1-nano", "max_tokens": 16, "messages": [{"role": "user", "content": "hi"}]}


def _passthrough_resolver(monkeypatch):
    monkeypatch.setattr(
        main,
        "_context_resolver",
        SimpleNamespace(prepare_headers_and_payload=lambda context, payload: ({}, payload)),
        raising=False,
    )


def _events(body: str):
    out = []
    for block in body.split("\n\n"):
        if not block.strip():
            continue
        name = data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[len("event: ") :]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: ") :])
        out.append((name, data))
    return out


@pytest.mark.asyncio
async def test_sync_response_is_returned_as_an_anthropic_message(monkeypatch):
    dummy_db = _make_dummy_db()
    monkeypatch.setattr(main, "DBManager", dummy_db)
    _passthrough_resolver(monkeypatch)

    pipeline, _, _ = _make_pipeline(
        sync_result=ExecutionResult(
            success=True,
            response={
                "id": "chatcmpl-1",
                "model": "gpt-4.1-nano",
                "choices": [{"message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 18, "completion_tokens": 2},
            },
            error=None,
            usage={},
            is_streaming=False,
            headers={},
            status_code=200,
        )
    )
    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)

    response = await main._sync_response(
        CLOUD_CONTEXT, MESSAGES_BODY, 70, 12, 27, -1, {"policy": "ok"}, request_path="v1/messages"
    )
    body = json.loads(response.body)

    assert body["type"] == "message"
    assert body["content"] == [{"type": "text", "text": "OK"}]
    assert body["usage"]["input_tokens"] == 18

    # The ledger keeps the upstream's own field names, so billing and the
    # statistics page are unaffected by the translation.
    logged = dummy_db.payload_calls[0]
    assert logged["payload"]["choices"][0]["message"]["content"] == "OK"
    assert logged["usage"]["prompt_tokens"] == 18


@pytest.mark.asyncio
async def test_sync_error_is_returned_in_the_anthropic_error_shape(monkeypatch):
    dummy_db = _make_dummy_db()
    monkeypatch.setattr(main, "DBManager", dummy_db)
    _passthrough_resolver(monkeypatch)

    pipeline, _, _ = _make_pipeline(
        sync_result=ExecutionResult(
            success=False,
            response={"error": {"message": "model not found", "type": "invalid_request_error"}},
            error="model not found",
            usage={},
            is_streaming=False,
            headers={},
            status_code=404,
        )
    )
    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)

    response = await main._sync_response(
        CLOUD_CONTEXT, MESSAGES_BODY, 71, 12, 27, -1, {"policy": "ok"}, request_path="v1/messages"
    )
    body = json.loads(response.body)

    assert response.status_code == 404
    assert body["type"] == "error"
    assert body["error"]["message"] == "model not found"


@pytest.mark.asyncio
async def test_streaming_response_is_rewritten_while_the_ledger_sees_openai(monkeypatch):
    dummy_db = _make_dummy_db()
    monkeypatch.setattr(main, "DBManager", dummy_db)
    _passthrough_resolver(monkeypatch)

    pipeline, _, _ = _make_pipeline(
        stream_chunks=[
            b'data: {"id":"chunk-1","model":"gpt-4.1-nano","choices":[{"delta":{"content":"He"}}]}\n\n',
            b'data: {"id":"chunk-1","choices":[{"delta":{"content":"llo"}}]}\n\n',
            b'data: {"id":"chunk-1","choices":[{"delta":{},"finish_reason":"stop"}]}\n\n',
            b'data: {"id":"chunk-1","choices":[],"usage":{"prompt_tokens":3,"completion_tokens":2,'
            b'"total_tokens":5}}\n\n',
            b"data: [DONE]\n\n",
        ],
        stream_headers={"Content-Type": "text/event-stream"},
    )
    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)

    response = await main._streaming_response(
        CLOUD_CONTEXT, MESSAGES_BODY, 72, 12, 27, -1, {"policy": "ok"}, request_path="v1/messages"
    )
    body = await _read_stream_response(response)
    events = _events(body)

    assert [name for name, _ in events] == [
        "message_start",
        "content_block_start",
        "content_block_delta",
        "content_block_delta",
        "content_block_stop",
        "message_delta",
        "message_stop",
    ]
    assert "".join(d["delta"]["text"] for n, d in events if n == "content_block_delta") == "Hello"
    # No OpenAI framing leaks through: [DONE] is not part of the Messages protocol.
    assert "[DONE]" not in body

    # Usage was still accumulated from the upstream frames, under the upstream's
    # own field names — the translation never reaches the ledger.
    usage = dummy_db.payload_calls[0]["usage"]
    assert usage["prompt_tokens"] == 3
    assert usage["completion_tokens"] == 2
    assert usage["total_tokens"] == 5


@pytest.mark.asyncio
async def test_midstream_failure_is_reported_as_an_anthropic_error_event(monkeypatch):
    dummy_db = _make_dummy_db()
    monkeypatch.setattr(main, "DBManager", dummy_db)
    _passthrough_resolver(monkeypatch)

    class ExplodingPipeline:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

    pipeline, _, _ = _make_pipeline(
        stream_chunks=[b'data: {"id":"c","model":"m","choices":[{"delta":{"content":"partial"}}]}\n\n'],
        stream_headers={"Content-Type": "text/event-stream"},
        terminal_status_error=None,
    )

    original = pipeline.executor.execute_streaming

    async def failing_stream(*args, **kwargs):
        async for chunk in original(*args, **kwargs):
            yield chunk
        raise RuntimeError("connection reset")

    pipeline.executor.execute_streaming = failing_stream
    monkeypatch.setattr(main, "_pipeline", ExplodingPipeline(pipeline), raising=False)

    response = await main._streaming_response(
        CLOUD_CONTEXT, MESSAGES_BODY, 73, 12, 27, -1, {"policy": "ok"}, request_path="v1/messages"
    )
    body = await _read_stream_response(response)
    events = _events(body)

    assert events[-1][0] == "error"
    assert events[-1][1]["error"]["message"] == "connection reset"
    # message_stop would read as a completed turn, so it must not be there.
    assert "message_stop" not in body


@pytest.mark.asyncio
async def test_pre_stream_error_is_returned_in_the_anthropic_error_shape(monkeypatch):
    dummy_db = _make_dummy_db()
    monkeypatch.setattr(main, "DBManager", dummy_db)
    _passthrough_resolver(monkeypatch)

    pipeline, _, _ = _make_pipeline(
        stream_error=UpstreamStreamError(429, {"error": {"message": "rate limited", "type": "rate_limit_error"}}),
    )
    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)

    response = await main._streaming_response(
        CLOUD_CONTEXT, MESSAGES_BODY, 74, 12, 27, -1, {"policy": "ok"}, request_path="v1/messages"
    )
    body = json.loads(response.body)

    assert response.status_code == 429
    assert body["type"] == "error"
    assert body["error"]["message"] == "rate limited"
