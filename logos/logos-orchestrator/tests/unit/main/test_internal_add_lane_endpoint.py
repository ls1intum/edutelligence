from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

import logos as main_mod


def _make_request(authorization: str = "") -> MagicMock:
    request = MagicMock()
    request.headers.get = lambda key, default="": authorization if key == "authorization" else default
    return request


def _payload(provider_id: int = 1, lane: dict | None = None):
    return main_mod._InternalAddLaneRequest(
        provider_id=provider_id,
        lane={"model": "org/model-a"} if lane is None else lane,
    )


def _planner(rejection: str | None = None) -> MagicMock:
    planner = MagicMock()
    planner.manual_load_rejection_reason.return_value = rejection

    async def _load(provider_id: int, model_name: str) -> bool:
        return True

    planner.load_lane_manually = MagicMock(side_effect=_load)
    return planner


@pytest.mark.asyncio
async def test_returns_403_when_secret_not_configured(monkeypatch):
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", None)
    with pytest.raises(HTTPException) as exc_info:
        await main_mod.internal_logosnode_add_lane(_payload(), _make_request("Bearer secret"))
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_returns_401_when_secret_is_wrong(monkeypatch):
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", "correct-secret")
    with pytest.raises(HTTPException) as exc_info:
        await main_mod.internal_logosnode_add_lane(_payload(), _make_request("Bearer wrong-secret"))
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_rejects_lane_without_model(monkeypatch):
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", "correct-secret")
    monkeypatch.setattr(main_mod, "_capacity_planner", _planner())
    with pytest.raises(HTTPException) as exc_info:
        await main_mod.internal_logosnode_add_lane(
            _payload(lane={"model": "  "}), _make_request("Bearer correct-secret")
        )
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_returns_503_when_planner_is_not_ready(monkeypatch):
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", "correct-secret")
    monkeypatch.setattr(main_mod, "_capacity_planner", None)
    with pytest.raises(HTTPException) as exc_info:
        await main_mod.internal_logosnode_add_lane(_payload(), _make_request("Bearer correct-secret"))
    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_returns_409_while_the_provider_is_calibrating(monkeypatch):
    """A lane placed during calibration takes the VRAM the probes need.

    The planner excludes calibrating providers from its own cycle; a manual load
    must be refused for the same reason, and refused synchronously so the
    operator sees why.
    """
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", "correct-secret")
    planner = _planner(rejection="Provider is calibrating; its VRAM is reserved for the calibration probes.")
    monkeypatch.setattr(main_mod, "_capacity_planner", planner)

    with pytest.raises(HTTPException) as exc_info:
        await main_mod.internal_logosnode_add_lane(_payload(provider_id=7), _make_request("Bearer correct-secret"))

    assert exc_info.value.status_code == 409
    assert "calibrating" in exc_info.value.detail
    planner.load_lane_manually.assert_not_called()


@pytest.mark.asyncio
async def test_accepts_and_loads_through_the_planner(monkeypatch):
    """The load runs on the planner's path, in the background.

    Dispatching add_lane straight to the worker would skip the profile lookup,
    the VRAM reservation and the desired-lane bookkeeping — without the last of
    those, the next apply_lanes reconcile removes the lane again. And a load
    takes minutes, so the request must not wait for it.
    """
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", "correct-secret")
    planner = _planner()
    monkeypatch.setattr(main_mod, "_capacity_planner", planner)

    result = await main_mod.internal_logosnode_add_lane(_payload(provider_id=7), _make_request("Bearer correct-secret"))

    assert result == {"status": "accepted", "model": "org/model-a", "provider_id": 7}
    planner.load_lane_manually.assert_called_once_with(7, "org/model-a")
    # Let the scheduled task run so it does not outlive the test.
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_add_lane_has_no_dispatch_timeout_entry(monkeypatch):
    """add_lane no longer goes through _dispatch_logosnode_command.

    Its 180 s budget was below the planner's own 1800 s lane-load timeout, so a
    large model reported failure while the worker was still loading it.
    """
    assert "add_lane" not in main_mod._LOGOSNODE_CMD_TIMEOUTS
