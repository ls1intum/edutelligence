"""Tests for `GET /v1/peer/status`.

This endpoint is consumed by remote Logos servers that use this instance as a
`logos_peer` upstream. It must:

* require a valid logos_key (authenticate_with_profile)
* report each profile-accessible model with an `available` / `loaded` /
  `queue_depth` triple
* aggregate a top-level `capacity.free_slots` count
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

import logos.main as main


def _make_request():
    req = MagicMock()
    req.headers = {"authorization": "Bearer test-key"}
    return req


class _DummyDB:
    def __init__(self, *, models, deployments):
        self._models = models
        self._deployments = deployments

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def get_models_for_profile(self, _profile_id):
        return self._models

    def get_all_deployments(self):
        return self._deployments


def _set_pipeline_globals(monkeypatch, *, azure=None, logosnode=None, queue_mgr=None):
    """The pipeline globals are only populated by start_pipeline() at runtime;
    inject the ones the endpoint reads, creating them if needed."""
    monkeypatch.setattr(main, "_azure_facade", azure, raising=False)
    monkeypatch.setattr(main, "_logosnode_facade", logosnode, raising=False)
    monkeypatch.setattr(main, "_queue_mgr", queue_mgr, raising=False)


@pytest.mark.asyncio
async def test_peer_status_returns_models_and_capacity(monkeypatch):
    fake_models = [{"id": 1, "name": "gpt-4o"}]
    fake_deployments = [{"model_id": 1, "provider_id": 7, "type": "azure"}]

    monkeypatch.setattr(
        main, "DBManager", lambda: _DummyDB(models=fake_models, deployments=fake_deployments)
    )
    fake_azure = MagicMock()
    fake_azure.get_model_capacity.return_value = MagicMock(has_capacity=True)
    fake_qmgr = MagicMock()
    fake_qmgr.get_total_depth_by_model.return_value = 0
    _set_pipeline_globals(monkeypatch, azure=fake_azure, logosnode=None, queue_mgr=fake_qmgr)

    with patch("logos.auth.authenticate_with_profile") as mock_auth:
        from logos.auth import AuthContext

        mock_auth.return_value = AuthContext(
            logos_key="test-key", process_id=1, profile_id=42, profile_name="p"
        )
        response = await main.peer_status(_make_request())

    body = json.loads(response.body)
    assert body["status"] == "healthy"
    assert body["capacity"]["free_slots"] == 1
    assert body["capacity"]["total_models"] == 1
    assert body["models"] == [
        {"id": "gpt-4o", "available": True, "loaded": True, "queue_depth": 0}
    ]


@pytest.mark.asyncio
async def test_peer_status_excludes_logos_peer_deployments(monkeypatch):
    """Peer-of-peer deployments must not be reported — avoids loops."""
    fake_models = [{"id": 1, "name": "gpt-4o"}]
    fake_deployments = [{"model_id": 1, "provider_id": 9, "type": "logos_peer"}]

    monkeypatch.setattr(
        main, "DBManager", lambda: _DummyDB(models=fake_models, deployments=fake_deployments)
    )
    _set_pipeline_globals(monkeypatch, azure=None, logosnode=None, queue_mgr=None)

    with patch("logos.auth.authenticate_with_profile") as mock_auth:
        from logos.auth import AuthContext

        mock_auth.return_value = AuthContext(
            logos_key="test-key", process_id=1, profile_id=42, profile_name="p"
        )
        response = await main.peer_status(_make_request())

    body = json.loads(response.body)
    assert body["capacity"]["free_slots"] == 0
    assert body["models"][0]["available"] is False
