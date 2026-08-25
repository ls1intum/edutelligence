"""Tests for _register_models_with_facades (DB deployments -> SDI facades)."""

from __future__ import annotations

import pytest

import logos as main_mod
from logos import LogosNodeRuntimeRegistry
from logos.queue.priority_queue import PriorityQueueManager
from logos.sdi.azure_facade import AzureSchedulingDataFacade
from logos.sdi.logosnode_facade import LogosNodeSchedulingDataFacade


class _FakeWebSocket:
    async def close(self):
        pass


class _FakeDB:
    """Minimal DBManager stub with a fixed set of deployments."""

    def __init__(self, deployments, models, providers):
        self._deployments = deployments
        self._models = {m["id"]: m for m in models}
        self._providers = {p["id"]: p for p in providers}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get_all_deployments(self):
        return self._deployments

    def get_model(self, model_id):
        return self._models.get(model_id)

    def get_provider(self, provider_id):
        return self._providers.get(provider_id)

    def get_provider_config(self, provider_id):
        return {}

    def get_endpoint_for_deployment(self, model_id, provider_id):
        return None


async def _attach(registry, provider_id, worker_id, capabilities):
    ticket = await registry.consume_ticket(
        await registry.issue_ticket(provider_id, worker_id, list(capabilities))
    )
    assert ticket is not None
    await registry.attach_session(ticket, _FakeWebSocket())


@pytest.mark.asyncio
async def test_register_models_filters_connected_logosnode_by_live_capabilities(monkeypatch):
    """Deployments of a connected logosnode worker are filtered to its live
    capabilities (stale links are skipped), while a disconnected worker's DB
    deployments stay registered as before."""
    registry = LogosNodeRuntimeRegistry()
    # worker-a is connected and only serves model-b
    await _attach(registry, 100, "worker-a", ["model-b"])
    # worker-empty is connected with no capabilities — its stale DB link
    # must not be registered
    await _attach(registry, 102, "worker-empty", [])
    # worker-offline (101) has no session at all
    monkeypatch.setattr(main_mod, "_logosnode_registry", registry)

    db = _FakeDB(
        deployments=[
            {"model_id": 1, "provider_id": 100, "type": "logosnode"},  # stale for connected worker-a
            {"model_id": 2, "provider_id": 100, "type": "logosnode"},  # in worker-a's live capabilities
            {"model_id": 3, "provider_id": 101, "type": "logosnode"},  # offline worker: unfiltered
            {"model_id": 4, "provider_id": 102, "type": "logosnode"},  # stale for empty-caps worker
        ],
        models=[
            {"id": 1, "name": "model-a", "parallel": 1},
            {"id": 2, "name": "model-b", "parallel": 1},
            {"id": 3, "name": "model-c", "parallel": 1},
            {"id": 4, "name": "model-d", "parallel": 1},
        ],
        providers=[
            {"id": 100, "name": "worker-a", "provider_type": "logosnode", "base_url": "http://a:8080"},
            {"id": 101, "name": "worker-offline", "provider_type": "logosnode", "base_url": "http://o:8080"},
            {"id": 102, "name": "worker-empty", "provider_type": "logosnode", "base_url": "http://e:8080"},
        ],
    )
    monkeypatch.setattr(main_mod, "DBManager", lambda: db)

    facade = LogosNodeSchedulingDataFacade(PriorityQueueManager(), db)
    azure_facade = AzureSchedulingDataFacade(None)

    await main_mod._register_models_with_facades(facade, azure_facade)

    # model-a (100) and model-d (102) are skipped; model-b (100) and
    # model-c (101) are registered
    assert facade._model_to_provider == {2: {100}, 3: {101}}
