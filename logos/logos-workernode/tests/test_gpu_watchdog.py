"""Tests for the GPU wedge watchdog state machine.

These exercise ``record_tick()`` directly with a fake reboot function so
the test process never actually risks calling ``reboot(2)``. The async
``start()`` / ``_poll_loop()`` plumbing is tested separately with a
mocked health function and a small sleep.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest
from logos_worker_node.gpu_watchdog import GpuWatchdog
from logos_worker_node.node_health import NodeHealthStatus


def _gpu_failure(reason: str = "gpu-error", detail: str = "synthetic") -> NodeHealthStatus:
    return NodeHealthStatus(
        healthy=False,
        checked_at="2026-06-05T12:00:00Z",
        sensors={"gpu": {"state": reason, "detail": detail}},
        reason_code=reason,
        reason_detail=detail,
    )


def _healthy() -> NodeHealthStatus:
    return NodeHealthStatus(
        healthy=True,
        checked_at="2026-06-05T12:00:00Z",
        sensors={"gpu": {"state": "ok", "detail": ""}},
        reason_code=None,
        reason_detail=None,
    )


def _non_gpu_failure() -> NodeHealthStatus:
    return NodeHealthStatus(
        healthy=False,
        checked_at="2026-06-05T12:00:00Z",
        sensors={"storage": {"state": "filesystem-eio", "detail": "EIO"}},
        reason_code="filesystem-eio",
        reason_detail="EIO on /mnt/cache",
    )


def _make_watchdog(
    tmp_path: Path,
    *,
    threshold: int = 3,
    rate_limit: float = 30 * 60,
    startup_grace: float = 0.0,
) -> tuple[GpuWatchdog, list[bool]]:
    """Build a watchdog wired with a no-op reboot fn. Returns the watchdog
    and a list that captures each reboot invocation."""
    reboots: list[bool] = []

    def fake_reboot() -> None:
        reboots.append(True)

    wd = GpuWatchdog(
        state_dir=tmp_path,
        poll_interval_seconds=0.01,
        trigger_threshold=threshold,
        rate_limit_seconds=rate_limit,
        startup_grace_seconds=startup_grace,
        reboot_fn=fake_reboot,
    )
    # Skip the start() task — tests drive record_tick() directly. But the
    # safety rails check _started_monotonic, so prime it.
    wd._started_monotonic = time.monotonic() - max(startup_grace + 1.0, 1.0)
    tmp_path.mkdir(parents=True, exist_ok=True)
    return wd, reboots


def test_single_unhealthy_tick_does_not_reboot(tmp_path: Path) -> None:
    wd, reboots = _make_watchdog(tmp_path)
    wd.record_tick(_gpu_failure())
    assert reboots == []
    assert wd._consecutive_failures == 1


def test_threshold_consecutive_failures_triggers_reboot(tmp_path: Path) -> None:
    wd, reboots = _make_watchdog(tmp_path, threshold=3)
    for _ in range(3):
        wd.record_tick(_gpu_failure())
    assert reboots == [True]
    # Marker file written so the rate limit holds across container restarts.
    assert (tmp_path / ".gpu_watchdog_last_reboot").exists()


def test_recovery_resets_streak(tmp_path: Path) -> None:
    wd, reboots = _make_watchdog(tmp_path, threshold=3)
    wd.record_tick(_gpu_failure())
    wd.record_tick(_gpu_failure())
    wd.record_tick(_healthy())  # recovery wipes the streak
    wd.record_tick(_gpu_failure())
    wd.record_tick(_gpu_failure())
    assert reboots == []
    assert wd._consecutive_failures == 2


def test_non_gpu_failure_does_not_count(tmp_path: Path) -> None:
    """A storage/filesystem failure should not trigger a reboot — rebooting
    won't fix a degraded Ceph mount and would just amplify the outage."""
    wd, reboots = _make_watchdog(tmp_path, threshold=3)
    for _ in range(5):
        wd.record_tick(_non_gpu_failure())
    assert reboots == []
    assert wd._consecutive_failures == 0


def test_startup_grace_blocks_reboot(tmp_path: Path) -> None:
    """In the first few minutes after container start the GPU may still
    be settling — never reboot during that window."""
    wd, reboots = _make_watchdog(tmp_path, threshold=3, startup_grace=10.0)
    # Override the priming from _make_watchdog so we're INSIDE the grace.
    wd._started_monotonic = time.monotonic()
    for _ in range(3):
        wd.record_tick(_gpu_failure())
    assert reboots == []


def test_rate_limit_blocks_second_reboot(tmp_path: Path) -> None:
    """Reboot marker exists with a recent mtime → watchdog must not
    reboot again until the rate-limit window expires."""
    wd, reboots = _make_watchdog(tmp_path, threshold=2, rate_limit=3600)
    # Pre-create the marker file with a recent mtime, as if we just rebooted.
    marker = tmp_path / ".gpu_watchdog_last_reboot"
    marker.touch()
    for _ in range(5):
        wd.record_tick(_gpu_failure())
    assert reboots == []


def test_rate_limit_allows_reboot_after_window(tmp_path: Path) -> None:
    wd, reboots = _make_watchdog(tmp_path, threshold=2, rate_limit=60.0)
    marker = tmp_path / ".gpu_watchdog_last_reboot"
    marker.touch()
    # Simulate the marker being from 2 minutes ago.
    old = time.time() - 120
    import os as _os

    _os.utime(marker, (old, old))
    for _ in range(2):
        wd.record_tick(_gpu_failure())
    assert reboots == [True]


def test_diagnostics_file_is_written_on_reboot(tmp_path: Path) -> None:
    wd, _reboots = _make_watchdog(tmp_path, threshold=2)
    for _ in range(2):
        wd.record_tick(_gpu_failure(detail="GPU1.power='ERR!'"))
    diag_files = list((tmp_path / "gpu_watchdog_diagnostics").glob("*.log"))
    assert len(diag_files) == 1
    body = diag_files[0].read_text()
    assert "gpu-error" in body
    assert "GPU1.power" in body
    assert "consecutive_failures" in body


def test_reboot_eperm_does_not_crash(tmp_path: Path) -> None:
    """If CAP_SYS_BOOT is missing reboot() returns EPERM. The watchdog
    must log and continue, not propagate the exception out of the loop."""

    def perm_denied() -> None:
        raise PermissionError(1, "Operation not permitted", "reboot()")

    wd = GpuWatchdog(
        state_dir=tmp_path,
        poll_interval_seconds=0.01,
        trigger_threshold=2,
        rate_limit_seconds=3600,
        startup_grace_seconds=0.0,
        reboot_fn=perm_denied,
    )
    wd._started_monotonic = time.monotonic() - 10.0
    # Must not raise.
    wd.record_tick(_gpu_failure())
    wd.record_tick(_gpu_failure())


@pytest.mark.asyncio
async def test_poll_loop_calls_health_and_triggers_reboot(tmp_path: Path) -> None:
    """End-to-end check of the async loop: feed three failure samples
    via the injected health_fn, ensure reboot fires."""
    reboots: list[bool] = []

    def fake_reboot() -> None:
        reboots.append(True)

    samples = [_gpu_failure(), _gpu_failure(), _gpu_failure()]
    samples_iter = iter(samples)

    def health() -> NodeHealthStatus:
        try:
            return next(samples_iter)
        except StopIteration:
            return _healthy()

    wd = GpuWatchdog(
        state_dir=tmp_path,
        poll_interval_seconds=0.01,
        trigger_threshold=3,
        rate_limit_seconds=3600,
        startup_grace_seconds=0.0,
        reboot_fn=fake_reboot,
        health_fn=health,
    )
    await wd.start()
    # Let the loop run long enough to consume the three samples.
    await asyncio.sleep(0.15)
    await wd.stop()
    assert reboots == [True]
