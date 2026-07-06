from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

import logos as main_mod


def _make_request(authorization: str = "") -> MagicMock:
    request = MagicMock()
    request.headers.get = lambda key, default="": authorization if key == "authorization" else default
    return request


def _make_data(rebuild_classifier: bool = False) -> main_mod._RefreshPipelineRequest:
    return main_mod._RefreshPipelineRequest(rebuild_classifier=rebuild_classifier)


@pytest.fixture(autouse=True)
def reset_pipeline(monkeypatch):
    monkeypatch.setattr(main_mod, "_pipeline", MagicMock(), raising=False)
    monkeypatch.setattr(main_mod, "_logosnode_facade", MagicMock(), raising=False)
    monkeypatch.setattr(main_mod, "_azure_facade", MagicMock(), raising=False)


@pytest.mark.asyncio
async def test_returns_403_when_secret_not_configured(monkeypatch):
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", None)
    with pytest.raises(HTTPException) as exc_info:
        await main_mod.internal_refresh_pipeline(_make_data(), _make_request("Bearer secret"))
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_returns_401_when_secret_is_wrong(monkeypatch):
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", "correct-secret")
    with pytest.raises(HTTPException) as exc_info:
        await main_mod.internal_refresh_pipeline(_make_data(), _make_request("Bearer wrong-secret"))
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_returns_401_when_authorization_missing(monkeypatch):
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", "correct-secret")
    with pytest.raises(HTTPException) as exc_info:
        await main_mod.internal_refresh_pipeline(_make_data(), _make_request(""))
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_returns_503_when_pipeline_not_initialized(monkeypatch):
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", "correct-secret")
    monkeypatch.setattr(main_mod, "_pipeline", None)
    with pytest.raises(HTTPException) as exc_info:
        await main_mod.internal_refresh_pipeline(_make_data(), _make_request("Bearer correct-secret"))
    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_calls_refresh_with_rebuild_false_by_default(monkeypatch):
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", "correct-secret")
    refresh_calls = []

    async def _fake_refresh(*, rebuild_model_classifier: bool = False):
        refresh_calls.append(rebuild_model_classifier)

    monkeypatch.setattr(main_mod, "refresh_pipeline_runtime_state", _fake_refresh)

    result = await main_mod.internal_refresh_pipeline(_make_data(False), _make_request("Bearer correct-secret"))

    assert result == {"status": "ok"}
    assert refresh_calls == [False]


@pytest.mark.asyncio
async def test_calls_refresh_with_rebuild_true_when_requested(monkeypatch):
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", "correct-secret")
    refresh_calls = []

    async def _fake_refresh(*, rebuild_model_classifier: bool = False):
        refresh_calls.append(rebuild_model_classifier)

    monkeypatch.setattr(main_mod, "refresh_pipeline_runtime_state", _fake_refresh)

    result = await main_mod.internal_refresh_pipeline(_make_data(True), _make_request("Bearer correct-secret"))

    assert result == {"status": "ok"}
    assert refresh_calls == [True]
