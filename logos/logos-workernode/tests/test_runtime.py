from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from logos_worker_node.models import (
    DeviceSummary,
    LaneConfig,
    LaneStatus,
    ProcessState,
    ProcessStatus,
    WorkerTransportStatus,
)
from logos_worker_node.runtime import build_runtime_status


class _LaneManager:
    def __init__(self, lanes):
        self._lanes = lanes

    async def get_all_statuses(self):
        return self._lanes


class _GpuCollector:
    async def get_snapshot(self):
        return DeviceSummary(
            timestamp=datetime(2026, 3, 16, 19, 0, 0, tzinfo=timezone.utc),
            mode="none",
            nvidia_smi_available=False,
            degraded_reason="nvidia-smi not found",
            devices=[],
            total_memory_mb=0.0,
            used_memory_mb=0.0,
            free_memory_mb=0.0,
        )


class _Bridge:
    worker_id = "worker-1"

    def transport_status(self):
        return WorkerTransportStatus(
            connected=True,
            worker_id=self.worker_id,
        )


def _make_app(lanes):
    worker_cfg = SimpleNamespace(name="logos-workernode", max_lanes=0)
    state = SimpleNamespace(
        config=SimpleNamespace(worker=worker_cfg),
        lane_manager=_LaneManager(lanes),
        gpu_collector=_GpuCollector(),
        logos_bridge=_Bridge(),
    )
    return SimpleNamespace(state=state)


@pytest.mark.asyncio
async def test_build_runtime_status_uses_proc_meminfo_for_degraded_ollama(monkeypatch):
    monkeypatch.setattr(
        "logos_worker_node.runtime._read_proc_meminfo_mb",
        lambda: (8192.0, 3072.0, 5120.0),
    )

    lanes = [
        LaneStatus(
            lane_id="lane-a",
            lane_uid="ollama:lane-a",
            model="gemma2:2b",
            port=11437,
            vllm=False,
            process=ProcessStatus(state=ProcessState.RUNNING, pid=101),
            runtime_state="loaded",
            routing_url="http://127.0.0.1:11437",
            num_parallel=4,
            context_length=4096,
            keep_alive="5m",
            kv_cache_type="q8_0",
            flash_attention=True,
            lane_config=LaneConfig(model="gemma2:2b"),
            loaded_models=[],
            effective_vram_mb=0.0,
        )
    ]

    runtime = await build_runtime_status(_make_app(lanes))

    assert runtime.devices.mode == "derived"
    assert runtime.devices.nvidia_smi_available is False
    assert runtime.devices.total_memory_mb == 8192.0
    assert runtime.devices.used_memory_mb == 3072.0
    assert runtime.devices.free_memory_mb == 5120.0
    assert runtime.capacity.free_memory_mb == 5120.0
    assert runtime.devices.devices[0].name == "system-memory"
