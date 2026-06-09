"""Targeted tests for the worker-driven CalibrationOrchestrator."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from logos.capacity.calibration_orchestrator import CalibrationConfig, CalibrationOrchestrator
from logos.sdi.models import ModelProfile


class _StubFacade:
    def __init__(self, profiles: dict[str, ModelProfile], configured: list[str]) -> None:
        self._profiles = profiles
        self._configured = configured

    def provider_ids(self) -> list[int]:
        return [15]

    def get_configured_models(self, provider_id: int) -> list[str]:  # noqa: ARG002
        return list(self._configured)

    def get_worker_capabilities(self, provider_id: int) -> list[str]:  # noqa: ARG002
        return list(self._configured)

    def get_model_profiles(self, provider_id: int) -> dict[str, ModelProfile]:  # noqa: ARG002
        return dict(self._profiles)

    def get_provider_name(self, provider_id: int) -> str:
        return f"worker-{provider_id}"

    def get_all_provider_lane_signals(self, provider_id: int) -> list:  # noqa: ARG002
        return []


class _StubRegistry:
    def __init__(self, node_health: dict[int, dict] | None = None) -> None:
        self._node_health = node_health or {}
        self.send_command = AsyncMock(return_value={"ok": True})
        self._subscribers = []

    def has_received_first_status(self, provider_id: int) -> bool:  # noqa: ARG002
        return True

    def peek_runtime_snapshot(self, provider_id: int) -> dict | None:
        nh = self._node_health.get(provider_id)
        return {"runtime": {"node_health": nh}} if nh is not None else {"runtime": {}}

    def subscribe_to_events(self, cb):
        self._subscribers.append(cb)

    def unsubscribe_from_events(self, cb):
        if cb in self._subscribers:
            self._subscribers.remove(cb)


def _make_orchestrator(
    profiles: dict[str, ModelProfile],
    configured: list[str],
    node_health: dict[int, dict] | None = None,
) -> CalibrationOrchestrator:
    facade: Any = _StubFacade(profiles, configured)
    registry: Any = _StubRegistry(node_health=node_health)
    return CalibrationOrchestrator(registry=registry, facade=facade, config=CalibrationConfig())


def test_provider_has_uncalibrated_models_true_when_profile_incomplete():
    """Missing sleep_l1_transient_host_ram_mb still counts as needing calibration."""
    profile = ModelProfile(
        model_name="microsoft/Phi-4-reasoning",
        base_residency_mb=47113.0,
        sleeping_residual_mb=1329.0,
        sleep_l1_transient_host_ram_mb=None,
        sleep_mode_disabled=False,
    )
    orch = _make_orchestrator(
        profiles={"microsoft/Phi-4-reasoning": profile},
        configured=["microsoft/Phi-4-reasoning"],
    )
    assert orch._provider_has_uncalibrated_models(15) is True


def test_provider_has_uncalibrated_models_false_when_sleep_na_and_base_known():
    """A sleep-disabled model with base_residency measured has nothing left
    to calibrate — sleep fields are N/A by design on this worker."""
    profile = ModelProfile(
        model_name="openai/gpt-oss-120b",
        base_residency_mb=91203.0,
        sleep_mode_disabled=True,
    )
    orch = _make_orchestrator(
        profiles={"openai/gpt-oss-120b": profile},
        configured=["openai/gpt-oss-120b"],
    )
    assert orch._provider_has_uncalibrated_models(15) is False


def test_provider_has_uncalibrated_models_skips_unsupported_models():
    """Models flagged calibration_unsupported never count as needing
    calibration — they would fail the same way every window."""
    profile = ModelProfile(
        model_name="Qwen/Qwen-Image-Edit",
        calibration_unsupported=True,
        calibration_unsupported_reason="invalid-repo-id",
    )
    orch = _make_orchestrator(
        profiles={"Qwen/Qwen-Image-Edit": profile},
        configured=["Qwen/Qwen-Image-Edit"],
    )
    assert orch._provider_has_uncalibrated_models(15) is False


def test_pick_next_provider_skips_unhealthy_worker():
    """Worker reporting node_health.healthy=False is never picked."""
    needs_calib = ModelProfile(
        model_name="microsoft/Phi-4-reasoning",
        base_residency_mb=None,
    )
    orch = _make_orchestrator(
        profiles={"microsoft/Phi-4-reasoning": needs_calib},
        configured=["microsoft/Phi-4-reasoning"],
        node_health={15: {"healthy": False, "reason_code": "filesystem-eio"}},
    )
    assert orch._pick_next_provider() is None


def test_pick_next_provider_resumes_after_node_recovers():
    """Once healthy=True returns, the provider becomes pickable again."""
    needs_calib = ModelProfile(
        model_name="microsoft/Phi-4-reasoning",
        base_residency_mb=None,
    )
    orch = _make_orchestrator(
        profiles={"microsoft/Phi-4-reasoning": needs_calib},
        configured=["microsoft/Phi-4-reasoning"],
        node_health={15: {"healthy": True}},
    )
    assert orch._pick_next_provider() == 15


def test_pick_next_provider_marks_fully_calibrated_worker_done_for_window():
    """A worker with nothing left to calibrate is added to
    _completed_this_window so we don't re-evaluate it every tick."""
    profile = ModelProfile(
        model_name="microsoft/Phi-4-reasoning",
        base_residency_mb=47113.0,
        sleeping_residual_mb=1329.0,
        sleep_l1_transient_host_ram_mb=4096.0,
    )
    orch = _make_orchestrator(
        profiles={"microsoft/Phi-4-reasoning": profile},
        configured=["microsoft/Phi-4-reasoning"],
    )
    assert orch._pick_next_provider() is None
    assert 15 in orch._completed_this_window


@pytest.mark.asyncio
async def test_start_session_sends_session_rpc_and_tracks_active_provider():
    """Tick inside the window sends start_calibration_session and remembers
    the active provider so the next tick doesn't double-fire."""
    profile = ModelProfile(
        model_name="microsoft/Phi-4-reasoning",
        base_residency_mb=None,
    )
    orch = _make_orchestrator(
        profiles={"microsoft/Phi-4-reasoning": profile},
        configured=["microsoft/Phi-4-reasoning"],
    )
    await orch._start_session_on(15)

    orch._registry.send_command.assert_awaited_once_with(
        15,
        "start_calibration_session",
        params={"sleep_level": orch._config.sleep_level},
        timeout_seconds=30,
    )
    assert orch._active_provider_id == 15


@pytest.mark.asyncio
async def test_terminal_event_frees_active_slot():
    """When the worker emits calibration_session_finished, the orchestrator
    clears the active-provider slot and marks the worker done for the
    current window so the next tick picks a different worker."""
    profile = ModelProfile(
        model_name="microsoft/Phi-4-reasoning",
        base_residency_mb=None,
    )
    orch = _make_orchestrator(
        profiles={"microsoft/Phi-4-reasoning": profile},
        configured=["microsoft/Phi-4-reasoning"],
    )
    orch._active_provider_id = 15

    orch._on_provider_event(15, {"event": "calibration_session_finished"})
    assert orch._active_provider_id is None
    assert 15 in orch._completed_this_window


@pytest.mark.asyncio
async def test_terminal_event_ignored_for_other_provider():
    """Events from a provider other than the active one don't free the slot."""
    profile = ModelProfile(
        model_name="microsoft/Phi-4-reasoning",
        base_residency_mb=None,
    )
    orch = _make_orchestrator(
        profiles={"microsoft/Phi-4-reasoning": profile},
        configured=["microsoft/Phi-4-reasoning"],
    )
    orch._active_provider_id = 15

    orch._on_provider_event(99, {"event": "calibration_session_finished"})
    assert orch._active_provider_id == 15


@pytest.mark.asyncio
async def test_non_terminal_event_does_not_free_active_slot():
    """Per-model events (started/completed/failed) are not session-terminal
    and must not free the active-provider slot."""
    profile = ModelProfile(
        model_name="microsoft/Phi-4-reasoning",
        base_residency_mb=None,
    )
    orch = _make_orchestrator(
        profiles={"microsoft/Phi-4-reasoning": profile},
        configured=["microsoft/Phi-4-reasoning"],
    )
    orch._active_provider_id = 15

    orch._on_provider_event(15, {"event": "calibration_model_completed"})
    assert orch._active_provider_id == 15
    assert 15 not in orch._completed_this_window


@pytest.mark.asyncio
async def test_stop_active_session_sends_stop_session_rpc():
    """Outside the window (or on shutdown), the orchestrator sends
    stop_calibration_session to whichever worker holds the active slot."""
    orch = _make_orchestrator(profiles={}, configured=[])
    orch._active_provider_id = 15

    await orch._stop_active_session_if_any("outside-window")
    orch._registry.send_command.assert_awaited_once_with(
        15,
        "stop_calibration_session",
        timeout_seconds=20,
    )


@pytest.mark.asyncio
async def test_stop_active_session_noop_when_none_active():
    """No active session → no RPC fired, no error."""
    orch = _make_orchestrator(profiles={}, configured=[])
    await orch._stop_active_session_if_any("outside-window")
    orch._registry.send_command.assert_not_awaited()
