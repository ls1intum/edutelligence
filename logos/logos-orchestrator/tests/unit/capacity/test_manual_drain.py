"""The manual drain of a busy lane — what the statistics UI's Drain button runs.

The manual sleep endpoint is withheld from a lane that is still serving, and
the worker's wait-mode drain is best-effort (it proceeds once its 30 s budget
runs out, dropping whatever is still in flight). ``drain_lane_manually`` is
the strict counterpart: cold mark (no new requests routed to the lane), a
bounded strict wait for the in-flight ones, then the terminal step handed to
the confirmed executor — a sleep, or an unload when the host cannot afford a
resident sleeper, or the lane's backend has no sleep mode. Routing the
terminal step through the executor is what keeps the manual path consistent
with a planned one: the executor syncs the desired-lane set, keeps the VRAM
ledger current, and waits for the worker to confirm the state, so the manual
path never reports success on the strength of a command that was merely sent.
The cold mark must be cleared on every exit, including the failures, or a
lane the drain could not finish would stay out of the rotation with no action
left to clear it.
"""

from __future__ import annotations

import sys
import time
from unittest.mock import AsyncMock, MagicMock

from logos.capacity.capacity_planner import CapacityPlanner

# logos/__init__ aliases itself to logos.main, which breaks the plain
# `import logos.capacity...` attribute chain; the module object comes from
# the import above.
planner_mod = sys.modules["logos.capacity.capacity_planner"]


def _lane(lane_id: str = "lane-1", sleep_state: str = "awake", active_requests: int = 0) -> dict:
    return {
        "lane_id": lane_id,
        "model": "org/model-a",
        "sleep_state": sleep_state,
        "active_requests": active_requests,
    }


def _planner(lanes: list) -> CapacityPlanner:
    """A planner whose registry reports ``lanes`` in every snapshot.

    ``lanes`` is a mutable list of the same dict objects each snapshot
    exposes, so the terminal-step mock can mutate it to simulate what the
    executor's command did to the worker (put the lane to sleep, or remove
    it), and the drain's terminal-state re-read sees the effect.
    """
    planner = CapacityPlanner.__new__(CapacityPlanner)
    registry = MagicMock()
    registry.peek_runtime_snapshot = lambda pid: {"provider_id": 1, "runtime": {"lanes": list(lanes)}}
    registry.send_command = AsyncMock(return_value={})
    planner._registry = registry
    planner._facade = MagicMock()
    planner._facade.get_provider_name.return_value = "worker-a"
    planner._facade.get_model_profiles.return_value = {}
    planner._marked_cold_lanes = set()
    planner._lane_action_locks = {}
    return planner


def _patch_ram_headroom(planner, monkeypatch, ok: bool) -> MagicMock:
    check = MagicMock(return_value=(ok, 100.0, 500.0))
    monkeypatch.setattr(planner, "_check_host_ram_headroom_for_sleep", check)
    return check


def _executor(planner, lanes: list, effect) -> AsyncMock:
    """Mock the confirmed executor. ``effect(lane, lanes)`` simulates what the
    executor's command did to the worker when it runs."""

    async def run(action, timeout_seconds=60.0, deadline=None):
        lane = next((item for item in lanes if item.get("lane_id") == action.lane_id), None)
        if lane is not None:
            effect(lane, lanes)
        return True

    mock = AsyncMock(side_effect=run)
    planner._execute_action_with_confirmation = mock
    return mock


def _sleep(lane, lanes):
    lane["sleep_state"] = "sleeping"


def _remove(lane, lanes):
    lanes.remove(lane)


# ── the happy path: mark, drain, sleep, unmark ──────────────────────────────


async def test_a_drained_lane_is_slept_and_the_mark_cleared(monkeypatch):
    lane = _lane()
    lanes = [lane]
    planner = _planner(lanes)
    _patch_ram_headroom(planner, monkeypatch, ok=True)

    # Let the real _drain_lane run against the (already drained) snapshot and
    # spy on it, so the test also pins the wait budget the drain uses.
    real_drain = planner._drain_lane
    calls = []

    async def spy(pid, lid, timeout_seconds=30.0):
        calls.append((pid, lid, timeout_seconds))
        return await real_drain(pid, lid, timeout_seconds)

    planner._drain_lane = spy

    executor = _executor(planner, lanes, _sleep)
    result = await planner.drain_lane_manually(1, "lane-1")

    assert result == {"status": "slept", "lane_id": "lane-1"}
    assert calls == [(1, "lane-1", CapacityPlanner.DRAIN_TIMEOUT_SECONDS)]
    executor.assert_awaited_once()
    action = executor.await_args.args[0]
    assert action.action == "sleep_l1"
    assert action.lane_id == "lane-1"
    assert action.model_name == "org/model-a"
    assert action.bypass_load_cooldown is False
    planner._registry.mark_lane_cold.assert_called_once_with(1, "lane-1")
    planner._registry.unmark_lane_cold.assert_called_once_with(1, "lane-1")
    assert planner._marked_cold_lanes == set()


# ── a lane that does not drain is left exactly as found ─────────────────────


async def test_a_lane_that_does_not_drain_keeps_serving(monkeypatch):
    lane = _lane(active_requests=3)
    lanes = [lane]
    planner = _planner(lanes)
    planner._drain_lane = AsyncMock(return_value=False)
    ram_check = _patch_ram_headroom(planner, monkeypatch, ok=True)
    executor = _executor(planner, lanes, _sleep)

    result = await planner.drain_lane_manually(1, "lane-1")

    assert result["status"] == "drain_timeout"
    assert "60s" in result["error"]
    # No terminal step may run, no command may go out, and the RAM decision
    # is never reached.
    executor.assert_not_awaited()
    ram_check.assert_not_called()
    planner._registry.send_command.assert_not_awaited()
    planner._registry.unmark_lane_cold.assert_called_once_with(1, "lane-1")
    assert planner._marked_cold_lanes == set()


# ── the escalation to an unload ─────────────────────────────────────────────


async def test_low_host_ram_escalates_the_sleep_to_an_unload(monkeypatch):
    lane = _lane()
    lanes = [lane]
    planner = _planner(lanes)
    planner._drain_lane = AsyncMock(return_value=True)
    _patch_ram_headroom(planner, monkeypatch, ok=False)
    executor = _executor(planner, lanes, _remove)

    result = await planner.drain_lane_manually(1, "lane-1")

    assert result["status"] == "unloaded"
    assert "100MB available < 500MB required" in result["reason"]
    executor.assert_awaited_once()
    action = executor.await_args.args[0]
    assert action.action == "stop"
    assert action.bypass_load_cooldown is True
    planner._registry.unmark_lane_cold.assert_called_once_with(1, "lane-1")
    assert planner._marked_cold_lanes == set()


async def test_a_lane_without_sleep_mode_is_unloaded(monkeypatch):
    lane = _lane(sleep_state="unsupported")
    lanes = [lane]
    planner = _planner(lanes)
    planner._drain_lane = AsyncMock(return_value=True)
    ram_check = _patch_ram_headroom(planner, monkeypatch, ok=True)
    executor = _executor(planner, lanes, _remove)

    result = await planner.drain_lane_manually(1, "lane-1")

    assert result["status"] == "unloaded"
    assert "does not support sleep mode" in result["reason"]
    ram_check.assert_not_called()
    executor.assert_awaited_once()
    assert executor.await_args.args[0].action == "stop"
    planner._registry.unmark_lane_cold.assert_called_once_with(1, "lane-1")


# ── the terminal step is confirmed, not assumed ─────────────────────────────


async def test_a_terminal_step_that_does_not_take_effect_reports_an_error(monkeypatch):
    lane = _lane()
    lanes = [lane]
    planner = _planner(lanes)
    planner._drain_lane = AsyncMock(return_value=True)
    _patch_ram_headroom(planner, monkeypatch, ok=True)
    # The executor runs but the lane never sleeps (the worker refused and the
    # confirmation timed out): it is still awake when the drain re-reads it.
    executor = _executor(planner, lanes, lambda lane, lanes: None)

    result = await planner.drain_lane_manually(1, "lane-1")

    assert result["status"] == "error"
    assert "still awake and serving" in result["error"]
    executor.assert_awaited_once()
    planner._registry.unmark_lane_cold.assert_called_once_with(1, "lane-1")
    assert planner._marked_cold_lanes == set()


async def test_a_sleep_the_executor_escalates_to_a_stop_is_an_unload(monkeypatch):
    lane = _lane()
    lanes = [lane]
    planner = _planner(lanes)
    planner._drain_lane = AsyncMock(return_value=True)
    # The drain's own RAM check says sleep is fine…
    _patch_ram_headroom(planner, monkeypatch, ok=True)
    # …but the executor's fresh recheck escalates the sleep to a full stop
    # and removes the lane. The terminal state is the lane, so this is an
    # unload, not a failed sleep.
    executor = _executor(planner, lanes, _remove)

    result = await planner.drain_lane_manually(1, "lane-1")

    assert result["status"] == "unloaded"
    assert "escalated" in result["reason"]
    assert executor.await_args.args[0].action == "sleep_l1"
    planner._registry.unmark_lane_cold.assert_called_once_with(1, "lane-1")
    assert planner._marked_cold_lanes == set()


# ── a lane a direct admin unload takes out mid-drain is already offline ─────


async def test_a_lane_removed_mid_drain_is_reported_unloaded(monkeypatch):
    lane = _lane()
    lanes = [lane]
    planner = _planner(lanes)
    planner._drain_lane = AsyncMock(return_value=True)  # reports drained
    _patch_ram_headroom(planner, monkeypatch, ok=True)
    executor = _executor(planner, lanes, _sleep)
    lanes.remove(lane)  # a direct admin unload took it out while the drain ran

    result = await planner.drain_lane_manually(1, "lane-1")

    assert result == {
        "status": "unloaded",
        "lane_id": "lane-1",
        "reason": "the lane was removed while the drain was in flight",
    }
    executor.assert_not_awaited()
    planner._registry.unmark_lane_cold.assert_called_once_with(1, "lane-1")
    assert planner._marked_cold_lanes == set()


# ── a worker disconnect is an unknown state, not a success ──────────────────


async def test_a_worker_disconnect_during_drain_is_an_error_not_an_unload(monkeypatch):
    lane = _lane()
    lanes = [lane]
    planner = _planner(lanes)
    planner._drain_lane = AsyncMock(return_value=True)  # reports drained
    _patch_ram_headroom(planner, monkeypatch, ok=True)
    executor = _executor(planner, lanes, _sleep)
    # The worker drops after the drain: the snapshot is unavailable, so the
    # lane's state is unknown — not provably offline.
    planner._registry.peek_runtime_snapshot = lambda pid: None

    result = await planner.drain_lane_manually(1, "lane-1")

    assert result["status"] == "error"
    assert "disconnected" in result["error"]
    executor.assert_not_awaited()
    planner._registry.unmark_lane_cold.assert_called_once_with(1, "lane-1")
    assert planner._marked_cold_lanes == set()


# ── the whole ride is budgeted under the webservice read timeout ────────────


def test_step_budget_caps_a_step_at_the_deadline():
    planner = _planner([])
    # No deadline carried in: the default is returned untouched.
    assert planner._step_budget(None, 60.0) == 60.0
    # A deadline in the future caps the step at the time left on the call.
    future = time.monotonic() + 5.0
    assert 4.0 < planner._step_budget(future, 60.0) <= 5.0
    # An exhausted (past) deadline leaves nothing to spend.
    assert planner._step_budget(time.monotonic() - 1.0, 60.0) == 0.0


async def test_waiting_for_the_lane_lock_spends_the_endpoint_budget(monkeypatch):
    # The budget starts before the lane lock: a planned reclaim holding it
    # can wait out most of the endpoint's time, and the strict wait must only
    # get what is left — not its full DRAIN_TIMEOUT_SECONDS on top.
    clock = {"now": 1000.0}
    monkeypatch.setattr(planner_mod.time, "monotonic", lambda: clock["now"])
    lane = _lane(active_requests=3)  # still busy when the drain finally runs
    lanes = [lane]
    planner = _planner(lanes)
    _patch_ram_headroom(planner, monkeypatch, ok=True)
    executor = _executor(planner, lanes, _sleep)

    class SlowLock:
        async def __aenter__(self):
            # The reclaim held the lock for most of the budget.
            clock["now"] = 1000.0 + CapacityPlanner.DRAIN_ENDPOINT_BUDGET_SECONDS - 10.0
            return self

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(planner, "_lane_lock", lambda pid, lid: SlowLock())
    budgets = []

    async def never_drains(pid, lid, timeout_seconds=30.0):
        budgets.append(timeout_seconds)
        return False  # the busy lane does not drain in what is left

    planner._drain_lane = never_drains

    result = await planner.drain_lane_manually(1, "lane-1")

    # 10 s left for the strict wait — the lane does not drain in that, so the
    # call ends as a drain timeout with the lane left exactly as found.
    assert budgets == [10.0]
    assert result["status"] == "drain_timeout"
    executor.assert_not_awaited()
    planner._registry.unmark_lane_cold.assert_called_once_with(1, "lane-1")
    assert planner._marked_cold_lanes == set()


async def test_the_terminal_step_gets_the_remaining_endpoint_budget(monkeypatch):
    # A controlled clock: the deadline must be "drain start + the endpoint
    # budget" exactly, independent of any wall-clock time the test process
    # spends between the call and the assertion. (The event loop keeps its
    # own clock reference, and no real sleep runs on this path — the strict
    # wait is mocked — so freezing the module's monotonic is safe here.)
    monkeypatch.setattr(planner_mod.time, "monotonic", lambda: 1000.0)
    lane = _lane()
    lanes = [lane]
    planner = _planner(lanes)
    planner._drain_lane = AsyncMock(return_value=True)
    _patch_ram_headroom(planner, monkeypatch, ok=True)
    executor = _executor(planner, lanes, _sleep)

    result = await planner.drain_lane_manually(1, "lane-1")

    assert result["status"] == "slept"
    # That shared pot — not the per-step budgets — is what keeps the whole
    # call under the webservice timeout.
    deadline = executor.await_args.kwargs.get("deadline")
    assert deadline is not None
    assert deadline == 1000.0 + CapacityPlanner.DRAIN_ENDPOINT_BUDGET_SECONDS
