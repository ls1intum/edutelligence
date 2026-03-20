"""Runtime status helpers for LogosWorkerNode."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from logos_worker_node.models import CapacitySummary, DeviceInfo, DeviceSummary, WorkerRuntimeStatus

SERVICE_VERSION = "2.0.0"


def _read_proc_meminfo_mb() -> tuple[float, float, float] | None:
    """Read Linux memory totals in MiB from /proc/meminfo for degraded telemetry mode."""
    meminfo_path = Path("/proc/meminfo")
    if not meminfo_path.exists():
        return None

    values_kb: dict[str, float] = {}
    try:
        for raw_line in meminfo_path.read_text(encoding="utf-8").splitlines():
            if ":" not in raw_line:
                continue
            key, raw_value = raw_line.split(":", 1)
            parts = raw_value.strip().split()
            if not parts:
                continue
            try:
                values_kb[key] = float(parts[0])
            except ValueError:
                continue
    except OSError:
        return None

    total_kb = values_kb.get("MemTotal")
    available_kb = values_kb.get("MemAvailable")
    if not total_kb or available_kb is None:
        return None

    total_mb = total_kb / 1024.0
    free_mb = max(available_kb / 1024.0, 0.0)
    used_mb = max(total_mb - free_mb, 0.0)
    return total_mb, used_mb, free_mb


def _build_derived_device_summary(lanes) -> DeviceSummary:
    usage_by_device: dict[str, float] = defaultdict(float)
    for lane in lanes:
        selector = lane.effective_gpu_devices or lane.gpu_devices or "derived"
        key = selector if selector not in {"", "all", "none"} else "derived"
        usage_by_device[key] += float(lane.effective_vram_mb or 0.0)

    meminfo = _read_proc_meminfo_mb()
    if meminfo is not None:
        total, used, free = meminfo
        devices = [
            DeviceInfo(
                device_id="system",
                kind="derived",
                name="system-memory",
                memory_used_mb=used,
                memory_total_mb=total,
                memory_free_mb=free,
                extra={
                    "source": "proc-meminfo",
                    "lane_effective_vram_mb": sum(float(v or 0.0) for v in usage_by_device.values()),
                },
            )
        ]
        degraded_reason = "derived from lane telemetry and system memory"
    else:
        devices = [
            DeviceInfo(
                device_id=device_id,
                kind="derived",
                name=f"derived:{device_id}",
                memory_used_mb=used,
                memory_total_mb=used,
                memory_free_mb=0.0,
            )
            for device_id, used in sorted(usage_by_device.items())
            if used > 0
        ]
        total = sum(device.memory_total_mb for device in devices)
        used = sum(device.memory_used_mb for device in devices)
        free = 0.0
        degraded_reason = "derived from lane telemetry"

    return DeviceSummary(
        timestamp=datetime.now(timezone.utc),
        mode="derived" if devices else "none",
        nvidia_smi_available=False,
        degraded_reason=degraded_reason,
        devices=devices,
        total_memory_mb=total,
        used_memory_mb=used,
        free_memory_mb=free,
    )


async def build_runtime_status(app: FastAPI) -> WorkerRuntimeStatus:
    cfg = app.state.config
    lane_manager = app.state.lane_manager
    gpu_collector = app.state.gpu_collector
    bridge = app.state.logos_bridge

    lanes = await lane_manager.get_all_statuses()
    devices = await gpu_collector.get_snapshot()
    if not devices.nvidia_smi_available:
        devices = _build_derived_device_summary(lanes)

    capacity = CapacitySummary(
        lane_count=len(lanes),
        active_requests=sum(lane.active_requests for lane in lanes),
        loaded_lane_count=sum(1 for lane in lanes if lane.runtime_state == "loaded"),
        sleeping_lane_count=sum(1 for lane in lanes if lane.runtime_state == "sleeping"),
        cold_lane_count=sum(1 for lane in lanes if lane.runtime_state == "cold"),
        total_effective_vram_mb=sum(float(lane.effective_vram_mb or 0.0) for lane in lanes),
        free_memory_mb=float(devices.free_memory_mb or 0.0),
    )

    # Include model profiles if available
    model_profiles = None
    if hasattr(app.state, "model_profiles") and app.state.model_profiles is not None:
        model_profiles = app.state.model_profiles.get_all_profiles()

    return WorkerRuntimeStatus(
        worker_name=cfg.worker.name,
        worker_id=bridge.worker_id,
        service_version=SERVICE_VERSION,
        timestamp=datetime.now(timezone.utc),
        transport=bridge.transport_status(),
        devices=devices,
        capacity=capacity,
        lanes=lanes,
        model_profiles=model_profiles if model_profiles else None,
    )
