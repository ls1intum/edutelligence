from __future__ import annotations

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
    with pytest.raises(HTTPException) as exc_info:
        await main_mod.internal_logosnode_add_lane(
            _payload(lane={"model": "  "}), _make_request("Bearer correct-secret")
        )
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_dispatches_planner_built_params_not_the_raw_lane(monkeypatch):
    """A manual load must carry the calibrated profile, not LaneConfig defaults.

    Forwarding the caller's bare ``{"model": ...}`` would make the worker build a
    LaneConfig with ``vllm=False``, starting a vLLM-calibrated model on the wrong
    backend and bypassing the planner's VRAM accounting.
    """
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", "correct-secret")

    planner_params = {
        "lane_id": "planner-org_model-a",
        "model": "org/model-a",
        "vllm": True,
        "vllm_config": {"enable_sleep_mode": True, "tensor_parallel_size": 2},
    }
    planner = MagicMock()
    planner.build_manual_load_params.return_value = planner_params
    monkeypatch.setattr(main_mod, "_capacity_planner", planner)

    dispatched: dict = {}

    async def _fake_dispatch(provider_id: int, action: str, params: dict):
        dispatched.update(provider_id=provider_id, action=action, params=params)
        return {"status": "ok"}

    monkeypatch.setattr(main_mod, "_dispatch_logosnode_command", _fake_dispatch)

    result = await main_mod.internal_logosnode_add_lane(_payload(provider_id=7), _make_request("Bearer correct-secret"))

    assert result == {"status": "ok"}
    planner.build_manual_load_params.assert_called_once_with(7, "org/model-a")
    assert dispatched == {"provider_id": 7, "action": "add_lane", "params": planner_params}


@pytest.mark.asyncio
async def test_returns_503_when_planner_is_not_ready(monkeypatch):
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", "correct-secret")
    monkeypatch.setattr(main_mod, "_capacity_planner", None)
    with pytest.raises(HTTPException) as exc_info:
        await main_mod.internal_logosnode_add_lane(_payload(), _make_request("Bearer correct-secret"))
    assert exc_info.value.status_code == 503
