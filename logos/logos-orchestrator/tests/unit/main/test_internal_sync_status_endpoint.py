"""The cloud model sync status endpoint the admin UI polls after a manual refresh."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

import logos as main_mod
from logos.routers import internal as internal_mod


def _make_request(authorization: str = "") -> MagicMock:
    request = MagicMock()
    request.headers.get = lambda key, default="": authorization if key == "authorization" else default
    return request


@pytest.mark.asyncio
async def test_returns_403_when_secret_not_configured(monkeypatch):
    monkeypatch.setattr(internal_mod, "_INTERNAL_SECRET", None)
    with pytest.raises(HTTPException) as exc_info:
        await internal_mod.internal_cloud_model_sync_status(_make_request("Bearer secret"))
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_returns_401_when_secret_is_wrong(monkeypatch):
    monkeypatch.setattr(internal_mod, "_INTERNAL_SECRET", "correct-secret")
    with pytest.raises(HTTPException) as exc_info:
        await internal_mod.internal_cloud_model_sync_status(_make_request("Bearer wrong-secret"))
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_returns_401_when_authorization_missing(monkeypatch):
    monkeypatch.setattr(internal_mod, "_INTERNAL_SECRET", "correct-secret")
    with pytest.raises(HTTPException) as exc_info:
        await internal_mod.internal_cloud_model_sync_status(_make_request(""))
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_a_running_pass_is_reported_as_running(monkeypatch):
    monkeypatch.setattr(internal_mod, "_INTERNAL_SECRET", "correct-secret")
    sync = MagicMock()
    sync.is_busy.return_value = True
    monkeypatch.setattr(main_mod, "_cloud_model_sync", sync, raising=False)

    result = await internal_mod.internal_cloud_model_sync_status(_make_request("Bearer correct-secret"))

    assert result == {"running": True}


@pytest.mark.asyncio
async def test_an_idle_sync_is_reported_as_not_running(monkeypatch):
    monkeypatch.setattr(internal_mod, "_INTERNAL_SECRET", "correct-secret")
    sync = MagicMock()
    sync.is_busy.return_value = False
    monkeypatch.setattr(main_mod, "_cloud_model_sync", sync, raising=False)

    result = await internal_mod.internal_cloud_model_sync_status(_make_request("Bearer correct-secret"))

    assert result == {"running": False}


@pytest.mark.asyncio
async def test_a_missing_sync_service_is_not_running(monkeypatch):
    """The sync service is created late in startup; the endpoint must tolerate that."""
    monkeypatch.setattr(internal_mod, "_INTERNAL_SECRET", "correct-secret")
    monkeypatch.setattr(main_mod, "_cloud_model_sync", None, raising=False)

    result = await internal_mod.internal_cloud_model_sync_status(_make_request("Bearer correct-secret"))

    assert result == {"running": False}
