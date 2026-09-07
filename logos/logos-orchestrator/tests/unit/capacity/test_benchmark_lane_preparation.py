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
async def test_benchmark_lane_wakes_sleeping_lane_without_reclaim():
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
        allow_reclaim=False,
    )
    planner._cold_load_for_request.assert_not_awaited()


@pytest.mark.asyncio
async def test_benchmark_lane_cold_loads_without_reclaim():
    ready = _lane("loaded", "awake")
    planner = _planner(None)
    planner._pick_request_target_lane.side_effect = [None, ready]
    planner._cold_load_for_request.return_value = {"lane_id": "model-lane"}

    assert await planner.prepare_benchmark_lane(7, "org/model", 30.0) is True
    planner._cold_load_for_request.assert_awaited_once_with(
        7,
        "org/model",
        30.0,
        allow_reclaim=False,
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
async def test_benchmark_lane_rejects_production_load():
    target = _lane("loaded", "awake")
    target.active_requests = 1
    planner = _planner(target)
    planner._safe_get_lanes.return_value = [target]

    assert await planner.prepare_benchmark_lane(7, "org/model") is False


@pytest.mark.asyncio
async def test_benchmark_lane_does_not_load_while_production_request_is_queued():
    planner = _planner(None)
    planner._safe_get_profiles.return_value = {"org/model": MagicMock()}
    planner._facade.get_scheduler_queue_depth_by_model_name.return_value = 1

    assert await planner.prepare_benchmark_lane(7, "org/model") is False
    planner._cold_load_for_request.assert_not_awaited()


@pytest.mark.asyncio
async def test_benchmark_lane_fails_fast_when_an_existing_start_errors():
    starting = _lane("starting", "unsupported")
    planner = _planner(starting)
    planner._safe_get_lanes.return_value = [_lane("error", "unsupported")]

    assert await planner.prepare_benchmark_lane(7, "org/model", 30.0) is False
    planner._prepare_existing_lane.assert_not_awaited()
    planner._cold_load_for_request.assert_not_awaited()


def _configured_planner():
    from logos.benchmarks.configuration import ServingOverrides
    from unittest.mock import MagicMock
    import asyncio
    target = _lane("loaded", "awake")
    planner = _planner(target)
    planner.prepare_benchmark_lane = AsyncMock(return_value=True)
    planner._lane_lock = MagicMock(return_value=asyncio.Lock())
    planner._mark_lane_cold = MagicMock()
    planner._unmark_lane_cold = MagicMock()
    current = {"dtype": "auto", "enable_sleep_mode": True, "tensor_parallel_size": 1}
    updated = {**current, "tensor_parallel_size": 2}
    def snapshot(config):
        return {"runtime": {"lanes": [{"lane_id": target.lane_id, "model": target.model_name,
            "lane_config": {"vllm": True, "vllm_config": config}}]}}
    planner._registry.peek_runtime_snapshot.side_effect = [snapshot(current), snapshot(updated)]
    planner._registry.send_command = AsyncMock(return_value={})
    return planner, ServingOverrides(tensor_parallel_size=2), updated


async def test_configured_benchmark_waits_for_worker_configuration():
    planner, overrides, updated = _configured_planner()
    assert await planner.prepare_configured_benchmark_lane(7, "org/model", overrides) is True
    planner._registry.send_command.assert_awaited_once_with(7, "reconfigure_lane",
        {"lane_id": "model-lane", "updates": {"vllm_config": updated}, "require_idle": True}, timeout_seconds=600)
    planner._unmark_lane_cold.assert_called_once_with(7, "model-lane")
    assert planner.prepare_benchmark_lane.await_count == 2


async def test_configured_benchmark_restores_routing_if_worker_refuses():
    planner, overrides, _ = _configured_planner()
    planner._registry.send_command.side_effect = RuntimeError("Requests are active")
    with pytest.raises(RuntimeError, match="Requests are active"):
        await planner.prepare_configured_benchmark_lane(7, "org/model", overrides)
    planner._unmark_lane_cold.assert_called_once_with(7, "model-lane")


async def test_configured_benchmark_does_not_restart_busy_provider():
    planner, overrides, _ = _configured_planner()
    planner._benchmark_provider_is_idle = MagicMock(return_value=False)
    assert await planner.prepare_configured_benchmark_lane(7, "org/model", overrides) is False
    planner._registry.send_command.assert_not_awaited()
