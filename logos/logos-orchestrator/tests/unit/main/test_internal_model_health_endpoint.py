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
    deployments: list[dict] = []
    providers: list[dict] = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get_all_deployments_with_names(self):
        return list(type(self).deployments)

    def list_local_providers(self):
        return list(type(self).providers)


def _fresh_snapshot(capabilities: list[str], lanes: list[dict], node_health: dict | None = None) -> dict:
    runtime: dict = {"lanes": lanes}
    if node_health is not None:
        runtime["node_health"] = node_health
    return {
        "last_heartbeat": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "capabilities_models": capabilities,
        "runtime": runtime,
    }


@pytest.fixture(autouse=True)
def fake_db(monkeypatch):
    _FakeDBManager.deployments = []
    _FakeDBManager.providers = []
    monkeypatch.setattr(main_mod, "DBManager", _FakeDBManager)


@pytest.mark.asyncio
async def test_returns_403_when_secret_not_configured(monkeypatch):
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", None)
    with pytest.raises(HTTPException) as exc_info:
        await main_mod.internal_model_health(_make_request("Bearer secret"))
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_returns_401_when_secret_is_wrong(monkeypatch):
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", "correct-secret")
    with pytest.raises(HTTPException) as exc_info:
        await main_mod.internal_model_health(_make_request("Bearer wrong-secret"))
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_reports_model_level_health(monkeypatch):
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", "correct-secret")
    _FakeDBManager.providers = [
        {"provider_id": 1, "name": "node-a", "provider_type": "logosnode"},
        {"provider_id": 2, "name": "node-b", "provider_type": "logosnode"},
        {"provider_id": 3, "name": "node-c", "provider_type": "logosnode"},
    ]
    _FakeDBManager.deployments = [
        {"model_id": 1, "model_name": "model-a", "provider_id": 1, "provider_name": "node-a", "type": "logosnode"},
        {"model_id": 1, "model_name": "model-a", "provider_id": 2, "provider_name": "node-b", "type": "logosnode"},
        {"model_id": 1, "model_name": "model-a", "provider_id": 4, "provider_name": "openai", "type": "cloud"},
        {"model_id": 2, "model_name": "model-b", "provider_id": 1, "provider_name": "node-a", "type": "logosnode"},
        {"model_id": 3, "model_name": "model-c", "provider_id": 1, "provider_name": "node-a", "type": "logosnode"},
        {"model_id": 4, "model_name": "model-d", "provider_id": 4, "provider_name": "openai", "type": "cloud"},
        {"model_id": 5, "model_name": "model-e", "provider_id": 3, "provider_name": "node-c", "type": "logosnode"},
        {"model_id": 6, "model_name": "model-f", "provider_id": 1, "provider_name": "node-a", "type": "logosnode"},
    ]

    node_a = _fresh_snapshot(
        capabilities=["model-a", "model-b", "model-c"],
        lanes=[
            {"model": "model-a", "runtime_state": "loaded"},
            {"model": "model-b", "runtime_state": "sleeping"},
        ],
    )
    node_c = _fresh_snapshot(
        capabilities=["model-e"],
        lanes=[{"model": "model-e", "runtime_state": "loaded"}],
        node_health={"healthy": False, "reason_code": "gpu-error"},
    )
    snapshots = {1: node_a, 2: None, 3: node_c}
    registry = MagicMock()
    registry.peek_runtime_snapshot = snapshots.get
    monkeypatch.setattr(main_mod, "_logosnode_registry", registry)

    result = await main_mod.internal_model_health(_make_request("Bearer correct-secret"))

    by_name = {model["name"]: model for model in result["models"]}
    assert set(by_name) == {"model-a", "model-b", "model-c", "model-d", "model-e", "model-f"}

    # Warm lane on node-a, offline node-b, configured cloud -> UP overall.
    model_a = by_name["model-a"]
    assert model_a["status"] == "UP"
    assert [d["status"] for d in model_a["deployments"]] == ["UP", "DOWN", "UP"]
    assert [d["state"] for d in model_a["deployments"]] == ["warm", "offline", None]

    # Sleeping lane is still serveable (a wake is needed), so the model is UP.
    model_b = by_name["model-b"]
    assert model_b["status"] == "UP"
    assert model_b["deployments"][0]["state"] == "sleeping"

    # Calibrated but no lane loaded: cold, yet still UP.
    model_c = by_name["model-c"]
    assert model_c["status"] == "UP"
    assert model_c["deployments"][0]["state"] == "cold"

    # Cloud deployment: UP whenever configured.
    model_d = by_name["model-d"]
    assert model_d["status"] == "UP"
    assert model_d["deployments"][0]["state"] is None

    # Warm lane on a node that reports unhealthy hardware -> DEGRADED.
    model_e = by_name["model-e"]
    assert model_e["status"] == "DEGRADED"
    assert model_e["deployments"][0]["state"] == "warm"

    # Online worker that has not calibrated the model -> DOWN/uncalibrated.
    model_f = by_name["model-f"]
    assert model_f["status"] == "DOWN"
    assert model_f["deployments"][0]["state"] == "uncalibrated"


@pytest.mark.asyncio
async def test_stale_heartbeat_counts_as_offline(monkeypatch):
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", "correct-secret")
    _FakeDBManager.providers = [
        {"provider_id": 7, "name": "node-stale", "provider_type": "logosnode"},
    ]
    _FakeDBManager.deployments = [
        {"model_id": 1, "model_name": "model-a", "provider_id": 7, "provider_name": "node-stale", "type": "logosnode"},
    ]

    stale = (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(seconds=main_mod._LOGOSNODE_STATS_STALE_AFTER_SECONDS + 60)
    ).isoformat()
    snapshot = _fresh_snapshot(capabilities=["model-a"], lanes=[{"model": "model-a", "runtime_state": "running"}])
    snapshot["last_heartbeat"] = stale
    registry = MagicMock()
    registry.peek_runtime_snapshot = lambda pid: snapshot if pid == 7 else None
    monkeypatch.setattr(main_mod, "_logosnode_registry", registry)

    result = await main_mod.internal_model_health(_make_request("Bearer correct-secret"))

    assert result["models"][0]["status"] == "DOWN"
    assert result["models"][0]["deployments"][0]["state"] == "offline"


@pytest.mark.asyncio
async def test_models_sorted_by_name(monkeypatch):
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", "correct-secret")
    _FakeDBManager.providers = []
    _FakeDBManager.deployments = [
        {"model_id": 2, "model_name": "zeta", "provider_id": 3, "provider_name": "openai", "type": "cloud"},
        {"model_id": 1, "model_name": "alpha", "provider_id": 3, "provider_name": "openai", "type": "cloud"},
    ]
    registry = MagicMock()
    registry.peek_runtime_snapshot = lambda pid: None
    monkeypatch.setattr(main_mod, "_logosnode_registry", registry)

    result = await main_mod.internal_model_health(_make_request("Bearer correct-secret"))

    assert [model["name"] for model in result["models"]] == ["alpha", "zeta"]
