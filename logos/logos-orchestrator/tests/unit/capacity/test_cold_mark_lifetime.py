"""The cold mark only covers a lane while the planner takes it out of service.

A sleep or stop marks its lane cold before the drain, so the scheduler stops
routing new requests to a lane that is about to go away. Once the action has
ended, the worker's own runtime state keeps a sleeping or removed lane out of
the rotation, so the mark has nothing left to do. A mark that outlives the
action is never read again until something clears it, and only a confirmed
planner wake does. Every other way back to an awake lane, such as the panel's
wake button, the worker restarting the engine, or a wake confirmed only after
its poll gave up, leaves a lane that the worker reports as loaded and idle
but the scheduler never picks, while its sibling lane takes the entire load.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from logos import CapacityPlanner, LogosNodeRuntimeRegistry
from logos.sdi.models import CapacityPlanAction

PROVIDER_ID = 7
MODEL = "Qwen/Qwen3-Reranker-8B"
BUSY_LANE = "planner-Qwen_Qwen3-Reranker-8B"
IDLE_LANE = "planner-Qwen_Qwen3-Reranker-8B-2"


class _FakeWebSocket:
    async def send_json(self, payload: dict) -> None:  # noqa: ARG002
        return None

    async def close(self) -> None:
        return None


def _lane(lane_id: str, runtime_state: str, sleep_state: str, queue_waiting: float) -> dict:
    return {
        "lane_id": lane_id,
        "model": MODEL,
        "runtime_state": runtime_state,
        "sleep_state": sleep_state,
        "active_requests": 0,
        "backend_metrics": {"queue_waiting": queue_waiting, "requests_running": 1.0 if queue_waiting else 0.0},
    }


async def _registry_with(lanes: list[dict]) -> LogosNodeRuntimeRegistry:
    registry = LogosNodeRuntimeRegistry()
    ticket = await registry.consume_ticket(await registry.issue_ticket(PROVIDER_ID, "worker-a", [MODEL]))
    assert ticket is not None
    await registry.attach_session(ticket, _FakeWebSocket())
    await registry.update_runtime(provider_id=PROVIDER_ID, runtime={"lanes": lanes})
    return registry


def _planner(registry: LogosNodeRuntimeRegistry, worker_lanes: dict[str, dict]) -> CapacityPlanner:
    """A planner running the real executor against the real registry.

    The worker is simulated by ``send_command``: a sleep or wake command
    flips the lane's state and reports the new runtime to the registry, which
    is what the executor's confirmation poll then reads.
    """
    planner = CapacityPlanner.__new__(CapacityPlanner)
    planner._registry = registry
    planner._facade = MagicMock()
    planner._facade.get_provider_name.return_value = "worker-a"
    planner._marked_cold_lanes = set()
    planner._lane_action_locks = {}
    planner._lane_sleep_since = {}
    planner._lane_sleep_level = {}
    planner._lane_idle_since = {}
    planner._lane_loaded_at = {}
    planner._drain_timestamps = {}
    planner._safe_get_profiles = MagicMock(return_value={})
    planner._safe_get_capacity = MagicMock(return_value=None)
    planner._lane_gpu_devices_str = MagicMock(return_value=None)
    planner._get_per_gpu_free = MagicMock(return_value=None)
    planner._release_vram = MagicMock()
    planner._check_host_ram_headroom_for_sleep = MagicMock(return_value=(True, 100_000.0, 1_000.0))
    planner._drain_lane = AsyncMock(return_value=True)
    planner._on_state_change = None
    planner._pending_capacity = {}

    async def send_command(provider_id, action, params, timeout_seconds=30):  # noqa: ARG001
        lane = worker_lanes[params["lane_id"]]
        if action == "sleep_lane":
            lane.update(runtime_state="sleeping", sleep_state="sleeping")
        elif action == "wake_lane":
            lane.update(runtime_state="loaded", sleep_state="awake")
        await registry.update_runtime(provider_id=PROVIDER_ID, runtime={"lanes": list(worker_lanes.values())})
        return {}

    registry.send_command = send_command  # type: ignore[method-assign]
    return planner


@pytest.fixture(autouse=True)
def _fast_confirmation_poll(monkeypatch):
    """The confirmation poll waits 2 s between reads; the simulated worker is instant."""
    real_sleep = asyncio.sleep

    async def no_wait(_seconds, *args, **kwargs):
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", no_wait)


def _sleep_action() -> CapacityPlanAction:
    return CapacityPlanAction(
        action="sleep_l1",
        provider_id=PROVIDER_ID,
        lane_id=IDLE_LANE,
        model_name=MODEL,
        reason="Evicted for wake of another model",
    )


async def _wake_outside_the_planner(registry, worker_lanes: dict[str, dict]) -> None:
    """What the panel's wake button does: the worker wakes the lane, the planner is not involved."""
    worker_lanes[IDLE_LANE].update(runtime_state="loaded", sleep_state="awake")
    await registry.update_runtime(provider_id=PROVIDER_ID, runtime={"lanes": list(worker_lanes.values())})


async def test_a_lane_woken_outside_the_planner_takes_requests_again():
    worker_lanes = {
        BUSY_LANE: _lane(BUSY_LANE, "running", "awake", queue_waiting=453.0),
        IDLE_LANE: _lane(IDLE_LANE, "loaded", "awake", queue_waiting=0.0),
    }
    registry = await _registry_with(list(worker_lanes.values()))
    planner = _planner(registry, worker_lanes)

    assert await planner._execute_action_with_confirmation(_sleep_action(), timeout_seconds=10.0)
    selected = await registry.select_lane_for_model(PROVIDER_ID, MODEL)
    assert selected["lane_id"] == BUSY_LANE  # the sleeping sibling is not routable

    await _wake_outside_the_planner(registry, worker_lanes)

    selected = await registry.select_lane_for_model(PROVIDER_ID, MODEL)
    assert selected["lane_id"] == IDLE_LANE
    assert not registry.is_lane_cold_marked(PROVIDER_ID, IDLE_LANE)


async def test_a_sleep_cancelled_mid_drain_does_not_leave_the_lane_cold():
    worker_lanes = {
        BUSY_LANE: _lane(BUSY_LANE, "running", "awake", queue_waiting=453.0),
        IDLE_LANE: _lane(IDLE_LANE, "loaded", "awake", queue_waiting=0.0),
    }
    registry = await _registry_with(list(worker_lanes.values()))
    planner = _planner(registry, worker_lanes)
    planner._drain_lane = AsyncMock(side_effect=asyncio.CancelledError)

    with pytest.raises(asyncio.CancelledError):
        await planner._execute_action_with_confirmation(_sleep_action(), timeout_seconds=10.0)

    selected = await registry.select_lane_for_model(PROVIDER_ID, MODEL)
    assert selected["lane_id"] == IDLE_LANE
    assert not registry.is_lane_cold_marked(PROVIDER_ID, IDLE_LANE)


async def test_the_lane_stays_cold_while_the_sleep_is_in_flight():
    worker_lanes = {
        BUSY_LANE: _lane(BUSY_LANE, "running", "awake", queue_waiting=453.0),
        IDLE_LANE: _lane(IDLE_LANE, "loaded", "awake", queue_waiting=0.0),
    }
    registry = await _registry_with(list(worker_lanes.values()))
    planner = _planner(registry, worker_lanes)
    seen_during_drain: list[str] = []

    async def drain(provider_id, lane_id, timeout_seconds=30.0):  # noqa: ARG001
        selected = await registry.select_lane_for_model(PROVIDER_ID, MODEL)
        seen_during_drain.append(selected["lane_id"])
        return True

    planner._drain_lane = drain

    assert await planner._execute_action_with_confirmation(_sleep_action(), timeout_seconds=10.0)
    assert seen_during_drain == [BUSY_LANE]
