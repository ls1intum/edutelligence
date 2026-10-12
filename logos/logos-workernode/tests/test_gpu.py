from __future__ import annotations

import pytest

from logos_worker_node.gpu import GpuMetricsCollector


@pytest.mark.asyncio
async def test_gpu_collector_keeps_device_with_partial_telemetry() -> None:
    collector = GpuMetricsCollector()
    collector._available = True
    collector._run_nvidia_smi = lambda: (
        "0, GPU-aaa, Quadro RTX 5000, 10864, 16384, 0, 44, 42.47\n"
        "1, GPU-bbb, Quadro RTX 5000, 10864, 16384, [N/A], [N/A], [N/A]\n"
    )

    await collector._poll()
    snapshot = await collector.get_snapshot()

    assert len(snapshot.devices) == 2
    assert snapshot.total_memory_mb == 32768.0
    assert snapshot.used_memory_mb == 21728.0
    assert snapshot.free_memory_mb == 11040.0
    assert snapshot.devices[1].device_id == "GPU-bbb"
    assert snapshot.devices[1].utilization_percent is None
    assert snapshot.devices[1].temperature_celsius is None
    assert snapshot.devices[1].power_draw_watts is None
    assert "gpu1: missing utilization, temperature" in snapshot.degraded_reason
    assert snapshot.devices[1].health == "degraded"
    assert snapshot.devices[0].health == "ok"
    assert snapshot.gpu_faults == []


@pytest.mark.asyncio
async def test_gpu_collector_marks_gpu_that_requires_reset_as_faulted() -> None:
    collector = GpuMetricsCollector()
    collector._available = True
    collector._run_nvidia_smi = lambda: (
        "0, GPU-aaa, RTX PRO 6000, 82989, 97887, [N/A], [GPU requires reset], [N/A]\n"
        "1, GPU-bbb, RTX PRO 6000, 4, 97887, 0, 34, 11.58\n"
    )

    await collector._poll()
    snapshot = await collector.get_snapshot()

    assert [device.health for device in snapshot.devices] == ["faulted", "ok"]
    assert snapshot.devices[0].health_reason == "GPU requires reset"
    assert snapshot.devices[0].memory_used_mb == 82989.0
    assert snapshot.gpu_faults == ["gpu0 (GPU-aaa): GPU requires reset"]
    assert snapshot.faulted_gpu_indices == [0]
    assert "gpu0: faulted (GPU requires reset)" in snapshot.degraded_reason


@pytest.mark.asyncio
async def test_gpu_collector_reports_fault_of_gpu_without_memory_reading() -> None:
    collector = GpuMetricsCollector()
    collector._available = True
    collector._run_nvidia_smi = lambda: (
        "0, GPU-aaa, RTX PRO 6000, [GPU is lost], [GPU is lost], [GPU is lost], [GPU is lost], [GPU is lost]\n"
        "1, GPU-bbb, RTX PRO 6000, 4, 97887, 0, 34, 11.58\n"
    )

    await collector._poll()
    snapshot = await collector.get_snapshot()

    assert [device.device_id for device in snapshot.devices] == ["GPU-bbb"]
    assert snapshot.gpu_faults == ["gpu0 (GPU-aaa): GPU is lost"]
    assert snapshot.faulted_gpu_indices == [0]


@pytest.mark.asyncio
async def test_gpu_collector_reports_compute_capability():
    collector = GpuMetricsCollector()
    collector._run_nvidia_smi = lambda: "0, GPU-aaa, Quadro RTX 5000, 0, 16384, 0, 44, 42.47, 7.5"
    await collector._poll()
    assert (await collector.get_snapshot()).devices[0].extra["compute_capability"] == "7.5"


def test_unsupported_compute_cap_query_preserves_memory_telemetry(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    run = Mock(side_effect=[SimpleNamespace(returncode=1), SimpleNamespace(returncode=0, stdout="legacy telemetry")])
    monkeypatch.setattr("logos_worker_node.gpu.subprocess.run", run)
    assert GpuMetricsCollector._run_nvidia_smi() == "legacy telemetry"
    assert "compute_cap" in run.call_args_list[0].args[0][1]
    assert "compute_cap" not in run.call_args_list[1].args[0][1]
