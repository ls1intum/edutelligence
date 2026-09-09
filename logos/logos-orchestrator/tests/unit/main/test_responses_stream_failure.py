"""Mid-stream failures on /v1/responses end the stream in the client's dialect.

The resolver marks only Messages requests with an upstream dialect, so a
Responses request reaches the streaming layer with ``anthropic_dialect=None``
and a failure frame built for chat/completions. The client, however, parses
Responses events: it ends a failed turn on ``response.failed``, and a bare
error object — or silence — is neither.
"""

import json
from types import SimpleNamespace

import pytest

import logos as main

from .test_request_logging import _make_dummy_db, _make_pipeline, _read_stream_response

# The context the resolver produces for a /v1/responses request against a
# cloud upstream that speaks the Responses API: no dialect marker (the
# resolver sets one only for Messages), the Responses surface on both ends.
RESPONSES_CONTEXT = SimpleNamespace(
    provider_type="cloud",
    forward_url="https://provider.test/v1/responses",
    model_name="gpt-4.1-nano",
    lane_id=None,
    anthropic_dialect=None,
)

RESPONSES_BODY = {"model": "gpt-4.1-nano", "input": "hi"}


def _passthrough_resolver(monkeypatch):
    monkeypatch.setattr(
        main,
        "_context_resolver",
        SimpleNamespace(prepare_headers_and_payload=lambda context, payload: ({}, payload)),
        raising=False,
    )


def _events(body: str):
    """SSE blocks as (event_name, data) pairs; [DONE] stays a plain string."""
    out = []
    for block in body.split("\n\n"):
        if not block.strip():
            continue
        name = data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[len("event: ") :]
            elif line.startswith("data: "):
                raw = line[len("data: ") :]
                data = raw if raw == "[DONE]" else json.loads(raw)
        out.append((name, data))
    return out


@pytest.mark.asyncio
async def test_midstream_failure_is_reported_as_a_responses_failed_event(monkeypatch):
    dummy_db = _make_dummy_db()
    monkeypatch.setattr(main, "DBManager", dummy_db)
    _passthrough_resolver(monkeypatch)

    class ExplodingPipeline:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

    pipeline, completion_calls, _ = _make_pipeline(
        stream_chunks=[
            b"event: response.created\n"
            b'data: {"type":"response.created","response":{"id":"resp_1","status":"in_progress"}}\n\n',
            b"event: response.output_text.delta\n" b'data: {"type":"response.output_text.delta","delta":"partial"}\n\n',
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
        RESPONSES_CONTEXT,
        RESPONSES_BODY,
        75,
        12,
        27,
        -1,
        {"policy": "ok"},
        {
            "request_id": "req-resp-fail",
            "provider_type": "cloud",
            "queue_depth_at_arrival": 0,
            "utilization_at_arrival": 1,
            "is_cold_start": False,
        },
        request_path="v1/responses",
    )
    body = await _read_stream_response(response)
    events = _events(body)

    # The upstream's own frames pass through untouched...
    assert [name for name, _ in events[:-2]] == ["response.created", "response.output_text.delta"]
    # ...and the failure ends the stream in the dialect the client reads: the
    # terminal response.failed event, then the protocol's [DONE].
    failed_name, failed = events[-2]
    assert failed_name == "response.failed"
    assert failed["type"] == "response.failed"
    assert failed["response"]["object"] == "response"
    assert failed["response"]["id"].startswith("resp_")
    assert failed["response"]["status"] == "failed"
    assert failed["response"]["error"]["code"] == "server_error"
    assert failed["response"]["error"]["message"] == "connection reset"
    assert events[-1] == (None, "[DONE]")
    # ...not in the dialect it does not read: the chat/completions terminal
    # failure is a bare error object with no event name, and it must not stand
    # in for response.failed.
    assert not any(isinstance(data, dict) and "error" in data and "type" not in data for _, data in events)

    # The failure still lands in the ledger as an error, not a success.
    assert completion_calls == [
        {
            "request_id": "req-resp-fail",
            "result_status": "error",
            "error_message": "connection reset",
            "cold_start": False,
            "usage_tokens": {"billed_input_characters": 2, "billed_output_characters": 7},
        }
    ]
