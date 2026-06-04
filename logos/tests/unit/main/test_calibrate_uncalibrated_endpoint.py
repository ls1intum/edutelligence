"""Tests for the admin "calibrate uncalibrated models on a node" path.

Covers the model-selection helper that powers the endpoint (matches the
orchestrator's notion of "uncalibrated") and the endpoint's interaction with
the worker registry — without actually starting calibration on any worker.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from logos import main as main_mod
from logos.sdi.models import ModelProfile


def _profile(
    *,
    name: str,
    base: float | None = 1000.0,
    sleep: float | None = 50.0,
    sleep_l1: float | None = 200.0,
) -> ModelProfile:
    return ModelProfile(
        model_name=name,
        base_residency_mb=base,
        sleeping_residual_mb=sleep,
        sleep_l1_transient_host_ram_mb=sleep_l1,
    )


class _FakeFacade:
    """Minimal facade stub exposing the methods the helper consults."""

    def __init__(self, configured: list[str], profiles: dict[str, ModelProfile]):
        self._configured = configured
        self._profiles = profiles

    def get_configured_models(self, provider_id: int) -> list[str]:
        return list(self._configured)

    def get_worker_capabilities(self, provider_id: int) -> list[str]:
        return list(self._configured)

    def get_model_profiles(self, provider_id: int) -> dict[str, ModelProfile]:
        return dict(self._profiles)


def test_find_uncalibrated_returns_models_with_missing_profile_fields(monkeypatch):
    facade = _FakeFacade(
        configured=["calibrated-model", "no-profile", "missing-base", "missing-sleep", "missing-sleep-l1"],
        profiles={
            "calibrated-model": _profile(name="calibrated-model"),
            "missing-base": _profile(name="missing-base", base=None),
            "missing-sleep": _profile(name="missing-sleep", sleep=None),
            "missing-sleep-l1": _profile(name="missing-sleep-l1", sleep_l1=None),
        },
    )
    monkeypatch.setattr(main_mod, "_logosnode_facade", facade, raising=False)

    result = main_mod._find_uncalibrated_models_on_provider(7)

    # "no-profile" is missing from the profiles dict entirely.
    assert result == ["no-profile", "missing-base", "missing-sleep", "missing-sleep-l1"]


def test_find_uncalibrated_empty_when_everything_calibrated(monkeypatch):
    facade = _FakeFacade(
        configured=["a", "b"],
        profiles={"a": _profile(name="a"), "b": _profile(name="b")},
    )
    monkeypatch.setattr(main_mod, "_logosnode_facade", facade, raising=False)

    assert main_mod._find_uncalibrated_models_on_provider(1) == []


def test_find_uncalibrated_falls_back_to_capabilities_when_configured_empty(monkeypatch):
    class _LegacyFacade(_FakeFacade):
        def get_configured_models(self, provider_id: int) -> list[str]:
            return []

    facade = _LegacyFacade(configured=["legacy"], profiles={})
    monkeypatch.setattr(main_mod, "_logosnode_facade", facade, raising=False)

    # capabilities fallback exposes the model even though configured_models is empty.
    assert main_mod._find_uncalibrated_models_on_provider(1) == ["legacy"]


def test_find_uncalibrated_returns_empty_when_facade_unset(monkeypatch):
    monkeypatch.setattr(main_mod, "_logosnode_facade", None, raising=False)
    assert main_mod._find_uncalibrated_models_on_provider(1) == []


@pytest.mark.asyncio
async def test_endpoint_returns_uncalibrated_list_and_kicks_off_background_task(monkeypatch):
    facade = _FakeFacade(
        configured=["calibrated", "new-model"],
        profiles={"calibrated": _profile(name="calibrated")},
    )
    monkeypatch.setattr(main_mod, "_logosnode_facade", facade, raising=False)

    # Pretend the worker is connected and has reported status.
    fake_registry = MagicMock()
    fake_registry.peek_runtime_snapshot.return_value = {
        "provider_id": 4,
        "first_status_received": True,
        "capabilities_models": ["calibrated"],
        "configured_models": ["calibrated", "new-model"],
    }
    fake_registry.send_command = AsyncMock(return_value={"active": False})
    monkeypatch.setattr(main_mod, "_logosnode_registry", fake_registry, raising=False)

    # Bypass admin-key validation in the unit test.
    monkeypatch.setattr(main_mod, "_require_root_access", lambda _key: None, raising=False)

    # Track tasks spawned so the test can await the background work.
    spawned: list[asyncio.Task[Any]] = []
    original_create_task = asyncio.create_task

    def _capture_create_task(coro, *, name=None):
        task = original_create_task(coro, name=name)
        spawned.append(task)
        return task

    monkeypatch.setattr("logos.main.asyncio.create_task", _capture_create_task)

    body = main_mod.LogosNodeStatusRequest(logos_key="admin", provider_id=4)
    response = await main_mod.logosnode_calibrate_uncalibrated(body)

    assert response["count"] == 1
    assert response["models"] == ["new-model"]
    assert "Calibration started" in response["message"]
    assert spawned, "endpoint must spawn a background calibration task"

    # Let the background task finish so we can verify it actually issued the RPC.
    await asyncio.gather(*spawned)
    calls = [c.args + (c.kwargs,) for c in fake_registry.send_command.call_args_list]
    actions = [c[1] for c in calls]
    assert "start_calibration" in actions, f"expected start_calibration in {actions}"


@pytest.mark.asyncio
async def test_endpoint_returns_empty_when_no_uncalibrated_models(monkeypatch):
    facade = _FakeFacade(configured=["a"], profiles={"a": _profile(name="a")})
    monkeypatch.setattr(main_mod, "_logosnode_facade", facade, raising=False)

    fake_registry = MagicMock()
    fake_registry.peek_runtime_snapshot.return_value = {
        "provider_id": 4,
        "first_status_received": True,
    }
    fake_registry.send_command = AsyncMock()
    monkeypatch.setattr(main_mod, "_logosnode_registry", fake_registry, raising=False)
    monkeypatch.setattr(main_mod, "_require_root_access", lambda _key: None, raising=False)

    body = main_mod.LogosNodeStatusRequest(logos_key="admin", provider_id=4)
    response = await main_mod.logosnode_calibrate_uncalibrated(body)

    assert response == {"message": "No uncalibrated models on this worker", "count": 0, "models": []}
    fake_registry.send_command.assert_not_called()


@pytest.mark.asyncio
async def test_endpoint_503_when_worker_not_connected(monkeypatch):
    fake_registry = MagicMock()
    fake_registry.peek_runtime_snapshot.return_value = None
    monkeypatch.setattr(main_mod, "_logosnode_registry", fake_registry, raising=False)
    monkeypatch.setattr(main_mod, "_require_root_access", lambda _key: None, raising=False)

    body = main_mod.LogosNodeStatusRequest(logos_key="admin", provider_id=99)
    response = await main_mod.logosnode_calibrate_uncalibrated(body)

    assert response.status_code == 503
