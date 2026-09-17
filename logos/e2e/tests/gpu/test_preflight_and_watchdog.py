"""Toolchain preflight, and the escalation path for a GPU nothing can recover.

The preflight cases are why the simulator supports an isolated ``PATH``: the
worker looks for ``nvcc`` and a C compiler with ``shutil.which``, so the only
way to genuinely reproduce "the image was built without CUDA toolkit
visibility" is to control the whole search path.

The watchdog case closes the loop the corpus opens. A wedged GPU is classified
from nvidia-smi output (``test_gpu_telemetry``), but classification only matters
if it escalates — and the escalation is a host reboot, which must not fire on a
transient blip, during startup, or twice in a row.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from harness import lane as lane_harness
from harness.gpusim.scenario import GpuScenario

from logos_worker_node.gpu_watchdog import GpuWatchdog
from logos_worker_node.node_health import evaluate_node_health

#: Everything except the toolchain binary each test wants missing.
WITHOUT_NVCC = ("nvidia-smi", "vllm", "cc", "gcc")
WITHOUT_COMPILER = ("nvidia-smi", "vllm", "nvcc")


async def test_missing_nvcc_fails_before_the_process_is_spawned(gpu_sim, lane):
    """A lane with no CUDA toolkit must fail with instructions, not a timeout.

    Without the preflight this surfaces ten minutes later as "vLLM did not
    become ready", with the real cause buried in a FlashInfer JIT traceback.
    """
    env = gpu_sim(GpuScenario.homogeneous("l40s", 1), tools=WITHOUT_NVCC, path_mode="isolated")

    async with lane() as handle:
        error = await lane_harness.try_spawn(handle, lane_harness.lane_config())

        assert isinstance(error, RuntimeError)
        assert "nvcc" in str(error)
        assert "CUDA_HOME" in str(error), "the error does not say how to fix it"
        assert env.invocations() == [], "vLLM was spawned despite the failed preflight"


async def test_missing_c_compiler_fails_before_the_process_is_spawned(gpu_sim, lane):
    env = gpu_sim(GpuScenario.homogeneous("l40s", 1), tools=WITHOUT_COMPILER, path_mode="isolated")

    async with lane() as handle:
        error = await lane_harness.try_spawn(handle, lane_harness.lane_config())

        assert isinstance(error, RuntimeError)
        assert "No C compiler found" in str(error)
        assert env.invocations() == [], "vLLM was spawned despite the failed preflight"


async def test_cpu_only_lane_does_not_require_the_cuda_toolkit(gpu_sim, lane):
    """``gpu_devices="none"`` is a legitimate configuration; nvcc is irrelevant to it."""
    env = gpu_sim(GpuScenario.homogeneous("l40s", 1), tools=WITHOUT_NVCC, path_mode="isolated")

    async with lane(worker_overrides={"gpu_devices": "none"}) as handle:
        config = lane_harness.lane_config()
        config.gpu_devices = "none"
        await handle.spawn(config)

        assert env.invocations(), "the lane never started"


# ---------------------------------------------------------------------------
# Watchdog escalation
# ---------------------------------------------------------------------------


@pytest.fixture
def watchdog(tmp_path):
    """A watchdog with the reboot replaced by a recorder.

    ``reboot_fn`` exists in the production code as an injection point for
    exactly this — nothing here needs to be monkeypatched.
    """
    reboots: list[str] = []
    instance = GpuWatchdog(
        state_dir=tmp_path / "state",
        trigger_threshold=3,
        startup_grace_seconds=0.0,
        rate_limit_seconds=1800.0,
        reboot_fn=lambda *args, **kwargs: reboots.append("reboot"),
    )
    instance.reboots = reboots  # type: ignore[attr-defined]
    return instance


async def test_sustained_gpu_wedge_escalates_to_a_host_reboot(gpu_sim, watchdog):
    env = gpu_sim(GpuScenario.homogeneous("rtx6000ada", 1))
    with env.mutate() as sim:
        sim.wedge_device(0)

    await watchdog.start()
    try:
        for _ in range(3):
            watchdog.record_tick(evaluate_node_health())
    finally:
        await watchdog.stop()

    assert watchdog.reboots, "three consecutive wedge ticks did not trigger the reboot"

    diagnostics = sorted((Path(watchdog._state_dir) / "gpu_watchdog_diagnostics").glob("*.log"))
    assert diagnostics, "no diagnostics dump was written — the postmortem has nothing to read"
    dump = diagnostics[-1].read_text()
    assert "gpu-error" in dump
    assert "NVIDIA-SMI" in dump, "the nvidia-smi capture is missing from the dump"


async def test_a_single_bad_tick_does_not_reboot(gpu_sim, watchdog):
    """One noisy poll is not a wedge. Rebooting on it costs the node every
    in-flight request for a reading that clears on the next tick."""
    env = gpu_sim(GpuScenario.homogeneous("rtx6000ada", 1))

    await watchdog.start()
    try:
        with env.mutate() as sim:
            sim.wedge_device(0)
        watchdog.record_tick(evaluate_node_health())

        with env.mutate() as sim:
            sim.unwedge_device(0)
        for _ in range(3):
            watchdog.record_tick(evaluate_node_health())
    finally:
        await watchdog.stop()

    assert not watchdog.reboots, "a transient blip triggered a host reboot"


async def test_startup_grace_blocks_the_reboot(gpu_sim, tmp_path):
    """A GPU already wedged at container start must not cause a boot loop."""
    env = gpu_sim(GpuScenario.homogeneous("rtx6000ada", 1))
    with env.mutate() as sim:
        sim.wedge_device(0)

    reboots: list[str] = []
    guarded = GpuWatchdog(
        state_dir=tmp_path / "state",
        trigger_threshold=2,
        startup_grace_seconds=300.0,
        reboot_fn=lambda *a, **k: reboots.append("reboot"),
    )
    await guarded.start()
    try:
        for _ in range(5):
            guarded.record_tick(evaluate_node_health())
    finally:
        await guarded.stop()

    assert not reboots, "the watchdog rebooted during its startup grace period"


async def test_rate_limit_survives_the_reboot_it_caused(gpu_sim, tmp_path):
    """A GPU that comes back wedged is an operator problem, not a reboot problem.

    The marker lives on disk so the limit holds across the restart — otherwise
    a hardware fault turns into an endless reboot cycle.
    """
    env = gpu_sim(GpuScenario.homogeneous("rtx6000ada", 1))
    with env.mutate() as sim:
        sim.wedge_device(0)

    state_dir = tmp_path / "state"
    reboots: list[str] = []

    def _make() -> GpuWatchdog:
        return GpuWatchdog(
            state_dir=state_dir,
            trigger_threshold=2,
            startup_grace_seconds=0.0,
            rate_limit_seconds=1800.0,
            reboot_fn=lambda *a, **k: reboots.append("reboot"),
        )

    first = _make()
    await first.start()
    try:
        for _ in range(2):
            first.record_tick(evaluate_node_health())
    finally:
        await first.stop()
    assert len(reboots) == 1

    # A fresh process after the reboot, finding the same wedged card.
    second = _make()
    await second.start()
    try:
        for _ in range(4):
            second.record_tick(evaluate_node_health())
    finally:
        await second.stop()

    assert len(reboots) == 1, "the watchdog rebooted again inside the rate-limit window"
