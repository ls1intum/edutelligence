"""The drain endpoint: taking a busy lane offline without dropping its requests.

The manual sleep button is withheld from a lane that is still serving, so a
busy lane had no way to be put to sleep at all. This endpoint is the
counterpart: the planner marks the lane cold (no new requests routed to it),
waits for the in-flight ones to finish, then sleeps the lane — or unloads it
when the host cannot afford a resident sleeper, or the lane's backend has no
sleep mode. A lane that does not drain in time is left exactly as found, and
the endpoint answers 409 rather than killing its requests.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

import logos as main_mod
from logos.dbutils.dbrequest import InternalDrainLaneRequest
from logos.routers import internal as internal_mod


def _patch_registry(monkeypatch, registry) -> None:
    monkeypatch.setattr(main_mod, "_logosnode_registry", registry)


def _make_request(authorization: str = "") -> MagicMock:
    request = MagicMock()
    request.headers.get = lambda key, default="": authorization if key == "authorization" else default
    return request


def _lane(lane_id: str = "lane-1", active_requests: int = 1, sleep_state: str = "awake") -> dict:
    return {
        "lane_id": lane_id,
        "model": "org/model-a",
        "sleep_state": sleep_state,
        "active_requests": active_requests,
    }


def _snapshot(lanes: list[dict] | None = None, first_status: bool = True) -> dict:
    return {
        "provider_id": 1,
        "worker_id": "worker-1",
        "first_status_received": first_status,
        "runtime": {"lanes": lanes if lanes is not None else []},
    }


def _registry(snap: dict | None = None) -> MagicMock:
    registry = MagicMock()
    registry.peek_runtime_snapshot = lambda pid: snap
    return registry


def _planner(result: dict) -> MagicMock:
    planner = MagicMock()
    planner.drain_lane_manually = AsyncMock(return_value=result)
    return planner


def _payload(provider_id: int = 1, lane_id: str = "lane-1") -> InternalDrainLaneRequest:
    return InternalDrainLaneRequest(provider_id=provider_id, lane_id=lane_id)


def _drain(monkeypatch, registry, planner_result: dict):
    """Run the endpoint with a secret, a registry and a planner in place."""
    monkeypatch.setattr(internal_mod, "_INTERNAL_SECRET", "correct-secret")
    _patch_registry(monkeypatch, registry)
    monkeypatch.setattr(main_mod, "_capacity_planner", _planner(planner_result))
    return internal_mod.internal_logosnode_drain_lane(
        _payload(), _make_request("Bearer correct-secret")
    )


# ── validation (mirrors the sleep endpoint) ──────────────────────────────────


@pytest.mark.asyncio
async def test_returns_403_when_secret_not_configured(monkeypatch):
    monkeypatch.setattr(internal_mod, "_INTERNAL_SECRET", None)
    with pytest.raises(HTTPException) as exc_info:
        await internal_mod.internal_logosnode_drain_lane(_payload(), _make_request("Bearer secret"))
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_returns_401_when_secret_is_wrong(monkeypatch):
    monkeypatch.setattr(internal_mod, "_INTERNAL_SECRET", "correct-secret")
    with pytest.raises(HTTPException) as exc_info:
        await internal_mod.internal_logosnode_drain_lane(_payload(), _make_request("Bearer wrong-secret"))
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_returns_503_when_worker_not_connected(monkeypatch):
    response = await _drain(monkeypatch, _registry(snap=None), {"status": "slept"})

    assert response.status_code == 503
    assert json.loads(response.body) == {"error": "Worker not connected"}


@pytest.mark.asyncio
async def test_returns_503_before_the_worker_sent_its_first_status(monkeypatch):
    response = await _drain(monkeypatch, _registry(snap=_snapshot(first_status=False)), {"status": "slept"})

    assert response.status_code == 503


@pytest.mark.asyncio
async def test_returns_404_for_a_lane_the_worker_does_not_report(monkeypatch):
    registry = _registry(snap=_snapshot(lanes=[_lane(lane_id="lane-2")]))
    planner = MagicMock()
    planner.drain_lane_manually = AsyncMock()
    monkeypatch.setattr(internal_mod, "_INTERNAL_SECRET", "correct-secret")
    _patch_registry(monkeypatch, registry)
    monkeypatch.setattr(main_mod, "_capacity_planner", planner)

    response = await internal_mod.internal_logosnode_drain_lane(
        _payload(lane_id="lane-1"), _make_request("Bearer correct-secret")
    )

    assert response.status_code == 404
    planner.drain_lane_manually.assert_not_called()


@pytest.mark.asyncio
async def test_returns_503_when_the_planner_is_not_ready(monkeypatch):
    monkeypatch.setattr(internal_mod, "_INTERNAL_SECRET", "correct-secret")
    _patch_registry(monkeypatch, _registry(snap=_snapshot(lanes=[_lane()])))
    monkeypatch.setattr(main_mod, "_capacity_planner", None)

    with pytest.raises(HTTPException) as exc_info:
        await internal_mod.internal_logosnode_drain_lane(
            _payload(), _make_request("Bearer correct-secret")
        )
    assert exc_info.value.status_code == 503


# ── the planner's result mapped onto a status code ───────────────────────────


@pytest.mark.asyncio
async def test_slept_answers_200_with_the_result(monkeypatch):
    result = {"status": "slept", "lane_id": "lane-1"}
    response = await _drain(monkeypatch, _registry(snap=_snapshot(lanes=[_lane()])), result)

    assert response.status_code == 200
    assert json.loads(response.body) == result


@pytest.mark.asyncio
async def test_unloaded_answers_200_with_the_reason(monkeypatch):
    result = {"status": "unloaded", "lane_id": "lane-1", "reason": "host RAM headroom too low"}
    response = await _drain(monkeypatch, _registry(snap=_snapshot(lanes=[_lane()])), result)

    assert response.status_code == 200
    assert json.loads(response.body) == result


@pytest.mark.asyncio
async def test_drain_timeout_answers_409_with_the_reason(monkeypatch):
    result = {
        "status": "drain_timeout",
        "lane_id": "lane-1",
        "error": "Lane lane-1 did not drain within 60s; its requests keep running and the lane keeps serving.",
    }
    response = await _drain(monkeypatch, _registry(snap=_snapshot(lanes=[_lane()])), result)

    assert response.status_code == 409
    assert json.loads(response.body) == {"error": result["error"]}


@pytest.mark.asyncio
async def test_command_failure_answers_502_with_the_reason(monkeypatch):
    result = {"status": "error", "lane_id": "lane-1", "error": "worker refused 'sleep_lane'"}
    response = await _drain(monkeypatch, _registry(snap=_snapshot(lanes=[_lane()])), result)

    assert response.status_code == 502
    assert json.loads(response.body) == {"error": "worker refused 'sleep_lane'"}


@pytest.mark.asyncio
async def test_the_planner_receives_provider_and_lane_from_the_payload(monkeypatch):
    planner = _planner({"status": "slept", "lane_id": "lane-9"})
    monkeypatch.setattr(internal_mod, "_INTERNAL_SECRET", "correct-secret")
    _patch_registry(monkeypatch, _registry(snap=_snapshot(lanes=[_lane(lane_id="lane-9")])))
    monkeypatch.setattr(main_mod, "_capacity_planner", planner)

    await internal_mod.internal_logosnode_drain_lane(
        _payload(provider_id=7, lane_id="lane-9"), _make_request("Bearer correct-secret")
    )

    planner.drain_lane_manually.assert_awaited_once_with(7, "lane-9")
