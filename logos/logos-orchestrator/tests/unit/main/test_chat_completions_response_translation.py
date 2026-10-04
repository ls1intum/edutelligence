"""End-to-end shape of a /v1/chat/completions response from a Claude upstream.

The mirror of ``test_messages_response_translation``. Same rule about where
the translation sits: logging, billing and the rate-limit accounting all read
the upstream's own (Anthropic-shaped) body, and only the bytes on the wire
change shape.
"""

import json
from types import SimpleNamespace

import pytest

import logos as main
from logos import ExecutionResult
from logos.errors import UpstreamStreamError

from .test_request_logging import _make_dummy_db, _make_pipeline, _read_stream_response

CLAUDE_CONTEXT = SimpleNamespace(
    provider_type="cloud",
    forward_url="https://ase-se01.openai.azure.com/anthropic/v1/messages",
    model_name="claude-opus-5",
    lane_id=None,
    anthropic_dialect=None,
    messages_upstream=True,
)

CHAT_BODY = {"model": "claude-opus-5", "messages": [{"role": "user", "content": "hi"}]}


def _passthrough_resolver(monkeypatch):
    monkeypatch.setattr(
        main,
        "_context_resolver",
        SimpleNamespace(prepare_headers_and_payload=lambda context, payload: ({}, payload)),
        raising=False,
    )


def _frames(body: str):
    out = []
    for block in body.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        assert block.startswith("data: "), block
        payload = block[len("data: ") :]
        out.append(payload if payload == "[DONE]" else json.loads(payload))
    return out


@pytest.mark.asyncio
async def test_sync_response_is_returned_as_a_chat_completion(monkeypatch):
    dummy_db = _make_dummy_db()
    monkeypatch.setattr(main, "DBManager", dummy_db)
    _passthrough_resolver(monkeypatch)

    pipeline, _, _ = _make_pipeline(
        sync_result=ExecutionResult(
            success=True,
            response={
                "id": "msg_011Cf8xV",
                "type": "message",
                "role": "assistant",
                "model": "claude-opus-5",
                "content": [{"type": "text", "text": "OK"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 18, "output_tokens": 2},
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
        CLAUDE_CONTEXT, CHAT_BODY, 80, 12, 27, -1, {"policy": "ok"}, request_path="v1/chat/completions"
    )
    body = json.loads(response.body)

    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["content"] == "OK"
    assert body["choices"][0]["finish_reason"] == "stop"
    assert body["usage"]["prompt_tokens"] == 18
    assert body["usage"]["completion_tokens"] == 2

    # The ledger keeps the upstream's own field names.
    logged = dummy_db.store_calls[0]
    assert logged["payload"]["content"] == [{"type": "text", "text": "OK"}]


@pytest.mark.asyncio
async def test_sync_error_is_returned_in_the_openai_error_shape(monkeypatch):
    """No translation needed here, and that is worth pinning.

    An Anthropic failure body nests ``{"type", "message"}`` under ``error``,
    which is already the OpenAI shape once ``coerce_upstream_error`` has
    unwrapped it — so the error path needs no second translation and must not
    grow one.
    """
    dummy_db = _make_dummy_db()
    monkeypatch.setattr(main, "DBManager", dummy_db)
    _passthrough_resolver(monkeypatch)

    pipeline, _, _ = _make_pipeline(
        sync_result=ExecutionResult(
            success=False,
            response={
                "type": "error",
                "error": {"type": "invalid_request_error", "message": "max_tokens: Field required"},
            },
            error="max_tokens: Field required",
            usage={},
            is_streaming=False,
            headers={},
            status_code=400,
        )
    )
    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)

    response = await main._sync_response(
        CLAUDE_CONTEXT, CHAT_BODY, 81, 12, 27, -1, {"policy": "ok"}, request_path="v1/chat/completions"
    )
    body = json.loads(response.body)

    assert response.status_code == 400
    assert body["error"]["message"] == "max_tokens: Field required"
    assert body["error"]["type"] == "invalid_request_error"
    # The Anthropic wrapper must not survive: an OpenAI client reads
    # response["error"], not response["type"].
    assert "type" not in body


@pytest.mark.asyncio
async def test_streaming_response_is_rewritten_while_the_ledger_sees_anthropic(monkeypatch):
    dummy_db = _make_dummy_db()
    monkeypatch.setattr(main, "DBManager", dummy_db)
    _passthrough_resolver(monkeypatch)

    pipeline, _, _ = _make_pipeline(
        stream_chunks=[
            b'event: message_start\ndata: {"type":"message_start","message":{"id":"msg_s",'
            b'"model":"claude-opus-5","usage":{"input_tokens":3}}}\n\n',
            b'event: content_block_start\ndata: {"type":"content_block_start","index":0,'
            b'"content_block":{"type":"text","text":""}}\n\n',
            b'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,'
            b'"delta":{"type":"text_delta","text":"He"}}\n\n',
            b'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,'
            b'"delta":{"type":"text_delta","text":"llo"}}\n\n',
            b'event: content_block_stop\ndata: {"type":"content_block_stop","index":0}\n\n',
            b'event: message_delta\ndata: {"type":"message_delta","delta":{"stop_reason":"end_turn"},'
            b'"usage":{"output_tokens":2}}\n\n',
            b'event: message_stop\ndata: {"type":"message_stop"}\n\n',
        ],
        stream_headers={"Content-Type": "text/event-stream"},
    )
    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)

    response = await main._streaming_response(
        CLAUDE_CONTEXT, CHAT_BODY, 82, 12, 27, -1, {"policy": "ok"}, request_path="v1/chat/completions"
    )
    body = await _read_stream_response(response)
    frames = _frames(body)

    assert all(frame == "[DONE]" or frame["object"] == "chat.completion.chunk" for frame in frames)
    text = "".join(
        frame["choices"][0]["delta"].get("content", "") for frame in frames if frame != "[DONE]" and frame["choices"]
    )
    assert text == "Hello"
    assert frames[-1] == "[DONE]"
    # No Anthropic framing leaks through: the event: lines are not part of the
    # chat/completions protocol.
    assert "event: " not in body
    assert "message_stop" not in body


@pytest.mark.asyncio
async def test_midstream_failure_is_reported_as_an_openai_error_frame(monkeypatch):
    dummy_db = _make_dummy_db()
    monkeypatch.setattr(main, "DBManager", dummy_db)
    _passthrough_resolver(monkeypatch)

    class ExplodingPipeline:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

    pipeline, _, _ = _make_pipeline(
        stream_chunks=[
            b'event: message_start\ndata: {"type":"message_start","message":'
            b'{"id":"msg_p","model":"claude-opus-5"}}\n\n',
            b'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,'
            b'"delta":{"type":"text_delta","text":"partial"}}\n\n',
        ],
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
        CLAUDE_CONTEXT, CHAT_BODY, 83, 12, 27, -1, {"policy": "ok"}, request_path="v1/chat/completions"
    )
    frames = _frames(await _read_stream_response(response))

    assert frames[-2]["error"]["message"] == "connection reset"
    assert frames[-1] == "[DONE]"
    # A terminal choice would read as a turn that completed normally.
    assert not any(frame != "[DONE]" and frame.get("choices") for frame in frames[-2:])


@pytest.mark.asyncio
async def test_pre_stream_error_keeps_the_openai_error_shape(monkeypatch):
    dummy_db = _make_dummy_db()
    monkeypatch.setattr(main, "DBManager", dummy_db)
    _passthrough_resolver(monkeypatch)

    pipeline, _, _ = _make_pipeline(
        stream_error=UpstreamStreamError(
            429, {"type": "error", "error": {"message": "Overloaded", "type": "overloaded_error"}}
        ),
    )
    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)

    response = await main._streaming_response(
        CLAUDE_CONTEXT, CHAT_BODY, 84, 12, 27, -1, {"policy": "ok"}, request_path="v1/chat/completions"
    )
    body = json.loads(response.body)

    assert response.status_code == 429
    assert body["error"]["message"] == "Overloaded"
    assert "type" not in body


@pytest.mark.asyncio
async def test_a_silent_terminal_failure_is_not_closed_as_a_complete_answer(monkeypatch):
    """A caught post-yield failure ends the iterator without raising.

    It therefore reaches the normal close rather than the except branch, and
    finishing the translated stream there would emit a finish_reason and
    [DONE] — a truncated answer the client cannot tell from a complete one.
    """
    dummy_db = _make_dummy_db()
    monkeypatch.setattr(main, "DBManager", dummy_db)
    _passthrough_resolver(monkeypatch)

    pipeline, _, _ = _make_pipeline(
        stream_chunks=[
            b'event: message_start\ndata: {"type":"message_start","message":'
            b'{"id":"msg_t","model":"claude-opus-5"}}\n\n',
            b'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,'
            b'"delta":{"type":"text_delta","text":"partial"}}\n\n',
        ],
        stream_headers={"Content-Type": "text/event-stream"},
        terminal_status_error="upstream went away",
    )
    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)

    response = await main._streaming_response(
        CLAUDE_CONTEXT, CHAT_BODY, 85, 12, 27, -1, {"policy": "ok"}, request_path="v1/chat/completions"
    )
    frames = _frames(await _read_stream_response(response))

    assert frames[-2]["error"]["message"] == "upstream went away"
    assert frames[-1] == "[DONE]"
    assert not any(
        frame != "[DONE]" and frame.get("choices") and frame["choices"][0].get("finish_reason") for frame in frames
    )
