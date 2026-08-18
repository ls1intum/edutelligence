"""The planner must leave a calibrating worker alone.

A calibration session frees all VRAM for its probes, so the worker presents as
an idle node with a lot of headroom — precisely the node the capacity planner
wants to load a model onto. A lane placed there holds the memory the probes
need, and the kv-cache search fails at sizes that would otherwise fit.

The state is tracked from the worker's own session events rather than from
CalibrationOrchestrator._active_provider_id: the admin calibrate_uncalibrated
endpoints send start_calibration_session straight through the registry and
never set that slot, so it does not see every session.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import pytest

from logos.capacity.capacity_planner import CapacityPlanner
from logos.logosnode_registry import LogosNodeRuntimeRegistry, ProviderSession

# ---------------------------------------------------------------------------
# Registry: calibrating flag driven by worker events
# ---------------------------------------------------------------------------


def _registry_with_session(provider_id: int = 1) -> tuple[LogosNodeRuntimeRegistry, ProviderSession]:
    registry = LogosNodeRuntimeRegistry()
    session = ProviderSession(
        provider_id=provider_id,
        worker_id="worker-a",
        websocket=MagicMock(),
    )
    registry._sessions[provider_id] = session  # noqa: SLF001
    return registry, session


def _event(name: str) -> dict:
    return {"event": name, "model": "", "details": ""}


def test_worker_events_flip_the_calibrating_flag():
    """started → calibrating, finished → not calibrating."""
    registry, _ = _registry_with_session()

    assert registry.is_calibrating(1) is False

    asyncio.run(registry.append_event(1, _event("calibration_session_started")))
    assert registry.is_calibrating(1) is True

    asyncio.run(registry.append_event(1, _event("calibration_session_finished")))
    assert registry.is_calibrating(1) is False


def test_cancelled_session_also_clears_the_flag():
    """A stop mid-session must not strand the worker as permanently excluded."""
    registry, _ = _registry_with_session()

    asyncio.run(registry.append_event(1, _event("calibration_session_started")))
    asyncio.run(registry.append_event(1, _event("calibration_session_cancelled")))
    assert registry.is_calibrating(1) is False


def test_unrelated_events_do_not_clear_the_flag():
    """Per-model events stream throughout a session — only the terminal
    session events may end it."""
    registry, _ = _registry_with_session()

    asyncio.run(registry.append_event(1, _event("calibration_session_started")))
    for name in (
        "calibration_model_started",
        "calibration_model_completed",
        "calibration_model_failed",
        "calibration_model_skipped",
        "calibration_model_cancelled",
    ):
        asyncio.run(registry.append_event(1, _event(name)))
        assert registry.is_calibrating(1) is True, f"{name} must not end the session"


def test_replayed_events_do_not_move_the_flag():
    """The post-connect replay is a backlog whose order says nothing about what
    is running now — hello owns the state at connect (see the hello tests)."""
    registry, session = _registry_with_session()

    asyncio.run(registry.append_event(1, _event("calibration_session_started"), replay=True))
    assert registry.is_calibrating(1) is False

    session.calibrating = True
    asyncio.run(registry.append_event(1, _event("calibration_session_finished"), replay=True))
    assert registry.is_calibrating(1) is True


def test_a_stale_terminal_event_in_the_replay_cannot_clear_the_hello_state():
    """The concrete reconnect case: the log still holds the terminal event of an
    earlier session, and it is replayed *before* the current session's started
    event. Acting on it would clear the flag hello had just set correctly."""
    registry, session = _registry_with_session()
    session.first_status_received = True
    planner = _planner_with_registry(registry)

    # Reconnect mid-session: hello reports the truth.
    asyncio.run(registry.on_hello(provider_id=1, worker_id="worker-a", calibrating=True))

    # Replay: previous session's terminal event, then the current session's start.
    asyncio.run(registry.append_event(1, _event("calibration_session_finished"), replay=True))
    assert planner._is_plannable(1) is False, "a stale terminal event must not open a placement window"

    asyncio.run(registry.append_event(1, _event("calibration_session_started"), replay=True))
    assert registry.is_calibrating(1) is True

    # Live events still end the session normally.
    asyncio.run(registry.append_event(1, _event("calibration_session_finished")))
    assert planner._is_plannable(1) is True


def test_is_calibrating_is_false_for_unknown_provider():
    registry = LogosNodeRuntimeRegistry()
    assert registry.is_calibrating(999) is False


# ---------------------------------------------------------------------------
# Planner: calibrating providers are not plannable
# ---------------------------------------------------------------------------


def _planner_with_registry(registry) -> CapacityPlanner:
    planner = CapacityPlanner.__new__(CapacityPlanner)
    planner._registry = registry
    return planner


def _cycle_planner(registry, validated_actions, executed) -> CapacityPlanner:
    """A planner wired just far enough to run `_run_cycle`'s execution loop.

    No providers are iterated; the actions are injected where the real cycle
    hands its plan over to `_validate_vram_budget`.
    """
    planner = _planner_with_registry(registry)
    planner._vram_ledger = MagicMock(**{"cleanup_stale.return_value": 0})
    planner._host_ram_ledger = MagicMock(**{"cleanup_stale.return_value": 0})
    planner._demand = MagicMock(**{"get_ranked_models.return_value": []})
    planner._pending_capacity = {}
    planner._facade = MagicMock(**{"provider_ids.return_value": []})
    planner._cross_provider_dedup = False
    planner._cross_provider_best_first = False
    planner._replica_first_eviction = False
    planner._replicate_on_free_vram = False
    planner._log_cluster_summary = lambda *_a, **_k: None
    planner._log_action_plan = lambda *_a, **_k: None
    planner._validate_vram_budget = lambda _actions: list(validated_actions)

    @asynccontextmanager
    async def _lane_lock(_provider_id, _lane_id):
        yield

    planner._lane_lock = _lane_lock
    return planner


@pytest.mark.parametrize(
    ("first_status", "calibrating", "expected"),
    [
        (True, False, True),  # normal worker
        (True, True, False),  # mid-calibration — hands off
        (False, False, False),  # no status yet
        (False, True, False),  # both reasons
    ],
)
def test_is_plannable_matrix(first_status, calibrating, expected):
    registry = MagicMock()
    registry.has_received_first_status.return_value = first_status
    registry.is_calibrating.return_value = calibrating
    assert _planner_with_registry(registry)._is_plannable(1) is expected


def test_is_plannable_without_registry():
    """No registry wired (unit-test / standalone paths) → don't block."""
    assert _planner_with_registry(None)._is_plannable(1) is True


def test_planner_skips_worker_calibrating_via_admin_endpoint():
    """End-to-end of the two halves: a session started outside the
    CalibrationOrchestrator (admin endpoint → registry) still excludes the
    worker, because the flag comes from the worker's own event."""
    registry, _ = _registry_with_session()
    planner = _planner_with_registry(registry)
    # first status arrived before the session began
    registry._sessions[1].first_status_received = True  # noqa: SLF001

    assert planner._is_plannable(1) is True

    asyncio.run(registry.append_event(1, _event("calibration_session_started")))
    assert planner._is_plannable(1) is False

    asyncio.run(registry.append_event(1, _event("calibration_session_finished")))
    assert planner._is_plannable(1) is True


# ---------------------------------------------------------------------------
# Registry: hello carries the authoritative state at connect
# ---------------------------------------------------------------------------


def test_hello_marks_a_reconnecting_worker_as_calibrating():
    """The replay is not enough on reconnect.

    A fresh ProviderSession starts non-calibrating, and the worker sends its
    forced status (which flips first_status_received, making the provider
    plannable) *before* the event loop replays the session events. Hello
    arrives first, so it closes that window.
    """
    registry, session = _registry_with_session()
    planner = _planner_with_registry(registry)

    asyncio.run(registry.on_hello(provider_id=1, worker_id="worker-a", calibrating=True))
    assert registry.is_calibrating(1) is True

    # ... and only now does the first status arrive.
    session.first_status_received = True
    assert planner._is_plannable(1) is False

    asyncio.run(registry.append_event(1, _event("calibration_session_finished")))
    assert planner._is_plannable(1) is True


def test_hello_clears_the_flag_after_a_worker_restart():
    """A restarted worker lost its in-memory event log, so no terminal event
    will ever arrive. Hello reporting False is what keeps the provider from
    being excluded forever."""
    registry, session = _registry_with_session()
    session.calibrating = True

    asyncio.run(registry.on_hello(provider_id=1, worker_id="worker-a", calibrating=False))
    assert registry.is_calibrating(1) is False


def test_hello_without_the_field_leaves_the_flag_untouched():
    """Worker predating the field → fall back to the event replay alone."""
    registry, session = _registry_with_session()
    session.calibrating = True

    asyncio.run(registry.on_hello(provider_id=1, worker_id="worker-a"))
    assert registry.is_calibrating(1) is True


# ---------------------------------------------------------------------------
# Planner: the other two paths that can place a lane
# ---------------------------------------------------------------------------


def test_speculative_replication_skips_a_calibrating_worker():
    """A replica is a plain `load`, so it takes the probes' VRAM just as
    readily as a demand-driven one. Guarded behind LOGOS_REPLICATE_ON_FREE_VRAM,
    which this test enables."""
    registry = MagicMock()
    registry.has_received_first_status.return_value = True
    registry.is_calibrating.return_value = True

    planner = _planner_with_registry(registry)
    planner._replicate_on_free_vram = True
    planner._facade = MagicMock()

    actions = planner._compute_replication_actions(
        [1],
        [("model-a", 99.0)],
        {"model-a": 1},  # already loaded once → replication is in play
        set(),
    )

    assert actions == []
    planner._facade.get_all_provider_lane_signals.assert_not_called()


def test_cycle_drops_an_action_whose_provider_started_calibrating():
    """Actions are planned up front and executed sequentially — a cold load
    takes ~90s — so the verdict can go stale between planning and execution."""
    from logos.sdi.models import CapacityPlanAction

    registry = MagicMock()
    registry.has_received_first_status.return_value = True
    registry.is_calibrating.return_value = False

    planned = [
        CapacityPlanAction(action="load", provider_id=1, lane_id="lane-0", model_name="model-a"),
        CapacityPlanAction(action="load", provider_id=1, lane_id="lane-1", model_name="model-b"),
    ]
    executed: list[str] = []
    planner = _cycle_planner(registry, planned, executed)

    # The first action executes, and calibration starts while it runs.
    async def _execute(action):
        executed.append(action.lane_id)
        registry.is_calibrating.return_value = True

    planner._execute_action_with_confirmation = _execute
    asyncio.run(planner._run_cycle())

    assert executed == ["lane-0"], "the second action must be dropped, not executed"


# ---------------------------------------------------------------------------
# Registry: the dispatch of start_calibration_session marks the provider
# ---------------------------------------------------------------------------


def _registry_answering_start(provider_id: int = 1, reply: dict | None = None):
    """A registry whose websocket answers `start_calibration_session` with
    *reply* as the command payload, plus a probe that records whether the
    provider was already excluded when the command hit the wire."""
    registry, session = _registry_with_session(provider_id)
    session.first_status_received = True
    planner = _planner_with_registry(registry)
    seen_plannable: list[bool] = []

    async def _send_json(message):
        seen_plannable.append(planner._is_plannable(provider_id))
        cmd_id = message["cmd_id"]
        fut = session.pending_commands[cmd_id]
        fut.set_result({"cmd_id": cmd_id, "success": True, "result": reply if reply is not None else {"ok": True}})

    session.websocket.send_json = _send_json
    return registry, session, seen_plannable


def test_dispatching_a_start_excludes_the_provider_before_the_worker_confirms():
    """The worker's started event is forwarded by a one-second poll loop, so
    waiting for it leaves a window in which a cycle can still place a lane."""
    registry, _session, seen_plannable = _registry_answering_start()

    result = asyncio.run(registry.send_command(1, "start_calibration_session", params={"sleep_level": 1}))

    assert result == {"ok": True}
    assert seen_plannable == [False], "provider must be excluded before the command is sent"
    assert registry.is_calibrating(1) is True


def test_a_refused_start_releases_the_provider_again():
    """The worker reports a refusal as a successful command carrying ok=False,
    so the mark has to be undone on that payload — otherwise a worker that
    never starts a session stays excluded forever."""
    registry, _session, _ = _registry_answering_start(reply={"ok": False, "error": "node is in a degraded state"})

    asyncio.run(registry.send_command(1, "start_calibration_session"))

    assert registry.is_calibrating(1) is False


def test_a_refused_start_keeps_an_already_running_session_excluded():
    """The worker refuses a second start while one is in progress. Undoing must
    restore the previous value, not clear it — clearing would hand the running
    session's VRAM to the planner."""
    registry, session, _ = _registry_answering_start(
        reply={"ok": False, "error": "calibration session already in progress"}
    )
    asyncio.run(registry.append_event(1, _event("calibration_session_started")))
    assert registry.is_calibrating(1) is True

    asyncio.run(registry.send_command(1, "start_calibration_session"))

    assert registry.is_calibrating(1) is True


def test_an_unrelated_command_does_not_touch_the_flag():
    registry, session, _ = _registry_answering_start(reply={"ok": True})

    asyncio.run(registry.send_command(1, "wake_lane", params={"lane_id": "lane-0"}))

    assert registry.is_calibrating(1) is False
