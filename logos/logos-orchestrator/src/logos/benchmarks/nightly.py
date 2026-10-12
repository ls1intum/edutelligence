"""Time-window guard for sequential nightly benchmark batches."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from logos.benchmarks.batch_runner import run_benchmark_batch
from logos.benchmarks.configuration import BenchmarkBatch, BenchmarkRunSettings


def remaining_window_seconds(now: datetime) -> float:
    """Return the remaining 03:00–05:00 Europe/Berlin window, or zero.

    The start is inclusive and the end exclusive. Require an aware timestamp
    so the host timezone cannot silently change the benchmark schedule.
    """
    if now.utcoffset() is None:
        raise ValueError("The benchmark clock must include a timezone")
    local = now.astimezone(ZoneInfo("Europe/Berlin"))
    if not time(3) <= local.time() < time(5):
        return 0.0
    end = local.replace(hour=5, minute=0, second=0, microsecond=0)
    return (end.astimezone(timezone.utc) - now.astimezone(timezone.utc)).total_seconds()


async def run_nightly_benchmark_batch(
    batch: BenchmarkBatch,
    execute_run: Callable[[BenchmarkRunSettings, dict[str, int], bool], Awaitable[int | None]],
) -> bool:
    """Run a batch within the current window; return False when outside it.

    The caller owns provider selection, isolation and lease cleanup. At the
    window deadline, cancel the active callback and raise TimeoutError after
    its cancellation cleanup completes. External cancellation propagates.
    A True return means the batch was admitted, not that every run succeeded.
    """
    remaining = remaining_window_seconds(datetime.now(timezone.utc))
    if remaining <= 0:
        return False
    async with asyncio.timeout(remaining):
        await run_benchmark_batch(batch, execute_run)
    return True
