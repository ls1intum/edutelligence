from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

import logos as main_mod


def _make_request(authorization: str = "") -> MagicMock:
    request = MagicMock()
    request.headers.get = lambda key, default="": authorization if key == "authorization" else default
    return request


@pytest.mark.asyncio
async def test_returns_403_when_secret_not_configured(monkeypatch):
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", None)
    with pytest.raises(HTTPException) as exc_info:
        await main_mod.internal_model_context_windows(_make_request("Bearer secret"))
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_returns_401_when_secret_is_wrong(monkeypatch):
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", "correct-secret")
    with pytest.raises(HTTPException) as exc_info:
        await main_mod.internal_model_context_windows(_make_request("Bearer wrong-secret"))
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_returns_served_windows_per_model(monkeypatch):
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", "correct-secret")

    registry = MagicMock()
    registry.active_provider_ids = lambda: [7]
    registry.peek_runtime_snapshot = lambda pid: {
        "runtime": {
            "lanes": [
                {
                    "model": "qwen-14b",
                    "vllm": True,
                    "context_length": 4096,
                    "backend_metrics": {"max_model_len": 40960},
                },
                {"model": "mistral-7b", "vllm": False, "context_length": 32768, "backend_metrics": {}},
            ],
            "model_profiles": {},
        }
    }
    monkeypatch.setattr(main_mod, "_logosnode_registry", registry)

    result = await main_mod.internal_model_context_windows(_make_request("Bearer correct-secret"))

    assert result == {"windows": {"qwen-14b": 40960, "mistral-7b": 32768}}
