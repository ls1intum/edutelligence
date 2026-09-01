"""Internal retry loop and stream-resume helpers in the request funnel
(#815): failed requests are re-dispatched within a bounded budget, pinned to
their model, excluding the node that just failed."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.responses import JSONResponse, StreamingResponse

import logos as main
from logos.queue.models import Priority

DEPLOYMENTS = [
    {"model_id": 27, "provider_id": 1, "type": "logosnode"},
    {"model_id": 27, "provider_id": 2, "type": "logosnode"},
]


class _FakeDB:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _fail_result(error, request_id="req-1", model_id=27, provider_id=1):
    return SimpleNamespace(
        success=False,
        error=error,
        model_id=model_id,
        provider_id=provider_id,
        execution_context=None,
        classification_stats={},
        scheduling_stats={"request_id": request_id, "model_id": model_id, "provider_id": provider_id},
    )


def _ok_result(request_id="req-1", model_id=27, provider_id=2, provider_type="logosnode"):
    return SimpleNamespace(
        success=True,
        error=None,
        model_id=model_id,
        provider_id=provider_id,
        execution_context=SimpleNamespace(model_name="stub-model"),
        classification_stats={},
        scheduling_stats={
            "request_id": request_id,
            "model_id": model_id,
            "provider_id": provider_id,
            "provider_type": provider_type,
        },
    )


class _FakePipeline:
    """Scripted pipeline: each process() call returns the next result."""

    def __init__(self, results):
        self.results = list(results)
        self.requests = []
        self.scheduler = MagicMock()

    async def process(self, request):
        self.requests.append(request)
        if not self.results:
            raise AssertionError("pipeline.process called more times than scripted")
        return self.results.pop(0)

    def record_completion(self, **kwargs):  # noqa: ARG002
        return None


def _auth():
    return SimpleNamespace(key_value="lg-key", default_priority=0, api_key_id=None, cloud_rl=None, local_rl=None)


@pytest.fixture
def retry_env(monkeypatch):
    """Wire _execute_resource_mode's collaborators to fakes and zero the
    backoff so retry loops run instantly."""
    monkeypatch.setattr(main, "DBManager", lambda: _FakeDB())
    monkeypatch.setattr(main, "_check_budget_if_cloud", lambda *a, **k: None)
    monkeypatch.setattr(main, "_extract_policy", lambda headers, key_value, body: {})
    monkeypatch.setattr(main, "_record_log_failure", lambda *a, **k: None)
    monkeypatch.setattr(main, "_REQUEST_RETRY_BACKOFF_BASE_S", 0.0)
    monkeypatch.setattr(main, "_REQUEST_RETRY_BACKOFF_CAP_S", 0.0)
    return monkeypatch


def _run_sync_response(retry_env, results, sync_responses, **kwargs):
    """Drive _execute_resource_mode with scripted pipeline + sync responses."""
    pipeline = _FakePipeline(results)
    retry_env.setattr(main, "_pipeline", pipeline, raising=False)

    responses = list(sync_responses)
    pipeline.sync_calls = []

    async def fake_sync(
        context, payload, log_id, provider_id, model_id, policy_id, classification_stats, scheduling_stats, **kw
    ):
        assert responses, "_sync_response called more times than scripted"
        pipeline.sync_calls.append(kw)
        return responses.pop(0)

    retry_env.setattr(main, "_sync_response", fake_sync)
    return pipeline


class _FakeRateLimiter:
    """Records the (bucket, config) pairs it was checked with; rejects the
    buckets named in ``rejected`` like a rate-limited caller would be."""

    def __init__(self, rejected=()):
        self.checks = []
        self.rejected = set(rejected)

    def check_and_record(self, key, config):
        self.checks.append((key, config))
        if key in self.rejected:
            return False, "RPM limit reached"
        return True, ""


def _auth_with_rl(api_key_id=1):
    return SimpleNamespace(
        key_value="lg-key",
        default_priority=0,
        api_key_id=api_key_id,
        cloud_rl={"rpm": 10, "tpm": 1000},
        local_rl={"rpm": 5, "tpm": 5000},
    )


# ---------------------------------------------------------------------------
# Scheduling-failure retries (wait-mode timeout, no capacity, lane never ready)
# ---------------------------------------------------------------------------


async def test_retryable_scheduling_failure_is_retried_and_succeeds(retry_env):
    pipeline = _run_sync_response(
        retry_env,
        results=[
            _fail_result("All candidate models unavailable (rate-limited or no capacity)", provider_id=1),
            _ok_result(provider_id=2),
        ],
        sync_responses=[JSONResponse(content={"ok": True}, status_code=200)],
    )

    response = await main._execute_resource_mode(
        deployments=DEPLOYMENTS,
        body={"messages": [{"role": "user", "content": "hi"}]},
        headers={},
        auth=_auth(),
        log_id=None,
        is_async_job=False,
        request_id="req-1",
    )

    assert response.status_code == 200
    assert len(pipeline.requests) == 2
    retry_req = pipeline.requests[1]
    # The retry keeps the model the request already had and excludes the node
    # that just failed it; a plain retry keeps its original priority.
    assert retry_req.pinned_model_id == 27
    assert retry_req.exclude_provider_ids == frozenset({1})
    assert retry_req.priority_override is None
    assert retry_req.request_id == "req-1"
    assert retry_req.context_resolve_timeout_s is not None


async def test_non_retryable_scheduling_failure_fails_immediately(retry_env):
    pipeline = _run_sync_response(
        retry_env,
        results=[_fail_result("No models passed classification")],
        sync_responses=[],
    )

    with pytest.raises(main.HTTPException) as exc:
        await main._execute_resource_mode(
            deployments=DEPLOYMENTS,
            body={},
            headers={},
            auth=_auth(),
            log_id=None,
            is_async_job=False,
            request_id="req-1",
        )

    assert exc.value.status_code == 503
    assert len(pipeline.requests) == 1


async def test_scheduling_failure_not_retried_when_budget_disabled(retry_env):
    retry_env.setattr(main, "_REQUEST_MAX_ATTEMPTS", 1)  # retry budget off
    pipeline = _run_sync_response(
        retry_env,
        results=[_fail_result("Failed to resolve execution context: lane not ready after 600s")],
        sync_responses=[],
    )

    result = await main._execute_resource_mode(
        deployments=DEPLOYMENTS,
        body={},
        headers={},
        auth=_auth(),
        log_id=None,
        is_async_job=True,
        request_id="req-1",
    )

    assert result["status_code"] == 503
    assert len(pipeline.requests) == 1


async def test_queue_wait_timeout_is_not_internally_retried(retry_env):
    """A queue-wait timeout says the queue is saturated, not that a node is
    broken: re-queueing under the same pressure cannot help, so the timeout
    goes back to the caller — which backs off on its own terms (and sees a
    429 + Retry-After once the queue-wait overload response lands) instead
    of being silently re-queued by the platform."""
    pipeline = _run_sync_response(
        retry_env,
        results=[_fail_result("Queue wait timeout after 1200s", provider_id=1)],
        sync_responses=[],
    )

    with pytest.raises(main.HTTPException) as exc:
        await main._execute_resource_mode(
            deployments=DEPLOYMENTS,
            body={},
            headers={},
            auth=_auth(),
            log_id=None,
            is_async_job=False,
            request_id="req-1",
        )

    assert exc.value.status_code == 503
    assert "Queue wait timeout" in exc.value.detail
    assert len(pipeline.requests) == 1


# ---------------------------------------------------------------------------
# Terminal-status retries (execution failed with a transient HTTP status)
# ---------------------------------------------------------------------------


async def test_retryable_terminal_status_is_retried(retry_env):
    pipeline = _run_sync_response(
        retry_env,
        results=[_ok_result(provider_id=1), _ok_result(provider_id=2)],
        sync_responses=[
            JSONResponse(content={"error": "worker gone"}, status_code=503),
            JSONResponse(content={"ok": True}, status_code=200),
        ],
    )

    response = await main._execute_resource_mode(
        deployments=DEPLOYMENTS,
        body={},
        headers={},
        auth=_auth(),
        log_id=None,
        is_async_job=False,
        request_id="req-1",
    )

    assert response.status_code == 200
    assert len(pipeline.requests) == 2
    assert pipeline.requests[1].pinned_model_id == 27
    assert pipeline.requests[1].exclude_provider_ids == frozenset({1})


async def test_non_retryable_terminal_status_is_not_retried(retry_env):
    pipeline = _run_sync_response(
        retry_env,
        results=[_ok_result(provider_id=1)],
        sync_responses=[JSONResponse(content={"error": "bad payload"}, status_code=400)],
    )

    response = await main._execute_resource_mode(
        deployments=DEPLOYMENTS,
        body={},
        headers={},
        auth=_auth(),
        log_id=None,
        is_async_job=False,
        request_id="req-1",
    )

    assert response.status_code == 400
    assert len(pipeline.requests) == 1


async def test_retryable_terminal_status_exhausts_the_budget(retry_env):
    pipeline = _run_sync_response(
        retry_env,
        results=[_ok_result(provider_id=1), _ok_result(provider_id=2), _ok_result(provider_id=1)],
        sync_responses=[
            JSONResponse(content={"error": "boom"}, status_code=502),
            JSONResponse(content={"error": "boom"}, status_code=502),
            JSONResponse(content={"error": "boom"}, status_code=502),
        ],
    )

    response = await main._execute_resource_mode(
        deployments=DEPLOYMENTS,
        body={},
        headers={},
        auth=_auth(),
        log_id=None,
        is_async_job=False,
        request_id="req-1",
    )

    # max_attempts=3 (default): three dispatches, then the raw error is
    # returned — the budget is bounded.
    assert response.status_code == 502
    assert len(pipeline.requests) == 3
    # Each retry excludes every node that failed so far.
    assert pipeline.requests[1].exclude_provider_ids == frozenset({1})
    assert pipeline.requests[2].exclude_provider_ids == frozenset({1, 2})


async def test_committed_streaming_response_is_never_retried(retry_env):
    """A committed stream has no terminal status; its failures recover inside
    the stream (pre-token JSON error / resume), not in the outer loop."""
    pipeline = _run_sync_response(
        retry_env,
        results=[_ok_result(provider_id=1)],
        sync_responses=[],
    )
    stream = StreamingResponse(iter([b"data: x\n\n"]), media_type="text/event-stream")

    async def fake_stream(*args, **kw):
        return stream

    retry_env.setattr(main, "_streaming_response", fake_stream)

    response = await main._execute_resource_mode(
        deployments=DEPLOYMENTS,
        body={"stream": True, "messages": []},
        headers={},
        auth=_auth(),
        log_id=None,
        is_async_job=False,
        request_id="req-1",
    )

    assert response is stream
    assert len(pipeline.requests) == 1


async def test_async_job_dict_terminal_status_is_retried(retry_env):
    pipeline = _run_sync_response(
        retry_env,
        results=[_ok_result(provider_id=1), _ok_result(provider_id=2)],
        sync_responses=[
            {"status_code": 503, "data": {"error": "worker gone"}},
            {"status_code": 200, "data": {"ok": True}},
        ],
    )

    result = await main._execute_resource_mode(
        deployments=DEPLOYMENTS,
        body={},
        headers={},
        auth=_auth(),
        log_id=None,
        is_async_job=True,
        request_id="req-1",
    )

    assert result == {"status_code": 200, "data": {"ok": True}}
    assert len(pipeline.requests) == 2


# ---------------------------------------------------------------------------
# Rate-limit bucket + cloud budget follow the provider type the attempt
# actually runs on
# ---------------------------------------------------------------------------


async def test_failover_to_cloud_reselects_bucket_and_reruns_budget_check(retry_env):
    """The bucket and the budget check are properties of WHERE the request
    runs: a local→cloud failover must charge the cloud bucket (so this
    attempt's tokens are recorded against the cloud limit, not the local
    bucket from the first attempt) and re-run the cloud budget check — a key
    over its monthly cloud budget must not gain cloud capacity through a
    failover."""
    import logos.rate_limiter as rl_module

    limiter = _FakeRateLimiter()
    retry_env.setattr(rl_module, "get_rate_limiter", lambda: limiter)
    budget_calls = []
    retry_env.setattr(main, "_check_budget_if_cloud", lambda db, auth, is_cloud, month: budget_calls.append(is_cloud))

    pipeline = _run_sync_response(
        retry_env,
        results=[
            _ok_result(provider_id=1, provider_type="logosnode"),
            _ok_result(provider_id=2, provider_type="cloud"),
        ],
        sync_responses=[
            JSONResponse(content={"error": "worker gone"}, status_code=502),
            JSONResponse(content={"ok": True}, status_code=200),
        ],
    )

    response = await main._execute_resource_mode(
        deployments=DEPLOYMENTS,
        body={},
        headers={},
        auth=_auth_with_rl(),
        log_id=None,
        is_async_job=False,
        request_id="req-1",
    )

    assert response.status_code == 200
    # One rate-limit hit per provider type the request was dispatched to,
    # against the right bucket each time.
    assert [key for key, _ in limiter.checks] == ["api_key:1:local", "api_key:1:cloud"]
    # The budget check followed the provider type as well.
    assert budget_calls == [False, True]
    # The attempt that actually ran records its tokens against the cloud
    # bucket, not the local bucket of the failed first attempt.
    assert pipeline.sync_calls[0]["rl_key"] == "api_key:1:local"
    assert pipeline.sync_calls[1]["rl_key"] == "api_key:1:cloud"


async def test_same_provider_retry_does_not_recharge_the_bucket(retry_env):
    """A retry on the provider type the request was already charged to must
    not count a second rate-limit hit — a retry must never trip the
    caller's own limit."""
    import logos.rate_limiter as rl_module

    limiter = _FakeRateLimiter()
    retry_env.setattr(rl_module, "get_rate_limiter", lambda: limiter)
    budget_calls = []
    retry_env.setattr(main, "_check_budget_if_cloud", lambda db, auth, is_cloud, month: budget_calls.append(is_cloud))

    pipeline = _run_sync_response(
        retry_env,
        results=[_ok_result(provider_id=1), _ok_result(provider_id=2)],
        sync_responses=[
            JSONResponse(content={"error": "worker gone"}, status_code=502),
            JSONResponse(content={"ok": True}, status_code=200),
        ],
    )

    response = await main._execute_resource_mode(
        deployments=DEPLOYMENTS,
        body={},
        headers={},
        auth=_auth_with_rl(),
        log_id=None,
        is_async_job=False,
        request_id="req-1",
    )

    assert response.status_code == 200
    # Same provider type on both attempts: exactly one rate-limit hit total.
    assert [key for key, _ in limiter.checks] == ["api_key:1:local"]
    assert pipeline.sync_calls[0]["rl_key"] == "api_key:1:local"
    assert pipeline.sync_calls[1]["rl_key"] == "api_key:1:local"


async def test_azure_to_cloud_failover_charges_the_cloud_bucket_once(retry_env):
    """A failover between two *cloud* provider types (azure -> cloud)
    re-selects the same rate-limit bucket, so the request must be charged
    exactly once — not once per provider type. ``rl_key`` (local/cloud) is
    coarser than ``provider_type`` (azure, cloud, ...), so keying the dedup on
    the bucket rather than the provider type is what stops a single request
    from consuming two rpm slots on the platform's own failure and tripping
    the caller's limit."""
    import logos.rate_limiter as rl_module

    limiter = _FakeRateLimiter()
    retry_env.setattr(rl_module, "get_rate_limiter", lambda: limiter)
    budget_calls = []
    retry_env.setattr(main, "_check_budget_if_cloud", lambda db, auth, is_cloud, month: budget_calls.append(is_cloud))

    pipeline = _run_sync_response(
        retry_env,
        results=[
            _ok_result(provider_id=1, provider_type="azure"),
            _ok_result(provider_id=2, provider_type="cloud"),
        ],
        sync_responses=[
            JSONResponse(content={"error": "worker gone"}, status_code=502),
            JSONResponse(content={"ok": True}, status_code=200),
        ],
    )

    response = await main._execute_resource_mode(
        deployments=DEPLOYMENTS,
        body={},
        headers={},
        auth=_auth_with_rl(),
        log_id=None,
        is_async_job=False,
        request_id="req-1",
    )

    assert response.status_code == 200
    # Both attempts land in the cloud bucket (azure and cloud are not local),
    # so the request is charged once — the second attempt re-selects a bucket
    # it was already charged to. (Deduping by provider_type would charge it
    # twice, once per type.)
    assert [key for key, _ in limiter.checks] == ["api_key:1:cloud"]
    assert len(limiter.checks) == 1
    # Both attempts are cloud for budget purposes.
    assert budget_calls == [True, True]
    assert pipeline.sync_calls[0]["rl_key"] == "api_key:1:cloud"
    assert pipeline.sync_calls[1]["rl_key"] == "api_key:1:cloud"


async def test_failover_into_exhausted_bucket_is_rejected(retry_env):
    """If the bucket the failover re-selects is already exhausted, the
    request is rejected against THAT bucket — with the attempt's slot
    released — instead of running over the caller's limit."""
    import logos.rate_limiter as rl_module

    limiter = _FakeRateLimiter(rejected={"api_key:1:cloud"})
    retry_env.setattr(rl_module, "get_rate_limiter", lambda: limiter)

    pipeline = _run_sync_response(
        retry_env,
        results=[_ok_result(provider_id=1), _ok_result(provider_id=2, provider_type="cloud")],
        sync_responses=[JSONResponse(content={"error": "worker gone"}, status_code=502)],
    )

    with pytest.raises(main.HTTPException) as exc:
        await main._execute_resource_mode(
            deployments=DEPLOYMENTS,
            body={},
            headers={},
            auth=_auth_with_rl(),
            log_id=None,
            is_async_job=False,
            request_id="req-1",
        )

    assert exc.value.status_code == 429
    assert [key for key, _ in limiter.checks] == ["api_key:1:local", "api_key:1:cloud"]
    # The slot of the attempt that was rejected is released again.
    pipeline.scheduler.release.assert_called_once_with(27, 2, "cloud", "req-1")


# ---------------------------------------------------------------------------
# Resume payload / terminal-status helpers
# ---------------------------------------------------------------------------


def test_build_resume_payload_appends_partial_answer_as_assistant_message():
    base = {"messages": [{"role": "user", "content": "hi"}], "temperature": 0.2}
    out = main._build_resume_payload(base, "partial answer")

    assert out is not None
    assert out["messages"] == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "partial answer"},
    ]
    assert out["temperature"] == 0.2
    # The vLLM continuation contract keeps the trailing assistant message
    # open so the engine continues the prefix instead of opening a fresh
    # turn to answer it.
    assert out["continue_final_message"] is True
    assert out["add_generation_prompt"] is False
    # The original payload is not mutated.
    assert len(base["messages"]) == 1


def test_build_resume_payload_refuses_an_explicit_limit_without_an_exact_figure():
    # A caller that capped its completion cannot be held under that cap by a
    # character estimate: the failed stream never reports its final usage and
    # the serving model's tokenizer is not on hand to count the prefix. Refuse
    # rather than let the combined answer overshoot the cap — but resume once
    # the engine's own count is known.
    base = {"messages": [{"role": "user", "content": "hi"}], "max_tokens": 100}
    assert main._build_resume_payload(base, "partial answer") is None
    out = main._build_resume_payload(base, "partial answer", streamed_completion_tokens=40)
    assert out is not None and out["max_tokens"] == 60


@pytest.mark.parametrize(
    "limit_key",
    ["max_tokens", "max_completion_tokens", "max_output_tokens"],
)
def test_build_resume_payload_shrinks_the_completion_budget_by_the_streamed_prefix(limit_key):
    base = {"messages": [{"role": "user", "content": "hi"}], limit_key: 100}
    out = main._build_resume_payload(base, "partial answer", streamed_completion_tokens=40)

    assert out is not None
    assert out[limit_key] == 60


def test_build_resume_payload_refuses_when_the_prefix_filled_the_budget():
    base = {"messages": [{"role": "user", "content": "hi"}], "max_tokens": 100}
    # 100 requested, 100 already streamed: there is nothing left to generate.
    assert main._build_resume_payload(base, "partial answer", streamed_completion_tokens=100) is None
    assert main._build_resume_payload(base, "partial answer", streamed_completion_tokens=140) is None


@pytest.mark.parametrize(
    "base, prefix",
    [
        ({"prompt": "hi"}, "partial"),  # not a chat payload
        ({"messages": []}, "partial"),  # nothing to continue from
        ({"messages": [{"role": "user", "content": "hi"}]}, ""),  # no prefix delivered
        ({"messages": [{"role": "user", "content": "hi"}], "n": 2}, "partial"),  # parallel candidates
        (
            {"messages": [{"role": "user", "content": "hi"}], "response_format": {"type": "json_object"}},
            "partial",
        ),  # structured output cannot be continued
    ],
)
def test_build_resume_payload_rejects_inexpressible_continuations(base, prefix):
    assert main._build_resume_payload(base, prefix) is None


def test_response_terminal_status():
    assert main._response_terminal_status({"status_code": 503, "data": {}}) == 503
    assert main._response_terminal_status(JSONResponse(content={}, status_code=200)) == 200
    assert main._response_terminal_status(StreamingResponse(iter([]), media_type="text/event-stream")) is None


# ---------------------------------------------------------------------------
# _schedule_stream_resume (phase 2 re-dispatch at RESUME priority)
# ---------------------------------------------------------------------------


def _resume_pipeline(result):
    pipeline = _FakePipeline([result])
    return pipeline


def _result_with_context(ctx):
    return SimpleNamespace(
        success=True,
        error=None,
        model_id=ctx.model_id,
        provider_id=ctx.provider_id,
        execution_context=ctx,
        classification_stats={},
        scheduling_stats={"request_id": "req-1"},
    )


async def test_schedule_stream_resume_returns_logosnode_context(retry_env):
    ctx = SimpleNamespace(model_id=27, provider_id=2, provider_type="logosnode", lane_id="lane-2", engine="vllm")
    pipeline = _resume_pipeline(_result_with_context(ctx))
    retry_env.setattr(main, "_pipeline", pipeline, raising=False)

    clock_t = [1000.0]
    budget = main.RetryBudget(max_attempts=3, deadline_s=100.0, now=lambda: clock_t[0])

    out = await main._schedule_stream_resume(
        request_id="req-1",
        model_id=27,
        failed_provider_id=1,
        deployments=DEPLOYMENTS,
        resume_payload={"messages": [{"role": "assistant", "content": "partial"}], "stream": True},
        request_path="v1/chat/completions",
        policy=None,
        default_priority=0,
        api_key_id=None,
        budget=budget,
    )

    assert out is ctx
    req = pipeline.requests[0]
    # Resume is the absolute highest priority and skips re-classification.
    assert req.priority_override == Priority.RESUME.value
    assert req.pinned_model_id == 27
    assert req.skip_laura is True
    assert req.exclude_provider_ids == frozenset({1})
    assert req.context_resolve_timeout_s is not None
    # The budget recorded the failed node for further failover.
    assert budget.failed_provider_ids == [1]


async def test_schedule_stream_resume_none_when_budget_exhausted(retry_env):
    pipeline = _resume_pipeline(_ok_result())
    retry_env.setattr(main, "_pipeline", pipeline, raising=False)

    budget = main.RetryBudget(max_attempts=1, deadline_s=100.0, now=lambda: 1000.0)

    out = await main._schedule_stream_resume(
        request_id="req-1",
        model_id=27,
        failed_provider_id=1,
        deployments=DEPLOYMENTS,
        resume_payload={"messages": []},
        request_path=None,
        policy=None,
        default_priority=0,
        api_key_id=None,
        budget=budget,
    )

    assert out is None
    assert pipeline.requests == []  # nothing was re-queued


async def test_schedule_stream_resume_none_when_scheduling_fails(retry_env):
    pipeline = _resume_pipeline(_fail_result("All candidate models unavailable (rate-limited or no capacity)"))
    retry_env.setattr(main, "_pipeline", pipeline, raising=False)

    budget = main.RetryBudget(max_attempts=3, deadline_s=100.0, now=lambda: 1000.0)

    out = await main._schedule_stream_resume(
        request_id="req-1",
        model_id=27,
        failed_provider_id=1,
        deployments=DEPLOYMENTS,
        resume_payload={"messages": []},
        request_path=None,
        policy=None,
        default_priority=0,
        api_key_id=None,
        budget=budget,
    )

    assert out is None


async def test_schedule_stream_resume_rejects_non_logosnode_takeover(retry_env):
    """A cloud deployment would restart the answer from scratch — only a local
    lane can continue after the partial prefix, so the slot is released and
    None comes back."""
    ctx = SimpleNamespace(model_id=27, provider_id=9, provider_type="cloud", lane_id=None, engine=None)
    pipeline = _resume_pipeline(_result_with_context(ctx))
    retry_env.setattr(main, "_pipeline", pipeline, raising=False)

    budget = main.RetryBudget(max_attempts=3, deadline_s=100.0, now=lambda: 1000.0)

    out = await main._schedule_stream_resume(
        request_id="req-1",
        model_id=27,
        failed_provider_id=1,
        deployments=DEPLOYMENTS,
        resume_payload={"messages": []},
        request_path=None,
        policy=None,
        default_priority=0,
        api_key_id=None,
        budget=budget,
    )

    assert out is None
    pipeline.scheduler.release.assert_called_once_with(27, 9, "cloud", "req-1")


async def test_schedule_stream_resume_rejects_non_vllm_lane_takeover(retry_env):
    """An Ollama lane cannot keep the partial assistant message open — the
    takeover would start a second, full answer — so it is refused the same
    way a cloud placement is: slot released, None back."""
    ctx = SimpleNamespace(model_id=27, provider_id=9, provider_type="logosnode", lane_id="lane-9", engine="ollama")
    pipeline = _resume_pipeline(_result_with_context(ctx))
    retry_env.setattr(main, "_pipeline", pipeline, raising=False)

    budget = main.RetryBudget(max_attempts=3, deadline_s=100.0, now=lambda: 1000.0)

    out = await main._schedule_stream_resume(
        request_id="req-1",
        model_id=27,
        failed_provider_id=1,
        deployments=DEPLOYMENTS,
        resume_payload={"messages": []},
        request_path=None,
        policy=None,
        default_priority=0,
        api_key_id=None,
        budget=budget,
    )

    assert out is None
    pipeline.scheduler.release.assert_called_once_with(27, 9, "logosnode", "req-1")


# ---------------------------------------------------------------------------
# Pre-token failures surface as JSON errors before commit (#815 phase 1)
# ---------------------------------------------------------------------------


async def test_logosnode_pre_token_failure_comes_back_as_json_error(retry_env):
    """Pulling the first chunk before the response is committed is what makes
    a pre-token failure a proper JSON error the outer loop can retry
    cross-node, instead of a broken 200 stream that can only end in an error
    frame."""
    from tests.unit.main.test_request_logging import _make_dummy_db

    from logos.logosnode_registry import LogosNodeOfflineError
    from logos.pipeline.retry import status_is_retryable

    async def broken_send_stream_command(**kwargs):  # noqa: ARG001
        raise LogosNodeOfflineError("worker session dropped")
        yield b""  # unreachable; makes this an async generator

    retry_env.setattr(main, "DBManager", _make_dummy_db())
    retry_env.setattr(
        main,
        "_context_resolver",
        SimpleNamespace(prepare_headers_and_payload=lambda context, payload: ({}, payload)),
        raising=False,
    )
    retry_env.setattr(
        main,
        "_logosnode_registry",
        SimpleNamespace(send_stream_command=broken_send_stream_command),
        raising=False,
    )
    retry_env.setattr(main, "_LOGOSNODE_PRETOKEN_RETRIES", 0)
    retry_env.setattr(main, "_LOGOSNODE_PRETOKEN_RETRY_BACKOFF_S", 0.0)
    retry_env.setattr(main, "_pipeline", _FakePipeline([_fail_result("unused")]), raising=False)

    response = await main._streaming_response(
        SimpleNamespace(provider_id=12, provider_type="logosnode", lane_id="lane-1"),
        {"messages": [{"role": "user", "content": "hi"}]},
        42,
        12,
        27,
        -1,
        {"policy": "ok"},
        {
            "request_id": "req-pretoken",
            "provider_type": "logosnode",
            "queue_depth_at_arrival": 0,
            "utilization_at_arrival": 1,
            "is_cold_start": False,
        },
    )

    # A JSONResponse (not a StreamingResponse) with a retryable status — the
    # outer loop re-dispatches it to a peer node serving the same model.
    assert isinstance(response, JSONResponse)
    assert response.status_code == 502
    assert status_is_retryable(response.status_code)
