import asyncio
from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from logos.benchmarks import nightly
from logos.benchmarks.configuration import BenchmarkBatch, BenchmarkRunSettings


@pytest.mark.parametrize(
    "timestamp, expected",
    [
        ("2026-10-13T02:59:59+02:00", 0),
        ("2026-10-13T03:00:00+02:00", 7200),
        ("2026-10-13T04:30:00+02:00", 1800),
        ("2026-10-13T04:59:59+02:00", 1),
        ("2026-10-13T05:00:00+02:00", 0),
        ("2026-10-13T23:00:00+02:00", 0),
        ("2026-10-13T01:00:00+00:00", 7200),
        ("2026-12-13T02:00:00+00:00", 7200),
        ("2026-03-29T01:00:00+00:00", 7200),
        ("2026-10-25T02:00:00+00:00", 7200),
        ("2026-10-25T01:30:00+00:00", 0),
    ],
)
def test_window_boundaries_and_daylight_saving(timestamp, expected):
    assert nightly.remaining_window_seconds(datetime.fromisoformat(timestamp)) == expected


def test_naive_clock_is_rejected():
    with pytest.raises(ValueError, match="timezone"):
        nightly.remaining_window_seconds(datetime(2026, 10, 13, 3))


async def test_outside_window_does_not_start_a_run(monkeypatch):
    monkeypatch.setattr(nightly, "remaining_window_seconds", lambda now: 0)
    execute = AsyncMock()
    batch = BenchmarkBatch(configurations=[BenchmarkRunSettings()])
    assert await nightly.run_nightly_benchmark_batch(batch, execute) is False
    execute.assert_not_awaited()


async def test_runs_are_sequential_and_keep_generation_settings(monkeypatch):
    monkeypatch.setattr(nightly, "remaining_window_seconds", lambda now: 7200)
    settings = BenchmarkRunSettings(max_output_tokens=512)
    batch = BenchmarkBatch(configurations=[settings], repetitions=2)
    execute = AsyncMock(side_effect=[11, 12])
    assert await nightly.run_nightly_benchmark_batch(batch, execute) is True
    assert [call.args[1]["run_index"] for call in execute.await_args_list] == [1, 2]
    assert [call.args[2] for call in execute.await_args_list] == [False, True]
    assert all(call.args[0].max_output_tokens == 512 for call in execute.await_args_list)


async def test_deadline_cancels_active_run_and_waits_for_cleanup(monkeypatch):
    monkeypatch.setattr(nightly, "remaining_window_seconds", lambda now: 0.01)
    cleaned_up = asyncio.Event()

    async def execute(*args):
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            cleaned_up.set()

    callback = AsyncMock(side_effect=execute)
    batch = BenchmarkBatch(configurations=[BenchmarkRunSettings()], repetitions=2)
    with pytest.raises(TimeoutError):
        await nightly.run_nightly_benchmark_batch(batch, callback)
    assert cleaned_up.is_set()
    assert callback.await_count == 1


async def test_external_cancellation_propagates(monkeypatch):
    monkeypatch.setattr(nightly, "remaining_window_seconds", lambda now: 7200)
    callback = AsyncMock(side_effect=asyncio.CancelledError)
    batch = BenchmarkBatch(configurations=[BenchmarkRunSettings()], repetitions=2)
    with pytest.raises(asyncio.CancelledError):
        await nightly.run_nightly_benchmark_batch(batch, callback)
    assert callback.await_count == 1
