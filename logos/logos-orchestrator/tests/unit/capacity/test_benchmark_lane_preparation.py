from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from logos.capacity.capacity_planner import CapacityPlanner


def _planner(target):
    planner = object.__new__(CapacityPlanner)
    planner._registry = MagicMock()
    planner._registry.has_received_first_status.return_value = True
    planner._pick_request_target_lane = MagicMock(return_value=target)
    planner._prepare_existing_lane = AsyncMock()
    planner._cold_load_for_request = AsyncMock()
    return planner


@pytest.mark.asyncio
async def test_benchmark_lane_reuses_ready_lane_on_exact_worker():
    planner = _planner(SimpleNamespace(runtime_state="loaded", sleep_state="awake"))

    assert await planner.prepare_benchmark_lane(7, "org/model") is True
    planner._prepare_existing_lane.assert_not_awaited()
    planner._cold_load_for_request.assert_not_awaited()


@pytest.mark.asyncio
async def test_benchmark_lane_wakes_sleeping_lane_on_exact_worker():
    target = SimpleNamespace(runtime_state="sleeping", sleep_state="sleeping")
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
    starting = SimpleNamespace(runtime_state="starting", sleep_state="unsupported")
    ready = SimpleNamespace(runtime_state="loaded", sleep_state="awake")
    planner = _planner(starting)
    planner._pick_request_target_lane.side_effect = [starting, ready]

    assert await planner.prepare_benchmark_lane(7, "org/model", 30.0) is True
    planner._prepare_existing_lane.assert_not_awaited()
    planner._cold_load_for_request.assert_not_awaited()
