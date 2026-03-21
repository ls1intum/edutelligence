"""GPU metrics collector for LogosWorkerNode."""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
from datetime import datetime, timezone

from logos_worker_node.models import DeviceInfo, DeviceSummary

logger = logging.getLogger("logos_worker_node.gpu")

_NVIDIA_SMI_QUERY = (
    "index,uuid,name,memory.used,memory.total,utilization.gpu,"
    "temperature.gpu,power.draw"
)
_NVIDIA_SMI_FORMAT = "csv,noheader,nounits"
_SUBPROCESS_TIMEOUT = 10


class GpuMetricsCollector:
    def __init__(self, poll_interval: int = 5) -> None:
        self._poll_interval = poll_interval
        self._devices: list[DeviceInfo] = []
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self._available = False
        self._degraded_reason = ""

    @property
    def available(self) -> bool:
        return self._available

    @property
    def device_count(self) -> int:
        """Number of GPU devices detected (0 if nvidia-smi unavailable)."""
        return len(self._devices)

    async def start(self) -> None:
        if shutil.which("nvidia-smi") is None:
            logger.warning("nvidia-smi not found in PATH — GPU metrics disabled")
            self._available = False
            self._degraded_reason = "nvidia-smi not found"
            return

        self._available = True
        self._degraded_reason = ""
        await self._poll()
        self._task = asyncio.create_task(self._poll_loop(), name="gpu-poll")
        logger.info("GPU collector started — %d device(s)", len(self._devices))

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("GPU collector stopped")

    async def get_snapshot(self) -> DeviceSummary:
        async with self._lock:
            devices = [device.model_copy() for device in self._devices]
            available = self._available
            degraded_reason = self._degraded_reason

        total = sum(device.memory_total_mb for device in devices)
        used = sum(device.memory_used_mb for device in devices)
        free = sum(device.memory_free_mb for device in devices)

        return DeviceSummary(
            timestamp=datetime.now(timezone.utc),
            mode="nvidia" if available and devices else ("none" if not devices else "derived"),
            nvidia_smi_available=available,
            degraded_reason=degraded_reason,
            devices=devices,
            total_memory_mb=total,
            used_memory_mb=used,
            free_memory_mb=free,
        )

    async def _poll_loop(self) -> None:
        while True:
            await asyncio.sleep(self._poll_interval)
            try:
                await self._poll()
            except Exception:
                logger.exception("Error polling nvidia-smi")

    async def _poll(self) -> None:
        loop = asyncio.get_running_loop()
        raw = await loop.run_in_executor(None, self._run_nvidia_smi)
        if raw is None:
            return

        devices: list[DeviceInfo] = []
        for line in raw.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 8:
                continue
            try:
                mem_used = float(parts[3])
                mem_total = float(parts[4])
                devices.append(
                    DeviceInfo(
                        device_id=parts[1] or parts[0],
                        kind="nvidia",
                        name=parts[2],
                        memory_used_mb=mem_used,
                        memory_total_mb=mem_total,
                        memory_free_mb=mem_total - mem_used,
                        utilization_percent=float(parts[5]),
                        temperature_celsius=float(parts[6]),
                        power_draw_watts=float(parts[7]) if parts[7] != "[N/A]" else None,
                        extra={"index": int(parts[0])},
                    )
                )
            except (ValueError, IndexError):
                logger.debug("Skipping malformed nvidia-smi line: %s", line)

        async with self._lock:
            self._devices = devices

    @staticmethod
    def _run_nvidia_smi() -> str | None:
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
