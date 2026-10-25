"""The endpoints a node manager uses to cordon its node while it replaces the worker container.

The manager authenticates with the key of the worker, so the orchestrator resolves the node from the key and a caller
cannot act on another node. Like the other worker endpoints, they require TLS because the key travels in the body.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

# Reuse the registry double of the service tests
from tests.unit.test_node_maintenance import FakeClock, FakeRegistry

import logos as main_mod
from logos.dbutils.dbrequest import LogosNodeMaintenanceRequest
from logos.node_maintenance import NodeMaintenance
from logos.routers import logosnode as logosnode_mod

KEYS = {"key-a": 1, "key-b": 2}


def _request(scheme: str = "https") -> MagicMock:
    request = MagicMock()
    request.url.scheme = scheme
    request.headers.get = lambda key, default="": default
    return request


def _body(key: str = "key-a", deployment_id: str = "d1") -> LogosNodeMaintenanceRequest:
    return LogosNodeMaintenanceRequest(shared_key=key, deployment_id=deployment_id)


@pytest.fixture
def service(monkeypatch) -> NodeMaintenance:
    registry = FakeRegistry()
    registry.add(1, "node-a", ["model-a"])
    registry.add(2, "node-b", ["model-b"])
    service = NodeMaintenance(registry, ttl_s=600, settle_s=10, clock=FakeClock())
    monkeypatch.setattr(main_mod, "_node_maintenance", service)

    def provider_for_key(shared_key: str) -> dict:
        if shared_key not in KEYS:
            raise HTTPException(status_code=404, detail="Provider not found for this API key")
        return {"id": KEYS[shared_key]}

    monkeypatch.setattr(logosnode_mod, "_logosnode_provider_for_key", provider_for_key)
    return service


@pytest.mark.asyncio
async def test_cordon_resolves_the_node_from_the_key(service):
    answer = await logosnode_mod.logosnode_maintenance_cordon(_body("key-b"), _request())

    assert answer["status"] == "granted"
    assert service.is_cordoned(2)
    assert not service.is_cordoned(1)


@pytest.mark.asyncio
async def test_a_key_that_belongs_to_no_node_is_rejected(service):
    with pytest.raises(HTTPException) as exc_info:
        await logosnode_mod.logosnode_maintenance_cordon(_body("unknown"), _request())

    assert exc_info.value.status_code == 404
    assert not service.is_cordoned(1)


@pytest.mark.asyncio
@pytest.mark.parametrize("call", ["cordon", "status", "release"])
async def test_the_key_must_not_travel_over_plain_http(service, call):
    endpoint = getattr(logosnode_mod, f"logosnode_maintenance_{call}")

    with pytest.raises(HTTPException) as exc_info:
        await endpoint(_body(), _request(scheme="http"))

    assert exc_info.value.status_code == 400
    assert not service.is_cordoned(1)


@pytest.mark.asyncio
async def test_a_node_cannot_release_the_lease_of_another_node(service):
    await logosnode_mod.logosnode_maintenance_cordon(_body("key-a", "d1"), _request())

    answer = await logosnode_mod.logosnode_maintenance_release(_body("key-b", "d1"), _request())

    assert answer == {"status": "no_lease"}
    assert service.is_cordoned(1)


@pytest.mark.asyncio
async def test_the_second_node_is_denied_until_the_first_released(service):
    await logosnode_mod.logosnode_maintenance_cordon(_body("key-a", "d1"), _request())

    denied = await logosnode_mod.logosnode_maintenance_cordon(_body("key-b", "d2"), _request())
    await logosnode_mod.logosnode_maintenance_release(_body("key-a", "d1"), _request())
    granted = await logosnode_mod.logosnode_maintenance_cordon(_body("key-b", "d2"), _request())

    assert denied["status"] == "denied"
    assert denied["holder"] == "node-a"
    assert granted["status"] == "granted"


@pytest.mark.asyncio
async def test_status_reports_the_session_the_manager_waits_for(service):
    await logosnode_mod.logosnode_maintenance_cordon(_body(), _request())

    answer = await logosnode_mod.logosnode_maintenance_status(_body(), _request())

    assert answer["status"] == "leased"
    assert answer["online"] is True
    assert answer["session_id"] == "session-1"
    assert answer["first_status_received"] is True


@pytest.mark.asyncio
async def test_release_ends_the_cordon(service):
    await logosnode_mod.logosnode_maintenance_cordon(_body(), _request())

    answer = await logosnode_mod.logosnode_maintenance_release(_body(), _request())

    assert answer == {"status": "released"}
    assert not service.is_cordoned(1)


@pytest.mark.parametrize("deployment_id", ["123456789-2", "a", "run.7_attempt-2", "A" * 64])
def test_a_deployment_id_of_the_node_manager_is_accepted(deployment_id):
    assert _body(deployment_id=deployment_id).deployment_id == deployment_id


@pytest.mark.parametrize(
    "deployment_id", ["", "-starts-with-dash", "has space", "semi;colon", "x" * 65, "new\nline", "trailing\n"]
)
def test_anything_else_is_not_a_deployment_id(deployment_id):
    with pytest.raises(ValidationError):
        _body(deployment_id=deployment_id)
