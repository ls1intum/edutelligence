from __future__ import annotations

import datetime
import json
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

import logos as main_mod


class _FakeDBManager:
    deployments: ClassVar[list[dict]] = []
    providers: ClassVar[list[dict]] = []
    raise_on_enter: ClassVar[bool] = False

    def __enter__(self):
        if type(self).raise_on_enter:
            raise RuntimeError("db down")
        return self

    def __exit__(self, *args):
        return False

    def get_all_deployments(self):
        return list(type(self).deployments)

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
    _FakeDBManager.raise_on_enter = False
    monkeypatch.setattr(main_mod, "DBManager", _FakeDBManager)
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", "test-secret")


def _body(response) -> dict:
    return json.loads(response.body)


def _internal_request(authorization: str = "Bearer test-secret") -> SimpleNamespace:
    return SimpleNamespace(headers={"authorization": authorization} if authorization else {})


# ---------------------------------------------------------------------------
# /health — public liveness signal, no model catalogue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_local_up_returns_200_lean_payload(monkeypatch):
    _FakeDBManager.providers = [
        {"provider_id": 1, "name": "node-a", "provider_type": "logosnode"},
    ]
    _FakeDBManager.deployments = [
        {"model_id": 1, "model_name": "model-a", "provider_id": 1, "provider_name": "node-a", "type": "logosnode"},
    ]
    snapshots = {1: _fresh_snapshot(capabilities=["model-a"], lanes=[{"model": "model-a", "runtime_state": "loaded"}])}
    registry = MagicMock()
    registry.peek_runtime_snapshot = snapshots.get
    monkeypatch.setattr(main_mod, "_logosnode_registry", registry)

    response = await main_mod.health()

    assert response.status_code == 200
    body = _body(response)
    assert body["status"] == "UP"
    assert body["local_models"] == "UP"
    # /health stays a lean liveness signal — it is public, so the model
    # catalogue lives on /internal/model_health instead.
    assert "models" not in body


@pytest.mark.asyncio
async def test_local_down_returns_503_and_keeps_cloud_breakdown(monkeypatch):
    _FakeDBManager.providers = [
        {"provider_id": 1, "name": "node-a", "provider_type": "logosnode"},
    ]
    _FakeDBManager.deployments = [
        {"model_id": 1, "model_name": "model-a", "provider_id": 1, "provider_name": "node-a", "type": "logosnode"},
        {"model_id": 2, "model_name": "model-d", "provider_id": 2, "provider_name": "openai", "type": "cloud"},
    ]
    registry = MagicMock()
    registry.peek_runtime_snapshot = lambda pid: None
    monkeypatch.setattr(main_mod, "_logosnode_registry", registry)

    response = await main_mod.health()

    assert response.status_code == 503
    body = _body(response)
    assert body["status"] == "DOWN"
    assert body["local_models"] == "DOWN"
    assert body["cloud_models"] == "UP"
    assert "Cloud models may still be served" in body["detail"]
    assert "models" not in body


@pytest.mark.asyncio
async def test_legacy_local_provider_is_not_counted_as_cloud(monkeypatch):
    # "ollama" is a legacy local worker type: list_local_providers counts it
    # as local, so its deployment must not flip cloud_models to UP.
    _FakeDBManager.providers = [
        {"provider_id": 1, "name": "node-a", "provider_type": "logosnode"},
        {"provider_id": 2, "name": "ollama-x", "provider_type": "ollama"},
    ]
    _FakeDBManager.deployments = [
        {"model_id": 1, "model_name": "model-a", "provider_id": 1, "provider_name": "node-a", "type": "logosnode"},
        {"model_id": 2, "model_name": "model-b", "provider_id": 2, "provider_name": "ollama-x", "type": "ollama"},
    ]
    registry = MagicMock()
    registry.peek_runtime_snapshot = lambda pid: None
    monkeypatch.setattr(main_mod, "_logosnode_registry", registry)

    response = await main_mod.health()

    assert _body(response)["cloud_models"] == "DOWN"


@pytest.mark.asyncio
async def test_db_failure_reports_down(monkeypatch):
    _FakeDBManager.raise_on_enter = True
    registry = MagicMock()
    registry.peek_runtime_snapshot = lambda pid: None
    monkeypatch.setattr(main_mod, "_logosnode_registry", registry)

    response = await main_mod.health()

    assert response.status_code == 503
    body = _body(response)
    assert body["status"] == "DOWN"
    assert "models" not in body


# ---------------------------------------------------------------------------
# /internal/model_health — secret-gated per-model breakdown
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_internal_model_health_requires_secret(monkeypatch):
    registry = MagicMock()
    registry.peek_runtime_snapshot = lambda pid: None
    monkeypatch.setattr(main_mod, "_logosnode_registry", registry)

    # No secret configured at all: the endpoint is disabled.
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", None)
    with pytest.raises(HTTPException) as exc:
        await main_mod.internal_model_health(_internal_request("Bearer anything"))
    assert exc.value.status_code == 403

    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", "test-secret")
    with pytest.raises(HTTPException) as exc:
        await main_mod.internal_model_health(_internal_request("Bearer wrong"))
    assert exc.value.status_code == 401
    with pytest.raises(HTTPException) as exc:
        await main_mod.internal_model_health(_internal_request(""))
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_internal_model_health_reports_200_with_model_breakdown(monkeypatch):
    _FakeDBManager.providers = [
        {"provider_id": 1, "name": "node-a", "provider_type": "logosnode"},
    ]
    _FakeDBManager.deployments = [
        {"model_id": 1, "model_name": "model-a", "provider_id": 1, "provider_name": "node-a", "type": "logosnode"},
    ]
    snapshots = {1: _fresh_snapshot(capabilities=["model-a"], lanes=[{"model": "model-a", "runtime_state": "loaded"}])}
    registry = MagicMock()
    registry.peek_runtime_snapshot = snapshots.get
    monkeypatch.setattr(main_mod, "_logosnode_registry", registry)

    response = await main_mod.internal_model_health(_internal_request())

    assert response.status_code == 200
    assert _body(response)["models"] == [{"name": "model-a", "status": "UP"}]


@pytest.mark.asyncio
async def test_internal_model_health_returns_503_when_local_down(monkeypatch):
    # 503 mirrors /health; the body still carries the breakdown, so cloud
    # models that are still serveable stay visible to the webservice client.
    _FakeDBManager.providers = [
        {"provider_id": 1, "name": "node-a", "provider_type": "logosnode"},
    ]
    _FakeDBManager.deployments = [
        {"model_id": 1, "model_name": "model-a", "provider_id": 1, "provider_name": "node-a", "type": "logosnode"},
        {"model_id": 2, "model_name": "model-d", "provider_id": 2, "provider_name": "openai", "type": "cloud"},
    ]
    registry = MagicMock()
    registry.peek_runtime_snapshot = lambda pid: None
    monkeypatch.setattr(main_mod, "_logosnode_registry", registry)

    response = await main_mod.internal_model_health(_internal_request())

    assert response.status_code == 503
    assert _body(response)["models"] == [
        {"name": "model-a", "status": "DOWN"},
        {"name": "model-d", "status": "UP"},
    ]


@pytest.mark.asyncio
async def test_models_report_overall_status_per_model(monkeypatch):
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
    stale = (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(seconds=main_mod._LOGOSNODE_STATS_STALE_AFTER_SECONDS + 60)
    ).isoformat()
    node_b = _fresh_snapshot(capabilities=["model-a"], lanes=[{"model": "model-a", "runtime_state": "running"}])
    node_b["last_heartbeat"] = stale
    node_c = _fresh_snapshot(
        capabilities=["model-e"],
        lanes=[{"model": "model-e", "runtime_state": "loaded"}],
        node_health={"healthy": False, "reason_code": "gpu-error"},
    )
    snapshots = {1: node_a, 2: node_b, 3: node_c}
    registry = MagicMock()
    registry.peek_runtime_snapshot = snapshots.get
    monkeypatch.setattr(main_mod, "_logosnode_registry", registry)

    response = await main_mod.internal_model_health(_internal_request())

    body = _body(response)
    by_name = {model["name"]: model["status"] for model in body["models"]}
    # Warm lane on node-a wins over the offline node-b and the cloud deployment.
    assert by_name["model-a"] == "UP"
    # Sleeping lane: still serveable (a wake is fast).
    assert by_name["model-b"] == "UP"
    # Calibrated but no lane loaded: a cold load is needed -> DEGRADED.
    assert by_name["model-c"] == "DEGRADED"
    # Cloud deployment: UP whenever configured.
    assert by_name["model-d"] == "UP"
    # Warm lane on a node reporting unhealthy hardware -> DEGRADED.
    assert by_name["model-e"] == "DEGRADED"
    # Online worker without the model calibrated -> DOWN.
    assert by_name["model-f"] == "DOWN"


@pytest.mark.asyncio
async def test_model_entries_expose_only_name_and_status(monkeypatch):
    _FakeDBManager.providers = [
        {"provider_id": 1, "name": "node-a", "provider_type": "logosnode"},
    ]
    _FakeDBManager.deployments = [
        {"model_id": 1, "model_name": "model-a", "provider_id": 1, "provider_name": "node-a", "type": "logosnode"},
    ]
    snapshots = {1: _fresh_snapshot(capabilities=["model-a"], lanes=[{"model": "model-a", "runtime_state": "loaded"}])}
    registry = MagicMock()
    registry.peek_runtime_snapshot = snapshots.get
    monkeypatch.setattr(main_mod, "_logosnode_registry", registry)

    response = await main_mod.internal_model_health(_internal_request())

    for model in _body(response)["models"]:
        assert set(model) == {"name", "status"}


@pytest.mark.asyncio
async def test_models_sorted_by_name(monkeypatch):
    _FakeDBManager.providers = []
    _FakeDBManager.deployments = [
        {"model_id": 2, "model_name": "zeta", "provider_id": 3, "provider_name": "openai", "type": "cloud"},
        {"model_id": 1, "model_name": "alpha", "provider_id": 3, "provider_name": "openai", "type": "cloud"},
    ]
    registry = MagicMock()
    registry.peek_runtime_snapshot = lambda pid: None
    monkeypatch.setattr(main_mod, "_logosnode_registry", registry)

    response = await main_mod.internal_model_health(_internal_request())

    assert [model["name"] for model in _body(response)["models"]] == ["alpha", "zeta"]


@pytest.mark.asyncio
async def test_db_failure_reports_503_with_empty_models(monkeypatch):
    _FakeDBManager.raise_on_enter = True
    registry = MagicMock()
    registry.peek_runtime_snapshot = lambda pid: None
    monkeypatch.setattr(main_mod, "_logosnode_registry", registry)

    response = await main_mod.internal_model_health(_internal_request())

    assert response.status_code == 503
    assert _body(response)["models"] == []
