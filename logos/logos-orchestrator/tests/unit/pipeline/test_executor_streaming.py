"""Regression tests for byte-preserving upstream streaming."""

import asyncio
import json
import time

import httpx
import pytest
from openai import OpenAI

from logos.errors import RetryDeadlineExceeded, UpstreamStreamError
from logos.pipeline.executor import Executor, StreamingExecutionStatus


class FakeResponse:
    """Minimal async streaming response with controllable byte chunks."""

    def __init__(self, chunks, *, status_code=200, headers=None):
        self.chunks = chunks
        self.status_code = status_code
        self.headers = headers if headers is not None else {"content-type": "text/event-stream"}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def aread(self):
        return b"".join(chunk for chunk in self.chunks if isinstance(chunk, bytes))

    async def aiter_bytes(self):
        for chunk in self.chunks:
            if isinstance(chunk, Exception):
                raise chunk
            yield chunk

    async def aiter_lines(self):
        """Model httpx line iteration closely enough to expose lost delimiters."""
        body = await self.aread()
        for line in body.decode().splitlines():
            yield line


class FakeAsyncClient:
    def __init__(self, response, **_kwargs):
        self.response = response
        self.request = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def stream(self, method, url, *, headers, json):
        self.request = (method, url, headers, json)
        return self.response


def install_response(monkeypatch, response):
    client = FakeAsyncClient(response)
    monkeypatch.setattr("logos.pipeline.executor.httpx.AsyncClient", lambda **_kwargs: client)
    return client


async def collect_stream(monkeypatch, chunks, *, url="https://provider.test/v1/chat/completions"):
    install_response(monkeypatch, FakeResponse(chunks))
    return b"".join(
        [
            chunk
            async for chunk in Executor().execute_streaming(
                url,
                {"authorization": "Bearer test"},
                {"model": "test-model", "messages": [{"role": "user", "content": "hi"}]},
            )
        ]
    )


@pytest.mark.parametrize(
    ("url", "chunks"),
    [
        (
            "https://provider.test/v1/chat/completions",
            [
                b'data: {"choices":[{"delta":{"content":"Hel',
                b'lo"}}]}\n',
                b'\ndata: {"choices":[{"delta":{"content":" world"}}]}\n\n',
                b"data: [DONE]\n",
                b"\n",
            ],
        ),
        (
            "https://provider.test/v1/responses",
            [
                b"event: response.output_text.delta\n",
                b'data: {"type":"response.output_text.delta","delta":"OK"}',
                b"\n\nevent: response.completed\n",
                b'data: {"type":"response.completed"}\n\n',
            ],
        ),
    ],
    ids=["chat-completions", "responses"],
)
async def test_sse_stream_is_forwarded_byte_for_byte(monkeypatch, url, chunks):
    assert await collect_stream(monkeypatch, chunks, url=url) == b"".join(chunks)


async def test_ndjson_stream_is_forwarded_byte_for_byte(monkeypatch):
    """Generic HTTP-local streams retain NDJSON framing and chunk splits."""
    chunks = [
        b'{"model":"local","message":{"content":"Hel',
        b'lo"},"done":false}\n{"model":"local",',
        b'"message":{"content":"!"},"done":true}\n',
    ]

    assert await collect_stream(monkeypatch, chunks, url="http://worker:8000/api/chat") == b"".join(chunks)


@pytest.mark.parametrize(
    "content_type",
    [
        "application/x-ndjson",
        "text/event-streaming",
        "application/text/event-stream+json",
        None,
    ],
    ids=["ndjson", "sse-prefix", "sse-suffix", "missing"],
)
async def test_non_sse_mid_stream_error_does_not_append_sse_frames(monkeypatch, content_type):
    partial = b'{"model":"local","message":{"content":"partial'
    headers = {} if content_type is None else {"content-type": content_type}
    install_response(
        monkeypatch,
        FakeResponse(
            [partial, RuntimeError("connection reset")],
            headers=headers,
        ),
    )

    status = StreamingExecutionStatus()
    body = b"".join(
        [
            chunk
            async for chunk in Executor().execute_streaming(
                "http://worker:8000/api/chat",
                {},
                {"model": "local"},
                status=status,
            )
        ]
    )

    assert body == partial
    assert b"data: " not in body
    assert b"[DONE]" not in body
    assert status.error == "connection reset"


@pytest.mark.parametrize(
    "headers",
    [
        {"content-type": "application/x-ndjson"},
        {"content-type": "text/event-stream"},
        {},
    ],
    ids=["ndjson", "sse", "missing-content-type"],
)
async def test_transport_error_before_first_byte_is_raised(monkeypatch, headers):
    install_response(monkeypatch, FakeResponse([RuntimeError("connection reset")], headers=headers))

    with pytest.raises(RuntimeError, match="connection reset"):
        _ = [
            chunk
            async for chunk in Executor().execute_streaming(
                "https://provider.test/v1/chat/completions", {}, {"model": "test-model"}
            )
        ]


async def test_upstream_http_error_is_still_raised_before_streaming(monkeypatch):
    body = {"error": {"message": "rate limited"}}
    install_response(
        monkeypatch,
        FakeResponse([json.dumps(body).encode()], status_code=429, headers={"retry-after": "1"}),
    )

    with pytest.raises(UpstreamStreamError) as exc_info:
        _ = [
            chunk
            async for chunk in Executor().execute_streaming(
                "https://provider.test/v1/chat/completions", {}, {"model": "test-model"}
            )
        ]

    assert exc_info.value.status_code == 429
    assert exc_info.value.body == body


async def test_mid_stream_error_after_complete_event_emits_error_and_done(monkeypatch):
    install_response(
        monkeypatch,
        FakeResponse(
            [b'data: {"partial":true}\n\n', RuntimeError("connection reset")],
            headers={"content-type": "Text/Event-Stream; charset=utf-8"},
        ),
    )

    status = StreamingExecutionStatus()
    chunks = [
        chunk
        async for chunk in Executor().execute_streaming(
            "https://provider.test/v1/chat/completions",
            {},
            {"model": "test-model"},
            status=status,
        )
    ]

    assert chunks[0] == b'data: {"partial":true}\n\n'
    assert chunks[-3] == b"\n\n"
    assert json.loads(chunks[-2].removeprefix(b"data: "))["error"]["message"] == "connection reset"
    assert chunks[-1] == b"data: [DONE]\n\n"
    assert status.error == "connection reset"


@pytest.mark.parametrize(
    "partial",
    [
        b'data: {"choices":[{"delta":{"content":"bro',
        b'data: {"partial":true}\n',
        b"event: response.output_text.delta\n",
    ],
    ids=["inside-data", "between-delimiter-newlines", "after-event-line"],
)
async def test_mid_stream_error_after_partial_event_starts_new_sse_frame(monkeypatch, partial):
    install_response(monkeypatch, FakeResponse([partial, RuntimeError("connection reset")]))

    body = b"".join(
        [
            chunk
            async for chunk in Executor().execute_streaming(
                "https://provider.test/v1/chat/completions", {}, {"model": "test-model"}
            )
        ]
    )
    assert body.startswith(partial + b"\n\n")
    error_and_done = body.removeprefix(partial + b"\n\n").split(b"\n\n")

    assert json.loads(error_and_done[0].removeprefix(b"data: "))["error"]["message"] == "connection reset"
    assert error_and_done[1] == b"data: [DONE]"


async def test_openai_sdk_parses_content_tool_finish_and_usage_chunks(monkeypatch):
    upstream = b"".join(
        [
            b'data: {"id":"chatcmpl-1","object":"chat.completion.chunk","created":1,"model":"gpt-5.5",'
            b'"choices":[{"index":0,"delta":{"role":"assistant","content":"OK"},"finish_reason":null}]}\n\n',
            b'data: {"id":"chatcmpl-1","object":"chat.completion.chunk","created":1,"model":"gpt-5.5",'
            b'"choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"id":"call_1","type":"function",'
            b'"function":{"name":"lookup","arguments":"{}"}}]},"finish_reason":null}]}\n\n',
            b'data: {"id":"chatcmpl-1","object":"chat.completion.chunk","created":1,"model":"gpt-5.5",'
            b'"choices":[{"index":0,"delta":{},"finish_reason":"tool_calls"}]}\n\n',
            b'data: {"id":"chatcmpl-1","object":"chat.completion.chunk","created":1,"model":"gpt-5.5",'
            b'"choices":[],"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}\n\n',
            b"data: [DONE]\n\n",
        ]
    )
    proxied = await collect_stream(monkeypatch, [upstream[:19], upstream[19:-1], upstream[-1:]])
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(200, headers={"content-type": "text/event-stream"}, content=proxied)
    )

    with httpx.Client(transport=transport) as http_client:
        client = OpenAI(api_key="test", base_url="https://logos.test/v1", http_client=http_client)
        chunks = list(
            client.chat.completions.create(
                model="test-model",
                messages=[{"role": "user", "content": "hi"}],
                stream=True,
            )
        )

    assert chunks[0].choices[0].delta.content == "OK"
    assert chunks[1].choices[0].delta.tool_calls[0].function.name == "lookup"
    assert chunks[2].choices[0].finish_reason == "tool_calls"
    assert chunks[3].usage.total_tokens == 2


async def test_openai_sdk_parses_responses_content_and_terminal_events(monkeypatch):
    upstream = b"".join(
        [
            b"event: response.output_text.delta\n",
            b'data: {"type":"response.output_text.delta","sequence_number":1,"item_id":"item_1",'
            b'"output_index":0,"content_index":0,"delta":"OK","logprobs":[]}\n\n',
            b"event: response.completed\n",
            b'data: {"type":"response.completed","sequence_number":2,"response":{"id":"resp_1",'
            b'"object":"response","created_at":1,"status":"completed","error":null,"incomplete_details":null,'
            b'"instructions":null,"max_output_tokens":null,"model":"gpt-5.5","output":[],"parallel_tool_calls":true,'
            b'"previous_response_id":null,"reasoning":{"effort":null,"summary":null},"store":false,'
            b'"temperature":null,"text":{"format":{"type":"text"}},"tool_choice":"auto","tools":[],'
            b'"top_p":null,"truncation":"disabled","usage":{"input_tokens":1,'
            b'"input_tokens_details":{"cached_tokens":0},"output_tokens":1,'
            b'"output_tokens_details":{"reasoning_tokens":0},"total_tokens":2},"metadata":{}}}\n\n',
        ]
    )
    proxied = await collect_stream(
        monkeypatch,
        [upstream[:34], upstream[34:35], upstream[35:-2], upstream[-2:-1], upstream[-1:]],
        url="https://provider.test/v1/responses",
    )
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(200, headers={"content-type": "text/event-stream"}, content=proxied)
    )

    with httpx.Client(transport=transport) as http_client:
        client = OpenAI(api_key="test", base_url="https://logos.test/v1", http_client=http_client)
        events = list(client.responses.create(model="test-model", input="hi", stream=True))

    assert events[0].type == "response.output_text.delta"
    assert events[0].delta == "OK"
    assert events[-1].type == "response.completed"
    assert events[-1].response.status == "completed"


# ---------------------------------------------------------------------------
# The absolute execution deadline
#
# The httpx timeout is a per-operation bound — the longest gap between chunks.
# A stream that keeps delivering can never trip it, so a retry would run
# indefinitely past its deadline; the deadline must be an absolute wall on the
# whole execution instead.
# ---------------------------------------------------------------------------


async def test_a_spent_deadline_fails_the_stream_before_the_first_byte(monkeypatch):
    install_response(monkeypatch, FakeResponse([b"data: {}\n\n"]))

    with pytest.raises(RetryDeadlineExceeded):
        _ = [
            chunk
            async for chunk in Executor().execute_streaming(
                "https://provider.test/v1/chat/completions",
                {},
                {"model": "test-model"},
                deadline_at=time.monotonic() - 1.0,  # spent before the first read
            )
        ]


async def test_chunks_cannot_push_the_stream_past_the_deadline(monkeypatch):
    """The scenario a per-read bound misses: chunks arriving more often than
    the read timeout can ever fire. The execution must still stop at the
    absolute deadline, however steadily the upstream delivers."""

    class DripResponse:
        """Keeps delivering a chunk every 20 ms for well over a second."""

        status_code = 200
        headers = {"content-type": "text/event-stream"}
        stop_after = time.monotonic() + 1.0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def aread(self):
            return b""

        async def aiter_bytes(self):
            while time.monotonic() < self.stop_after:
                await asyncio.sleep(0.02)
                yield b"data: {}\n\n"

    install_response(monkeypatch, DripResponse())

    status = StreamingExecutionStatus()
    t0 = time.monotonic()
    body = b"".join(
        [
            chunk
            async for chunk in Executor().execute_streaming(
                "https://provider.test/v1/chat/completions",
                {},
                {"model": "test-model"},
                status=status,
                deadline_at=t0 + 0.15,
            )
        ]
    )
    elapsed = time.monotonic() - t0

    # The stream was cut at the wall, not at the end of the drip: without the
    # deadline it would have run to the drip's own end a full second out.
    assert elapsed < 0.8
    assert status.error == "stream execution passed its retry deadline"
    # After the first byte the failure is appended as protocol-compatible
    # recovery frames, like every other mid-stream transport error.
    assert b"passed its retry deadline" in body
    assert body.endswith(b"data: [DONE]\n\n")


async def test_a_recovery_disabled_stream_hands_the_mid_stream_error_back(monkeypatch):
    """With emit_recovery_frames=False the executor does not append the Chat
    Completions error frame + [DONE]: the caller's client speaks a dialect
    for which those frames are protocol noise, and it owns the terminal. The
    failure is recorded on the status and the error is handed back."""
    partial = b'data: {"type":"response.output_text.delta","delta":"par'
    install_response(
        monkeypatch,
        FakeResponse(
            [partial, RuntimeError("connection reset")],
            headers={"content-type": "text/event-stream"},
        ),
    )

    status = StreamingExecutionStatus()
    chunks = []
    with pytest.raises(RuntimeError, match="connection reset"):
        async for chunk in Executor().execute_streaming(
            "https://provider.test/v1/responses",
            {},
            {"model": "test-model"},
            status=status,
            emit_recovery_frames=False,
        ):
            chunks.append(chunk)

    # Only the partial upstream bytes came back — no recovery frame was
    # appended by the executor.
    assert b"".join(chunks) == partial
    assert b"[DONE]" not in b"".join(chunks)
    assert status.error == "connection reset"


async def test_a_deadline_cut_stream_with_recovery_disabled_propagates_the_deadline(monkeypatch):
    """The same wall, recovery disabled: the deadline is what a /v1/responses
    streamer takes back so it can end the stream in a response.failed event,
    so the executor must raise it instead of appending Chat Completions
    framing."""

    class DripResponse:
        status_code = 200
        headers = {"content-type": "text/event-stream"}
        stop_after = time.monotonic() + 1.0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def aread(self):
            return b""

        async def aiter_bytes(self):
            while time.monotonic() < self.stop_after:
                await asyncio.sleep(0.02)
                yield b"data: {}\n\n"

    install_response(monkeypatch, DripResponse())

    status = StreamingExecutionStatus()
    t0 = time.monotonic()
    chunks = []
    with pytest.raises(RetryDeadlineExceeded):
        async for chunk in Executor().execute_streaming(
            "https://provider.test/v1/responses",
            {},
            {"model": "test-model"},
            status=status,
            deadline_at=t0 + 0.15,
            emit_recovery_frames=False,
        ):
            chunks.append(chunk)
    body = b"".join(chunks)

    # The wall is recorded and raised; no recovery frame was appended.
    assert status.error == "stream execution passed its retry deadline"
    assert b"[DONE]" not in body
    assert b"passed its retry deadline" not in body


# ---------------------------------------------------------------------------
# The same absolute wall over the synchronous (non-streaming) execution
#
# The httpx timeout is a per-operation bound: its read bound resets after
# every response-body chunk, so a drip-fed JSON response can keep arriving
# forever without ever tripping it. The retry deadline has to be checked as
# one wall over the complete POST — connect, send, body read.
# ---------------------------------------------------------------------------


class _SyncResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body
        self.headers = {"content-type": "application/json"}

    def json(self):
        return json.loads(self._body)


class _FakeSyncClient:
    """Async client whose post() takes longer than any per-read bound could
    ever catch — the drip-fed response the timeout cannot stop."""

    def __init__(self, delay=0.0, body=b'{"ok": true}', status_code=200):
        self.delay = delay
        self.body = body
        self.status_code = status_code
        self.started = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, url, headers=None, timeout=None, json=None, **_kwargs):  # noqa: ARG002
        self.started = time.monotonic()
        if self.delay:
            await asyncio.sleep(self.delay)
        return _SyncResponse(self.status_code, self.body)


def install_sync_client(monkeypatch, client):
    monkeypatch.setattr("logos.pipeline.executor.httpx.AsyncClient", lambda **_kwargs: client)
    return client


async def test_sync_execution_cannot_run_past_the_absolute_deadline(monkeypatch):
    client = install_sync_client(monkeypatch, _FakeSyncClient(delay=0.5))

    t0 = time.monotonic()
    result = await Executor().execute_sync(
        "https://provider.test/v1/chat/completions",
        {},
        {"model": "test-model"},
        timeout=60.0,  # a per-read bound no drip can ever trip
        deadline_at=t0 + 0.15,
    )
    elapsed = time.monotonic() - t0

    # Cut at the wall, not at the drip's own end.
    assert elapsed < 0.4
    assert result.success is False
    assert result.error == "sync execution passed its retry deadline"
    assert result.status_code == 504


async def test_a_spent_sync_deadline_fails_before_the_request(monkeypatch):
    client = install_sync_client(monkeypatch, _FakeSyncClient())

    result = await Executor().execute_sync(
        "https://provider.test/v1/chat/completions",
        {},
        {"model": "test-model"},
        deadline_at=time.monotonic() - 1.0,  # spent before the first read
    )

    assert client.started is None  # nothing was sent
    assert result.success is False
    assert result.error == "sync execution passed its retry deadline"


async def test_sync_execution_inside_the_deadline_is_unaffected(monkeypatch):
    install_sync_client(monkeypatch, _FakeSyncClient(body=b'{"ok": true}'))

    result = await Executor().execute_sync(
        "https://provider.test/v1/chat/completions",
        {},
        {"model": "test-model"},
        deadline_at=time.monotonic() + 5.0,
    )

    assert result.success is True
    assert result.response == {"ok": True}
