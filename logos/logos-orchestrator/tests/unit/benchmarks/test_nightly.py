import asyncio
from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from starlette.responses import JSONResponse, StreamingResponse

from logos.benchmarks import nightly
from logos.benchmarks.progress import observe_response


@pytest.mark.parametrize(
    "timestamp, expected",
    [
        ("2026-10-13T02:59:59+02:00", False),
        ("2026-10-13T03:00:00+02:00", True),
        ("2026-10-13T04:49:59+02:00", True),
        ("2026-10-13T04:50:00+02:00", False),
        ("2026-10-13T05:00:00+02:00", False),
        ("2026-10-13T01:00:00+00:00", True),
        ("2026-12-13T02:00:00+00:00", True),
        ("2026-03-29T01:00:00+00:00", True),
        ("2026-10-25T02:00:00+00:00", True),
        ("2026-10-25T01:30:00+00:00", False),
    ],
)
def test_admission_window(timestamp, expected):
    assert nightly.can_start(datetime.fromisoformat(timestamp)) is expected


def test_naive_clock_rejected():
    with pytest.raises(ValueError):
        nightly.can_start(datetime(2026, 10, 13, 3))


@pytest.fixture
def policy_clock(monkeypatch):
    monkeypatch.setattr(nightly, "POLL_SECONDS", 0)
    monkeypatch.setattr(nightly, "local_now", lambda: datetime.fromisoformat("2026-10-13T05:00:00+02:00"))


@pytest.mark.parametrize("completed", [0, 24])
async def test_cutoff_cancels_below_half_and_awaits_cleanup(policy_clock, completed):
    cleaned = []

    async def execute():
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            cleaned.append(True)

    progress = nightly.RunProgress(50, completed=completed, measuring=True)
    with pytest.raises(nightly.NightlyStopped, match="window_closed_below_half"):
        await nightly.supervise(execute, progress, lambda: True)
    assert cleaned == [True]


@pytest.mark.parametrize("completed", [25, 49])
async def test_half_complete_run_finishes_after_five(policy_clock, completed):
    async def execute():
        for _ in range(5):
            await asyncio.sleep(0)
        return 17

    assert (
        await nightly.supervise(execute, nightly.RunProgress(50, completed=completed, measuring=True), lambda: True)
        == 17
    )


@pytest.mark.parametrize("measuring, last, reason", [(True, -301, "stalled"), (False, -901, "preparation_timeout")])
async def test_watchdogs_cancel_even_during_overrun(policy_clock, measuring, last, reason):
    progress = nightly.RunProgress(50, completed=25, measuring=measuring)
    progress.last_progress += last
    progress.phase_started += last
    with pytest.raises(nightly.NightlyStopped, match=reason):
        await nightly.supervise(lambda: asyncio.Event().wait(), progress, lambda: True)


async def test_disabled_cancels_even_half_complete(policy_clock):
    with pytest.raises(nightly.NightlyStopped, match="disabled"):
        await nightly.supervise(lambda: asyncio.Event().wait(), nightly.RunProgress(50, completed=25), lambda: False)


async def test_external_cancellation_propagates(policy_clock):
    with pytest.raises(asyncio.CancelledError):
        await nightly.supervise(AsyncMock(side_effect=asyncio.CancelledError), nightly.RunProgress(50), lambda: True)


async def test_sse_heartbeats_are_not_progress_and_finish_count_is_once():
    progress = nightly.RunProgress(50, measuring=True)
    progress.last_progress = -1
    nightly.PROGRESS[7] = progress

    async def chunks():
        yield b": heartbeat\n\n"
        assert progress.last_progress == -1
        yield b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'
        assert progress.last_progress > 0
        assert progress.completed == 0
        yield b'data: {"choices":[{"finish_reason":"stop"}]}\n\n'
        yield b"data: [DONE]\n\n"

    try:
        response = observe_response(StreamingResponse(chunks()), 7)
        async for _ in response.body_iterator:
            pass
        assert progress.completed == 1
    finally:
        nightly.PROGRESS.pop(7)


async def test_failed_or_truncated_stream_does_not_count_as_complete():
    progress = nightly.RunProgress(50, measuring=True)
    nightly.PROGRESS[7] = progress

    async def chunks():
        yield b'data: {"error":{"message":"failed"}}\n\n'

    try:
        response = observe_response(StreamingResponse(chunks()), 7)
        async for _ in response.body_iterator:
            pass
        assert progress.completed == 0
        observe_response(JSONResponse({"error": "failure"}, status_code=500), 7)
        assert progress.completed == 0
    finally:
        nightly.PROGRESS.pop(7)


def test_parameter_plan_changes_only_one_known_parameter_and_fixes_workload():
    plan = nightly.parameter_plan({"max_num_seqs": 16, "max_num_batched_tokens": 4096})
    assert len(plan) == 5
    baseline = plan[0].serving_overrides.model_dump(exclude_none=True)
    for run in plan[1:]:
        changed = run.serving_overrides.model_dump(exclude_none=True)
        assert sum(changed[key] != baseline[key] for key in baseline) == 1
        assert run.model_dump(exclude={"serving_overrides"}) == plan[0].model_dump(exclude={"serving_overrides"})
    assert plan[0].samples == 50
    assert plan[0].max_output_tokens == 512


def test_unknown_batching_settings_only_run_baseline():
    assert len(nightly.parameter_plan({})) == 1
