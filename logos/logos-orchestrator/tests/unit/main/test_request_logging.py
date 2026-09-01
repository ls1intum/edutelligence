import json
import logging
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import logos as main
from logos import ExecutionResult
from logos.errors import UpstreamStreamError
from logos.terminal_logging import strip_ansi


def _make_dummy_db(cost_micro_cents=None):
    class DummyDB:
        ttft_calls = []
        payload_calls = []
        metric_calls = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def set_time_at_first_token(self, log_id):
            self.ttft_calls.append(log_id)

        def set_response_payload(
            self,
            log_id,
            payload,
            provider_id=None,
            model_id=None,
            usage=None,
            policy_id=-1,
            classified=None,
            **kwargs,
        ):
            self.payload_calls.append(
                {
                    "log_id": log_id,
                    "payload": payload,
                    "provider_id": provider_id,
                    "model_id": model_id,
                    "usage": usage,
                    "policy_id": policy_id,
                    "classified": classified,
                    "kwargs": kwargs,
                }
            )

        def update_log_entry_metrics(self, **kwargs):
            self.metric_calls.append(kwargs)

        def get_usage_cost_micro_cents(self, model_id, provider_id, usage, response_at):  # noqa: ARG002
            return cost_micro_cents

    return DummyDB


async def _read_stream_response(response) -> str:
    chunks = []
    async for chunk in response.body_iterator:
        if isinstance(chunk, str):
            chunks.append(chunk.encode("utf-8"))
        else:
            chunks.append(chunk)
    return b"".join(chunks).decode("utf-8")


def _make_pipeline(
    *,
    sync_result=None,
    stream_chunks=None,
    stream_error=None,
    terminal_status_error=None,
    stream_headers=None,
    completion_calls=None,
    release_calls=None,
    sync_payloads=None,
):
    completion_calls = completion_calls if completion_calls is not None else []
    release_calls = release_calls if release_calls is not None else []
    sync_payloads = sync_payloads if sync_payloads is not None else []

    class DummyExecutor:
        async def execute_sync(self, url, headers, payload):  # noqa: ARG002
            sync_payloads.append(payload)
            return sync_result

        async def execute_streaming(
            self,
            url,
            headers,
            payload,
            on_headers=None,
            status=None,
        ):  # noqa: ARG002
            if on_headers:
                on_headers(stream_headers or {})
            if stream_error:
                raise stream_error
            for chunk in stream_chunks or []:
                yield chunk
            if status is not None:
                status.error = terminal_status_error

    class DummyScheduler:
        def release(self, model_id, provider_id, provider_type, request_id):
            release_calls.append((model_id, provider_id, provider_type, request_id))

    class DummyPipeline:
        executor = DummyExecutor()
        scheduler = DummyScheduler()

        @staticmethod
        def update_provider_stats(model_id, provider_id, headers):  # noqa: ARG002
            return None

        @staticmethod
        def record_completion(**kwargs):
            completion_calls.append(kwargs)

    return DummyPipeline(), completion_calls, release_calls


@pytest.mark.asyncio
async def test_streaming_response_logs_usage_when_sse_events_are_split(monkeypatch):
    dummy_db = _make_dummy_db()
    monkeypatch.setattr(main, "DBManager", dummy_db)
    monkeypatch.setattr(
        main,
        "_context_resolver",
        SimpleNamespace(prepare_headers_and_payload=lambda context, payload: ({}, payload)),
        raising=False,
    )

    async def fake_send_stream_command(**kwargs):  # noqa: ARG001
        chunks = [
            b'data: {"id":"chunk-1","choices":[{"delta":{"content":"hel',
            b'lo"}}]}\n\n',
            b'data: {"id":"chunk-1","choices":[],"usage":{"prompt_tokens":3',
            b',"completion_tokens":5,"total_tokens":8}}\n\n',
            b"data: [DONE]\n\n",
        ]
        for chunk in chunks:
            yield chunk

    monkeypatch.setattr(
        main,
        "_logosnode_registry",
        SimpleNamespace(send_stream_command=fake_send_stream_command),
        raising=False,
    )

    pipeline, completion_calls, release_calls = _make_pipeline()
    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)

    response = await main._streaming_response(
        SimpleNamespace(provider_type="logosnode", lane_id="lane-1"),
        {"messages": [{"role": "user", "content": "hi"}]},
        42,
        12,
        27,
        -1,
        {"policy": "ok"},
        {
            "request_id": "req-stream",
            "provider_type": "logosnode",
            "queue_depth_at_arrival": 0,
            "utilization_at_arrival": 1,
            "is_cold_start": False,
        },
    )
    body = await _read_stream_response(response)

    assert "data: [DONE]" in body
    assert response.headers["x-request-id"] == "req-stream"
    assert dummy_db.ttft_calls == [42]
    assert dummy_db.payload_calls[0]["usage"] == {
        "prompt_tokens": 3,
        "completion_tokens": 5,
        "total_tokens": 8,
    }
    assert dummy_db.payload_calls[0]["payload"]["usage"]["total_tokens"] == 8
    assert completion_calls == [
        {
            "request_id": "req-stream",
            "result_status": "success",
            "error_message": None,
            "cold_start": False,
            "usage_tokens": {
                "prompt_tokens": 3,
                "completion_tokens": 5,
                "total_tokens": 8,
            },
        }
    ]
    assert release_calls == [(27, 12, "logosnode", "req-stream")]


@pytest.mark.asyncio
async def test_streaming_local_response_logs_cached_token_details(monkeypatch):
    # vLLM lanes report usage.prompt_tokens_details.cached_tokens (the worker
    # starts them with --enable-prompt-tokens-details); the orchestrator must
    # relay it to the application and log it the same way as the cloud
    # provider's cached count (#813).
    dummy_db = _make_dummy_db()
    monkeypatch.setattr(main, "DBManager", dummy_db)
    monkeypatch.setattr(
        main,
        "_context_resolver",
        SimpleNamespace(prepare_headers_and_payload=lambda context, payload: ({}, payload)),
        raising=False,
    )

    async def fake_send_stream_command(**kwargs):  # noqa: ARG001
        chunks = [
            b'data: {"id":"chunk-1","choices":[{"delta":{"content":"hi"}}]}\n\n',
            b'data: {"id":"chunk-1","choices":[],"usage":{"prompt_tokens":10,'
            b'"completion_tokens":4,"total_tokens":14,'
            b'"prompt_tokens_details":{"cached_tokens":6}}}\n\n',
            b"data: [DONE]\n\n",
        ]
        for chunk in chunks:
            yield chunk

    monkeypatch.setattr(
        main,
        "_logosnode_registry",
        SimpleNamespace(send_stream_command=fake_send_stream_command),
        raising=False,
    )

    pipeline, _, _ = _make_pipeline()
    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)

    response = await main._streaming_response(
        SimpleNamespace(provider_type="logosnode", lane_id="lane-1"),
        {"messages": [{"role": "user", "content": "hi"}]},
        43,
        12,
        27,
        -1,
        {"policy": "ok"},
        {
            "request_id": "req-cached",
            "provider_type": "logosnode",
            "queue_depth_at_arrival": 0,
            "utilization_at_arrival": 1,
            "is_cold_start": False,
        },
    )
    body = await _read_stream_response(response)

    # The client sees the provider's usage verbatim, details included.
    assert '"prompt_tokens_details":{"cached_tokens":6}' in body
    assert dummy_db.payload_calls[0]["usage"] == {
        "prompt_tokens": 10,
        "completion_tokens": 4,
        "total_tokens": 14,
        "prompt_cached_tokens": 6,
    }


@pytest.mark.asyncio
async def test_sync_local_response_keeps_cached_token_details(monkeypatch):
    # The lane's usage.prompt_tokens_details must reach the application in
    # the response and land in the request log as prompt_cached_tokens,
    # mirroring the cloud path (#813).
    dummy_db = _make_dummy_db()
    monkeypatch.setattr(main, "DBManager", dummy_db)
    monkeypatch.setattr(
        main,
        "_context_resolver",
        SimpleNamespace(prepare_headers_and_payload=lambda context, payload: ({}, payload)),
        raising=False,
    )

    async def send_command(**kwargs):  # noqa: ARG001
        return {
            "status_code": 200,
            "body": {
                "id": "cmpl-1",
                "choices": [{"message": {"role": "assistant", "content": "hi"}}],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 4,
                    "total_tokens": 14,
                    "prompt_tokens_details": {"cached_tokens": 6},
                },
            },
            "headers": {"content-type": "application/json"},
        }

    monkeypatch.setattr(
        main,
        "_logosnode_registry",
        SimpleNamespace(send_command=send_command),
        raising=False,
    )
    pipeline, _, _ = _make_pipeline()
    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)

    response = await main._sync_response(
        SimpleNamespace(provider_type="logosnode", lane_id="lane-a", model_name="local-model"),
        {"model": "local-model", "messages": [{"role": "user", "content": "hi"}]},
        44,
        12,
        27,
        -1,
        {"classified": True},
        scheduling_stats={
            "request_id": "req-sync-cached",
            "provider_type": "logosnode",
        },
    )

    content = json.loads(response.body)
    assert content["usage"]["prompt_tokens_details"]["cached_tokens"] == 6
    assert dummy_db.payload_calls[0]["usage"]["prompt_cached_tokens"] == 6


@pytest.mark.asyncio
async def test_cloud_streaming_response_returns_eur_cost_in_terminal_usage(monkeypatch):
    dummy_db = _make_dummy_db(cost_micro_cents=375)
    monkeypatch.setattr(main, "DBManager", dummy_db)
    monkeypatch.setattr(
        main,
        "_context_resolver",
        SimpleNamespace(prepare_headers_and_payload=lambda context, payload: ({}, payload)),
        raising=False,
    )

    pipeline, _, _ = _make_pipeline(
        stream_chunks=[
            b'data: {"id":"chunk-1","choices":[{"delta":{"content":"ok"}}]}\n\n',
            b'data: {"id":"chunk-1","choices":[],"usage":{"prompt_tokens":1',
            b',"completion_tokens":2,"total_tokens":3}}\n\n',
            b"data: [DONE]\n\n",
        ],
        stream_headers={"Content-Type": "text/event-stream"},
    )
    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)

    response = await main._streaming_response(
        SimpleNamespace(provider_type="cloud", forward_url="https://provider.test/v1/chat/completions"),
        {"messages": [{"role": "user", "content": "hi"}]},
        62,
        12,
        27,
        -1,
        {"policy": "ok"},
    )

    body = await _read_stream_response(response)
    usage_event = next(
        json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: {") and '"usage"' in line
    )
    assert usage_event["usage"]["cost"] == 0.00000375
    assert usage_event["usage"]["cost_currency"] == "USD"
    assert dummy_db.payload_calls[0]["payload"]["usage"]["cost"] == 0.00000375


@pytest.mark.asyncio
async def test_cloud_sync_response_returns_eur_cost(monkeypatch):
    dummy_db = _make_dummy_db(cost_micro_cents=12345)
    monkeypatch.setattr(main, "DBManager", dummy_db)
    monkeypatch.setattr(
        main,
        "_context_resolver",
        SimpleNamespace(prepare_headers_and_payload=lambda context, payload: ({}, payload)),
        raising=False,
    )
    pipeline, _, _ = _make_pipeline(
        sync_result=ExecutionResult(
            success=True,
            response={
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
            error=None,
            usage={},
            is_streaming=False,
            headers=None,
            status_code=200,
        )
    )
    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)

    response = await main._sync_response(
        SimpleNamespace(provider_type="cloud", forward_url="https://provider.test/v1/chat/completions"),
        {"messages": [{"role": "user", "content": "hi"}]},
        63,
        12,
        27,
        -1,
        {"policy": "ok"},
    )

    body = json.loads(response.body)
    assert body["usage"]["cost"] == 0.00012345
    assert body["usage"]["cost_currency"] == "USD"
    assert dummy_db.payload_calls[0]["usage"] == {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stream_error", "expected_status", "expected_message", "recorded_error"),
    [
        (
            RuntimeError("connection reset before response body"),
            502,
            "connection reset before response body",
            "connection reset before response body",
        ),
        (
            UpstreamStreamError(429, {"error": {"message": "rate limited"}}),
            429,
            "rate limited",
            "Upstream returned HTTP 429",
        ),
    ],
    ids=["transport", "upstream-http"],
)
async def test_pre_stream_error_records_failure_and_releases_scheduler(
    monkeypatch, stream_error, expected_status, expected_message, recorded_error
):
    dummy_db = _make_dummy_db()
    monkeypatch.setattr(main, "DBManager", dummy_db)
    monkeypatch.setattr(
        main,
        "_context_resolver",
        SimpleNamespace(prepare_headers_and_payload=lambda context, payload: ({}, payload)),
        raising=False,
    )
    completion_logs = []
    monkeypatch.setattr(main, "_log_request_completion", lambda **kwargs: completion_logs.append(kwargs))

    pipeline, completion_calls, release_calls = _make_pipeline(stream_error=stream_error)
    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)

    response = await main._streaming_response(
        SimpleNamespace(provider_type="cloud", forward_url="https://provider.test/v1/chat/completions"),
        {"messages": [{"role": "user", "content": "hi"}]},
        58,
        12,
        27,
        -1,
        {"policy": "ok"},
        {
            "request_id": "req-pre-stream-error",
            "provider_type": "cloud",
            "queue_depth_at_arrival": 1,
            "utilization_at_arrival": 0.75,
            "is_cold_start": False,
        },
    )

    assert response.status_code == expected_status
    assert json.loads(response.body)["error"]["message"] == expected_message
    assert response.headers["x-request-id"] == "req-pre-stream-error"
    assert dummy_db.ttft_calls == []
    assert dummy_db.payload_calls[0]["payload"] == json.loads(response.body)
    assert dummy_db.metric_calls == [
        {
            "log_id": 58,
            "request_id": "req-pre-stream-error",
            "model_id": 27,
            "provider_id": 12,
            "result_status": "error",
            "error_message": recorded_error,
            "cold_start": False,
        }
    ]
    assert completion_calls == [
        {
            "request_id": "req-pre-stream-error",
            "result_status": "error",
            "error_message": recorded_error,
            "cold_start": False,
        }
    ]
    assert release_calls == [(27, 12, "cloud", "req-pre-stream-error")]
    assert len(completion_logs) == 1
    assert completion_logs[0] == {
        "model_id": 27,
        "request_id": "req-pre-stream-error",
        "start_time": completion_logs[0]["start_time"],
        "usage": {},
        "status": "error",
        "is_streaming": True,
    }


@pytest.mark.asyncio
async def test_proxy_streaming_response_logs_usage_and_status(monkeypatch):
    dummy_db = _make_dummy_db()
    monkeypatch.setattr(main, "DBManager", dummy_db)

    pipeline, _, _ = _make_pipeline(
        stream_chunks=[
            b'data: {"id":"proxy-1","choices":[{"delta":{"content":"pro',
            b'xy"}}]}\n\n',
            b'data: {"id":"proxy-1","choices":[],"usage":{"prompt_tokens":2',
            b',"completion_tokens":4,"total_tokens":6}}\n\n',
            b"data: [DONE]\n\n",
        ]
    )
    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)

    response = main._proxy_streaming_response(
        "http://proxy",
        {"Authorization": "Bearer x"},
        {"stream": True},
        43,
        7,
        9,
        -1,
        {"classified": True},
        request_id="req-proxy-stream",
    )
    body = await _read_stream_response(response)

    assert "data: [DONE]" in body
    assert response.headers["x-request-id"] == "req-proxy-stream"
    assert dummy_db.ttft_calls == [43]
    assert dummy_db.payload_calls[0]["usage"] == {
        "prompt_tokens": 2,
        "completion_tokens": 4,
        "total_tokens": 6,
    }
    assert dummy_db.metric_calls == [
        {
            "log_id": 43,
            "provider_id": 7,
            "model_id": 9,
            "result_status": "success",
            "error_message": None,
        }
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal_error", ["connection reset", ""], ids=["message", "empty-message"])
async def test_http_streaming_terminal_error_is_recorded(monkeypatch, terminal_error):
    dummy_db = _make_dummy_db()
    monkeypatch.setattr(main, "DBManager", dummy_db)
    monkeypatch.setattr(
        main,
        "_context_resolver",
        SimpleNamespace(prepare_headers_and_payload=lambda context, payload: ({}, payload)),
        raising=False,
    )
    completion_logs = []
    monkeypatch.setattr(main, "_log_request_completion", lambda **kwargs: completion_logs.append(kwargs))

    pipeline, completion_calls, release_calls = _make_pipeline(
        stream_chunks=[b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'],
        terminal_status_error=terminal_error,
    )
    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)

    response = await main._streaming_response(
        SimpleNamespace(provider_type="cloud", forward_url="https://provider.test/v1/chat/completions"),
        {"messages": [{"role": "user", "content": "hi"}]},
        59,
        12,
        27,
        -1,
        {"policy": "ok"},
        {
            "request_id": "req-mid-stream-error",
            "provider_type": "cloud",
            "queue_depth_at_arrival": 0,
            "utilization_at_arrival": 0.5,
            "is_cold_start": False,
        },
    )
    await _read_stream_response(response)

    assert dummy_db.metric_calls == [
        {
            "log_id": 59,
            "request_id": "req-mid-stream-error",
            "model_id": 27,
            "provider_id": 12,
            "result_status": "error",
            "error_message": terminal_error,
        }
    ]
    assert completion_calls == [
        {
            "request_id": "req-mid-stream-error",
            "result_status": "error",
            "error_message": terminal_error,
            "cold_start": False,
            # The stream carried no usage chunk, so nothing was extracted.
            "usage_tokens": {},
        }
    ]
    assert completion_logs[0]["status"] == "error"
    assert release_calls == [(27, 12, "cloud", "req-mid-stream-error")]


@pytest.mark.asyncio
async def test_http_ndjson_response_preserves_content_type_and_does_not_append_sse_on_failure(monkeypatch):
    dummy_db = _make_dummy_db()

    class TtftFailingDB(dummy_db):
        def set_time_at_first_token(self, log_id):  # noqa: ARG002
            raise RuntimeError("failed to record first token")

    monkeypatch.setattr(main, "DBManager", TtftFailingDB)
    monkeypatch.setattr(
        main,
        "_context_resolver",
        SimpleNamespace(prepare_headers_and_payload=lambda context, payload: ({}, payload)),
        raising=False,
    )

    partial = b'{"message":{"content":"partial"}}\n'
    pipeline, completion_calls, _ = _make_pipeline(
        stream_chunks=[partial],
        stream_headers={"Content-Type": "application/x-ndjson"},
    )
    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)

    response = await main._streaming_response(
        SimpleNamespace(provider_type="local", forward_url="http://worker:8000/api/chat"),
        {"model": "local"},
        60,
        12,
        27,
        -1,
        {"policy": "ok"},
    )
    body = await _read_stream_response(response)

    assert response.headers["content-type"] == "application/x-ndjson"
    assert body.encode() == partial
    assert "data: " not in body
    assert "[DONE]" not in body
    assert completion_calls == []
    assert dummy_db.metric_calls == [
        {
            "log_id": 60,
            "request_id": None,
            "model_id": 27,
            "provider_id": 12,
            "result_status": "error",
            "error_message": "failed to record first token",
        }
    ]


@pytest.mark.asyncio
async def test_http_sse_response_delimits_recovery_after_partial_first_chunk(monkeypatch):
    dummy_db = _make_dummy_db()

    class TtftFailingDB(dummy_db):
        def set_time_at_first_token(self, log_id):  # noqa: ARG002
            raise RuntimeError("failed to record first token")

    monkeypatch.setattr(main, "DBManager", TtftFailingDB)
    monkeypatch.setattr(
        main,
        "_context_resolver",
        SimpleNamespace(prepare_headers_and_payload=lambda context, payload: ({}, payload)),
        raising=False,
    )

    partial = b'data: {"choices":[{"delta":{"content":"partial"}}]'
    pipeline, completion_calls, _ = _make_pipeline(
        stream_chunks=[partial],
        stream_headers={"Content-Type": "text/event-stream"},
    )
    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)

    response = await main._streaming_response(
        SimpleNamespace(provider_type="cloud", forward_url="https://provider.test/v1/chat/completions"),
        {"messages": [{"role": "user", "content": "hi"}]},
        61,
        12,
        27,
        -1,
        {"policy": "ok"},
    )
    body = await _read_stream_response(response)

    assert response.headers["content-type"] == "text/event-stream"
    assert body.startswith(partial.decode() + "\n\ndata: ")
    recovery_frames = body[len(partial) + 2 :]
    error_frame, terminal_frame, trailing = recovery_frames.split("\n\n")
    error_payload = json.loads(error_frame.removeprefix("data: "))
    assert error_payload["error"]["message"] == "failed to record first token"
    assert terminal_frame == "data: [DONE]"
    assert trailing == ""
    assert completion_calls == []
    assert dummy_db.metric_calls == [
        {
            "log_id": 61,
            "request_id": None,
            "model_id": 27,
            "provider_id": 12,
            "result_status": "error",
            "error_message": "failed to record first token",
        }
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal_error", ["connection reset", ""], ids=["message", "empty-message"])
async def test_proxy_streaming_terminal_error_is_recorded(monkeypatch, terminal_error):
    dummy_db = _make_dummy_db()
    monkeypatch.setattr(main, "DBManager", dummy_db)

    pipeline, _, _ = _make_pipeline(
        stream_chunks=[b'{"message":{"content":"partial"}}\n'],
        terminal_status_error=terminal_error,
    )
    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)

    response = main._proxy_streaming_response(
        "http://proxy",
        {"Authorization": "Bearer x"},
        {"stream": True},
        44,
        7,
        9,
        -1,
        {"classified": True},
    )
    await _read_stream_response(response)

    assert dummy_db.metric_calls == [
        {
            "log_id": 44,
            "provider_id": 7,
            "model_id": 9,
            "result_status": "error",
            "error_message": terminal_error,
        }
    ]


@pytest.mark.asyncio
async def test_sync_response_error_skips_ttft_and_records_error(monkeypatch):
    dummy_db = _make_dummy_db()
    monkeypatch.setattr(main, "DBManager", dummy_db)
    monkeypatch.setattr(
        main,
        "_context_resolver",
        SimpleNamespace(prepare_headers_and_payload=lambda context, payload: ({}, payload)),
        raising=False,
    )

    pipeline, completion_calls, release_calls = _make_pipeline(
        sync_result=ExecutionResult(
            success=False,
            response={"error": "bad request"},
            error="bad request",
            usage={},
            is_streaming=False,
            headers=None,
        )
    )
    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)

    response = await main._sync_response(
        SimpleNamespace(provider_type="cloud", forward_url="http://cloud"),
        {"messages": [{"role": "user", "content": "bad"}]},
        55,
        1,
        10,
        -1,
        {"classified": True},
        {
            "request_id": "req-sync-error",
            "provider_type": "cloud",
            "queue_depth_at_arrival": 0,
            "utilization_at_arrival": 0.5,
            "is_cold_start": False,
        },
    )

    assert response.status_code == 500
    assert response.headers["x-request-id"] == "req-sync-error"
    assert dummy_db.ttft_calls == []
    assert dummy_db.payload_calls[0]["payload"] == {"error": "bad request"}
    assert completion_calls == [
        {
            "request_id": "req-sync-error",
            "result_status": "error",
            "error_message": "bad request",
            "cold_start": False,
            # An error body carries no usage, so nothing was extracted.
            "usage_tokens": {},
        }
    ]
    assert release_calls == [(10, 1, "cloud", "req-sync-error")]


@pytest.mark.asyncio
async def test_sync_response_async_job_success_logs_usage(monkeypatch):
    dummy_db = _make_dummy_db()
    monkeypatch.setattr(main, "DBManager", dummy_db)
    monkeypatch.setattr(
        main,
        "_context_resolver",
        SimpleNamespace(prepare_headers_and_payload=lambda context, payload: ({}, payload)),
        raising=False,
    )

    pipeline, completion_calls, release_calls = _make_pipeline(
        sync_result=ExecutionResult(
            success=True,
            response={
                "id": "job-1",
                "usage": {
                    "prompt_tokens": 11,
                    "completion_tokens": 13,
                    "total_tokens": 24,
                },
                "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            },
            error=None,
            usage={},
            is_streaming=False,
            headers=None,
        )
    )
    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)

    result = await main._sync_response(
        SimpleNamespace(provider_type="cloud", forward_url="http://cloud"),
        {"messages": [{"role": "user", "content": "job"}]},
        56,
        1,
        10,
        -1,
        {"classified": True},
        {
            "request_id": "req-job",
            "provider_type": "cloud",
            "queue_depth_at_arrival": 0,
            "utilization_at_arrival": 0.25,
            "is_cold_start": True,
        },
        is_async_job=True,
    )

    assert result["status_code"] == 200
    assert dummy_db.ttft_calls == [56]
    assert dummy_db.payload_calls[0]["usage"] == {
        "prompt_tokens": 11,
        "completion_tokens": 13,
        "total_tokens": 24,
    }
    assert completion_calls == [
        {
            "request_id": "req-job",
            "result_status": "success",
            "error_message": None,
            "cold_start": True,
            "usage_tokens": {
                "prompt_tokens": 11,
                "completion_tokens": 13,
                "total_tokens": 24,
            },
        }
    ]
    assert release_calls == [(10, 1, "cloud", "req-job")]


@pytest.mark.asyncio
async def test_sync_response_async_job_base64_encodes_binary_body(monkeypatch):
    dummy_db = _make_dummy_db()
    monkeypatch.setattr(main, "DBManager", dummy_db)
    monkeypatch.setattr(
        main,
        "_context_resolver",
        SimpleNamespace(prepare_headers_and_payload=lambda context, payload: ({}, payload)),
        raising=False,
    )

    pipeline, _, _ = _make_pipeline(
        sync_result=ExecutionResult(
            success=True,
            response=None,
            error=None,
            usage={},
            is_streaming=False,
            headers={"content-type": "application/octet-stream"},
            status_code=200,
            raw_body=b"ID3",
            content_type="audio/mpeg",
        )
    )
    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)

    result = await main._sync_response(
        SimpleNamespace(provider_type="cloud", forward_url="http://cloud"),
        {"model": "audio-binary-model"},
        58,
        1,
        10,
        -1,
        {"classified": True},
        is_async_job=True,
        request_path="v1/audio/transcriptions",
    )

    assert result == {
        "status_code": 200,
        "data": {
            "content_base64": "SUQz",
            "content_type": "audio/mpeg",
            "encoding": "base64",
        },
    }


@pytest.mark.asyncio
async def test_sync_response_async_job_preserves_binary_logosnode_body(monkeypatch):
    dummy_db = _make_dummy_db()
    monkeypatch.setattr(main, "DBManager", dummy_db)
    monkeypatch.setattr(
        main,
        "_context_resolver",
        SimpleNamespace(prepare_headers_and_payload=lambda context, payload: ({}, payload)),
        raising=False,
    )
    monkeypatch.setattr(
        main,
        "_logosnode_registry",
        SimpleNamespace(
            send_command=AsyncMock(
                return_value={
                    "status_code": 200,
                    "body": None,
                    "body_base64": "/wBJRDM=",
                    "body_encoding": "base64",
                    "headers": {"content-type": "audio/mpeg"},
                }
            )
        ),
        raising=False,
    )
    pipeline, _, _ = _make_pipeline()
    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)

    result = await main._sync_response(
        SimpleNamespace(
            provider_type="logosnode",
            lane_id="lane-a",
            model_name="audio-binary-model",
        ),
        {
            "model": "audio-binary-model",
            "_logos_multipart": {
                "fields": [["model", "audio-binary-model"]],
                "files": [],
            },
        },
        59,
        12,
        10,
        -1,
        {"classified": True},
        is_async_job=True,
        request_path="v1/audio/transcriptions",
    )

    assert result == {
        "status_code": 200,
        "data": {
            "content_base64": "/wBJRDM=",
            "content_type": "audio/mpeg",
            "encoding": "base64",
        },
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "binary_metadata",
    [
        {"body_encoding": "base64"},
        {"body_encoding": "hex", "body_base64": "/wBJRDM="},
    ],
)
async def test_sync_response_rejects_invalid_logosnode_binary_metadata(monkeypatch, binary_metadata):
    dummy_db = _make_dummy_db()
    monkeypatch.setattr(main, "DBManager", dummy_db)
    monkeypatch.setattr(
        main,
        "_context_resolver",
        SimpleNamespace(prepare_headers_and_payload=lambda context, payload: ({}, payload)),
        raising=False,
    )
    monkeypatch.setattr(
        main,
        "_logosnode_registry",
        SimpleNamespace(
            send_command=AsyncMock(
                return_value={
                    "status_code": 200,
                    "body": None,
                    "headers": {"content-type": "audio/mpeg"},
                    **binary_metadata,
                }
            )
        ),
        raising=False,
    )
    pipeline, _, _ = _make_pipeline()
    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)

    result = await main._sync_response(
        SimpleNamespace(provider_type="logosnode", lane_id="lane-a", model_name="audio-binary-model"),
        {"model": "audio-binary-model"},
        60,
        12,
        10,
        -1,
        {"classified": True},
        is_async_job=True,
        request_path="v1/audio/transcriptions",
    )

    assert result["status_code"] == 502
    assert "invalid binary response metadata" in str(result["data"])


@pytest.mark.asyncio
async def test_sync_local_worker_translation_does_not_add_stream_field(monkeypatch):
    dummy_db = _make_dummy_db()
    monkeypatch.setattr(main, "DBManager", dummy_db)
    monkeypatch.setattr(
        main,
        "_context_resolver",
        SimpleNamespace(prepare_headers_and_payload=lambda context, payload: ({}, payload)),
        raising=False,
    )
    sent_params = None

    async def send_command(**kwargs):
        nonlocal sent_params
        sent_params = kwargs["params"]
        return {
            "status_code": 200,
            "body": {"text": "translated"},
            "headers": {"content-type": "application/json"},
        }

    monkeypatch.setattr(
        main,
        "_logosnode_registry",
        SimpleNamespace(send_command=send_command),
        raising=False,
    )
    pipeline, _, _ = _make_pipeline()
    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)

    result = await main._sync_response(
        SimpleNamespace(provider_type="logosnode", lane_id="lane-a", model_name="audio-translation-model"),
        {
            "model": "audio-translation-model",
            "_logos_multipart": {
                "fields": [["model", "audio-translation-model"]],
                "files": [],
            },
        },
        61,
        12,
        10,
        -1,
        {"classified": True},
        is_async_job=True,
        request_path="v1/audio/translations",
    )

    assert result == {"status_code": 200, "data": {"text": "translated"}}
    assert sent_params is not None
    assert "stream" not in sent_params["payload"]
    assert all(field[0] != "stream" for field in sent_params["payload"]["_logos_multipart"]["fields"])


@pytest.mark.asyncio
@pytest.mark.parametrize("is_async_job", [False, True])
async def test_sync_whisper_text_uses_metered_verbose_response(monkeypatch, is_async_job):
    dummy_db = _make_dummy_db()
    monkeypatch.setattr(main, "DBManager", dummy_db)
    monkeypatch.setattr(
        main,
        "_context_resolver",
        SimpleNamespace(prepare_headers_and_payload=lambda context, payload: ({}, payload)),
        raising=False,
    )

    sync_payloads = []
    pipeline, _, _ = _make_pipeline(
        sync_result=ExecutionResult(
            success=True,
            response={
                "text": "transcribed",
                "duration": 1.25,
                "segments": [{"start": 0, "end": 1.25, "text": "transcribed"}],
            },
            error=None,
            usage={},
            is_streaming=False,
            headers={"content-type": "application/json"},
            status_code=200,
        ),
        sync_payloads=sync_payloads,
    )
    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)
    payload = {
        "model": "whisper-1",
        "response_format": "text",
        "_logos_multipart": {
            "fields": [["model", "whisper-1"], ["response_format", "text"]],
            "files": [],
        },
    }

    response = await main._sync_response(
        SimpleNamespace(provider_type="cloud", forward_url="http://cloud"),
        payload,
        57,
        1,
        10,
        -1,
        {"classified": True},
        is_async_job=is_async_job,
        request_path="v1/audio/transcriptions",
    )

    if is_async_job:
        assert response == {"status_code": 200, "data": "transcribed"}
    else:
        assert response.body == b"transcribed"
        assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert sync_payloads[0]["response_format"] == "verbose_json"
    assert ["response_format", "verbose_json"] in sync_payloads[0]["_logos_multipart"]["fields"]
    assert dummy_db.payload_calls[0]["usage"] == {"audio_milliseconds": 1250}


@pytest.mark.asyncio
@pytest.mark.parametrize("is_async_job", [False, True])
@pytest.mark.parametrize("response_format", [None, "json"])
async def test_sync_whisper_json_uses_metered_verbose_response(monkeypatch, is_async_job, response_format):
    dummy_db = _make_dummy_db()
    monkeypatch.setattr(main, "DBManager", dummy_db)
    monkeypatch.setattr(
        main,
        "_context_resolver",
        SimpleNamespace(prepare_headers_and_payload=lambda context, payload: ({}, payload)),
        raising=False,
    )

    sync_payloads = []
    pipeline, _, _ = _make_pipeline(
        sync_result=ExecutionResult(
            success=True,
            response={"text": "transcribed", "duration": 1.25},
            error=None,
            usage={},
            is_streaming=False,
            headers={"content-type": "application/json"},
            status_code=200,
        ),
        sync_payloads=sync_payloads,
    )
    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)
    fields = [["model", "whisper-1"]]
    payload = {
        "model": "whisper-1",
        "_logos_multipart": {"fields": fields, "files": []},
    }
    if response_format is not None:
        payload["response_format"] = response_format
        fields.append(["response_format", response_format])

    response = await main._sync_response(
        SimpleNamespace(provider_type="cloud", forward_url="http://cloud"),
        payload,
        57,
        1,
        10,
        -1,
        {"classified": True},
        is_async_job=is_async_job,
        request_path="v1/audio/transcriptions",
    )

    if is_async_job:
        assert response == {"status_code": 200, "data": {"text": "transcribed"}}
    else:
        assert json.loads(response.body) == {"text": "transcribed"}
        assert response.headers["content-type"] == "application/json"
    assert sync_payloads[0]["response_format"] == "verbose_json"
    assert ["response_format", "verbose_json"] in sync_payloads[0]["_logos_multipart"]["fields"]
    assert dummy_db.payload_calls[0]["usage"] == {"audio_milliseconds": 1250}


@pytest.mark.asyncio
async def test_sync_whisper_rejects_unmetered_raw_upstream_response(monkeypatch):
    monkeypatch.setattr(
        main,
        "_context_resolver",
        SimpleNamespace(prepare_headers_and_payload=lambda context, payload: ({}, payload)),
        raising=False,
    )
    pipeline, _, _ = _make_pipeline(
        sync_result=ExecutionResult(
            success=True,
            response="unmetered raw text",
            error=None,
            usage={},
            is_streaming=False,
            headers={"content-type": "text/plain"},
            status_code=200,
            raw_body=b"unmetered raw text",
            content_type="text/plain",
        )
    )
    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)

    response = await main._sync_response(
        SimpleNamespace(provider_type="cloud", forward_url="http://cloud"),
        {
            "model": "whisper-1",
            "response_format": "text",
            "_logos_multipart": {
                "fields": [["model", "whisper-1"], ["response_format", "text"]],
                "files": [],
            },
        },
        None,
        1,
        10,
        -1,
        {"classified": True},
        request_path="v1/audio/transcriptions",
    )

    assert response.status_code == 502
    assert "Expected a verbose JSON transcription response" in json.loads(response.body)["error"]["message"]


@pytest.mark.asyncio
async def test_proxy_sync_response_logs_status_and_skips_ttft_on_error(monkeypatch):
    dummy_db = _make_dummy_db()
    monkeypatch.setattr(main, "DBManager", dummy_db)

    pipeline, _, _ = _make_pipeline(
        sync_result=ExecutionResult(
            success=False,
            response={"error": "proxy failed"},
            error="proxy failed",
            usage={},
            is_streaming=False,
            headers=None,
        )
    )
    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)

    response = await main._proxy_sync_response(
        "http://proxy",
        {"Authorization": "Bearer x"},
        {"messages": [{"role": "user", "content": "x"}]},
        57,
        7,
        9,
        -1,
        {"classified": True},
        is_async_job=False,
        request_id="req-proxy-sync",
    )

    assert response.status_code == 500
    assert response.headers["x-request-id"] == "req-proxy-sync"
    assert dummy_db.ttft_calls == []
    assert dummy_db.metric_calls == [
        {
            "log_id": 57,
            "provider_id": 7,
            "model_id": 9,
            "result_status": "error",
            "error_message": "proxy failed",
        }
    ]


# ---------------------------------------------------------------------------
# _log_request_completion — prefix-cache hit rate field (issue 748)
# ---------------------------------------------------------------------------


def _completion_log_line(monkeypatch, caplog, usage, status="success"):
    """Run _log_request_completion and return the emitted INFO line (ANSI-stripped)."""
    monkeypatch.setattr(main, "model_name_cache", {"get": lambda model_id: "test-model"})
    with caplog.at_level(logging.INFO, logger="LogosLogger"):
        main._log_request_completion(
            model_id=1,
            request_id="req-1",
            start_time=time.perf_counter() - 1.0,
            usage=usage,
            status=status,
            is_streaming=False,
        )
    lines = [record.getMessage() for record in caplog.records if "done " in record.getMessage()]
    return strip_ansi(lines[-1]) if lines else ""


def test_log_request_completion_includes_prefix_hit_rate(monkeypatch, caplog):
    """Flattened usage (prompt_cached_tokens) → prefix_hit=NN% on the log line."""
    line = _completion_log_line(
        monkeypatch,
        caplog,
        {"prompt_tokens": 1000, "completion_tokens": 100, "prompt_cached_tokens": 420},
    )
    assert "prefix_hit=42%" in line


def test_log_request_completion_includes_prefix_hit_rate_from_nested_details(monkeypatch, caplog):
    """Raw streaming usage (prompt_tokens_details.cached_tokens) is also reported."""
    line = _completion_log_line(
        monkeypatch,
        caplog,
        {
            "prompt_tokens": 1000,
            "completion_tokens": 100,
            "prompt_tokens_details": {"cached_tokens": 750},
        },
    )
    assert "prefix_hit=75%" in line


def test_log_request_completion_includes_zero_prefix_hit(monkeypatch, caplog):
    """An explicit cached_tokens=0 is a real 0% hit, not 'not reported'."""
    line = _completion_log_line(
        monkeypatch,
        caplog,
        {"prompt_tokens": 1000, "completion_tokens": 100, "prompt_cached_tokens": 0},
    )
    assert "prefix_hit=0%" in line


def test_log_request_completion_omits_prefix_hit_when_unreported(monkeypatch, caplog):
    """Providers that do not report cached tokens add no prefix_hit field."""
    line = _completion_log_line(
        monkeypatch,
        caplog,
        {"prompt_tokens": 1000, "completion_tokens": 100},
    )
    assert "prefix_hit" not in line
