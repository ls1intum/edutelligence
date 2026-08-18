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


def test_flag_is_restored_when_the_worker_replays_events_after_reconnect():
    """The worker resets _last_event_seq to 0 on reconnect and replays its
    log, so a session that is still running re-marks the fresh session."""
    registry, _ = _registry_with_session()
    asyncio.run(registry.append_event(1, _event("calibration_session_started")))

    # Reconnect: attach_session builds a brand new ProviderSession.
    _, fresh = _registry_with_session()
    registry._sessions[1] = fresh  # noqa: SLF001
    assert registry.is_calibrating(1) is False

    asyncio.run(registry.append_event(1, _event("calibration_session_started")))
    assert registry.is_calibrating(1) is True


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
