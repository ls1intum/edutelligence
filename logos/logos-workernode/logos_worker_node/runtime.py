"""Runtime status helpers for LogosWorkerNode."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI

from logos_worker_node.models import CapacitySummary, DeviceInfo, DeviceSummary, WorkerRuntimeStatus

SERVICE_VERSION = "2.0.0"


def _build_derived_device_summary(lanes) -> DeviceSummary:
    usage_by_device: dict[str, float] = defaultdict(float)
    for lane in lanes:
        selector = lane.effective_gpu_devices or lane.gpu_devices or "derived"
        key = selector if selector not in {"", "all", "none"} else "derived"
        usage_by_device[key] += float(lane.effective_vram_mb or 0.0)

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
    return DeviceSummary(
        timestamp=datetime.now(timezone.utc),
        mode="derived" if devices else "none",
        nvidia_smi_available=False,
        degraded_reason="derived from lane telemetry",
        devices=devices,
        total_memory_mb=total,
        used_memory_mb=used,
        free_memory_mb=0.0,
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

    return WorkerRuntimeStatus(
        worker_name=cfg.worker.name,
        worker_id=bridge.worker_id,
        service_version=SERVICE_VERSION,
        timestamp=datetime.now(timezone.utc),
        transport=bridge.transport_status(),
        devices=devices,
        capacity=capacity,
        lanes=lanes,
    )
