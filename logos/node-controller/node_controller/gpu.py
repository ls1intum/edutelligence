"""
GPU metrics collector via nvidia-smi.

Periodically polls nvidia-smi as a subprocess, parses CSV output into
GpuInfo objects, and caches the latest snapshot.  All public read methods
are protected by an asyncio.Lock to prevent partial reads during updates.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
from datetime import datetime, timezone

from node_controller.models import GpuInfo, GpuSnapshot

logger = logging.getLogger("node_controller.gpu")

_NVIDIA_SMI_QUERY = (
    "index,uuid,name,memory.used,memory.total,utilization.gpu,"
    "temperature.gpu,power.draw"
)
_NVIDIA_SMI_FORMAT = "csv,noheader,nounits"
_SUBPROCESS_TIMEOUT = 10  # seconds


class GpuMetricsCollector:
    """Background collector that polls nvidia-smi at a fixed interval."""

    def __init__(self, poll_interval: int = 5) -> None:
        self._poll_interval = poll_interval
        self._gpus: list[GpuInfo] = []
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self._available = False

    @property
    def available(self) -> bool:
        return self._available

    async def start(self) -> None:
        """Check for nvidia-smi and begin background polling."""
        if shutil.which("nvidia-smi") is None:
            logger.warning("nvidia-smi not found in PATH — GPU metrics disabled")
            self._available = False
            return

        self._available = True
        # Do an initial synchronous poll so first snapshot is ready
        await self._poll()
        self._task = asyncio.create_task(self._poll_loop(), name="gpu-poll")
        logger.info(
            "GPU collector started — %d GPU(s) detected, polling every %ds",
            len(self._gpus),
            self._poll_interval,
        )

    async def stop(self) -> None:
        """Cancel the background polling task."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("GPU collector stopped")

    async def get_snapshot(self) -> GpuSnapshot:
        """Return a timestamped snapshot of all GPU metrics."""
        async with self._lock:
            gpus = list(self._gpus)

        total = sum(g.memory_total_mb for g in gpus)
        used = sum(g.memory_used_mb for g in gpus)
        free = sum(g.memory_free_mb for g in gpus)

        return GpuSnapshot(
            timestamp=datetime.now(timezone.utc),
            gpus=gpus,
            total_vram_mb=total,
            used_vram_mb=used,
            free_vram_mb=free,
            nvidia_smi_available=self._available,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        """Infinite loop: sleep then poll."""
        while True:
            await asyncio.sleep(self._poll_interval)
            try:
                await self._poll()
            except Exception:
                logger.exception("Error polling nvidia-smi")

    async def _poll(self) -> None:
        """Run nvidia-smi in a thread and parse the output."""
        loop = asyncio.get_running_loop()
        raw = await loop.run_in_executor(None, self._run_nvidia_smi)
        if raw is None:
            return

        gpus: list[GpuInfo] = []
        for line in raw.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 8:
                continue
            try:
                mem_used = float(parts[3])
                mem_total = float(parts[4])
                gpus.append(
                    GpuInfo(
                        index=int(parts[0]),
                        uuid=parts[1],
                        name=parts[2],
                        memory_used_mb=mem_used,
                        memory_total_mb=mem_total,
                        memory_free_mb=mem_total - mem_used,
                        utilization_percent=float(parts[5]),
                        temperature_celsius=float(parts[6]),
                        power_draw_watts=(
                            float(parts[7]) if parts[7] != "[N/A]" else None
                        ),
                    )
                )
            except (ValueError, IndexError):
                logger.debug("Skipping malformed nvidia-smi line: %s", line)

        async with self._lock:
            self._gpus = gpus

    @staticmethod
    def _run_nvidia_smi() -> str | None:
        """Synchronous subprocess call to nvidia-smi."""
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    f"--query-gpu={_NVIDIA_SMI_QUERY}",
                    f"--format={_NVIDIA_SMI_FORMAT}",
                ],
                capture_output=True,
                text=True,
                timeout=_SUBPROCESS_TIMEOUT,
            )
            if result.returncode != 0:
                logger.warning("nvidia-smi returned %d: %s", result.returncode, result.stderr.strip())
                return None
            return result.stdout
        except FileNotFoundError:
            logger.warning("nvidia-smi binary not found")
            return None
        except subprocess.TimeoutExpired:
            logger.warning("nvidia-smi timed out after %ds", _SUBPROCESS_TIMEOUT)
            return None
