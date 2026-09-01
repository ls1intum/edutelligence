"""POST /v1/models/{model}/warmup — tell the planner a model is about to be used.

A coding assistant asks for the model list at startup and then sits idle while
the developer reads the terminal; the first real request lands seconds later and
pays for a cold load. This endpoint turns that pause into a hint.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

import logos as main
from logos.routers import user_facing as user_facing_mod


def _make_request():
    req = MagicMock()
    req.headers = {"authorization": "Bearer test-key"}
    return req


class DummyDB:
    def __init__(self, models):
        self._models = models

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get_models_for_api_key(self, _api_key_id):
        return self._models

    def get_model_for_api_key(self, _api_key_id, model_name):
        return next((m for m in self._models if m["name"] == model_name), None)


def _registry_serving(model: str, window: int) -> MagicMock:
    registry = MagicMock()
    registry.active_provider_ids = lambda: [1]
    registry.peek_runtime_snapshot = lambda pid: {
        "runtime": {
            "lanes": [{"model": model, "vllm": True, "backend_metrics": {"max_model_len": window}}],
            "model_profiles": {},
        }
    }
    return registry


@pytest.fixture
def wired(monkeypatch):
    """A warmup-able orchestrator with the demand tracker and planner spied on."""
    monkeypatch.setattr(main, "DBManager", lambda: DummyDB([{"id": 1, "name": "qwen-27b", "description": None}]))
    monkeypatch.setattr(
        user_facing_mod, "DBManager", lambda: DummyDB([{"id": 1, "name": "qwen-27b", "description": None}])
    )
    demand = MagicMock()
    planner = MagicMock()
    monkeypatch.setattr(main, "_demand_tracker", demand)
    monkeypatch.setattr(main, "_capacity_planner", planner)
    monkeypatch.setattr(main, "_logosnode_registry", MagicMock(active_provider_ids=lambda: []))
    return demand, planner


async def _warmup(model_id: str):
    with patch("logos.routers.user_facing.authenticate_api_key") as mock_auth:
        mock_auth.return_value = MagicMock(api_key_id=1, key_value="test-key")
        return await user_facing_mod.warmup_model(model_id, _make_request())


@pytest.mark.asyncio
async def test_records_latent_demand_and_wakes_the_planner(wired):
    demand, planner = wired

    response = await _warmup("qwen-27b")

    assert response.status_code == 202
    body = json.loads(response.body)
    assert body["model"] == "qwen-27b"
    assert body["hint_accepted"] is True
    # Latent demand, not a real request: weak enough that it cannot outrank live
    # traffic. The score alone cannot start a load, though — it is decayed before
    # the planner reads it — so the announcement is what the planner acts on.
    demand.record_latent_demand.assert_called_once_with("qwen-27b")
    planner.announce_upcoming_use.assert_called_once_with("qwen-27b")


@pytest.mark.asyncio
async def test_reports_serving_when_a_lane_is_already_up(monkeypatch, wired):
    monkeypatch.setattr(main, "_logosnode_registry", _registry_serving("qwen-27b", 262144))

    body = json.loads((await _warmup("qwen-27b")).body)

    assert body["status"] == "serving"
    assert body["max_model_len_current_min"] == 262144


@pytest.mark.asyncio
async def test_reports_preparing_when_nothing_is_loaded(wired):
    body = json.loads((await _warmup("qwen-27b")).body)
    assert body["status"] == "preparing"


@pytest.mark.asyncio
async def test_hints_again_for_an_already_serving_model(monkeypatch, wired):
    """A warm model still records the hint.

    Demand decays every planner cycle, so a long session with a quiet stretch
    would otherwise drift out of the planner's view and lose its lane to
    something else.
    """
    demand, planner = wired
    monkeypatch.setattr(main, "_logosnode_registry", _registry_serving("qwen-27b", 262144))

    await _warmup("qwen-27b")

    demand.record_latent_demand.assert_called_once_with("qwen-27b")
    planner.announce_upcoming_use.assert_called_once_with("qwen-27b")


@pytest.mark.asyncio
async def test_refuses_a_model_the_key_cannot_use(wired):
    """No warming models you have no permission for.

    Otherwise any authenticated key could push every model on the cluster up the
    planner's priority list.
    """
    demand, planner = wired

    with pytest.raises(HTTPException) as exc:
        await _warmup("some-other-model")

    assert exc.value.status_code == 404
    demand.record_latent_demand.assert_not_called()
    planner.announce_upcoming_use.assert_not_called()


@pytest.mark.asyncio
async def test_accepts_a_planner_sanitized_alias(wired):
    """The same aliases GET /v1/models/{id} accepts.

    A caller that read a model id from one endpoint has to be able to warm it
    with the other.
    """
    demand, _planner = wired
    monkeypatch_models = [{"id": 1, "name": "Qwen/Qwen2.5-0.5B", "description": None}]
    with (
        patch.object(main, "DBManager", lambda: DummyDB(monkeypatch_models)),
        patch.object(user_facing_mod, "DBManager", lambda: DummyDB(monkeypatch_models)),
    ):
        body = json.loads((await _warmup("Qwen_Qwen2.5-0.5B")).body)

    assert body["model"] == "Qwen/Qwen2.5-0.5B"
    demand.record_latent_demand.assert_called_once_with("Qwen/Qwen2.5-0.5B")


@pytest.mark.asyncio
async def test_accepts_a_stored_alias(wired):
    """Alt tags work the same as on the other model endpoints."""
    demand, _planner = wired
    monkeypatch_models = [{"id": 1, "name": "qwen-27b", "description": None, "aliases": ["local-flagship"]}]
    with (
        patch.object(main, "DBManager", lambda: DummyDB(monkeypatch_models)),
        patch.object(user_facing_mod, "DBManager", lambda: DummyDB(monkeypatch_models)),
    ):
        body = json.loads((await _warmup("local-flagship")).body)

    assert body["model"] == "qwen-27b"
    demand.record_latent_demand.assert_called_once_with("qwen-27b")


@pytest.mark.asyncio
async def test_accepts_case_variants(wired):
    demand, _planner = wired

    body = json.loads((await _warmup("QWEN-27B")).body)

    assert body["model"] == "qwen-27b"
    demand.record_latent_demand.assert_called_once_with("qwen-27b")


@pytest.mark.asyncio
async def test_survives_a_planner_that_is_not_running(monkeypatch):
    """Warmup is a nicety; it must never be the reason a session fails to start.

    The planner is ablatable (LOGOS_CAPACITY_PLANNER_ENABLED=false), so both
    collaborators can legitimately be absent.
    """
    monkeypatch.setattr(main, "DBManager", lambda: DummyDB([{"id": 1, "name": "qwen-27b", "description": None}]))
    monkeypatch.setattr(
        user_facing_mod, "DBManager", lambda: DummyDB([{"id": 1, "name": "qwen-27b", "description": None}])
    )
    monkeypatch.setattr(main, "_demand_tracker", None)
    monkeypatch.setattr(main, "_capacity_planner", None)
    monkeypatch.setattr(main, "_logosnode_registry", MagicMock(active_provider_ids=lambda: []))

    body = json.loads((await _warmup("qwen-27b")).body)

    assert body["hint_accepted"] is False


@pytest.mark.asyncio
async def test_auth_failure_propagates():
    with patch("logos.routers.user_facing.authenticate_api_key") as mock_auth:
        mock_auth.side_effect = HTTPException(status_code=401, detail="Invalid logos key")
        with pytest.raises(HTTPException) as exc:
            await user_facing_mod.warmup_model("qwen-27b", _make_request())
    assert exc.value.status_code == 401
