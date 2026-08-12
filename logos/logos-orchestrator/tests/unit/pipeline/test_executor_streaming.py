"""Regression tests for byte-preserving upstream streaming."""

import json

import httpx
import pytest
from openai import OpenAI

from logos.errors import UpstreamStreamError
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

    assert await collect_stream(monkeypatch, chunks, url="http://ollama:11434/api/chat") == b"".join(chunks)


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
                "http://ollama:11434/api/chat",
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
