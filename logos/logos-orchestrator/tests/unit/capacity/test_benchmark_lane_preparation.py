from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from logos.capacity.capacity_planner import CapacityPlanner


def _lane(runtime_state, sleep_state):
    return SimpleNamespace(
        lane_id="model-lane",
        model_name="org/model",
        runtime_state=runtime_state,
        sleep_state=sleep_state,
        queue_waiting=0,
        requests_running=0,
        active_requests=0,
        ttft_p95_seconds=0,
        e2e_latency_p50_seconds=0,
        effective_vram_mb=0,
    )


def _planner(target):
    planner = object.__new__(CapacityPlanner)
    planner._registry = MagicMock()
    planner._registry.has_received_first_status.return_value = True
    planner._facade = MagicMock()
    planner._facade.get_scheduler_queue_depth_by_model_name.return_value = 0
    planner._pick_request_target_lane = MagicMock(return_value=target)
    planner._safe_get_lanes = MagicMock(return_value=[])
    planner._safe_get_profiles = MagicMock(return_value={})
    planner._prepare_existing_lane = AsyncMock()
    planner._cold_load_for_request = AsyncMock()
    return planner


@pytest.mark.asyncio
async def test_benchmark_lane_reuses_ready_lane_on_exact_worker():
    planner = _planner(_lane("loaded", "awake"))

    assert await planner.prepare_benchmark_lane(7, "org/model") is True
    planner._prepare_existing_lane.assert_not_awaited()
    planner._cold_load_for_request.assert_not_awaited()


@pytest.mark.asyncio
async def test_benchmark_lane_wakes_sleeping_lane_with_normal_capacity_handling():
    target = _lane("sleeping", "sleeping")
    ready = _lane("loaded", "awake")
    planner = _planner(target)
    planner._pick_request_target_lane.side_effect = [target, ready]
    planner._prepare_existing_lane.return_value = {"lane_id": "model-lane"}

    assert await planner.prepare_benchmark_lane(7, "org/model", 30.0) is True
    planner._prepare_existing_lane.assert_awaited_once_with(
        7,
        "org/model",
        target,
        30.0,
        raise_on_failure=True,
    )
    planner._cold_load_for_request.assert_not_awaited()


@pytest.mark.asyncio
async def test_benchmark_lane_cold_loads_with_normal_capacity_handling():
    ready = _lane("loaded", "awake")
    planner = _planner(None)
    planner._pick_request_target_lane.side_effect = [None, ready]
    planner._cold_load_for_request.return_value = {"lane_id": "model-lane"}

    assert await planner.prepare_benchmark_lane(7, "org/model", 30.0) is True
    planner._cold_load_for_request.assert_awaited_once_with(
        7,
        "org/model",
        30.0,
        raise_on_failure=True,
    )


@pytest.mark.asyncio
async def test_benchmark_lane_waits_for_starting_lane():
    starting = _lane("starting", "unsupported")
    ready = _lane("loaded", "awake")
    planner = _planner(starting)
    planner._pick_request_target_lane.side_effect = [starting, ready]
    planner._safe_get_lanes.return_value = [ready]

    assert await planner.prepare_benchmark_lane(7, "org/model", 30.0) is True
    planner._prepare_existing_lane.assert_not_awaited()
    planner._cold_load_for_request.assert_not_awaited()


@pytest.mark.asyncio
async def test_benchmark_lane_allows_concurrent_requests():
    target = _lane("loaded", "awake")
    target.active_requests = 1
    planner = _planner(target)
    planner._safe_get_lanes.return_value = [target]

    assert await planner.prepare_benchmark_lane(7, "org/model") is True


@pytest.mark.asyncio
async def test_benchmark_lane_loads_while_other_requests_are_queued():
    ready = _lane("loaded", "awake")
    planner = _planner(None)
    planner._pick_request_target_lane.side_effect = [None, ready]
    planner._facade.get_scheduler_queue_depth_by_model_name.return_value = 1

    assert await planner.prepare_benchmark_lane(7, "org/model") is True
    planner._cold_load_for_request.assert_awaited_once()


@pytest.mark.asyncio
async def test_benchmark_lane_fails_fast_when_an_existing_start_errors():
    starting = _lane("starting", "unsupported")
    planner = _planner(starting)
    planner._safe_get_lanes.return_value = [_lane("error", "unsupported")]

    with pytest.raises(RuntimeError, match="failed to start on worker 7"):
        await planner.prepare_benchmark_lane(7, "org/model", 30.0)
    planner._prepare_existing_lane.assert_not_awaited()
    planner._cold_load_for_request.assert_not_awaited()


def _configured_planner():
    import asyncio
    from unittest.mock import MagicMock

    from logos.benchmarks.configuration import ServingOverrides

    target = _lane("loaded", "awake")
    planner = _planner(target)
    planner.prepare_benchmark_lane = AsyncMock(return_value=True)
    planner._lane_lock = MagicMock(return_value=asyncio.Lock())
    planner._mark_lane_cold = MagicMock()
    planner._unmark_lane_cold = MagicMock()
    current = {"dtype": "auto", "enable_sleep_mode": True, "tensor_parallel_size": 1}
    updated = {**current, "tensor_parallel_size": 2}

    def snapshot(config):
        return {
            "runtime": {
                "lanes": [
                    {
                        "lane_id": target.lane_id,
                        "model": target.model_name,
                        "lane_config": {"vllm": True, "vllm_config": config},
                    }
                ]
            }
        }

    planner._registry.peek_runtime_snapshot.side_effect = [snapshot(current), snapshot(updated)]
    planner._registry.send_command = AsyncMock(return_value={"lane_config": {"vllm_config": updated}})
    return planner, ServingOverrides(tensor_parallel_size=2), updated


async def test_configured_benchmark_waits_for_worker_configuration():
    planner, overrides, updated = _configured_planner()
    stages = []
    assert (
        await planner.prepare_configured_benchmark_lane(7, "org/model", overrides, progress_callback=stages.append)
        is True
    )
    assert stages == ["reconfiguring_worker", "waiting_for_model"]
    planner._registry.send_command.assert_awaited_once_with(
        7,
        "reconfigure_lane",
        {"lane_id": "model-lane", "updates": {"vllm_config": updated}, "require_idle": True},
        timeout_seconds=600,
    )
    planner._unmark_lane_cold.assert_called_once_with(7, "model-lane")
    assert planner.prepare_benchmark_lane.await_count == 2


async def test_configured_benchmark_restores_routing_if_worker_refuses():
    planner, overrides, _ = _configured_planner()
    planner._registry.send_command.side_effect = RuntimeError("Requests are active")
    with pytest.raises(RuntimeError, match="Requests are active"):
        await planner.prepare_configured_benchmark_lane(7, "org/model", overrides)
    planner._unmark_lane_cold.assert_called_once_with(7, "model-lane")


async def test_configured_benchmark_allows_requests_on_other_lanes():
    planner, overrides, _ = _configured_planner()
    other = _lane("running", "awake")
    other.lane_id = "other-lane"
    other.active_requests = 2
    planner._safe_get_lanes.return_value = [other]
    assert await planner.prepare_configured_benchmark_lane(7, "org/model", overrides) is True
    planner._registry.send_command.assert_awaited_once()


async def test_unchanged_serving_settings_do_not_restart_busy_model():
    from logos.benchmarks.configuration import ServingOverrides

    planner, _, _ = _configured_planner()
    target = _lane("running", "awake")
    target.active_requests = 1
    planner._safe_get_lanes.return_value = [target]
    assert (
        await planner.prepare_configured_benchmark_lane(7, "org/model", ServingOverrides(tensor_parallel_size=1))
        is True
    )
    planner._registry.send_command.assert_not_awaited()


async def test_benchmark_reports_missing_worker_status():
    planner = _planner(None)
    planner._registry.has_received_first_status.return_value = False
    with pytest.raises(RuntimeError, match="Worker 7 has not reported its status"):
        await planner.prepare_benchmark_lane(7, "org/model")
    planner._cold_load_for_request.assert_not_awaited()


async def test_benchmark_reports_startup_timeout():
    target = _lane("starting", "unsupported")
    planner = _planner(target)
    planner._safe_get_lanes.return_value = [target]
    with pytest.raises(RuntimeError, match="did not become ready within 0 seconds"):
        await planner.prepare_benchmark_lane(7, "org/model", 0)


async def test_benchmark_reports_missing_capacity():
    planner = _planner(None)
    planner._safe_get_capacity = MagicMock(return_value=None)
    with pytest.raises(RuntimeError, match="Worker capacity information is unavailable"):
        await CapacityPlanner._cold_load_for_request(planner, 7, "org/model", 30, raise_on_failure=True)
    # Normal request callers retain their existing retry/None behavior.
    assert await CapacityPlanner._cold_load_for_request(planner, 7, "org/model", 30) is None


async def test_benchmark_reports_gpu_capacity_failure():
    target = _lane("cold", "unsupported")
    planner = _planner(target)
    planner._ensure_request_capacity = AsyncMock(return_value=False)
    with pytest.raises(RuntimeError, match="Could not make enough GPU capacity"):
        await CapacityPlanner._prepare_existing_lane(planner, 7, "org/model", target, 30, raise_on_failure=True)
    planner._registry.select_lane_for_model.assert_not_called()


async def test_configured_benchmark_rejects_worker_override_without_polling():
    planner, overrides, updated = _configured_planner()
    planner._registry.send_command.return_value = {
        "lane_config": {"vllm_config": {**updated, "tensor_parallel_size": 1}}
    }
    with pytest.raises(RuntimeError, match="tensor_parallel_size: requested 2, reported 1"):
        await planner.prepare_configured_benchmark_lane(7, "org/model", overrides)
    assert planner._registry.peek_runtime_snapshot.call_count == 1
    planner._unmark_lane_cold.assert_called_once_with(7, "model-lane")


async def test_configured_benchmark_reports_missing_status_confirmation():
    planner, overrides, _ = _configured_planner()
    with pytest.raises(RuntimeError, match="applied the vLLM settings but did not report them"):
        await planner.prepare_configured_benchmark_lane(7, "org/model", overrides, timeout_seconds=0)
    assert planner.prepare_benchmark_lane.await_count == 1
    planner._unmark_lane_cold.assert_called_once_with(7, "model-lane")
