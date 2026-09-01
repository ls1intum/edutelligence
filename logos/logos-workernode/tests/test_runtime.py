from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from logos_worker_node.models import (
    DeviceInfo,
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


class _MetalCollector:
    """A healthy Metal snapshot: measured working set, no nvidia-smi.

    nvidia_smi_available stays False by design (this is not nvidia-smi
    data); telemetry_available is what marks it as measured.
    """

    async def get_snapshot(self):
        return DeviceSummary(
            timestamp=datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc),
            mode="metal",
            nvidia_smi_available=False,
            telemetry_available=True,
            degraded_reason="",
            devices=[
                DeviceInfo(
                    device_id="apple-gpu",
                    kind="metal",
                    name="Apple M3 Pro",
                    memory_used_mb=12000.0,
                    memory_total_mb=24000.0,
                    memory_free_mb=12000.0,
                )
            ],
            total_memory_mb=24000.0,
            used_memory_mb=12000.0,
            free_memory_mb=12000.0,
        )


class _DegradedMetalCollector:
    """Metal with the mlx probe unavailable: sysctl-fallback working-set
    budget. The estimate is marked by telemetry_available=False and
    degraded_reason, but it is still a device-level budget — and a
    conservative one at that."""

    async def get_snapshot(self):
        return DeviceSummary(
            timestamp=datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc),
            mode="metal",
            nvidia_smi_available=False,
            telemetry_available=False,
            degraded_reason="mlx device_info unavailable — GPU budget estimated from hw.memsize heuristic",
            devices=[
                DeviceInfo(
                    device_id="0",
                    kind="metal",
                    name="Apple Silicon GPU",
                    memory_used_mb=9000.0,
                    memory_total_mb=28000.0,
                    memory_free_mb=19000.0,
                    extra={"source": "sysctl-fallback", "unified_memory": True},
                )
            ],
            total_memory_mb=28000.0,
            used_memory_mb=9000.0,
            free_memory_mb=19000.0,
        )


class _NvidiaCollector:
    async def get_snapshot(self):
        return DeviceSummary(
            timestamp=datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc),
            mode="nvidia",
            nvidia_smi_available=True,
            telemetry_available=True,
            degraded_reason="",
            devices=[],
            total_memory_mb=8192.0,
            used_memory_mb=1024.0,
            free_memory_mb=7168.0,
        )


class _Bridge:
    worker_id = "worker-1"

    def transport_status(self):
        return WorkerTransportStatus(
            connected=True,
            worker_id=self.worker_id,
        )


def _make_app(lanes, collector=None):
    worker_cfg = SimpleNamespace(
        name="logos-workernode",
        max_lanes=0,
        gpu_performance_score=100,
    )
    # build_runtime_status reads engines.vllm.disable_sleep_mode for the
    # worker-wide sleep-mode kill switch reported in WorkerRuntimeStatus.
    engines_cfg = SimpleNamespace(vllm=SimpleNamespace(disable_sleep_mode=False))
    state = SimpleNamespace(
        config=SimpleNamespace(worker=worker_cfg, engines=engines_cfg),
        lane_manager=_LaneManager(lanes),
        gpu_collector=collector or _GpuCollector(),
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


@pytest.mark.asyncio
async def test_build_runtime_status_preserves_measured_metal_telemetry(monkeypatch):
    """A healthy Metal snapshot leaves nvidia_smi_available False by design
    (its measured working set is not nvidia-smi data) but sets
    telemetry_available. It must not be discarded for the derived summary —
    that would replace the measured working-set budget with host memory and
    gate lane loads on the wrong numbers."""
    monkeypatch.setattr(
        "logos_worker_node.runtime._read_proc_meminfo_mb",
        lambda: (36864.0, 8192.0, 28672.0),
    )

    runtime = await build_runtime_status(_make_app([], _MetalCollector()))

    assert runtime.devices.mode == "metal"
    assert runtime.devices.nvidia_smi_available is False
    assert runtime.devices.telemetry_available is True
    assert runtime.devices.total_memory_mb == 24000.0
    assert runtime.devices.used_memory_mb == 12000.0
    assert runtime.devices.free_memory_mb == 12000.0
    assert runtime.capacity.free_memory_mb == 12000.0


@pytest.mark.asyncio
async def test_build_runtime_status_preserves_degraded_metal_telemetry(monkeypatch):
    """A degraded Metal snapshot (sysctl-fallback budget, telemetry_available
    False) is still device-level data: the conservative working-set estimate
    plus real wired-page usage. Replacing it with the derived summary would
    report the full host hw.memsize as the device budget on macOS —
    overstating the Metal working set by ~22% and letting the orchestrator
    over-schedule the node. The snapshot's telemetry_available=False already
    tells the flag-gating consumers to keep their conservative values."""
    monkeypatch.setattr(
        "logos_worker_node.runtime._read_proc_meminfo_mb",
        # Host RAM, deliberately larger than the working-set estimate:
        # leaking this number into the device budget is the regression.
        lambda: (36864.0, 8192.0, 28672.0),
    )

    runtime = await build_runtime_status(_make_app([], _DegradedMetalCollector()))

    assert runtime.devices.mode == "metal"
    assert runtime.devices.telemetry_available is False
    assert runtime.devices.degraded_reason.startswith("mlx device_info unavailable")
    assert runtime.devices.total_memory_mb == 28000.0
    assert runtime.devices.free_memory_mb == 19000.0
    assert runtime.devices.devices[0].extra["source"] == "sysctl-fallback"
    assert runtime.capacity.free_memory_mb == 19000.0


@pytest.mark.asyncio
async def test_build_runtime_status_preserves_measured_nvidia_telemetry(monkeypatch):
    """The measured/derived decision is the OR of both availability flags:
    an nvidia-smi snapshot must keep passing through unchanged."""
    monkeypatch.setattr(
        "logos_worker_node.runtime._read_proc_meminfo_mb",
        lambda: (16384.0, 4096.0, 12288.0),
    )

    runtime = await build_runtime_status(_make_app([], _NvidiaCollector()))

    assert runtime.devices.mode == "nvidia"
    assert runtime.devices.nvidia_smi_available is True
    assert runtime.devices.total_memory_mb == 8192.0
    assert runtime.capacity.free_memory_mb == 7168.0
