import json
from types import SimpleNamespace

import pytest

import logos as main
from logos import ExecutionResult
from logos.errors import UpstreamStreamError


def _make_dummy_db():
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
    stream_body_error=None,
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
            if stream_body_error:
                raise stream_body_error
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
        }
    ]
    assert release_calls == [(27, 12, "logosnode", "req-stream")]


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
        }
    ]
    assert completion_logs[0]["status"] == "error"
    assert release_calls == [(27, 12, "cloud", "req-mid-stream-error")]


@pytest.mark.asyncio
async def test_http_ndjson_response_preserves_content_type_and_does_not_append_sse_on_failure(monkeypatch):
    dummy_db = _make_dummy_db()
    monkeypatch.setattr(main, "DBManager", dummy_db)
    monkeypatch.setattr(
        main,
        "_context_resolver",
        SimpleNamespace(prepare_headers_and_payload=lambda context, payload: ({}, payload)),
        raising=False,
    )

    partial = b'{"message":{"content":"partial"}}\n'
    pipeline, completion_calls, _ = _make_pipeline(
        stream_chunks=[partial],
        stream_body_error=RuntimeError("connection reset"),
        stream_headers={"Content-Type": "application/x-ndjson"},
    )
    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)

    response = await main._streaming_response(
        SimpleNamespace(provider_type="local", forward_url="http://ollama:11434/api/chat"),
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
            "error_message": "connection reset",
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
        }
    ]
    assert release_calls == [(10, 1, "cloud", "req-job")]


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
