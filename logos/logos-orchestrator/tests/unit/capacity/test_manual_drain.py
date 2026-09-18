"""The manual drain of a busy lane — what the statistics UI's Drain button runs.

The manual sleep endpoint is withheld from a lane that is still serving, and
the worker's wait-mode drain is best-effort (it proceeds once its 30 s budget
runs out, dropping whatever is still in flight). ``drain_lane_manually`` is
the strict counterpart: cold mark (no new requests routed to the lane), a
bounded strict wait for the in-flight ones, then a sleep — or an unload when
the host cannot afford a resident sleeper, or the lane's backend has no
sleep mode. The cold mark must be cleared on every exit, including the
failures, or a lane the drain could not finish would stay out of the
rotation with no action left to clear it.
"""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

from logos.capacity.capacity_planner import CapacityPlanner
from logos.logosnode_registry import LogosNodeCommandError, LogosNodeOfflineError

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


def _snapshot(lane: dict) -> dict:
    return {"provider_id": 1, "runtime": {"lanes": [lane]}}


def _planner(lane: dict, send_result: dict | None = None) -> CapacityPlanner:
    planner = CapacityPlanner.__new__(CapacityPlanner)
    registry = MagicMock()
    registry.peek_runtime_snapshot = lambda pid: _snapshot(lane)
    registry.send_command = AsyncMock(return_value=send_result if send_result is not None else {})
    planner._registry = registry
    planner._facade = MagicMock()
    planner._facade.get_provider_name.return_value = "worker-a"
    planner._facade.get_model_profiles.return_value = {}
    planner._marked_cold_lanes = set()
    return planner


def _patch_ram_headroom(planner, monkeypatch, ok: bool) -> MagicMock:
    check = MagicMock(return_value=(ok, 100.0, 500.0))
    monkeypatch.setattr(planner, "_check_host_ram_headroom_for_sleep", check)
    return check


# ── the happy path: mark, drain, sleep, unmark ──────────────────────────────


async def test_a_drained_lane_is_slept_and_the_mark_cleared(monkeypatch):
    planner = _planner(_lane())
    _patch_ram_headroom(planner, monkeypatch, ok=True)

    # Let the real _drain_lane run against the (already drained) snapshot and
    # spy on it, so the test also pins the wait budget the drain uses.
    real_drain = planner._drain_lane
    calls = []

    async def spy(pid, lid, timeout_seconds=30.0):
        calls.append((pid, lid, timeout_seconds))
        return await real_drain(pid, lid, timeout_seconds)

    planner._drain_lane = spy

    result = await planner.drain_lane_manually(1, "lane-1")

    assert result == {"status": "slept", "lane_id": "lane-1"}
    assert calls == [(1, "lane-1", CapacityPlanner.DRAIN_TIMEOUT_SECONDS)]
    planner._registry.send_command.assert_awaited_once_with(
        1, "sleep_lane", {"lane_id": "lane-1", "level": 1, "mode": "wait"}, timeout_seconds=60
    )
    planner._registry.mark_lane_cold.assert_called_once_with(1, "lane-1")
    planner._registry.unmark_lane_cold.assert_called_once_with(1, "lane-1")
    assert planner._marked_cold_lanes == set()


# ── a lane that does not drain is left exactly as found ─────────────────────


async def test_a_lane_that_does_not_drain_keeps_serving(monkeypatch):
    planner = _planner(_lane(active_requests=3))
    planner._drain_lane = AsyncMock(return_value=False)
    ram_check = _patch_ram_headroom(planner, monkeypatch, ok=True)

    result = await planner.drain_lane_manually(1, "lane-1")

    assert result["status"] == "drain_timeout"
    assert "60s" in result["error"]
    # No terminal command may go out, and the RAM decision is never reached.
    planner._registry.send_command.assert_not_awaited()
    ram_check.assert_not_called()
    planner._registry.unmark_lane_cold.assert_called_once_with(1, "lane-1")
    assert planner._marked_cold_lanes == set()


# ── the escalation to an unload ─────────────────────────────────────────────


async def test_low_host_ram_escalates_the_sleep_to_an_unload(monkeypatch):
    planner = _planner(_lane())
    planner._drain_lane = AsyncMock(return_value=True)
    _patch_ram_headroom(planner, monkeypatch, ok=False)

    result = await planner.drain_lane_manually(1, "lane-1")

    assert result["status"] == "unloaded"
    assert "100MB available < 500MB required" in result["reason"]
    planner._registry.send_command.assert_awaited_once_with(
        1, "delete_lane", {"lane_id": "lane-1"}, timeout_seconds=30
    )
    planner._registry.unmark_lane_cold.assert_called_once_with(1, "lane-1")


async def test_a_lane_without_sleep_mode_is_unloaded(monkeypatch):
    planner = _planner(_lane(sleep_state="unsupported"))
    planner._drain_lane = AsyncMock(return_value=True)
    ram_check = _patch_ram_headroom(planner, monkeypatch, ok=True)

    result = await planner.drain_lane_manually(1, "lane-1")

    assert result["status"] == "unloaded"
    assert "does not support sleep mode" in result["reason"]
    ram_check.assert_not_called()
    planner._registry.send_command.assert_awaited_once_with(
        1, "delete_lane", {"lane_id": "lane-1"}, timeout_seconds=30
    )


# ── command failures still clear the mark ───────────────────────────────────


async def test_a_refused_command_reports_an_error_and_clears_the_mark(monkeypatch):
    planner = _planner(_lane())
    planner._drain_lane = AsyncMock(return_value=True)
    _patch_ram_headroom(planner, monkeypatch, ok=True)
    planner._registry.send_command = AsyncMock(side_effect=LogosNodeCommandError("worker refused 'sleep_lane'"))

    result = await planner.drain_lane_manually(1, "lane-1")

    assert result == {"status": "error", "lane_id": "lane-1", "error": "worker refused 'sleep_lane'"}
    planner._registry.unmark_lane_cold.assert_called_once_with(1, "lane-1")
    assert planner._marked_cold_lanes == set()


async def test_a_lost_worker_reports_an_error_and_clears_the_mark(monkeypatch):
    planner = _planner(_lane())
    planner._drain_lane = AsyncMock(return_value=True)
    _patch_ram_headroom(planner, monkeypatch, ok=True)
    planner._registry.send_command = AsyncMock(
        side_effect=LogosNodeOfflineError("Command timeout waiting for worker response")
    )

    result = await planner.drain_lane_manually(1, "lane-1")

    assert result["status"] == "error"
    assert "Command timeout waiting for worker response" in result["error"]
    planner._registry.unmark_lane_cold.assert_called_once_with(1, "lane-1")
    assert planner._marked_cold_lanes == set()
