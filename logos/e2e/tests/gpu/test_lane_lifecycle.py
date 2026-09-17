"""Lane lifecycle against simulated hardware: serve, sleep, wake, die, leak.

The VRAM assertions here are the reason the simulator keeps a ledger rather
than returning canned telemetry. A lane that exits without its memory being
reclaimed is indistinguishable from a healthy one in every log line — the only
evidence is ``nvidia-smi --query-compute-apps`` still naming the dead pid, which
is exactly what ``_verify_vram_released`` polls for. Simulating that faithfully
is what makes the stuck-VRAM path testable without a GPU.
"""

from __future__ import annotations

import httpx
import pytest
from harness import lane as lane_harness
from harness.gpusim.scenario import GpuProfile, GpuScenario, VllmScript

L40S_TOTAL_MB = GpuProfile.load("l40s").memory_total_mb


async def test_healthy_lane_serves_and_gives_its_memory_back(gpu_sim, lane):
    env = gpu_sim(GpuScenario.homogeneous("l40s", 1))

    async with lane() as handle:
        await handle.spawn(lane_harness.lane_config(gpu_memory_utilization=0.85))

        assert env.used_mb(0) == pytest.approx(L40S_TOTAL_MB * 0.85, rel=0.01)
        assert handle.last_cold_load_s is not None, "cold-load duration was not recorded"

        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{handle.port}") as client:
            response = await client.post(
                "/v1/chat/completions",
                json={"model": lane_harness.DEFAULT_MODEL, "messages": [{"role": "user", "content": "hi"}]},
            )
        assert response.status_code == 200
        assert response.json()["choices"][0]["message"]["content"]

        await handle.stop()

        assert handle.has_stuck_vram is False
        assert env.used_mb(0) == 0.0, "VRAM was not released after a clean stop"


async def test_leaked_cuda_context_is_detected_as_stuck_vram(gpu_sim, lane):
    """The process is gone but the driver never reclaimed its context.

    This is the failure that a lane restart cannot fix and that the watchdog
    escalates to a host reboot, so mis-detecting it in either direction is
    costly: a false negative leaves the node silently unable to serve, a false
    positive reboots a healthy host.
    """
    env = gpu_sim(GpuScenario.homogeneous("l40s", 1), VllmScript(leak_vram=True))

    async with lane() as handle:
        await handle.spawn(lane_harness.lane_config(gpu_memory_utilization=0.5))
        leaked_mb = env.used_mb(0)
        assert leaked_mb > 0

        await handle.stop()

        assert handle.has_stuck_vram is True
        assert env.used_mb(0) == pytest.approx(leaked_mb), "the leaked allocation was reclaimed after all"
        assert env.leaked_pids(), "no pid is holding the leaked context"


async def test_sleep_and_wake_round_trip(gpu_sim, lane):
    gpu_sim(GpuScenario.homogeneous("l40s", 1))

    async with lane() as handle:
        await handle.spawn(lane_harness.lane_config(enable_sleep_mode=True))

        assert await handle.is_sleeping() is False

        await handle.sleep(level=1)
        assert await handle.is_sleeping() is True

        await handle.wake_up()
        assert await handle.is_sleeping() is False
        assert handle.last_wake_from_sleep_s is not None, "wake duration was not recorded"


async def test_sleep_is_refused_when_the_lane_did_not_enable_it(gpu_sim, lane):
    """Calling /sleep on a lane without dev mode would 404 in production.

    The worker is expected to refuse before the HTTP call, with a message
    naming the config keys to set.
    """
    gpu_sim(GpuScenario.homogeneous("l40s", 1))

    async with lane() as handle:
        await handle.spawn(lane_harness.lane_config(enable_sleep_mode=False))

        with pytest.raises(RuntimeError, match="Sleep mode is disabled"):
            await handle.sleep()


async def test_engine_core_wedge_is_visible_even_though_health_is_green(gpu_sim, lane):
    """The API server outlives its EngineCore — the nastiest liveness case.

    ``/health`` and ``/v1/models`` keep answering 200, so every ordinary probe
    says the lane is fine, while ``/is_sleeping`` hangs because it has to
    round-trip to the engine over ZMQ. The consecutive-failure counter is the
    only signal the lane manager can escalate on.
    """
    gpu_sim(GpuScenario.homogeneous("l40s", 1), VllmScript(wedge_engine_core=True))

    async with lane() as handle:
        await handle.spawn(lane_harness.lane_config(enable_sleep_mode=True))

        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{handle.port}") as client:
            assert (await client.get("/health")).status_code == 200
            assert (await client.get("/v1/models")).status_code == 200

        for _ in range(2):
            assert await handle.is_sleeping() is None
        assert handle.consecutive_liveness_failures >= 2, (
            "a wedged EngineCore did not accumulate liveness failures — " "the lane manager has nothing to escalate on"
        )


async def test_lane_that_never_becomes_ready_fails_with_the_logs_attached(gpu_sim, lane, monkeypatch):
    """A startup timeout must report why, not just that it timed out.

    ``LOGOS_VLLM_READY_TIMEOUT_S`` is read once at import and floored at 60s, so
    the module constant is what a test can shorten; setting the variable here
    would leave the spawn waiting the full production timeout.
    """
    monkeypatch.setattr("logos_worker_node.vllm_process._READY_TIMEOUT", 3)
    gpu_sim(GpuScenario.homogeneous("l40s", 1), VllmScript(ready_after_s=600))

    async with lane() as handle:
        error = await lane_harness.try_spawn(handle, lane_harness.lane_config())

        assert error is not None
        assert "did not become ready" in str(error)
        assert "Maximum concurrency" in str(error), "the captured startup logs were not attached to the failure"


async def test_max_concurrency_is_parsed_from_the_startup_banner(gpu_sim, lane):
    """vLLM reports achievable concurrency once, in a log line, at startup.

    The lane's capacity in the scheduler comes from this number, and it is only
    ever available as prose in a log line — so a change to vLLM's wording
    silently degrades scheduling instead of failing loudly. What the worker
    keeps is the concurrency *factor* (the ``12.50x``), not the token count it
    is quoted against.
    """
    gpu_sim(GpuScenario.homogeneous("l40s", 1), VllmScript(max_concurrency=12.5, max_concurrency_tokens=65536))

    async with lane() as handle:
        await handle.spawn(lane_harness.lane_config())
        assert handle.max_concurrency == 12


async def test_backend_metrics_are_read_from_the_prometheus_endpoint(gpu_sim, lane):
    gpu_sim(GpuScenario.homogeneous("l40s", 1))

    async with lane() as handle:
        await handle.spawn(lane_harness.lane_config())

        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{handle.port}") as client:
            await client.post(
                "/v1/chat/completions",
                json={"model": lane_harness.DEFAULT_MODEL, "messages": [{"role": "user", "content": "hi"}]},
            )

        metrics = await handle.get_backend_metrics()
        assert metrics["engine"] == "vllm"
        assert metrics["queue_waiting"] == 0.0
        assert metrics["gpu_cache_usage_percent"] == pytest.approx(12.0)
        assert metrics["prompt_tokens_total"] == pytest.approx(16.0)
        assert metrics["prefix_cache_hit_rate"] == pytest.approx(0.25)
