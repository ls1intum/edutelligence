from types import SimpleNamespace

import pytest

import logos.main as main
from logos.pipeline.executor import ExecutionResult


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
    completion_calls=None,
    release_calls=None,
):
    completion_calls = completion_calls if completion_calls is not None else []
    release_calls = release_calls if release_calls is not None else []

    class DummyExecutor:
        async def execute_sync(self, url, headers, payload):  # noqa: ARG002
            return sync_result

        async def execute_streaming(self, url, headers, payload, on_headers=None):  # noqa: ARG002
            if on_headers:
                on_headers({})
            for chunk in stream_chunks or []:
                yield chunk

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

    response = main._streaming_response(
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
    )
    body = await _read_stream_response(response)

    assert "data: [DONE]" in body
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
                "usage": {"prompt_tokens": 11, "completion_tokens": 13, "total_tokens": 24},
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
    )

    assert response.status_code == 500
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
