"""The load_status endpoint: the UI's way of learning a background load failed.

``lanes/add`` answers 202 and runs the load in the background, where a refusal
is otherwise only a log line. The statistics UI polls this endpoint while its
"Loading …" note is up and turns the note into the recorded reason once the
attempt is over — so the answer must carry the reason, and "no outcome known"
must stay distinguishable from "failed".
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

import logos as main_mod
from logos.routers import internal as internal_mod
from logos.dbutils.dbrequest import InternalLaneLoadStatusRequest


def _make_request(authorization: str = "") -> MagicMock:
    request = MagicMock()
    request.headers.get = lambda key, default="": authorization if key == "authorization" else default
    return request


def _payload(provider_id: int = 1, model: str = "org/model-a") -> InternalLaneLoadStatusRequest:
    return InternalLaneLoadStatusRequest(provider_id=provider_id, model=model)


@pytest.mark.asyncio
async def test_returns_403_when_secret_not_configured(monkeypatch):
    monkeypatch.setattr(internal_mod, "_INTERNAL_SECRET", None)
    with pytest.raises(HTTPException) as exc_info:
        await internal_mod.internal_logosnode_lane_load_status(_payload(), _make_request("Bearer secret"))
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_returns_401_when_secret_is_wrong(monkeypatch):
    monkeypatch.setattr(internal_mod, "_INTERNAL_SECRET", "correct-secret")
    with pytest.raises(HTTPException) as exc_info:
        await internal_mod.internal_logosnode_lane_load_status(_payload(), _make_request("Bearer wrong-secret"))
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_rejects_payload_without_model(monkeypatch):
    monkeypatch.setattr(internal_mod, "_INTERNAL_SECRET", "correct-secret")
    monkeypatch.setattr(main_mod, "_capacity_planner", MagicMock())
    with pytest.raises(HTTPException) as exc_info:
        await internal_mod.internal_logosnode_lane_load_status(_payload(model="  "), _make_request("Bearer correct-secret"))
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_returns_503_when_planner_is_not_ready(monkeypatch):
    monkeypatch.setattr(internal_mod, "_INTERNAL_SECRET", "correct-secret")
    monkeypatch.setattr(main_mod, "_capacity_planner", None)
    with pytest.raises(HTTPException) as exc_info:
        await internal_mod.internal_logosnode_lane_load_status(_payload(), _make_request("Bearer correct-secret"))
    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_returns_the_recorded_outcome(monkeypatch):
    monkeypatch.setattr(internal_mod, "_INTERNAL_SECRET", "correct-secret")
    planner = MagicMock()
    planner.get_manual_load_outcome.return_value = {
        "status": "failed",
        "updated_at": 123.0,
        "lane_id": "planner-org_model-a-2",
        "reason": "not enough free VRAM for this model",
    }
    monkeypatch.setattr(main_mod, "_capacity_planner", planner)

    response = await internal_mod.internal_logosnode_lane_load_status(
        _payload(provider_id=7), _make_request("Bearer correct-secret")
    )

    assert response == {
        "status": "failed",
        "model": "org/model-a",
        "provider_id": 7,
        "lane_id": "planner-org_model-a-2",
        "reason": "not enough free VRAM for this model",
        "updated_at": 123.0,
    }
    planner.get_manual_load_outcome.assert_called_once_with(7, "org/model-a")


@pytest.mark.asyncio
async def test_no_recorded_outcome_answers_unknown_not_failed(monkeypatch):
    """The planner holds no entry (never loaded here, expired, orchestrator
    restarted) — the UI must keep its note, not show a failure."""
    monkeypatch.setattr(internal_mod, "_INTERNAL_SECRET", "correct-secret")
    planner = MagicMock()
    planner.get_manual_load_outcome.return_value = None
    monkeypatch.setattr(main_mod, "_capacity_planner", planner)

    response = await internal_mod.internal_logosnode_lane_load_status(
        _payload(provider_id=7), _make_request("Bearer correct-secret")
    )

    assert response["status"] == "unknown"
    assert response["reason"] is None
    assert response["lane_id"] is None


@pytest.mark.asyncio
async def test_add_lane_records_running_before_answering(monkeypatch):
    """The UI polls from the moment it sees the 202 — a gap between the answer
    and the background task's first record would let it read the previous
    attempt's "failed" entry and show a stale failure for the fresh click."""
    monkeypatch.setattr(internal_mod, "_INTERNAL_SECRET", "correct-secret")
    planner = MagicMock()
    planner.manual_load_rejection_reason.return_value = None

    async def _load(provider_id: int, model_name: str) -> bool:
        return True

    planner.load_lane_manually = MagicMock(side_effect=_load)
    monkeypatch.setattr(main_mod, "_capacity_planner", planner)

    from logos.dbutils.dbrequest import InternalAddLaneRequest

    await internal_mod.internal_logosnode_add_lane(
        InternalAddLaneRequest(provider_id=7, lane={"model": "org/model-a"}),
        _make_request("Bearer correct-secret"),
    )

    # Recorded synchronously, before the 202 goes out — not by the task.
    planner.record_manual_load_outcome.assert_called_once_with(7, "org/model-a", "running")
    planner.load_lane_manually.assert_called_once_with(7, "org/model-a")
    # Let the scheduled task run so it does not outlive the test.
    await asyncio.sleep(0)
