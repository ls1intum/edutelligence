from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

import logos as main_mod
from logos.logosnode_registry import LogosNodeCommandError, LogosNodeOfflineError


def _make_request(authorization: str = "") -> MagicMock:
    request = MagicMock()
    request.headers.get = lambda key, default="": authorization if key == "authorization" else default
    return request


@pytest.mark.asyncio
async def test_returns_403_when_secret_not_configured(monkeypatch):
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", None)
    with pytest.raises(HTTPException) as exc_info:
        await main_mod.internal_compatibility_precheck("org/model", _make_request("Bearer secret"))
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_returns_401_when_secret_is_wrong(monkeypatch):
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", "correct-secret")
    with pytest.raises(HTTPException) as exc_info:
        await main_mod.internal_compatibility_precheck("org/model", _make_request("Bearer wrong-secret"))
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_single_provider_id_returns_one_result(monkeypatch):
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", "correct-secret")
    registry = MagicMock()
    registry.peek_runtime_snapshot = lambda pid: {"worker_id": "node-a"}
    registry.send_command = AsyncMock(
        return_value={"model": "org/model", "fit_tp_idle": 1, "fit_tp_current": 1, "unsupported_reason": None}
    )
    monkeypatch.setattr(main_mod, "_logosnode_registry", registry)

    response = await main_mod.internal_compatibility_precheck(
        "org/model", _make_request("Bearer correct-secret"), provider_id=7
    )
    body = json.loads(response.body)

    assert body["model"] == "org/model"
    assert len(body["results"]) == 1
    assert body["results"][0]["provider_id"] == 7
    assert body["results"][0]["provider_name"] == "node-a"
    assert body["results"][0]["fit_tp_idle"] == 1
    registry.send_command.assert_awaited_once_with(
        7, "run_compatibility_precheck", params={"model": "org/model"}, timeout_seconds=30
    )


@pytest.mark.asyncio
async def test_fans_out_across_all_active_providers_when_provider_id_omitted(monkeypatch):
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", "correct-secret")
    registry = MagicMock()
    registry.active_provider_ids = lambda: [1, 2]
    registry.peek_runtime_snapshot = lambda pid: {"worker_id": f"node-{pid}"}

    async def _send_command(pid, action, params, timeout_seconds):
        return {"fit_tp_idle": pid, "fit_tp_current": pid, "unsupported_reason": None}

    registry.send_command = AsyncMock(side_effect=_send_command)
    monkeypatch.setattr(main_mod, "_logosnode_registry", registry)

    response = await main_mod.internal_compatibility_precheck("org/model", _make_request("Bearer correct-secret"))
    body = json.loads(response.body)

    provider_ids = sorted(r["provider_id"] for r in body["results"])
    assert provider_ids == [1, 2]


@pytest.mark.asyncio
async def test_no_active_providers_returns_empty_results(monkeypatch):
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", "correct-secret")
    registry = MagicMock()
    registry.active_provider_ids = lambda: []
    monkeypatch.setattr(main_mod, "_logosnode_registry", registry)

    response = await main_mod.internal_compatibility_precheck("org/model", _make_request("Bearer correct-secret"))
    body = json.loads(response.body)

    assert body["results"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("exc", "expected_error"),
    [
        (LogosNodeOfflineError("no session"), "Worker not connected"),
        (LogosNodeCommandError("boom"), "boom"),
        (RuntimeError("totally unexpected"), "Unexpected error: totally unexpected"),
    ],
)
async def test_send_command_failure_reported_as_error_not_raised(monkeypatch, exc, expected_error):
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", "correct-secret")
    registry = MagicMock()
    registry.peek_runtime_snapshot = lambda pid: None
    registry.send_command = AsyncMock(side_effect=exc)
    monkeypatch.setattr(main_mod, "_logosnode_registry", registry)

    response = await main_mod.internal_compatibility_precheck(
        "org/model", _make_request("Bearer correct-secret"), provider_id=3
    )
    body = json.loads(response.body)

    assert body["results"][0]["ok"] is False
    assert body["results"][0]["error"] == expected_error


@pytest.mark.asyncio
async def test_one_providers_unexpected_failure_does_not_lose_the_others(monkeypatch):
    """The whole point of fanning out is answering "would this model run on
    ANY node" — one provider blowing up with something neither
    LogosNodeOfflineError nor LogosNodeCommandError must not take down the
    results already gathered for every other provider too."""
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", "correct-secret")
    registry = MagicMock()
    registry.active_provider_ids = lambda: [1, 2]
    registry.peek_runtime_snapshot = lambda pid: {"worker_id": f"node-{pid}"}

    async def _send_command(pid, action, params, timeout_seconds):
        if pid == 1:
            raise RuntimeError("boom")
        return {"fit_tp_idle": pid, "fit_tp_current": pid, "unsupported_reason": None}

    registry.send_command = AsyncMock(side_effect=_send_command)
    monkeypatch.setattr(main_mod, "_logosnode_registry", registry)

    response = await main_mod.internal_compatibility_precheck("org/model", _make_request("Bearer correct-secret"))
    body = json.loads(response.body)

    by_provider = {r["provider_id"]: r for r in body["results"]}
    assert by_provider[1]["ok"] is False
    assert by_provider[2]["fit_tp_idle"] == 2
