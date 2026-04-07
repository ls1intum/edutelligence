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


def _parse_nvidia_float(value: str) -> float | None:
    raw = (value or "").strip()
    if not raw or raw in {"[N/A]", "N/A", "ERR!", "[ERR!]", "[Unknown Error]"}:
        return None
    try:
        return float(raw)
    except ValueError:
        return None

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

    @property
    def per_gpu_vram_mb(self) -> float:
        """Average VRAM per GPU in MB (0 if unavailable)."""
        if not self._devices:
            return 0.0
        return sum(d.memory_total_mb for d in self._devices) / len(self._devices)

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

    async def force_poll(self) -> None:
        """Force an immediate GPU metrics refresh outside the regular poll schedule.

        Call this after operations that change GPU memory usage (sleep, wake) so
        the next heartbeat reflects the actual post-operation state rather than
        the cached pre-operation snapshot.
        """
        if not self._available:
            return
        try:
            await self._poll()
        except Exception:
            logger.warning("Forced GPU poll failed", exc_info=True)

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
        degraded_messages: list[str] = []
        for line in raw.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 8:
                continue
            try:
                device_index = int(parts[0])
            except (ValueError, IndexError):
                logger.debug("Skipping malformed nvidia-smi line: %s", line)
                continue

            mem_used = _parse_nvidia_float(parts[3])
            mem_total = _parse_nvidia_float(parts[4])
            if mem_used is None or mem_total is None:
                logger.warning("Skipping nvidia-smi line with invalid memory fields: %s", line)
                degraded_messages.append(f"gpu{device_index}: invalid memory telemetry")
                continue

            utilization = _parse_nvidia_float(parts[5])
            temperature = _parse_nvidia_float(parts[6])
            power_draw = _parse_nvidia_float(parts[7])
            partial_fields: list[str] = []
            if utilization is None:
                partial_fields.append("utilization")
            if temperature is None:
                partial_fields.append("temperature")
            if parts[7].strip() != "[N/A]" and power_draw is None:
                partial_fields.append("power")
            if partial_fields:
                logger.warning(
                    "Partial nvidia-smi telemetry for gpu%s (%s): missing %s",
                    device_index,
                    parts[1] or parts[0],
                    ", ".join(partial_fields),
                )
                degraded_messages.append(f"gpu{device_index}: missing {', '.join(partial_fields)}")

            devices.append(
                DeviceInfo(
                    device_id=parts[1] or parts[0],
                    kind="nvidia",
                    name=parts[2],
                    memory_used_mb=mem_used,
                    memory_total_mb=mem_total,
                    memory_free_mb=max(mem_total - mem_used, 0.0),
                    utilization_percent=utilization,
                    temperature_celsius=temperature,
                    power_draw_watts=power_draw,
                    extra={"index": device_index},
                )
            )

        async with self._lock:
            self._devices = devices
            self._degraded_reason = "; ".join(degraded_messages[:3]) if degraded_messages else ""

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
