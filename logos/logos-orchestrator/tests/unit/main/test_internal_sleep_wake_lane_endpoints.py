from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

import logos as main_mod
from logos.logosnode_registry import LogosNodeOfflineError


def _make_request(authorization: str = "") -> MagicMock:
    request = MagicMock()
    request.headers.get = lambda key, default="": authorization if key == "authorization" else default
    return request


def _lane(lane_id: str = "lane-1", active_requests: int | None = 0, sleep_state: str = "awake") -> dict:
    lane = {"lane_id": lane_id, "model": "org/model-a", "sleep_state": sleep_state}
    if active_requests is not None:
        lane["active_requests"] = active_requests
    return lane


def _snapshot(lanes: list[dict] | None = None, first_status: bool = True) -> dict:
    return {
        "provider_id": 1,
        "worker_id": "worker-1",
        "first_status_received": first_status,
        "runtime": {"lanes": lanes if lanes is not None else []},
    }


def _registry(snap: dict | None = None, command_result: dict | None = None) -> MagicMock:
    registry = MagicMock()
    registry.peek_runtime_snapshot = lambda pid: snap
    registry.send_command = AsyncMock(return_value=command_result if command_result is not None else {})
    return registry


def _sleep_payload(provider_id: int = 1, lane_id: str = "lane-1"):
    return main_mod._InternalSleepLaneRequest(provider_id=provider_id, lane_id=lane_id)


def _wake_payload(provider_id: int = 1, lane_id: str = "lane-1"):
    return main_mod._InternalWakeLaneRequest(provider_id=provider_id, lane_id=lane_id)


# ── sleep ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sleep_returns_403_when_secret_not_configured(monkeypatch):
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", None)
    with pytest.raises(HTTPException) as exc_info:
        await main_mod.internal_logosnode_sleep_lane(_sleep_payload(), _make_request("Bearer secret"))
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_sleep_returns_401_when_secret_is_wrong(monkeypatch):
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", "correct-secret")
    with pytest.raises(HTTPException) as exc_info:
        await main_mod.internal_logosnode_sleep_lane(_sleep_payload(), _make_request("Bearer wrong-secret"))
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_sleep_returns_503_when_worker_not_connected(monkeypatch):
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", "correct-secret")
    monkeypatch.setattr(main_mod, "_logosnode_registry", _registry(snap=None))

    response = await main_mod.internal_logosnode_sleep_lane(_sleep_payload(), _make_request("Bearer correct-secret"))

    assert response.status_code == 503
    assert json.loads(response.body) == {"error": "Worker not connected"}


@pytest.mark.asyncio
async def test_sleep_returns_503_before_the_worker_sent_its_first_status(monkeypatch):
    """No status means no lanes, so the guard has nothing to read.

    Dispatching anyway would burn the 30 s command timeout only to fail on the
    worker — say so up front, the same way calibrate_uncalibrated does.
    """
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", "correct-secret")
    monkeypatch.setattr(main_mod, "_logosnode_registry", _registry(snap=_snapshot(first_status=False)))

    response = await main_mod.internal_logosnode_sleep_lane(_sleep_payload(), _make_request("Bearer correct-secret"))

    assert response.status_code == 503


@pytest.mark.asyncio
async def test_sleep_returns_404_for_a_lane_the_worker_does_not_report(monkeypatch):
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", "correct-secret")
    registry = _registry(snap=_snapshot(lanes=[_lane(lane_id="lane-2")]))
    monkeypatch.setattr(main_mod, "_logosnode_registry", registry)

    response = await main_mod.internal_logosnode_sleep_lane(
        _sleep_payload(lane_id="lane-1"), _make_request("Bearer correct-secret")
    )

    assert response.status_code == 404
    registry.send_command.assert_not_called()


@pytest.mark.asyncio
async def test_sleep_refuses_a_lane_that_is_serving(monkeypatch):
    """Sleeping a busy lane cuts requests off mid-stream.

    The worker's mode="wait" drain would wait out the 30 s budget and end in a
    silent no-op; the operator instead gets the reason synchronously, in the
    shape the panel already displays for refusals.
    """
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", "correct-secret")
    registry = _registry(snap=_snapshot(lanes=[_lane(active_requests=2, sleep_state="awake")]))
    monkeypatch.setattr(main_mod, "_logosnode_registry", registry)

    with pytest.raises(HTTPException) as exc_info:
        await main_mod.internal_logosnode_sleep_lane(_sleep_payload(), _make_request("Bearer correct-secret"))

    assert exc_info.value.status_code == 409
    assert "2 active request" in exc_info.value.detail
    registry.send_command.assert_not_called()


@pytest.mark.asyncio
async def test_sleep_treats_a_missing_active_requests_count_as_idle(monkeypatch):
    """Older workers may omit the field; absence is not evidence of traffic."""
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", "correct-secret")
    registry = _registry(
        snap=_snapshot(lanes=[_lane(active_requests=None)]), command_result={"sleep_state": "sleeping"}
    )
    monkeypatch.setattr(main_mod, "_logosnode_registry", registry)

    response = await main_mod.internal_logosnode_sleep_lane(_sleep_payload(), _make_request("Bearer correct-secret"))

    assert response == {"sleep_state": "sleeping"}


@pytest.mark.asyncio
async def test_sleep_dispatches_level_1_wait(monkeypatch):
    """Level 1 keeps the weights resident so the wake is fast; the endpoint
    does not expose the level — see the endpoint docstring for why.
    """
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", "correct-secret")
    registry = _registry(snap=_snapshot(lanes=[_lane(active_requests=0)]), command_result={"lane_id": "lane-1"})
    monkeypatch.setattr(main_mod, "_logosnode_registry", registry)

    response = await main_mod.internal_logosnode_sleep_lane(
        _sleep_payload(provider_id=7), _make_request("Bearer correct-secret")
    )

    assert response == {"lane_id": "lane-1"}
    registry.send_command.assert_called_once_with(
        7,
        action="sleep_lane",
        params={"lane_id": "lane-1", "level": 1, "mode": "wait"},
        timeout_seconds=30,
    )


# ── wake ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_wake_returns_403_when_secret_not_configured(monkeypatch):
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", None)
    with pytest.raises(HTTPException) as exc_info:
        await main_mod.internal_logosnode_wake_lane(_wake_payload(), _make_request("Bearer secret"))
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_wake_returns_401_when_secret_is_wrong(monkeypatch):
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", "correct-secret")
    with pytest.raises(HTTPException) as exc_info:
        await main_mod.internal_logosnode_wake_lane(_wake_payload(), _make_request("Bearer wrong-secret"))
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_wake_dispatches_to_the_worker(monkeypatch):
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", "correct-secret")
    registry = _registry(command_result={"lane_id": "lane-1", "sleep_state": "awake"})
    monkeypatch.setattr(main_mod, "_logosnode_registry", registry)

    response = await main_mod.internal_logosnode_wake_lane(
        _wake_payload(provider_id=7), _make_request("Bearer correct-secret")
    )

    assert response == {"lane_id": "lane-1", "sleep_state": "awake"}
    registry.send_command.assert_called_once_with(
        7,
        action="wake_lane",
        params={"lane_id": "lane-1"},
        timeout_seconds=120,
    )


@pytest.mark.asyncio
async def test_wake_returns_503_when_the_worker_is_offline(monkeypatch):
    """No snapshot guard for wake: an offline worker is a transport failure,
    and _dispatch_logosnode_command already answers it with a 503."""
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", "correct-secret")
    registry = MagicMock()
    registry.send_command = AsyncMock(side_effect=LogosNodeOfflineError("No active logosnode worker session"))
    monkeypatch.setattr(main_mod, "_logosnode_registry", registry)

    response = await main_mod.internal_logosnode_wake_lane(_wake_payload(), _make_request("Bearer correct-secret"))

    assert response.status_code == 503
    assert json.loads(response.body) == {"error": "No active logosnode worker session"}
