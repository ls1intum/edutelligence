"""
Tests for the OpenAI-compatible /v1/models endpoints.
"""

import pytest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

import logos.main as main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_request(headers: dict | None = None):
    """Create a mock FastAPI Request with the given headers."""
    req = MagicMock()
    req.headers = headers or {"authorization": "Bearer test-key"}
    return req


class DummyDB:
    """Minimal DBManager stub used via monkeypatch."""

    def __init__(self, models=None):
        self._models = models if models is not None else []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get_models_for_profile(self, profile_id: int):
        return self._models

    def get_model_for_profile(self, profile_id: int, model_name: str):
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

    monkeypatch.setattr(
        main, "DBManager", lambda: DummyDB(models=fake_models)
    )

    with patch("logos.auth.authenticate_with_profile") as mock_auth:
        from logos.auth import AuthContext
        mock_auth.return_value = AuthContext(
            logos_key="test-key", process_id=1, profile_id=10, profile_name="default"
        )

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

    with patch("logos.auth.authenticate_with_profile") as mock_auth:
        from logos.auth import AuthContext
        mock_auth.return_value = AuthContext(
            logos_key="test-key", process_id=1, profile_id=10, profile_name="default"
        )

        response = await main.list_models(_make_request())

    import json
    data = json.loads(response.body)
    assert data["object"] == "list"
    assert data["data"] == []


@pytest.mark.asyncio
async def test_list_models_auth_failure():
    """Missing/invalid key returns 401."""
    with patch("logos.auth.authenticate_with_profile") as mock_auth:
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

    with patch("logos.auth.authenticate_with_profile") as mock_auth:
        from logos.auth import AuthContext
        mock_auth.return_value = AuthContext(
            logos_key="test-key", process_id=1, profile_id=10, profile_name="default"
        )

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

    with patch("logos.auth.authenticate_with_profile") as mock_auth:
        from logos.auth import AuthContext
        mock_auth.return_value = AuthContext(
            logos_key="test-key", process_id=1, profile_id=10, profile_name="default"
        )

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

    with patch("logos.auth.authenticate_with_profile") as mock_auth:
        from logos.auth import AuthContext
        mock_auth.return_value = AuthContext(
            logos_key="test-key", process_id=1, profile_id=10, profile_name="default"
        )

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

    with patch("logos.auth.authenticate_with_profile") as mock_auth:
        from logos.auth import AuthContext
        mock_auth.return_value = AuthContext(
            logos_key="test-key", process_id=1, profile_id=10, profile_name="default"
        )

        response = await main.retrieve_model(slash_model, _make_request())

    import json
    data = json.loads(response.body)

    assert data["id"] == slash_model
    assert data["object"] == "model"
    assert isinstance(data["created"], int)
    assert data["created"] > 0
    assert data["owned_by"] == "logos"


@pytest.mark.asyncio
async def test_retrieve_model_auth_failure():
    """Missing/invalid key on retrieve returns 401."""
    with patch("logos.auth.authenticate_with_profile") as mock_auth:
        mock_auth.side_effect = HTTPException(status_code=401, detail="Invalid logos key")

        with pytest.raises(HTTPException) as exc:
            await main.retrieve_model("gpt-4o", _make_request(headers={}))

        assert exc.value.status_code == 401
