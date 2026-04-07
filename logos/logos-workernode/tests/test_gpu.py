from __future__ import annotations

import pytest

from logos_worker_node.gpu import GpuMetricsCollector


@pytest.mark.asyncio
async def test_gpu_collector_keeps_device_with_partial_telemetry() -> None:
    collector = GpuMetricsCollector()
    collector._available = True
    collector._run_nvidia_smi = lambda: (
        "0, GPU-aaa, Quadro RTX 5000, 10864, 16384, 0, 44, 42.47\n"
        "1, GPU-bbb, Quadro RTX 5000, 10864, 16384, [N/A], [GPU requires reset], [N/A]\n"
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
