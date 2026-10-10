"""One resend after an upstream rejects the reasoning effort.

An upstream whose chat template accepts only part of the effort scale fails
the request before the first token, naming the levels it supports. Every
forwarding path — logosnode and cloud, streaming and sync (jobs go through
sync) — resends the request once with the effort rewritten onto those levels,
so the client gets the answer instead of the error. Any other upstream error
behaves exactly as before.
"""

from types import SimpleNamespace

import pytest
from tests.unit.main.test_request_logging import _make_dummy_db, _make_pipeline, _read_stream_response

import logos as main
from logos import ExecutionResult
from logos.errors import UpstreamStreamError
from logos.pipeline.effort_normalization import effort_scale_for_model, forget_learned_effort_scales

MODEL = "openai/gpt-oss-120b"
HARMONY = (
    "reasoning_effort='xhigh' is not supported by Harmony. Supported values are: high, medium, low. "
    "(parameter=reasoning_effort)"
)
REJECTION_BODY = {"error": {"message": HARMONY, "type": "BadRequestError", "code": 400}}
OTHER_ERROR_BODY = {"error": {"message": "This model's maximum context length is 32768 tokens.", "code": 400}}
PAYLOAD = {"model": MODEL, "messages": [{"role": "user", "content": "hi"}], "reasoning_effort": "xhigh"}
ANSWER_CHUNKS = [
    b'data: {"id":"c1","choices":[{"delta":{"content":"hello"}}]}\n\n',
    b'data: {"id":"c1","choices":[],"usage":{"prompt_tokens":3,"completion_tokens":1,"total_tokens":4}}\n\n',
    b"data: [DONE]\n\n",
]
SCHEDULING = {
    "request_id": "req-effort",
    "queue_depth_at_arrival": 0,
    "utilization_at_arrival": 1,
    "is_cold_start": False,
}


@pytest.fixture(autouse=True)
def _environment(monkeypatch):
    forget_learned_effort_scales()
    monkeypatch.setattr(main, "DBManager", _make_dummy_db())
    monkeypatch.setattr(
        main,
        "_context_resolver",
        SimpleNamespace(prepare_headers_and_payload=lambda context, payload: ({}, payload)),
        raising=False,
    )
    monkeypatch.setattr(main, "_LOGOSNODE_PRETOKEN_RETRY_BACKOFF_S", 0, raising=False)
    yield
    forget_learned_effort_scales()


def _context(provider_type):
    return SimpleNamespace(
        provider_type=provider_type,
        lane_id="lane-1" if provider_type == "logosnode" else None,
        provider_id=12,
        model_name=MODEL,
        anthropic_dialect=None,
        messages_upstream=False,
        forward_url="https://provider.test/v1/chat/completions",
    )


def _scheduling(provider_type):
    return {**SCHEDULING, "provider_type": provider_type}


# ── logosnode, streaming ─────────────────────────────────────────────────────


def _install_logosnode_stream(monkeypatch, first_error_body):
    sent = []

    async def fake_send_stream_command(**kwargs):
        sent.append(kwargs["params"]["payload"])
        if len(sent) == 1:
            # An upstream error status: the registry buffers the body and
            # surfaces it as an UpstreamStreamError before any chunk.
            raise UpstreamStreamError(400, first_error_body)
            yield b""  # pragma: no cover - marks this an async generator
        for chunk in ANSWER_CHUNKS:
            yield chunk

    monkeypatch.setattr(
        main, "_logosnode_registry", SimpleNamespace(send_stream_command=fake_send_stream_command), raising=False
    )
    pipeline, completion_calls, release_calls = _make_pipeline()
    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)
    return sent, completion_calls, release_calls


@pytest.mark.asyncio
async def test_logosnode_stream_resends_once_with_the_effort_adapted(monkeypatch):
    sent, completion_calls, release_calls = _install_logosnode_stream(monkeypatch, REJECTION_BODY)

    response = await main._streaming_response(
        _context("logosnode"), dict(PAYLOAD), 42, 12, 27, -1, {}, _scheduling("logosnode")
    )
    body = await _read_stream_response(response)

    assert [payload["reasoning_effort"] for payload in sent] == ["xhigh", "high"]
    # The rejection never reached the client; the answer did.
    assert "Harmony" not in body
    assert "hello" in body
    assert [call["result_status"] for call in completion_calls] == ["success"]
    assert release_calls == [(27, 12, "logosnode", "req-effort")]
    # The scale is learned, so later requests are normalized before they go out.
    assert effort_scale_for_model(MODEL) is not None


@pytest.mark.asyncio
async def test_logosnode_stream_forwards_any_other_error_body_as_before(monkeypatch):
    sent, completion_calls, _r = _install_logosnode_stream(monkeypatch, OTHER_ERROR_BODY)

    response = await main._streaming_response(
        _context("logosnode"), dict(PAYLOAD), 42, 12, 27, -1, {}, _scheduling("logosnode")
    )

    # Answered before the stream is committed, so the internal retry can still
    # decide from the real status.
    assert response.status_code == 400
    assert len(sent) == 1
    assert effort_scale_for_model(MODEL) is None
    assert [call["result_status"] for call in completion_calls] == ["error"]


# ── cloud, streaming ─────────────────────────────────────────────────────────


class _FailingOnceExecutor:
    """An executor whose first call fails with ``first_error`` and second call answers."""

    def __init__(self, first_error_body):
        self.first_error_body = first_error_body
        self.payloads = []
        self.bounds = []

    async def execute_streaming(
        self, url, headers, payload, on_headers=None, status=None, timeout=None, deadline_at=None, **_kwargs
    ):  # noqa: ARG002
        self.payloads.append(payload)
        self.bounds.append((timeout, deadline_at))
        if status is not None:
            status.dispatch_at = main.datetime.datetime.now(main.datetime.timezone.utc)
        if on_headers:
            on_headers({"content-type": "text/event-stream"})
        if len(self.payloads) == 1:
            raise UpstreamStreamError(400, self.first_error_body)
        for chunk in ANSWER_CHUNKS:
            yield chunk

    async def execute_sync(self, url, headers, payload, timeout=None, deadline_at=None):  # noqa: ARG002
        self.payloads.append(payload)
        self.bounds.append((timeout, deadline_at))
        if len(self.payloads) == 1:
            return ExecutionResult(
                success=False,
                response=self.first_error_body,
                error=self.first_error_body["error"],
                usage={},
                is_streaming=False,
                headers=None,
                status_code=400,
            )
        return ExecutionResult(
            success=True,
            response={"choices": [{"message": {"content": "hello"}}]},
            error=None,
            usage={},
            is_streaming=False,
            headers=None,
            status_code=200,
        )


def _install_cloud(monkeypatch, first_error_body):
    pipeline, completion_calls, release_calls = _make_pipeline()
    executor = _FailingOnceExecutor(first_error_body)
    pipeline.executor = executor
    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)
    return executor, completion_calls, release_calls


@pytest.mark.asyncio
async def test_cloud_stream_resends_once_with_the_effort_adapted(monkeypatch):
    executor, completion_calls, release_calls = _install_cloud(monkeypatch, REJECTION_BODY)

    response = await main._streaming_response(
        _context("cloud"), dict(PAYLOAD), 42, 12, 27, -1, {}, _scheduling("cloud")
    )
    body = await _read_stream_response(response)

    assert [payload["reasoning_effort"] for payload in executor.payloads] == ["xhigh", "high"]
    assert "hello" in body
    assert [call["result_status"] for call in completion_calls] == ["success"]
    assert release_calls == [(27, 12, "cloud", "req-effort")]


@pytest.mark.asyncio
async def test_cloud_stream_answers_any_other_error_as_before(monkeypatch):
    executor, completion_calls, release_calls = _install_cloud(monkeypatch, OTHER_ERROR_BODY)

    response = await main._streaming_response(
        _context("cloud"), dict(PAYLOAD), 42, 12, 27, -1, {}, _scheduling("cloud")
    )

    assert len(executor.payloads) == 1
    assert response.status_code == 400
    assert [call["result_status"] for call in completion_calls] == ["error"]
    assert release_calls == [(27, 12, "cloud", "req-effort")]


# ── sync (and with it every async job) ───────────────────────────────────────


class _FakeWriteQueueFactory:
    def get_write_queue(self):
        return SimpleNamespace(enqueue=lambda *args, **kwargs: None)


@pytest.mark.asyncio
async def test_cloud_sync_resends_once_with_the_effort_adapted(monkeypatch):
    executor, completion_calls, _r = _install_cloud(monkeypatch, REJECTION_BODY)
    monkeypatch.setattr(main, "write_queue", _FakeWriteQueueFactory(), raising=False)

    response = await main._sync_response(_context("cloud"), dict(PAYLOAD), 42, 12, 27, -1, {}, _scheduling("cloud"))

    assert [payload["reasoning_effort"] for payload in executor.payloads] == ["xhigh", "high"]
    assert response.status_code == 200
    assert [call["result_status"] for call in completion_calls] == ["success"]


@pytest.mark.asyncio
async def test_cloud_sync_answers_any_other_error_as_before(monkeypatch):
    executor, _c, _r = _install_cloud(monkeypatch, OTHER_ERROR_BODY)
    monkeypatch.setattr(main, "write_queue", _FakeWriteQueueFactory(), raising=False)

    response = await main._sync_response(_context("cloud"), dict(PAYLOAD), 42, 12, 27, -1, {}, _scheduling("cloud"))

    assert len(executor.payloads) == 1
    assert response.status_code == 400


@pytest.mark.parametrize(
    ("first_body", "expected_efforts", "expected_status"),
    [
        (REJECTION_BODY, ["xhigh", "high"], 200),
        # vLLM's older flat error shape carries the message at the top level.
        ({"object": "error", "message": HARMONY, "code": 400}, ["xhigh", "high"], 200),
        (OTHER_ERROR_BODY, ["xhigh"], 400),
    ],
    ids=["rejection", "flat-rejection", "other-error"],
)
@pytest.mark.asyncio
async def test_logosnode_sync_resends_once_only_for_an_effort_rejection(
    monkeypatch, first_body, expected_efforts, expected_status
):
    sent = []

    async def fake_send_command(**kwargs):
        sent.append(kwargs["params"]["payload"])
        if len(sent) == 1:
            return {"status_code": 400, "body": first_body, "headers": {}}
        return {"status_code": 200, "body": {"choices": [{"message": {"content": "hello"}}]}, "headers": {}}

    monkeypatch.setattr(main, "_logosnode_registry", SimpleNamespace(send_command=fake_send_command), raising=False)
    monkeypatch.setattr(main, "write_queue", _FakeWriteQueueFactory(), raising=False)
    pipeline, _c, _r = _make_pipeline()
    monkeypatch.setattr(main, "_pipeline", pipeline, raising=False)

    response = await main._sync_response(
        _context("logosnode"), dict(PAYLOAD), 42, 12, 27, -1, {}, _scheduling("logosnode")
    )

    assert [payload["reasoning_effort"] for payload in sent] == expected_efforts
    assert response.status_code == expected_status


RESPONSES_PAYLOAD = {"model": MODEL, "input": "hi", "reasoning": {"effort": "xhigh", "summary": "auto"}}


@pytest.mark.asyncio
async def test_cloud_sync_resends_a_responses_request_with_the_effort_adapted(monkeypatch):
    executor, completion_calls, _r = _install_cloud(monkeypatch, REJECTION_BODY)
    monkeypatch.setattr(main, "write_queue", _FakeWriteQueueFactory(), raising=False)

    response = await main._sync_response(
        _context("cloud"), dict(RESPONSES_PAYLOAD), 42, 12, 27, -1, {}, _scheduling("cloud")
    )

    assert [payload["reasoning"] for payload in executor.payloads] == [
        {"effort": "xhigh", "summary": "auto"},
        {"effort": "high", "summary": "auto"},
    ]
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_cloud_stream_resends_a_responses_request_with_the_effort_adapted(monkeypatch):
    executor, completion_calls, _r = _install_cloud(monkeypatch, REJECTION_BODY)

    response = await main._streaming_response(
        _context("cloud"), dict(RESPONSES_PAYLOAD), 42, 12, 27, -1, {}, _scheduling("cloud")
    )
    await _read_stream_response(response)

    assert [payload["reasoning"]["effort"] for payload in executor.payloads] == ["xhigh", "high"]
    assert [call["result_status"] for call in completion_calls] == ["success"]


# ── the resend keeps the retry deadline ──────────────────────────────────────


def _spent_attempt_budget():
    from logos.pipeline.retry import RetryBudget

    budget = RetryBudget(max_attempts=3, deadline_s=30.0)
    budget.attempts = 1  # a retry: bounded by the deadline instead of unbounded
    return budget


@pytest.mark.asyncio
async def test_cloud_stream_resend_keeps_the_retry_deadline(monkeypatch):
    executor, _c, _r = _install_cloud(monkeypatch, REJECTION_BODY)
    budget = _spent_attempt_budget()

    response = await main._streaming_response(
        _context("cloud"), dict(PAYLOAD), 42, 12, 27, -1, {}, _scheduling("cloud"), retry_budget=budget
    )
    await _read_stream_response(response)

    assert len(executor.bounds) == 2
    assert all(deadline == budget.deadline_at and timeout is not None for timeout, deadline in executor.bounds)


@pytest.mark.asyncio
async def test_cloud_sync_resend_keeps_the_retry_deadline(monkeypatch):
    executor, _c, _r = _install_cloud(monkeypatch, REJECTION_BODY)
    monkeypatch.setattr(main, "write_queue", _FakeWriteQueueFactory(), raising=False)
    budget = _spent_attempt_budget()

    await main._sync_response(
        _context("cloud"), dict(PAYLOAD), 42, 12, 27, -1, {}, _scheduling("cloud"), retry_budget=budget
    )

    assert len(executor.bounds) == 2
    assert all(deadline == budget.deadline_at and timeout is not None for timeout, deadline in executor.bounds)
