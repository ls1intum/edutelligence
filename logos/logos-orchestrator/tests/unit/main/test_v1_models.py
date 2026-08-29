"""
Tests for the OpenAI-compatible /v1/models endpoints.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

import logos as main

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(headers: dict | None = None):
    """Create a mock FastAPI Request with the given headers."""
    req = MagicMock()
    if headers is None:
        req.headers = {"authorization": "Bearer test-key"}
    else:
        req.headers = headers
    return req


class DummyDB:
    """Minimal DBManager stub used via monkeypatch."""

    def __init__(self, models=None):
        self._models = models if models is not None else []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get_models_for_api_key(self, _api_key_id: int):
        return self._models

    def get_model_for_api_key(self, _api_key_id: int, model_name: str):
        return next((m for m in self._models if m["name"] == model_name), None)


# ---------------------------------------------------------------------------
# GET /v1/models — list models
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_models_returns_openai_format(monkeypatch):
    """Successful request returns the OpenAI list format."""
    fake_models = [
        {"id": 1, "name": "gpt-4o", "description": "GPT-4o"},
        {"id": 2, "name": "gpt-3.5-turbo", "description": None},
    ]

    monkeypatch.setattr(main, "DBManager", lambda: DummyDB(models=fake_models))

    with patch("logos.main.authenticate_api_key") as mock_auth:
        mock_auth.return_value = MagicMock(api_key_id=1, key_value="test-key")

        response = await main.list_models(_make_request())

    body = response.body
    import json

    data = json.loads(body)

    assert data["object"] == "list"
    assert len(data["data"]) == 2

    first = data["data"][0]
    assert first["id"] == "gpt-4o"
    assert first["object"] == "model"
    assert isinstance(first["created"], int)
    assert first["created"] > 0
    assert first["owned_by"] == "logos"

    second = data["data"][1]
    assert second["id"] == "gpt-3.5-turbo"


@pytest.mark.asyncio
async def test_list_models_empty(monkeypatch):
    """When a profile has no models, returns an empty list."""
    monkeypatch.setattr(main, "DBManager", lambda: DummyDB(models=[]))

    with patch("logos.main.authenticate_api_key") as mock_auth:
        mock_auth.return_value = MagicMock(api_key_id=1, key_value="test-key")

        response = await main.list_models(_make_request())

    import json

    data = json.loads(response.body)
    assert data["object"] == "list"
    assert data["data"] == []


@pytest.mark.asyncio
async def test_list_models_auth_failure():
    """Missing/invalid key returns 401."""
    with patch("logos.main.authenticate_api_key") as mock_auth:
        mock_auth.side_effect = HTTPException(status_code=401, detail="Invalid logos key")

        with pytest.raises(HTTPException) as exc:
            await main.list_models(_make_request(headers={}))

        assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# GET /v1/models/{model_id} — retrieve single model
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retrieve_model_success(monkeypatch):
    """Retrieve an accessible model returns the OpenAI model object."""
    fake_models = [
        {"id": 1, "name": "gpt-4o", "description": "GPT-4o"},
        {"id": 2, "name": "gpt-3.5-turbo", "description": None},
    ]

    monkeypatch.setattr(main, "DBManager", lambda: DummyDB(models=fake_models))

    with patch("logos.main.authenticate_api_key") as mock_auth:
        mock_auth.return_value = MagicMock(api_key_id=1, key_value="test-key")

        response = await main.retrieve_model("gpt-4o", _make_request())

    import json

    data = json.loads(response.body)

    assert data["id"] == "gpt-4o"
    assert data["object"] == "model"
    assert isinstance(data["created"], int)
    assert data["created"] > 0
    assert data["owned_by"] == "logos"


@pytest.mark.asyncio
async def test_retrieve_model_not_found(monkeypatch):
    """Requesting a model that doesn't exist returns 404."""
    monkeypatch.setattr(main, "DBManager", lambda: DummyDB(models=[]))

    with patch("logos.main.authenticate_api_key") as mock_auth:
        mock_auth.return_value = MagicMock(api_key_id=1, key_value="test-key")

        with pytest.raises(HTTPException) as exc:
            await main.retrieve_model("nonexistent-model", _make_request())

        assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_retrieve_model_no_access(monkeypatch):
    """User has models but not the requested one → 404."""
    fake_models = [
        {"id": 1, "name": "gpt-4o", "description": "GPT-4o"},
    ]
    monkeypatch.setattr(main, "DBManager", lambda: DummyDB(models=fake_models))

    with patch("logos.main.authenticate_api_key") as mock_auth:
        mock_auth.return_value = MagicMock(api_key_id=1, key_value="test-key")

        with pytest.raises(HTTPException) as exc:
            await main.retrieve_model("gpt-3.5-turbo", _make_request())

        assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_retrieve_model_with_slashes(monkeypatch):
    """Model IDs containing slashes (e.g. meta-llama/Llama-3-8B) work correctly."""
    slash_model = "meta-llama/Llama-3-8B"
    fake_models = [
        {"id": 1, "name": slash_model, "description": "Llama 3 8B"},
    ]
    monkeypatch.setattr(main, "DBManager", lambda: DummyDB(models=fake_models))

    with patch("logos.main.authenticate_api_key") as mock_auth:
        mock_auth.return_value = MagicMock(api_key_id=1, key_value="test-key")

        response = await main.retrieve_model(slash_model, _make_request())

    import json

    data = json.loads(response.body)

    assert data["id"] == slash_model
    assert data["object"] == "model"
    assert isinstance(data["created"], int)
    assert data["created"] > 0
    assert data["owned_by"] == "logos"


@pytest.mark.asyncio
async def test_retrieve_model_with_planner_sanitized_alias(monkeypatch):
    """Planner-safe aliases with underscores resolve back to canonical model ids."""
    canonical_model = "Qwen/Qwen2.5-0.5B-Instruct"
    alias_model = "Qwen_Qwen2.5-0.5B-Instruct"
    fake_models = [
        {"id": 1, "name": canonical_model, "description": "Qwen 0.5B"},
    ]
    monkeypatch.setattr(main, "DBManager", lambda: DummyDB(models=fake_models))

    with patch("logos.main.authenticate_api_key") as mock_auth:
        mock_auth.return_value = MagicMock(api_key_id=1, key_value="test-key")

        response = await main.retrieve_model(alias_model, _make_request())

    import json

    data = json.loads(response.body)

    assert data["id"] == canonical_model
    assert data["object"] == "model"


@pytest.mark.asyncio
async def test_retrieve_model_auth_failure():
    """Missing/invalid key on retrieve returns 401."""
    with patch("logos.main.authenticate_api_key") as mock_auth:
        mock_auth.side_effect = HTTPException(status_code=401, detail="Invalid logos key")

        with pytest.raises(HTTPException) as exc:
            await main.retrieve_model("gpt-4o", _make_request(headers={}))

        assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# max_model_len enrichment from logosnode runtime snapshots
# ---------------------------------------------------------------------------


class DummyRegistry:
    """Registry stub exposing runtime snapshots keyed by provider id."""

    def __init__(self, snapshots=None):
        self._snapshots = snapshots or {}

    def active_provider_ids(self):
        return list(self._snapshots.keys())

    def peek_runtime_snapshot(self, provider_id):
        return self._snapshots.get(provider_id)


def _snapshot(lanes, model_profiles=None):
    return {"runtime": {"lanes": lanes, "model_profiles": model_profiles or {}}}


def _vllm_lane(model, max_model_len=0, context_length=4096):
    return {
        "model": model,
        "vllm": True,
        "context_length": context_length,
        "backend_metrics": {"max_model_len": max_model_len},
    }


async def _list_ids_to_entries(monkeypatch, models, registry):
    import json

    monkeypatch.setattr(main, "DBManager", lambda: DummyDB(models=models))
    monkeypatch.setattr(main, "_logosnode_registry", registry)
    with patch("logos.main.authenticate_api_key") as mock_auth:
        mock_auth.return_value = MagicMock(api_key_id=1, key_value="test-key")
        response = await main.list_models(_make_request())
    return {entry["id"]: entry for entry in json.loads(response.body)["data"]}


@pytest.mark.asyncio
async def test_list_models_includes_served_context_window(monkeypatch):
    """Models with a live lane report max_model_len; others omit the key."""
    models = [
        {"id": 1, "name": "qwen-14b", "description": None},
        {"id": 2, "name": "gpt-4o", "description": None},
    ]
    registry = DummyRegistry({7: _snapshot([_vllm_lane("qwen-14b", max_model_len=40960)])})

    entries = await _list_ids_to_entries(monkeypatch, models, registry)

    assert entries["qwen-14b"]["max_model_len"] == 40960
    assert "max_model_len" not in entries["gpt-4o"]


@pytest.mark.asyncio
async def test_list_models_lane_configured_context_length(monkeypatch):
    """A lane whose engine has not reported a window falls back to its
    configured context_length (the 4096 sentinel means "unset")."""
    models = [{"id": 1, "name": "mistral-7b", "description": None}]
    lane = _vllm_lane("mistral-7b", max_model_len=0, context_length=16384)
    registry = DummyRegistry({7: _snapshot([lane])})

    entries = await _list_ids_to_entries(monkeypatch, models, registry)

    assert entries["mistral-7b"]["max_model_len"] == 16384


@pytest.mark.asyncio
async def test_list_models_min_across_workers(monkeypatch):
    """When workers serve the same model with different windows, the smallest wins."""
    models = [{"id": 1, "name": "qwen-14b", "description": None}]
    registry = DummyRegistry(
        {
            7: _snapshot([_vllm_lane("qwen-14b", max_model_len=40960)]),
            8: _snapshot([_vllm_lane("qwen-14b", max_model_len=32768)]),
        }
    )

    entries = await _list_ids_to_entries(monkeypatch, models, registry)

    assert entries["qwen-14b"]["max_model_len"] == 32768


@pytest.mark.asyncio
async def test_list_models_vllm_calibration_fallback(monkeypatch):
    """Without an explicit max_model_len (and the sentinel 4096 lane context),
    the calibrated profile value is used."""
    models = [{"id": 1, "name": "gemma-12b", "description": None}]
    registry = DummyRegistry(
        {
            7: _snapshot(
                [_vllm_lane("gemma-12b")],
                model_profiles={"gemma-12b": {"calibration_max_model_len": 24576}},
            )
        }
    )

    entries = await _list_ids_to_entries(monkeypatch, models, registry)

    assert entries["gemma-12b"]["max_model_len"] == 24576


@pytest.mark.asyncio
async def test_list_models_vllm_explicit_lane_context(monkeypatch):
    """A non-sentinel lane context_length acts as the explicit override."""
    models = [{"id": 1, "name": "qwen-7b", "description": None}]
    registry = DummyRegistry({7: _snapshot([_vllm_lane("qwen-7b", context_length=20480)])})

    entries = await _list_ids_to_entries(monkeypatch, models, registry)

    assert entries["qwen-7b"]["max_model_len"] == 20480


@pytest.mark.asyncio
async def test_list_models_unknown_window_omitted(monkeypatch):
    """A vLLM lane with no explicit config, sentinel context, and no profile
    yields no max_model_len rather than a wrong one."""
    models = [{"id": 1, "name": "qwen-7b", "description": None}]
    registry = DummyRegistry({7: _snapshot([_vllm_lane("qwen-7b")])})

    entries = await _list_ids_to_entries(monkeypatch, models, registry)

    assert "max_model_len" not in entries["qwen-7b"]


@pytest.mark.asyncio
async def test_retrieve_model_includes_served_context_window(monkeypatch):
    """The single-model endpoint carries the same enrichment."""
    import json

    models = [{"id": 1, "name": "qwen-14b", "description": None}]
    monkeypatch.setattr(main, "DBManager", lambda: DummyDB(models=models))
    monkeypatch.setattr(
        main,
        "_logosnode_registry",
        DummyRegistry({7: _snapshot([_vllm_lane("qwen-14b", max_model_len=40960)])}),
    )

    with patch("logos.main.authenticate_api_key") as mock_auth:
        mock_auth.return_value = MagicMock(api_key_id=1, key_value="test-key")
        response = await main.retrieve_model("qwen-14b", _make_request())

    assert json.loads(response.body)["max_model_len"] == 40960


@pytest.mark.asyncio
async def test_list_models_reports_best_and_native_next_to_the_minimum(monkeypatch):
    """Three figures, because one number cannot serve every client.

    ``max_model_len_current_min`` is the smallest window being served (holds
    whichever deployment answers) and ``max_model_len`` repeats it under the
    name vLLM uses. A client that would rather advertise the ceiling gets
    ``max_model_len_current_max`` (widest served right now) and
    ``max_model_len_overall`` (the widest it is ever served with).
    """
    models = [{"id": 1, "name": "qwen-27b", "description": None}]
    registry = DummyRegistry(
        {
            7: _snapshot(
                [_vllm_lane("qwen-27b", max_model_len=262144)],
                model_profiles={"qwen-27b": {"max_context_length": 262144}},
            ),
            8: _snapshot([_vllm_lane("qwen-27b", max_model_len=33000)]),
        }
    )

    entries = await _list_ids_to_entries(monkeypatch, models, registry)

    assert entries["qwen-27b"]["max_model_len"] == 33000
    assert entries["qwen-27b"]["max_model_len_current_min"] == 33000
    assert entries["qwen-27b"]["max_model_len_current_max"] == 262144
    assert entries["qwen-27b"]["max_model_len_overall"] == 262144


@pytest.mark.asyncio
async def test_list_models_native_length_without_a_live_lane(monkeypatch):
    """A model with a profile but nothing loaded still reports its own limit.

    That is the number a config file has to be written from, and it does not
    depend on what happens to be running at the time the page is opened.
    """
    models = [{"id": 1, "name": "cold-model", "description": None}]
    registry = DummyRegistry({7: _snapshot([], model_profiles={"cold-model": {"max_context_length": 131072}})})

    entries = await _list_ids_to_entries(monkeypatch, models, registry)

    assert entries["cold-model"]["max_model_len_overall"] == 131072
    assert "max_model_len" not in entries["cold-model"]
    assert "max_model_len_current_min" not in entries["cold-model"]
    assert "max_model_len_current_max" not in entries["cold-model"]


@pytest.mark.asyncio
async def test_list_models_omits_every_context_field_when_unknown(monkeypatch):
    """Cloud models keep the exact object they had before these fields existed."""
    models = [{"id": 1, "name": "gpt-4o", "description": None}]
    entries = await _list_ids_to_entries(monkeypatch, models, DummyRegistry({}))

    assert set(entries["gpt-4o"]) == {"id", "object", "created", "owned_by"}
