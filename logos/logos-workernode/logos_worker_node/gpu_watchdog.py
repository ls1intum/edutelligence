"""GPU-wedge watchdog: hard-reboots the host when the GPU enters an
unrecoverable state that only a power cycle can clear.

Why this exists
---------------
A worker can survive almost any failure by killing and respawning the
offending lane — except a wedged GPU. We've seen two real signatures:

* RTX 6000 Ada / Quadro RTX 5000 with a GSP RPC failure: ``nvidia-smi``
  flips Pwr / Fan / Temp to ``ERR!`` (or returns ``Reset required`` in
  ``dmesg``), and every subsequent CUDA context allocation returns
  ``cudaErrorDevicesUnavailable``. Any ``add_lane`` from then on fails
  before vLLM can even load the model. The node stays "up" from
  Logos's perspective but cannot serve a single inference.

* PCIe-link / driver wedge: the device disappears from ``nvidia-smi``
  or its memory fields become unreadable. Same symptom from the
  scheduler's side — node looks up, can't accept work.

Both states are operator-action territory. Until an operator power-
cycles the host, the worker is dead weight that the scheduler keeps
trying to route work to. This module closes that loop: when
``node_health.evaluate_node_health()`` reports a ``gpu-*`` failure for
N consecutive ticks, the watchdog calls the ``reboot(2)`` syscall
directly. cf. [[node_health]] for the detection side.

Safety rails
------------
* **Startup grace** — no reboot during the first ``startup_grace_seconds``
  of process lifetime. Prevents a boot-loop if the GPU is wedged at
  container start and ``nvidia-smi`` is slow to settle.
* **Consecutive-tick threshold** — a single noisy tick never reboots;
  the wedge must persist across ``trigger_threshold`` consecutive
  evaluations. With the default 60s poll interval that's ~3 min of
  sustained failure.
* **Rate limit** — only one reboot per ``rate_limit_seconds`` window,
  persisted via the mtime of a sentinel file in the state dir so it
  survives the reboot itself. If the GPU comes back wedged immediately
  after a reboot, the watchdog logs LOUDLY but stops — that's an
  operator-needed condition (likely hardware).
* **Diagnostics dump** — every reboot trigger writes
  ``gpu_watchdog_diagnostics/<utc-timestamp>.log`` to the state dir
  with the failing health snapshot, current ``nvidia-smi`` output, and
  recent ``dmesg | grep -i nvidia`` so postmortem doesn't require
  re-deriving why we rebooted.

Container requirements
----------------------
The container must have ``CAP_SYS_BOOT``. In docker-compose that's
``cap_add: [SYS_BOOT]``. Without it, ``libc.reboot()`` returns ``EPERM``
and the watchdog logs the failure but leaves the host running.
"""

from __future__ import annotations

import asyncio
import ctypes
import logging
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from logos_worker_node.node_health import NodeHealthStatus, evaluate_node_health

logger = logging.getLogger(__name__)

# Reboot codes from <linux/reboot.h>. These are stable across kernels;
# no other Python package wraps them so we go straight to ctypes.
_LINUX_REBOOT_MAGIC1 = 0xFEE1DEAD
_LINUX_REBOOT_MAGIC2 = 672274793
_LINUX_REBOOT_CMD_RESTART = 0x01234567

# A node_health reason_code starting with this prefix means the GPU
# sensor itself flagged the node. Anything else (storage etc.) is not
# something a reboot would fix, so the watchdog ignores it.
_GPU_REASON_PREFIX = "gpu-"


class GpuWatchdog:
    """Polls ``evaluate_node_health()`` and triggers ``reboot(2)`` when
    the GPU sensor stays unhealthy for ``trigger_threshold`` ticks."""

    def __init__(
        self,
        state_dir: Path,
        *,
        poll_interval_seconds: float = 60.0,
        trigger_threshold: int = 3,
        rate_limit_seconds: float = 30 * 60,
        startup_grace_seconds: float = 5 * 60,
        reboot_fn=None,  # injection point for tests
        health_fn=evaluate_node_health,
    ) -> None:
        self._state_dir = Path(state_dir)
        self._poll_interval = poll_interval_seconds
        self._threshold = trigger_threshold
        self._rate_limit = rate_limit_seconds
        self._startup_grace = startup_grace_seconds
        self._reboot_fn = reboot_fn or _hard_reboot
        self._health_fn = health_fn

        self._consecutive_failures = 0
        self._last_reason: str | None = None
        self._task: asyncio.Task | None = None
        self._started_monotonic: float | None = None

    @property
    def _last_reboot_marker(self) -> Path:
        return self._state_dir / ".gpu_watchdog_last_reboot"

    @property
    def _diagnostics_dir(self) -> Path:
        return self._state_dir / "gpu_watchdog_diagnostics"

    async def start(self) -> None:
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._started_monotonic = time.monotonic()
        self._task = asyncio.create_task(self._poll_loop(), name="gpu-watchdog")
        logger.info(
            "GPU watchdog started — threshold=%d ticks, poll=%.0fs, grace=%.0fs, rate_limit=%.0fs",
            self._threshold,
            self._poll_interval,
            self._startup_grace,
            self._rate_limit,
        )

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("GPU watchdog stopped")

    async def _poll_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._poll_interval)
                health = self._health_fn()
                self.record_tick(health)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("gpu_watchdog: poll loop iteration failed")

    def record_tick(self, health: NodeHealthStatus) -> None:
        """Process one health evaluation. Public so the watchdog can also
        be driven by an external loop (e.g. the bridge's heartbeat) — the
        decision logic doesn't care where the tick came from."""
        reason = health.reason_code or ""
        is_gpu_failure = (not health.healthy) and reason.startswith(_GPU_REASON_PREFIX)

        if not is_gpu_failure:
            if self._consecutive_failures > 0:
                logger.info(
                    "gpu_watchdog: GPU recovered after %d unhealthy tick(s) (last reason=%s)",
                    self._consecutive_failures,
                    self._last_reason,
                )
            self._consecutive_failures = 0
            self._last_reason = None
            return

        self._consecutive_failures += 1
        self._last_reason = reason
        logger.warning(
            "gpu_watchdog: GPU unhealthy (reason=%s, streak=%d/%d): %s",
            reason,
            self._consecutive_failures,
            self._threshold,
            health.reason_detail,
        )

        if self._consecutive_failures < self._threshold:
            return

        block = self._reboot_blocker()
        if block is not None:
            logger.error(
                "gpu_watchdog: threshold reached (streak=%d) but reboot is blocked: %s",
                self._consecutive_failures,
                block,
            )
            return

        self._trigger_reboot(health)

    def _reboot_blocker(self) -> str | None:
        """Return a human-readable reason the reboot is blocked, or None
        if all safety rails allow it."""
        if self._started_monotonic is None:
            return "watchdog not fully started"
        in_grace = time.monotonic() - self._started_monotonic
        if in_grace < self._startup_grace:
            return (
                f"within startup grace ({in_grace:.0f}s / {self._startup_grace:.0f}s) — "
                "GPU may still be settling after container start"
            )
        marker = self._last_reboot_marker
        if marker.exists():
            since_last = time.time() - marker.stat().st_mtime
            if since_last < self._rate_limit:
                return (
                    f"rate-limited — last reboot was {since_last:.0f}s ago "
                    f"(< {self._rate_limit:.0f}s window). "
                    "The GPU coming back wedged this fast means an operator needs to look."
                )
        return None

    def _trigger_reboot(self, health: NodeHealthStatus) -> None:
        logger.critical(
            "gpu_watchdog: TRIGGERING HOST REBOOT — reason=%s streak=%d detail=%s",
            self._last_reason,
            self._consecutive_failures,
            health.reason_detail,
        )
        try:
            self._write_diagnostics(health)
        except Exception:  # noqa: BLE001
            logger.exception("gpu_watchdog: failed to write diagnostics; rebooting anyway")
        try:
            # Touch the marker BEFORE the reboot so the rate-limit holds
            # even if the host comes back wedged and the watchdog fires
            # again immediately on the next boot.
            self._last_reboot_marker.parent.mkdir(parents=True, exist_ok=True)
            self._last_reboot_marker.touch()
        except Exception:  # noqa: BLE001
            logger.exception("gpu_watchdog: failed to touch rate-limit marker")
        try:
            self._reboot_fn()
        except PermissionError:
            logger.critical(
                "gpu_watchdog: reboot() returned EPERM — container is missing CAP_SYS_BOOT. "
                "Add `cap_add: [SYS_BOOT]` to the worker compose service."
            )
        except Exception:  # noqa: BLE001
            logger.exception("gpu_watchdog: reboot() failed")

    def _write_diagnostics(self, health: NodeHealthStatus) -> None:
        self._diagnostics_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = self._diagnostics_dir / f"{stamp}.log"

        nvidia_smi_out = _capture("nvidia-smi", timeout=10)
        nvidia_smi_query = _capture(
            "nvidia-smi --query-gpu=index,name,memory.used,memory.total,"
            "utilization.gpu,temperature.gpu,power.draw,fan.speed "
            "--format=csv",
            timeout=10,
            shell=True,
        )
        dmesg_out = _capture(
            "dmesg -T | grep -iE 'nvidia|nvrm|xid' | tail -50",
            timeout=10,
            shell=True,
        )

        with path.open("w", encoding="utf-8") as f:
            f.write("# gpu_watchdog reboot diagnostics\n")
            f.write(f"# timestamp: {datetime.now(timezone.utc).isoformat()}\n")
            f.write(f"# reason_code: {health.reason_code}\n")
            f.write(f"# reason_detail: {health.reason_detail}\n")
            f.write(f"# consecutive_failures: {self._consecutive_failures}\n")
            f.write(f"# threshold: {self._threshold}\n\n")
            f.write("## node_health snapshot\n")
            f.write(repr(health.to_dict()))
            f.write("\n\n## nvidia-smi\n")
            f.write(nvidia_smi_out)
            f.write("\n\n## nvidia-smi --query-gpu (csv)\n")
            f.write(nvidia_smi_query)
            f.write("\n\n## dmesg | grep nvidia (last 50)\n")
            f.write(dmesg_out)
        logger.info("gpu_watchdog: diagnostics written to %s", path)


def _capture(cmd: str | list[str], *, timeout: float, shell: bool = False) -> str:
    """Best-effort subprocess capture for diagnostics. Never raises —
    failure mode is just an error string in the dump."""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=shell,
            check=False,
        )
        return f"$ {cmd}\n[exit={proc.returncode}]\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    except Exception as exc:  # noqa: BLE001
        return f"$ {cmd}\n[capture failed: {exc!r}]"


def _hard_reboot() -> None:
    """Call the ``reboot(2)`` syscall directly via ``libc.reboot``.

    Requires ``CAP_SYS_BOOT`` in the container (compose
    ``cap_add: [SYS_BOOT]``). On success this call does not return — the
    kernel reboots immediately. ``os.sync()`` first to flush buffered
    writes; we still rely on the kernel's own remount-readonly because
    the worker container probably isn't running its own filesystems."""
    os.sync()
    libc = ctypes.CDLL("libc.so.6", use_errno=True)
    ret = libc.reboot(
        _LINUX_REBOOT_MAGIC1,
        _LINUX_REBOOT_MAGIC2,
        _LINUX_REBOOT_CMD_RESTART,
        None,
    )
    err = ctypes.get_errno()
    if err == 1:  # EPERM
        raise PermissionError(err, os.strerror(err), "reboot()")
    raise OSError(err or 0, os.strerror(err) if err else "reboot returned", f"ret={ret}")
