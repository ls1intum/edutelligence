"""Tests for the temp-provider API endpoints in main.py."""

import json
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

import logos.main as main
from logos.temp_providers.discovery import DiscoveredModel
from logos.temp_providers.registry import TempProviderRegistry


@pytest.fixture(autouse=True)
def _reset_registry():
    TempProviderRegistry.reset_singleton()
    yield
    TempProviderRegistry.reset_singleton()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _auth_patch(monkeypatch, process_id=1, logos_key="lg-test"):
    """Patch authenticate_logos_key to avoid DB round-trips."""
    monkeypatch.setattr(
        main, "authenticate_logos_key",
        lambda headers: (logos_key, process_id),
    )


def _make_request(body: dict, headers: dict | None = None):
    """Build a fake Request-like object."""
    req = MagicMock()
    req.headers = headers or {"logos_key": "lg-test"}

    async def _json():
        return body

    req.json = _json
    return req


class _FakeDBManager:
    """Minimal DBManager stand-in."""

    def __init__(self, is_root=False):
        self._is_root = is_root

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def check_authorization(self, logos_key):
        return self._is_root


# ------------------------------------------------------------------
# POST /logosdb/add_temp_provider
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_temp_provider_success(monkeypatch):
    _auth_patch(monkeypatch, process_id=42)
    monkeypatch.setattr(
        main, "discover_models",
        AsyncMock(return_value=[DiscoveredModel(id="llama3")]),
    )

    req = _make_request({"url": "http://localhost:1234", "name": "my-mac"})
    resp = await main.add_temp_provider(req)

    assert resp.status_code == 201
    data = json.loads(resp.body)
    assert data["name"] == "my-mac"
    assert data["owner_process_id"] == 42
    assert len(data["models"]) == 1
    assert data["auth_token"].startswith("tpk-")


@pytest.mark.asyncio
async def test_add_temp_provider_missing_url(monkeypatch):
    _auth_patch(monkeypatch)
    req = _make_request({})
    with pytest.raises(main.HTTPException) as exc:
        await main.add_temp_provider(req)
    assert exc.value.status_code == 400


# ------------------------------------------------------------------
# DELETE /logosdb/remove_temp_provider/{provider_id}
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remove_temp_provider_owner(monkeypatch):
    _auth_patch(monkeypatch, process_id=5)
    monkeypatch.setattr(main, "DBManager", lambda: _FakeDBManager(is_root=False))

    reg = TempProviderRegistry()
    prov = reg.register(url="http://x", name="x", owner_process_id=5, models=[])

    req = _make_request({})
    resp = await main.remove_temp_provider(prov.id, req)
    assert resp.status_code == 200
    assert reg.get(prov.id) is None


@pytest.mark.asyncio
async def test_remove_temp_provider_not_owner(monkeypatch):
    _auth_patch(monkeypatch, process_id=999)
    monkeypatch.setattr(main, "DBManager", lambda: _FakeDBManager(is_root=False))

    reg = TempProviderRegistry()
    prov = reg.register(url="http://x", name="x", owner_process_id=5, models=[])

    req = _make_request({})
    with pytest.raises(main.HTTPException) as exc:
        await main.remove_temp_provider(prov.id, req)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_remove_temp_provider_root_can_remove(monkeypatch):
    _auth_patch(monkeypatch, process_id=999)
    monkeypatch.setattr(main, "DBManager", lambda: _FakeDBManager(is_root=True))

    reg = TempProviderRegistry()
    prov = reg.register(url="http://x", name="x", owner_process_id=5, models=[])

    req = _make_request({})
    resp = await main.remove_temp_provider(prov.id, req)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_remove_temp_provider_not_found(monkeypatch):
    _auth_patch(monkeypatch)
    req = _make_request({})
    with pytest.raises(main.HTTPException) as exc:
        await main.remove_temp_provider("nope", req)
    assert exc.value.status_code == 404


# ------------------------------------------------------------------
# GET /logosdb/temp_providers
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_temp_providers_root_sees_all(monkeypatch):
    _auth_patch(monkeypatch, process_id=1)
    monkeypatch.setattr(main, "DBManager", lambda: _FakeDBManager(is_root=True))

    reg = TempProviderRegistry()
    reg.register(url="http://a", name="a", owner_process_id=1, models=[])
    reg.register(url="http://b", name="b", owner_process_id=2, models=[])

    req = _make_request({})
    resp = await main.list_temp_providers(req)
    data = json.loads(resp.body)
    assert len(data["providers"]) == 2


@pytest.mark.asyncio
async def test_list_temp_providers_non_root_sees_own(monkeypatch):
    _auth_patch(monkeypatch, process_id=1)
    monkeypatch.setattr(main, "DBManager", lambda: _FakeDBManager(is_root=False))

    reg = TempProviderRegistry()
    reg.register(url="http://a", name="a", owner_process_id=1, models=[])
    reg.register(url="http://b", name="b", owner_process_id=2, models=[])

    req = _make_request({})
    resp = await main.list_temp_providers(req)
    data = json.loads(resp.body)
    assert len(data["providers"]) == 1
    assert data["providers"][0]["name"] == "a"


# ------------------------------------------------------------------
# POST /logosdb/refresh_temp_provider/{provider_id}
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_temp_provider(monkeypatch):
    _auth_patch(monkeypatch, process_id=5)
    monkeypatch.setattr(main, "DBManager", lambda: _FakeDBManager(is_root=False))
    monkeypatch.setattr(
        main, "discover_models",
        AsyncMock(return_value=[DiscoveredModel(id="new-model")]),
    )

    reg = TempProviderRegistry()
    prov = reg.register(url="http://x", name="x", owner_process_id=5, models=[])

    req = _make_request({})
    resp = await main.refresh_temp_provider(prov.id, req)
    data = json.loads(resp.body)
    assert len(data["models"]) == 1
    assert data["models"][0]["id"] == "new-model"


@pytest.mark.asyncio
async def test_refresh_temp_provider_not_found(monkeypatch):
    _auth_patch(monkeypatch)
    req = _make_request({})
    with pytest.raises(main.HTTPException) as exc:
        await main.refresh_temp_provider("nope", req)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_refresh_temp_provider_not_owner(monkeypatch):
    _auth_patch(monkeypatch, process_id=999)
    monkeypatch.setattr(main, "DBManager", lambda: _FakeDBManager(is_root=False))

    reg = TempProviderRegistry()
    prov = reg.register(url="http://x", name="x", owner_process_id=5, models=[])

    req = _make_request({})
    with pytest.raises(main.HTTPException) as exc:
        await main.refresh_temp_provider(prov.id, req)
    assert exc.value.status_code == 403
