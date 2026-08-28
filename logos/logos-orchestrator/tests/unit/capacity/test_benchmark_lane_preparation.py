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
        effective_vram_mb=0,
    )


def _planner(target):
    planner = object.__new__(CapacityPlanner)
    planner._registry = MagicMock()
    planner._registry.has_received_first_status.return_value = True
    planner._pick_request_target_lane = MagicMock(return_value=target)
    planner._safe_get_lanes = MagicMock(return_value=[])
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
async def test_benchmark_lane_wakes_sleeping_lane_on_exact_worker():
    target = _lane("sleeping", "sleeping")
    planner = _planner(target)
    planner._prepare_existing_lane.return_value = {"lane_id": "model-lane"}

    assert await planner.prepare_benchmark_lane(7, "org/model", 30.0) is True
    planner._prepare_existing_lane.assert_awaited_once_with(7, "org/model", target, 30.0)
    planner._cold_load_for_request.assert_not_awaited()


@pytest.mark.asyncio
async def test_benchmark_lane_cold_loads_only_on_selected_worker():
    planner = _planner(None)
    planner._cold_load_for_request.return_value = {"lane_id": "model-lane"}

    assert await planner.prepare_benchmark_lane(7, "org/model", 30.0) is True
    planner._cold_load_for_request.assert_awaited_once_with(7, "org/model", 30.0)


@pytest.mark.asyncio
async def test_benchmark_lane_waits_for_an_existing_start_instead_of_loading_again():
    starting = _lane("starting", "unsupported")
    ready = _lane("loaded", "awake")
    planner = _planner(starting)
    planner._safe_get_lanes.return_value = [ready]

    assert await planner.prepare_benchmark_lane(7, "org/model", 30.0) is True
    planner._prepare_existing_lane.assert_not_awaited()
    planner._cold_load_for_request.assert_not_awaited()


@pytest.mark.asyncio
async def test_benchmark_lane_fails_fast_when_an_existing_start_errors():
    starting = _lane("starting", "unsupported")
    planner = _planner(starting)
    planner._safe_get_lanes.return_value = [_lane("error", "unsupported")]

    assert await planner.prepare_benchmark_lane(7, "org/model", 30.0) is False
    planner._prepare_existing_lane.assert_not_awaited()
    planner._cold_load_for_request.assert_not_awaited()
