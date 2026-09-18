"""Degraded GPU telemetry, and the health verdicts derived from it.

These are the states a real node reaches when hardware goes wrong: a GSP RPC
failure that leaves memory readable but flips Pwr/Fan/Temp to ``ERR!``, a card
falling off the PCIe bus, a driver that stops answering. Each one has a distinct
remedy — and the wrong verdict either reboots a healthy host or leaves a dead
one in the scheduler's rotation — so the mapping from nvidia-smi output to
verdict is worth pinning precisely.

None of it needs a GPU: every input is text from a subprocess we own.
"""

from __future__ import annotations

import pytest
from harness.gpusim.scenario import GpuProfile, GpuScenario
from harness.gpusim.state import SmiBehaviour

from logos_worker_node.gpu import GpuMetricsCollector
from logos_worker_node.node_health import evaluate_node_health

L40S = GpuProfile.load("l40s")


async def _snapshot(poll_interval: int = 5):
    collector = GpuMetricsCollector(poll_interval=poll_interval)
    await collector.start()
    try:
        return await collector.get_snapshot()
    finally:
        await collector.stop()


async def test_healthy_node_reports_every_device(gpu_sim):
    gpu_sim(GpuScenario.homogeneous("l40s", 2))

    snapshot = await _snapshot()

    assert snapshot.nvidia_smi_available is True
    assert snapshot.telemetry_available is True
    assert snapshot.degraded_reason == ""
    assert len(snapshot.devices) == 2
    assert snapshot.total_memory_mb == pytest.approx(L40S.memory_total_mb * 2)
    assert {d.name for d in snapshot.devices} == {L40S.name}


async def test_vram_ledger_is_visible_in_the_snapshot(gpu_sim):
    """Used/free must track the ledger, not a fixed number baked into a fixture."""
    env = gpu_sim(GpuScenario.homogeneous("l40s", 1))
    with env.mutate() as sim:
        sim.allocate(pid=4242, device_index=0, mb=20_000)

    snapshot = await _snapshot()

    assert snapshot.used_memory_mb == pytest.approx(20_000)
    assert snapshot.free_memory_mb == pytest.approx(L40S.memory_total_mb - 20_000)


async def test_partial_telemetry_is_reported_as_degraded_not_lost(gpu_sim):
    """Missing power/temperature must not drop the device from the snapshot.

    Memory is the field the capacity planner needs; a card that can still
    report it is schedulable even if its power sensor is unreadable. Dropping
    the whole device here would silently remove capacity from the fleet.
    """
    env = gpu_sim(GpuScenario.homogeneous("l40s", 1))
    with env.mutate() as sim:
        sim.device(0).faults["power.draw"] = "[N/A]"
        sim.device(0).faults["temperature.gpu"] = "ERR!"

    snapshot = await _snapshot()

    assert len(snapshot.devices) == 1
    assert snapshot.devices[0].memory_total_mb == pytest.approx(L40S.memory_total_mb)
    assert "temperature" in snapshot.degraded_reason


async def test_unreadable_memory_drops_the_device(gpu_sim):
    """Without memory telemetry the device cannot be planned against at all."""
    env = gpu_sim(GpuScenario.homogeneous("l40s", 2))
    with env.mutate() as sim:
        sim.device(1).faults["memory.total"] = "ERR!"

    snapshot = await _snapshot()

    assert len(snapshot.devices) == 1
    assert "invalid memory telemetry" in snapshot.degraded_reason


async def test_no_nvidia_smi_means_no_gpu_telemetry_rather_than_a_crash(gpu_sim):
    """A dev laptop is a supported environment; it just cannot run vLLM lanes."""
    gpu_sim(GpuScenario.headless(), tools=("vllm", "nvcc", "cc", "gcc"), path_mode="isolated")

    collector = GpuMetricsCollector()
    await collector.start()
    try:
        assert collector.available is False
        snapshot = await collector.get_snapshot()
        assert snapshot.nvidia_smi_available is False
        assert snapshot.devices == []
    finally:
        await collector.stop()


# ---------------------------------------------------------------------------
# Health verdicts — what the watchdog escalates on
# ---------------------------------------------------------------------------


def gpu_sensor() -> tuple[str, str, bool]:
    """Run the health evaluation and return (state, detail, node_is_healthy).

    Only the GPU sensor's own verdict is asserted on; the other sensors
    (host RAM, disk) depend on whatever machine the suite runs on. The
    aggregate ``healthy`` flag is returned alongside so a test can still check
    that a GPU failure actually makes the node unhealthy.
    """
    health = evaluate_node_health()
    sensor = health.sensors.get("gpu", {})
    return sensor.get("state", "<missing>"), sensor.get("detail", ""), health.healthy


def test_gsp_wedge_is_diagnosed_as_a_gpu_error(gpu_sim):
    """The RTX 6000 Ada / Quadro RTX 5000 signature: memory fine, telemetry ERR!.

    Every CUDA context allocation fails from here on, so the node looks up to
    the scheduler while being unable to serve a single request. Only a host
    reboot clears it.
    """
    env = gpu_sim(GpuScenario.homogeneous("rtx6000ada", 1))
    with env.mutate() as sim:
        sim.wedge_device(0)

    state, detail, healthy = gpu_sensor()

    assert state == "gpu-error", f"expected gpu-error, got {state}: {detail}"
    assert "reboot required" in detail
    assert healthy is False, "a wedged GPU did not make the node unhealthy"


def test_healthy_hardware_produces_no_health_finding(gpu_sim):
    gpu_sim(GpuScenario.homogeneous("rtx6000ada", 1))

    assert gpu_sensor()[0] == "ok"


def test_fanless_card_reporting_na_is_not_treated_as_wedged(gpu_sim):
    """``N/A`` on a telemetry field is legitimate on datacentre cards.

    The A100 and L40S have no fan to report. Reading that as a wedge would
    reboot every such host in the fleet on a loop.
    """
    gpu_sim(GpuScenario.homogeneous("a100_80", 1))

    assert gpu_sensor()[0] == "ok"


def test_driver_query_failure_is_distinguished_from_a_wedged_card(gpu_sim):
    env = gpu_sim(GpuScenario.homogeneous("l40s", 1))
    with env.mutate() as sim:
        sim.smi = SmiBehaviour(exit_code=15, stderr="Unable to determine the device handle for GPU 0000:01:00.0")

    assert gpu_sensor()[0] == "gpu-query-failed"


def test_hung_driver_is_diagnosed_as_a_timeout(gpu_sim):
    """nvidia-smi that never returns means the driver is stuck.

    Distinct from a non-zero exit: it also blocks calibration and every metrics
    poll, so it has its own verdict.
    """
    env = gpu_sim(GpuScenario.homogeneous("l40s", 1))
    with env.mutate() as sim:
        # node_health gives nvidia-smi 10s.
        sim.smi = SmiBehaviour(hang_seconds=20)

    assert gpu_sensor()[0] == "gpu-query-timeout"


def test_missing_nvidia_smi_is_not_a_health_failure(gpu_sim):
    """Absence is a dev host, not a wedge — the sensor must not claim otherwise."""
    gpu_sim(GpuScenario.headless(), tools=("vllm", "nvcc", "cc", "gcc"), path_mode="isolated")

    state, detail, _ = gpu_sensor()

    assert state == "ok"
    assert "dev host" in detail
