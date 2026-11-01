"""Streamed completions must release their pooled connection.

An unclosed ``openai.Stream`` is freed only by the cyclic garbage collector. Its
cleanup takes the httpcore pool lock, so a collection that runs while the same
thread holds that lock deadlocks the model's shared client for good. These tests
run against a local SSE server with the real OpenAI client and connection pool.
"""

import gc
import http.server
import json
import threading
from contextlib import contextmanager

import pytest
from openai import ContentFilterFinishReasonError

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.llm import CompletionArguments  # noqa: E402
from iris.llm.external.openai_chat import DirectOpenAIChatModel  # noqa: E402

_COMPLETED_RESPONSE = {
    "id": "resp_1",
    "object": "response",
    "created_at": 0,
    "model": "gpt-test",
    "status": "completed",
    "output": [],
    "parallel_tool_calls": False,
    "tool_choice": "auto",
    "tools": [],
    "usage": {
        "input_tokens": 3,
        "output_tokens": 2,
        "total_tokens": 5,
        "input_tokens_details": {"cached_tokens": 0},
        "output_tokens_details": {"reasoning_tokens": 0},
    },
}


def _text_delta(text, sequence_number):
    return {
        "type": "response.output_text.delta",
        "delta": text,
        "item_id": "msg_1",
        "output_index": 0,
        "content_index": 0,
        "sequence_number": sequence_number,
        "logprobs": [],
    }


RESPONSES_COMPLETED = [
    _text_delta("Hel", 1),
    _text_delta("lo", 2),
    {
        "type": "response.completed",
        "sequence_number": 3,
        "response": _COMPLETED_RESPONSE,
    },
]

RESPONSES_FAILED = [
    {
        "type": "response.failed",
        "sequence_number": 1,
        "response": {
            **_COMPLETED_RESPONSE,
            "status": "failed",
            "error": {"code": "server_error", "message": "boom"},
        },
    },
]


def _chat_chunk(content, finish_reason=None):
    return {
        "id": "chatcmpl_1",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "gpt-test",
        "choices": [
            {
                "index": 0,
                "delta": {"content": content},
                "finish_reason": finish_reason,
            }
        ],
    }


CHAT_CONTENT_FILTER = [_chat_chunk("Hel"), _chat_chunk("", "content_filter")]


def _sse_body(events, with_event_names):
    parts = []
    for event in events:
        if with_event_names:
            event_type = event["type"]
            parts.append(f"event: {event_type}\ndata: {json.dumps(event)}\n\n")
        else:
            parts.append(f"data: {json.dumps(event)}\n\n")
    if not with_event_names:
        parts.append("data: [DONE]\n\n")
    return "".join(parts).encode()


@contextmanager
def _sse_server(events, with_event_names=True):
    body = _sse_body(events, with_event_names)

    class Handler(http.server.BaseHTTPRequestHandler):
        """Answers every POST with the given events as one SSE response."""

        protocol_version = "HTTP/1.1"

        def do_POST(self):  # noqa: N802  pylint: disable=invalid-name
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            self.wfile.write(f"{len(body):x}\r\n".encode() + body + b"\r\n")
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()

        def log_message(self, *args):  # silence test output
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1"
    finally:
        server.shutdown()
        server.server_close()


def _build_model(base_url, use_responses_api=True):
    return DirectOpenAIChatModel(
        id="test-model",
        type="openai_chat",
        model="gpt-test",
        api_key="sk-test",  # pragma: allowlist secret
        base_url=base_url,
        use_responses_api=use_responses_api,
    )


def _pool(model):
    # pylint: disable=protected-access
    return model.get_client()._client._transport._pool


@contextmanager
def _gc_paused():
    # Without the fix the abandoned stream would linger until the next automatic
    # collection; pausing the collector makes that state observable every time.
    gc.disable()
    try:
        yield
    finally:
        gc.enable()


def _assert_pool_released(model):
    pool = _pool(model)
    # pylint: disable=protected-access
    assert pool._requests == []

    def collect_inside_pool_lock():
        with pool._optional_thread_lock:
            gc.collect()

    collector = threading.Thread(target=collect_inside_pool_lock, daemon=True)
    collector.start()
    collector.join(5)
    assert not collector.is_alive(), "garbage collection deadlocked on the pool lock"


def test_responses_stream_is_closed_after_completion():
    with _sse_server(RESPONSES_COMPLETED) as base_url, _gc_paused():
        model = _build_model(base_url)
        deltas = []
        result = model._create_streamed_responses_completion(  # pylint: disable=protected-access
            model.get_client(), [], CompletionArguments(), None, deltas.append
        )

        assert deltas == ["Hel", "lo"]
        assert result.contents[0].text_content == "Hello"
        _assert_pool_released(model)


def test_responses_stream_is_closed_when_the_response_failed():
    with _sse_server(RESPONSES_FAILED) as base_url, _gc_paused():
        model = _build_model(base_url)
        with pytest.raises(
            RuntimeError, match="Responses API returned failed status:.*boom"
        ):
            model._create_streamed_responses_completion(  # pylint: disable=protected-access
                model.get_client(), [], CompletionArguments(), None, lambda _: None
            )

        _assert_pool_released(model)


def test_responses_stream_is_closed_when_the_stream_handler_raises():
    def failing_handler(delta):  # pylint: disable=unused-argument
        raise RuntimeError("partial sender broke")

    with _sse_server(RESPONSES_COMPLETED) as base_url, _gc_paused():
        model = _build_model(base_url)
        with pytest.raises(RuntimeError, match="partial sender broke"):
            model._create_streamed_responses_completion(  # pylint: disable=protected-access
                model.get_client(), [], CompletionArguments(), None, failing_handler
            )

        _assert_pool_released(model)


def test_chat_completion_stream_is_closed_on_content_filter():
    with _sse_server(
        CHAT_CONTENT_FILTER, with_event_names=False
    ) as base_url, _gc_paused():
        model = _build_model(base_url, use_responses_api=False)
        with pytest.raises(ContentFilterFinishReasonError):
            model._create_streamed_chat_completion(  # pylint: disable=protected-access
                model.get_client(),
                {"model": "gpt-test", "messages": []},
                lambda _: None,
            )

        _assert_pool_released(model)
