"""Nightly admission, progress and bounded recovery policy."""

import asyncio
import time as clock
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from logos.benchmarks.configuration import BenchmarkRunSettings, ServingOverrides
from logos.maintenance_window import MaintenanceWindow

NIGHTLY_CONTEXT: ContextVar[bool] = ContextVar("nightly_benchmark", default=False)
LEASE_CHECK: ContextVar[Callable[[], bool]] = ContextVar("nightly_lease_check", default=lambda: True)
STALL_SECONDS = 300
PREPARATION_SECONDS = 900
POLL_SECONDS = 1
MAX_PAIRS_PER_NIGHT = 2


def local_now() -> datetime:
    return datetime.now(timezone.utc).astimezone(ZoneInfo(MaintenanceWindow.from_env().timezone))


def can_start(now: datetime) -> bool:
    """Admit configurations until 10 minutes before the shared window ends."""
    return MaintenanceWindow.from_env().can_start_benchmark(now)


@dataclass
class RunProgress:
    """Only output content and successful measured requests advance progress."""

    total: int
    completed: int = 0
    measuring: bool = False
    last_progress: float = field(default_factory=clock.monotonic)
    phase_started: float = field(default_factory=clock.monotonic)

    def start_measurement(self) -> None:
        self.measuring = True
        self.last_progress = clock.monotonic()
        self.phase_started = self.last_progress

    def output(self) -> None:
        self.last_progress = clock.monotonic()

    def finish(self) -> None:
        self.completed += 1
        self.output()


PROGRESS: dict[int, RunProgress] = {}


class NightlyStopped(RuntimeError):
    """A run was stopped by nightly policy."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


async def supervise(
    execute: Callable[[], Awaitable[int | None]],
    progress: RunProgress,
    enabled: Callable[[], bool],
) -> int | None:
    """Cancel on inactivity, disable or a less-than-half-complete maintenance cutoff.

    The cutoff decision is made once for the current run. A permitted overrun
    still has the inactivity watchdog and the runner's existing total timeout.
    Cancellation is awaited before returning control to node cleanup.
    """
    cutoff = MaintenanceWindow.from_env().bounds(local_now())[1]
    task = asyncio.create_task(execute())
    cutoff_checked = False
    try:
        while not task.done():
            done, _ = await asyncio.wait({task}, timeout=POLL_SECONDS)
            if done:
                break
            now = local_now()
            reason = None
            if not LEASE_CHECK.get()():
                reason = "lease_lost"
            elif not enabled():
                reason = "disabled"
            elif not progress.measuring and clock.monotonic() - progress.phase_started >= PREPARATION_SECONDS:
                reason = "preparation_timeout"
            elif progress.measuring and clock.monotonic() - progress.last_progress >= STALL_SECONDS:
                reason = "stalled"
            elif not cutoff_checked and now >= cutoff:
                cutoff_checked = True
                if not progress.measuring or progress.completed * 2 < progress.total:
                    reason = "window_closed_below_half"
            if reason:
                raise NightlyStopped(reason)
        return await task
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def parameter_plan(current: dict) -> list[BenchmarkRunSettings]:
    """Compare current settings with at most four explicit batching configurations."""
    baseline = {
        key: int(current[key])
        for key in ("max_num_seqs", "max_num_batched_tokens")
        if isinstance(current.get(key), int) and current[key] > 0
    }
    values = [baseline]
    if len(baseline) < 2:
        # Auto values are not effective limits. Keep the baseline unchanged,
        # then set both limits explicitly so variants cannot inherit each other.
        seqs = [baseline["max_num_seqs"]] if "max_num_seqs" in baseline else [4, 8]
        tokens = [baseline["max_num_batched_tokens"]] if "max_num_batched_tokens" in baseline else [2048, 4096]
        values = [{}] + [
            {"max_num_seqs": seq, "max_num_batched_tokens": token} for seq in seqs for token in tokens if token >= seq
        ]
    for key, value in baseline.items() if len(baseline) == 2 else []:
        for factor in (0.75, 1.25):
            candidate = {**baseline, key: max(1, int(value * factor))}
            if key == "max_num_seqs" and candidate[key] > 65536:
                continue
            if candidate.get("max_num_batched_tokens", 65536) < candidate.get("max_num_seqs", 1):
                continue
            if candidate not in values:
                values.append(candidate)
    return [
        BenchmarkRunSettings(
            samples=50,
            max_output_tokens=512,
            profile="concurrent",
            concurrency=4,
            serving_overrides=ServingOverrides(**value),
        )
        for value in values
    ]
