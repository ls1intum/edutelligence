from __future__ import annotations

import datetime
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

import logos as main_mod


def _make_request(authorization: str = "") -> MagicMock:
    request = MagicMock()
    request.headers.get = lambda key, default="": authorization if key == "authorization" else default
    return request


class _FakeDBManager:
    providers: list[dict] = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def list_local_providers(self):
        return list(type(self).providers)


@pytest.fixture(autouse=True)
def fake_db(monkeypatch):
    _FakeDBManager.providers = []
    monkeypatch.setattr(main_mod, "DBManager", _FakeDBManager)


@pytest.mark.asyncio
async def test_returns_403_when_secret_not_configured(monkeypatch):
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", None)
    with pytest.raises(HTTPException) as exc_info:
        await main_mod.internal_provider_status(_make_request("Bearer secret"))
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_returns_401_when_secret_is_wrong(monkeypatch):
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", "correct-secret")
    with pytest.raises(HTTPException) as exc_info:
        await main_mod.internal_provider_status(_make_request("Bearer wrong-secret"))
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_reports_connected_and_offline_providers(monkeypatch):
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", "correct-secret")
    _FakeDBManager.providers = [
        {"provider_id": 1, "name": "node-a", "provider_type": "logosnode"},
        {"provider_id": 2, "name": "node-b", "provider_type": "logosnode"},
    ]

    fresh_heartbeat = datetime.datetime.now(datetime.timezone.utc).isoformat()
    registry = MagicMock()
    registry.peek_runtime_snapshot = lambda pid: ({"last_heartbeat": fresh_heartbeat} if pid == 1 else None)
    monkeypatch.setattr(main_mod, "_logosnode_registry", registry)

    result = await main_mod.internal_provider_status(_make_request("Bearer correct-secret"))

    by_id = {p["provider_id"]: p for p in result["providers"]}
    assert by_id[1]["connected"] is True
    assert by_id[1]["connection_state"] == "online"
    assert by_id[1]["last_heartbeat"] == fresh_heartbeat
    assert by_id[2]["connected"] is False
    assert by_id[2]["connection_state"] == "offline"
    assert by_id[2]["last_heartbeat"] is None


@pytest.mark.asyncio
async def test_stale_heartbeat_counts_as_offline(monkeypatch):
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", "correct-secret")
    _FakeDBManager.providers = [
        {"provider_id": 7, "name": "node-stale", "provider_type": "logosnode"},
    ]

    stale = (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(seconds=main_mod._LOGOSNODE_STATS_STALE_AFTER_SECONDS + 60)
    ).isoformat()
    registry = MagicMock()
    registry.peek_runtime_snapshot = lambda pid: {"last_heartbeat": stale}
    monkeypatch.setattr(main_mod, "_logosnode_registry", registry)

    result = await main_mod.internal_provider_status(_make_request("Bearer correct-secret"))

    assert result["providers"][0]["connection_state"] == "offline"
