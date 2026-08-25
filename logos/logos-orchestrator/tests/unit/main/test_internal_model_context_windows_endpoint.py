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

    # "windows" keeps its original shape for an older webservice.
    assert result["windows"] == {"qwen-14b": 40960, "mistral-7b": 32768}
    # With one worker, the smallest and the largest served window coincide, and
    # neither model's profile reports a context length, so there is no "native".
    assert result["stats"] == {
        "qwen-14b": {"current_min": 40960, "current_max": 40960},
        "mistral-7b": {"current_min": 32768, "current_max": 32768},
    }


@pytest.mark.asyncio
async def test_stats_separate_smallest_largest_and_native(monkeypatch):
    """Two workers serving the same model at different widths.

    ``current_min`` has to stay the narrow one (a request may land there),
    ``current_max`` the wide one, and ``overall`` the widest it is ever served
    with — known from the profile even on the worker whose lane runs narrow.
    """
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", "correct-secret")

    snapshots = {
        1: {
            "runtime": {
                "lanes": [
                    {
                        "model": "qwen-27b",
                        "vllm": True,
                        "backend_metrics": {"max_model_len": 262144},
                    }
                ],
                "model_profiles": {"qwen-27b": {"max_context_length": 262144}},
            }
        },
        2: {
            "runtime": {
                "lanes": [
                    {
                        "model": "qwen-27b",
                        "vllm": True,
                        "backend_metrics": {"max_model_len": 33000},
                    }
                ],
                "model_profiles": {
                    "qwen-27b": {
                        "kv_cache_to_max_model_len_pairs": [
                            {"kv_mb": 1024, "max_model_len": 33000},
                            {"kv_mb": 8192, "max_model_len": 262144},
                        ]
                    }
                },
            }
        },
    }
    registry = MagicMock()
    registry.active_provider_ids = lambda: [1, 2]
    registry.peek_runtime_snapshot = snapshots.get
    monkeypatch.setattr(main_mod, "_logosnode_registry", registry)

    result = await main_mod.internal_model_context_windows(_make_request("Bearer correct-secret"))

    assert result["windows"] == {"qwen-27b": 33000}
    assert result["stats"]["qwen-27b"] == {
        "current_min": 33000,
        "current_max": 262144,
        "overall": 262144,
    }


@pytest.mark.asyncio
async def test_native_is_known_without_a_live_lane(monkeypatch):
    """A model with a profile but no lane still reports its own limit.

    This is the case a config file has to be written from — OpenCode reads its
    context limit once at startup, so it needs a number even when nothing is
    loaded at that moment.
    """
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", "correct-secret")

    registry = MagicMock()
    registry.active_provider_ids = lambda: [1]
    registry.peek_runtime_snapshot = lambda pid: {
        "runtime": {
            "lanes": [],
            "model_profiles": {"cold-model": {"max_context_length": 131072}},
        }
    }
    monkeypatch.setattr(main_mod, "_logosnode_registry", registry)

    result = await main_mod.internal_model_context_windows(_make_request("Bearer correct-secret"))

    assert result["windows"] == {}
    assert result["stats"] == {"cold-model": {"overall": 131072}}
