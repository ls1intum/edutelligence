"""Metal / Apple-Silicon metrics collector for LogosWorkerNode.

Mirrors :class:`logos_worker_node.gpu.GpuMetricsCollector` so ``LaneManager``
and ``runtime.build_runtime_status`` can consume either without conditionals.

Design notes
────────────
• Unified memory — there is no separate VRAM pool. The number that matters is
  ``max_recommended_working_set_size``: how much a process may wire down for
  the GPU before Metal starts refusing allocations. macOS derives it from
  ``hw.memsize`` and the ``iogpu.wired_limit_mb`` sysctl. Reporting
  ``hw.memsize`` instead would overstate capacity by ~22% and let the
  orchestrator schedule a lane that cannot actually be resident.

• The static device facts are read ONCE at startup by shelling out to the
  vllm-metal interpreter (``mlx.core.device_info()``). The worker runs in its
  own venv and deliberately does not depend on mlx — the lanes do. A single
  subprocess at startup keeps the dependency where it belongs while still
  giving us the exact value Metal itself will enforce. When that interpreter
  is unreachable we fall back to a sysctl heuristic, which is close but not
  authoritative — and say so at the type level: the snapshot then carries
  ``telemetry_available=False`` (plus the reason in ``degraded_reason``), so
  consumers that gate on the flag do not schedule against the estimate.

• Per-poll usage comes from ``vm_stat``'s wired-down page count. It is the
  systemwide figure and therefore includes kernel wired memory, so it slightly
  overstates GPU usage — the conservative direction for a capacity planner.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone

from logos_worker_node.models import DeviceInfo, DeviceSummary

logger = logging.getLogger("logos_worker_node.metal")

_SUBPROCESS_TIMEOUT = 10
# Startup probe imports mlx and touches the GPU; slower than a plain sysctl.
_DEVICE_INFO_TIMEOUT = 60
_MB = 1024.0 * 1024.0

# Fraction of physical RAM macOS lets the GPU wire down when
# iogpu.wired_limit_mb is unset. Apple does not document this; measured at
# ~0.78 on a 36 GB M3 Pro. Only used when the mlx probe is unavailable.
_DEFAULT_WIRED_FRACTION = 0.78

_VM_STAT_PAGE_SIZE_RE = re.compile(r"page size of (\d+) bytes")
_VM_STAT_LINE_RE = re.compile(r'^"?([A-Za-z][^":]*)"?:\s+(\d+)\.?$')


def is_metal_backend() -> bool:
    """Whether this worker should drive lanes through the Metal backend.

    Auto-detected from the platform: macOS has no CUDA, so there is nothing to
    choose between and a misconfiguration is impossible. ``LOGOS_WORKER_BACKEND``
    (``metal`` or ``cuda``) overrides it — primarily so tests can exercise both
    paths on one machine, but it also leaves an escape hatch if a Mac should
    ever run Ollama-only lanes.
    """
    override = (os.environ.get("LOGOS_WORKER_BACKEND") or "").strip().lower()
    if override in {"metal", "cuda"}:
        return override == "metal"
    if override:
        logger.warning(
            "Ignoring LOGOS_WORKER_BACKEND=%r — expected 'metal' or 'cuda'; falling back to platform detection",
            override,
        )
    return sys.platform == "darwin"


def _run(cmd: list[str], timeout: int = _SUBPROCESS_TIMEOUT) -> str | None:
    """Run a command, returning stdout or None on any failure."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        logger.debug("command failed: %s (%s)", " ".join(cmd), exc)
        return None
    if result.returncode != 0:
        logger.debug("command returned %d: %s", result.returncode, " ".join(cmd))
        return None
    return result.stdout


def _sysctl_int(name: str) -> int | None:
    """Read an integer sysctl. Returns None when absent or unparseable."""
    raw = _run(["sysctl", "-n", name])
    if raw is None:
        return None
    try:
        return int(raw.strip())
    except ValueError:
        return None


def parse_vm_stat(raw: str) -> dict[str, int] | None:
    """Parse ``vm_stat`` output into a {label: bytes} mapping.

    Page counts are multiplied by the page size announced in the header
    (16 KiB on Apple Silicon, not the 4 KiB that would be assumed by default).
    """
    page_match = _VM_STAT_PAGE_SIZE_RE.search(raw)
    if not page_match:
        return None
    page_size = int(page_match.group(1))

    values: dict[str, int] = {}
    for line in raw.splitlines():
        match = _VM_STAT_LINE_RE.match(line.strip())
        if not match:
            continue
        label, count = match.group(1).strip(), match.group(2)
        try:
            values[label] = int(count) * page_size
        except ValueError:
            continue
    return values or None


def read_vm_stat() -> dict[str, int] | None:
    """Read and parse ``vm_stat``. Returns None when unavailable."""
    raw = _run(["vm_stat"])
    return parse_vm_stat(raw) if raw is not None else None


def read_host_memory_mb() -> tuple[float, float, float] | None:
    """Host memory as (total_mb, used_mb, available_mb), or None on failure.

    macOS counterpart to reading MemTotal/MemAvailable from /proc/meminfo.
    "Available" is free + inactive + speculative + purgeable: inactive and
    purgeable pages are reclaimable under pressure, which is the same notion
    Linux's MemAvailable encodes.
    """
    total_bytes = _sysctl_int("hw.memsize")
    stats = read_vm_stat()
    if not total_bytes or stats is None:
        return None

    available_bytes = (
        stats.get("Pages free", 0)
        + stats.get("Pages inactive", 0)
        + stats.get("Pages speculative", 0)
        + stats.get("Pages purgeable", 0)
    )
    total_mb = total_bytes / _MB
    available_mb = min(available_bytes / _MB, total_mb)
    used_mb = max(total_mb - available_mb, 0.0)
    return total_mb, used_mb, available_mb


def read_swap_mb() -> tuple[float, float]:
    """Swap as (total_mb, used_mb). Returns (0, 0) when unreadable."""
    raw = _run(["sysctl", "-n", "vm.swapusage"])
    if raw is None:
        return 0.0, 0.0

    # Format: "total = 2048.00M  used = 512.25M  free = 1535.75M  (encrypted)"
    def _field(name: str) -> float:
        match = re.search(rf"{name}\s*=\s*([\d.]+)([MGK])", raw)
        if not match:
            return 0.0
        value, unit = float(match.group(1)), match.group(2)
        return value * {"K": 1 / 1024.0, "M": 1.0, "G": 1024.0}[unit]

    return _field("total"), _field("used")


def read_process_rss_mb(pid: int) -> float:
    """Resident set size of a process in MiB. Returns 0 on failure.

    macOS has no /proc/<pid>/smaps_rollup, so PSS is not available without
    private task-port APIs. RSS is the practical substitute here: Metal lanes
    run single-process (no tensor parallelism), so there are no cross-rank
    shared weight mappings for PSS to deduplicate — the very case PSS exists
    for on the CUDA path.
    """
    raw = _run(["ps", "-o", "rss=", "-p", str(pid)])
    if raw is None:
        return 0.0
    try:
        return float(raw.strip()) / 1024.0  # ps reports KiB
    except ValueError:
        return 0.0


def default_metal_venv() -> str:
    """The vllm-metal venv, resolved exactly once for the whole worker.

    Reads LOGOS_METAL_VENV — the same variable scripts/install-macos.sh
    honours — falling back to the layout upstream's installer creates. Every
    runtime resolution that needs the venv (the vllm binary, this interpreter
    candidate list) goes through here, so a custom location installed on the
    host cannot be missed at lane spawn or telemetry probe time.
    """
    override = (os.environ.get("LOGOS_METAL_VENV") or "").strip()
    return os.path.expanduser(override or "~/.venv-vllm-metal")


def metal_python_candidates(configured: str = "") -> list[str]:
    """Candidate interpreters that can import mlx, most specific first."""
    candidates: list[str] = []
    if configured:
        candidates.append(os.path.expanduser(configured))
    env_override = (os.environ.get("LOGOS_METAL_PYTHON") or "").strip()
    if env_override:
        candidates.append(os.path.expanduser(env_override))
    candidates.append(os.path.join(default_metal_venv(), "bin", "python"))
    found = shutil.which("python3")
    if found:
        candidates.append(found)
    # Preserve order, drop duplicates and anything that is not executable.
    seen: set[str] = set()
    usable: list[str] = []
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            usable.append(candidate)
    return usable


_DEVICE_INFO_SNIPPET = (
    "import json, mlx.core as mx; "
    "info = mx.device_info(); "
    "print(json.dumps({k: v for k, v in info.items() if isinstance(v, (int, float, str))}))"
)


def probe_device_info(configured_python: str = "") -> dict[str, object] | None:
    """Read ``mlx.core.device_info()`` via the vllm-metal interpreter.

    Returns None when no candidate interpreter can import mlx.
    """
    for interpreter in metal_python_candidates(configured_python):
        raw = _run([interpreter, "-c", _DEVICE_INFO_SNIPPET], timeout=_DEVICE_INFO_TIMEOUT)
        if raw is None:
            continue
        # mlx prints deprecation notices on stderr, but be defensive and take
        # the last non-empty line rather than assuming stdout is pure JSON.
        for line in reversed(raw.strip().splitlines()):
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict) and parsed:
                logger.info("Metal device probe succeeded via %s", interpreter)
                return parsed
    return None


def _working_set_bytes_from_sysctl() -> tuple[int, str] | None:
    """Fallback GPU budget from sysctl. Returns (bytes, source_label)."""
    total = _sysctl_int("hw.memsize")
    if not total:
        return None
    wired_limit_mb = _sysctl_int("iogpu.wired_limit_mb") or 0
    if wired_limit_mb > 0:
        return int(wired_limit_mb * _MB), "iogpu.wired_limit_mb"
    return int(total * _DEFAULT_WIRED_FRACTION), "hw.memsize heuristic"


class MetalMetricsCollector:
    """Apple-Silicon counterpart to :class:`GpuMetricsCollector`.

    Exposes the same surface (``available``, ``device_count``,
    ``per_gpu_vram_mb``, ``start``/``stop``/``force_poll``/``get_snapshot``)
    so callers need no backend conditionals.
    """

    def __init__(self, poll_interval: int = 5, metal_python: str = "") -> None:
        self._poll_interval = poll_interval
        self._metal_python = metal_python
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self._available = False
        self._degraded_reason = ""
        self._device_name = "Apple Silicon GPU"
        self._architecture = ""
        self._working_set_bytes = 0
        self._max_buffer_bytes = 0
        self._used_bytes = 0.0

    @property
    def available(self) -> bool:
        return self._available

    @property
    def device_count(self) -> int:
        """Always 1 on Apple Silicon — a single integrated GPU."""
        return 1 if self._available else 0

    @property
    def per_gpu_vram_mb(self) -> float:
        """Usable GPU memory in MB (0 when unavailable)."""
        return self._working_set_bytes / _MB if self._available else 0.0

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        info = await loop.run_in_executor(None, probe_device_info, self._metal_python)

        if info:
            self._device_name = str(info.get("device_name") or self._device_name)
            self._architecture = str(info.get("architecture") or "")
            working_set = int(info.get("max_recommended_working_set_size") or 0)
            self._max_buffer_bytes = int(info.get("max_buffer_length") or 0)
            self._degraded_reason = ""
        else:
            working_set = 0

        if working_set <= 0:
            fallback = _working_set_bytes_from_sysctl()
            if fallback is None:
                self._available = False
                self._degraded_reason = "neither mlx device_info nor sysctl hw.memsize available"
                logger.warning("Metal collector disabled — %s", self._degraded_reason)
                return
            working_set, label = fallback
            self._degraded_reason = f"mlx device_info unavailable — GPU budget estimated from {label}"
            logger.warning("Metal collector degraded — %s", self._degraded_reason)

        self._working_set_bytes = working_set
        self._available = True
        await self._poll()
        self._task = asyncio.create_task(self._poll_loop(), name="metal-poll")
        logger.info(
            "Metal collector started — %s (%s), GPU budget %.0f MB",
            self._device_name,
            self._architecture or "unknown arch",
            self._working_set_bytes / _MB,
        )

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Metal collector stopped")

    async def force_poll(self) -> None:
        """Refresh immediately, outside the regular poll schedule."""
        if not self._available:
            return
        try:
            await self._poll()
        except Exception:
            logger.warning("Forced Metal poll failed", exc_info=True)

    async def get_snapshot(self) -> DeviceSummary:
        async with self._lock:
            available = self._available
            used_bytes = self._used_bytes
            working_set = self._working_set_bytes
            degraded_reason = self._degraded_reason
            device_name = self._device_name
            architecture = self._architecture
            max_buffer = self._max_buffer_bytes

        if not available:
            return DeviceSummary(
                timestamp=datetime.now(timezone.utc),
                mode="none",
                nvidia_smi_available=False,
                telemetry_available=False,
                degraded_reason=degraded_reason or "Metal collector unavailable",
            )

        total_mb = working_set / _MB
        used_mb = min(used_bytes / _MB, total_mb)
        free_mb = max(total_mb - used_mb, 0.0)

        device = DeviceInfo(
            device_id="0",
            kind="metal",
            name=device_name,
            memory_used_mb=used_mb,
            memory_total_mb=total_mb,
            memory_free_mb=free_mb,
            extra={
                "source": "mlx-device-info" if not degraded_reason else "sysctl-fallback",
                "architecture": architecture,
                # Metal refuses any single allocation above this, regardless of
                # how much of the working set is still free. A model whose
                # largest tensor buffer exceeds it cannot load at all.
                "max_buffer_length_mb": max_buffer / _MB if max_buffer else None,
                "unified_memory": True,
            },
        )

        return DeviceSummary(
            timestamp=datetime.now(timezone.utc),
            mode="metal",
            # No nvidia-smi here, and we must not claim otherwise: an
            # orchestrator that has not learned about telemetry_available yet
            # should fall back to its total-minus-used path rather than trust
            # a free_memory_mb it thinks came from nvidia-smi.
            nvidia_smi_available=False,
            # False on the sysctl-fallback path: the budget there is a
            # heuristic (one machine's measured constant), and reporting it
            # as measured telemetry would let the orchestrator size lanes
            # against a figure that is off by an unknown margin. Consumers
            # that gate on telemetry_available then keep their
            # registration-time / total-minus-used values until a real mlx
            # probe succeeds. The caveat stays visible in degraded_reason.
            telemetry_available=not degraded_reason,
            degraded_reason=degraded_reason,
            devices=[device],
            total_memory_mb=total_mb,
            used_memory_mb=used_mb,
            free_memory_mb=free_mb,
        )

    async def _poll_loop(self) -> None:
        while True:
            await asyncio.sleep(self._poll_interval)
            try:
                await self._poll()
            except Exception:
                logger.exception("Error polling Metal memory statistics")

    async def _poll(self) -> None:
        loop = asyncio.get_running_loop()
        stats = await loop.run_in_executor(None, read_vm_stat)
        if stats is None:
            return
        # Wired-down pages are the ones that cannot be paged out — which is
        # exactly what Metal allocations for model weights and KV cache are.
        # Systemwide, so it includes kernel wired memory and thus overstates
        # GPU usage a little; that errs toward reporting less free memory,
        # which is the safe direction for the capacity planner.
        wired = stats.get("Pages wired down")
        if wired is None:
            return
        async with self._lock:
            self._used_bytes = float(wired)
