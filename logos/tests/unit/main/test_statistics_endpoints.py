import json
from unittest.mock import AsyncMock, MagicMock

import pytest

import logos.main as main


def _make_request(body: dict | None = None, headers: dict | None = None):
    request = MagicMock()
    request.headers = headers or {"authorization": "Bearer test-key"}
    request.json = AsyncMock(return_value=body or {})
    return request


class DummyInventoryDB:
    def __init__(self, inventory, status=200):
        self.inventory = inventory
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get_local_provider_inventory(self, logos_key):
        assert logos_key == "test-key"
        return self.inventory, self.status


class DummyRegistry:
    def __init__(self, snapshots):
        self.snapshots = snapshots

    def peek_runtime_snapshot(self, provider_id: int):
        return self.snapshots.get(provider_id)


@pytest.mark.asyncio
async def test_get_ollama_vram_stats_returns_live_worker_inventory(monkeypatch):
    monkeypatch.setattr(main, "authenticate_logos_key", lambda headers: ("test-key", None))
    monkeypatch.setattr(
        main,
        "DBManager",
        lambda: DummyInventoryDB(
            [
                {
                    "provider_id": 12,
                    "name": "local-node",
                    "provider_type": "logosnode",
                    "base_url": "",
                    "ollama_admin_url": "",
                    "total_vram_mb": None,
                    "parallel_capacity": 4,
                },
                {
                    "provider_id": 4,
                    "name": "offline-node",
                    "provider_type": "logosnode",
                    "base_url": "",
                    "ollama_admin_url": "",
                    "total_vram_mb": None,
                    "parallel_capacity": 8,
                },
            ]
        ),
    )
    monkeypatch.setattr(
        main,
        "_logosnode_registry",
        DummyRegistry(
            {
                12: {
                    "last_heartbeat": "2026-03-16T18:00:00Z",
                    "runtime": {
                        "timestamp": "2026-03-16T18:00:00Z",
                        "transport": {"connected": True},
                        "devices": {
                            "nvidia_smi_available": True,
                            "used_memory_mb": 6144,
                            "total_memory_mb": 16384,
                            "free_memory_mb": 10240,
                        },
                        "capacity": {
                            "total_effective_vram_mb": 6144,
                        },
                        "lanes": [
                            {
                                "model": "Qwen/Qwen3-8B",
                                "vllm": True,
                                "loaded_models": [
                                    {
                                        "name": "Qwen/Qwen3-8B",
                                        "size": 0,
                                        "size_vram": 6442450944,
                                    }
                                ],
                            }
                        ],
                    },
                }
            }
        ),
    )
    monkeypatch.setattr(
        main.datetime,
        "datetime",
        type(
            "FrozenDateTime",
            (main.datetime.datetime,),
            {
                "now": classmethod(
                    lambda cls, tz=None: main.datetime.datetime.fromisoformat(
                        "2026-03-16T18:00:05+00:00"
                    )
                )
            },
        ),
    )

    response = await main.get_ollama_vram_stats(_make_request(body={}))

    assert response.status_code == 200
    payload = json.loads(response.body)
    assert [provider["name"] for provider in payload["providers"]] == [
        "local-node",
        "offline-node",
    ]

    local_provider = payload["providers"][0]
    assert local_provider["connected"] is True
    assert local_provider["runtime_modes"] == ["vllm"]
    assert len(local_provider["data"]) == 1
    assert local_provider["data"][0]["remaining_vram_mb"] == 10240
    assert local_provider["data"][0]["models_loaded"] == 1

    offline_provider = payload["providers"][1]
    assert offline_provider["connected"] is False
    assert offline_provider["connection_state"] == "offline"
    assert offline_provider["data"] == []


@pytest.mark.asyncio
async def test_get_ollama_vram_stats_keeps_connected_provider_without_sample(monkeypatch):
    monkeypatch.setattr(main, "authenticate_logos_key", lambda headers: ("test-key", None))
    monkeypatch.setattr(
        main,
        "DBManager",
        lambda: DummyInventoryDB(
            [
                {
                    "provider_id": 12,
                    "name": "local-ollama",
                    "provider_type": "logosnode",
                    "base_url": "",
                    "ollama_admin_url": "",
                    "total_vram_mb": None,
                    "parallel_capacity": 4,
                }
            ]
        ),
    )
    monkeypatch.setattr(
        main,
        "_logosnode_registry",
        DummyRegistry(
            {
                12: {
                    "last_heartbeat": "2026-03-16T18:00:00Z",
                    "runtime": {
                        "timestamp": "2026-03-16T18:00:00Z",
                        "transport": {"connected": True},
                        "devices": {
                            "nvidia_smi_available": False,
                            "used_memory_mb": 0,
                            "total_memory_mb": 0,
                            "free_memory_mb": 0,
                        },
                        "capacity": {
                            "total_effective_vram_mb": 0,
                        },
                        "lanes": [
                            {
                                "model": "gemma2:2b",
                                "vllm": False,
                                "loaded_models": [],
                            }
                        ],
                    },
                }
            }
        ),
    )
    monkeypatch.setattr(
        main.datetime,
        "datetime",
        type(
            "FrozenDateTime",
            (main.datetime.datetime,),
            {
                "now": classmethod(
                    lambda cls, tz=None: main.datetime.datetime.fromisoformat(
                        "2026-03-16T18:00:05+00:00"
                    )
                )
            },
        ),
    )

    response = await main.get_ollama_vram_stats(_make_request(body={"day": "2026-03-16"}))

    assert response.status_code == 200
    payload = json.loads(response.body)
    assert payload["providers"] == [
        {
            "provider_id": 12,
            "name": "local-ollama",
            "data": [],
            "provider_type": "logosnode",
            "base_url": "",
            "parallel_capacity": 4,
            "connected": True,
            "connection_state": "online",
            "last_heartbeat": "2026-03-16T18:00:00Z",
            "runtime_modes": ["ollama"],
            "transport_connected": True,
        }
    ]
