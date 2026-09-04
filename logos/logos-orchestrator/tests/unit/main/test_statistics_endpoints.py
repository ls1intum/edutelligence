import json
from unittest.mock import AsyncMock, MagicMock

import pytest

import logos as main
from logos.logosnode_snapshot import _build_logosnode_scheduler_signals
from logos.routers import admin as admin_mod


def _make_request(body: dict | None = None, headers: dict | None = None):
    request = MagicMock()
    request.headers = headers or {"authorization": "Bearer test-key"}
    request.json = AsyncMock(return_value=body or {})
    return request


class DummyInventoryDB:
    def __init__(
        self,
        inventory,
        status=200,
        stats_payload=None,
        stats_status=200,
        delta_payload=None,
        delta_status=200,
    ):
        self.inventory = inventory
        self.status = status
        self.stats_payload = stats_payload if stats_payload is not None else {"providers": []}
        self.stats_status = stats_status
        self.delta_payload = delta_payload if delta_payload is not None else {"providers": [], "last_snapshot_id": 0}
        self.delta_status = delta_status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get_local_provider_inventory(self, logos_key):
        assert logos_key == "test-key"
        return self.inventory, self.status

    def get_ollama_vram_stats(self, logos_key, day, bucket_seconds=5):  # noqa: ARG002
        assert logos_key == "test-key"
        return self.stats_payload, self.stats_status

    def get_ollama_vram_deltas(self, logos_key, day, after_snapshot_id=0):  # noqa: ARG002
        assert logos_key == "test-key"
        return self.delta_payload, self.delta_status


class DummyRegistry:
    def __init__(self, snapshots, recent_samples=None):
        self.snapshots = snapshots
        self.recent_samples = recent_samples or {}

    def peek_runtime_snapshot(self, provider_id: int):
        return self.snapshots.get(provider_id)

    def peek_recent_samples(self, provider_id: int, *, after_snapshot_id: int = 0):
        samples = self.recent_samples.get(provider_id, [])
        return [sample for sample in samples if int(sample.get("snapshot_id") or 0) > int(after_snapshot_id or 0)]


@pytest.fixture(autouse=True)
def mock_auth(monkeypatch):
    mock_auth_ctx = MagicMock()
    mock_auth_ctx.key_value = "test-key"
    mock_auth_ctx.api_key_id = 1
    mock_auth_ctx.team_id = 1

    def fake_authenticate(headers):
        return mock_auth_ctx

    monkeypatch.setattr(admin_mod, "authenticate_api_key", fake_authenticate)


@pytest.mark.asyncio
async def test_get_ollama_vram_stats_returns_live_worker_inventory(monkeypatch):
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
            ],
            stats_payload={"providers": [], "last_snapshot_id": 0},
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
                                "lane_id": "qwen-a",
                                "model": "Qwen/Qwen3-8B",
                                "vllm": True,
                                "runtime_state": "running",
                                "active_requests": 2,
                                "effective_vram_mb": 6144,
                                "backend_metrics": {
                                    "engine": "vllm",
                                    "queue_waiting": 3,
                                    "requests_running": 2,
                                    "gpu_cache_usage_percent": 66.0,
                                    "prefix_cache_hit_rate": 0.42,
                                    "mtp_acceptance_rate": 0.61,
                                    "mtp_draft_tokens_total": 1000,
                                    "mtp_accepted_tokens_total": 610,
                                    "prompt_tokens_total": 1200,
                                    "generation_tokens_total": 3400,
                                    "ttft_histogram": {"0.5": 8, "1.0": 10},
                                },
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
                    lambda cls, tz=None: main.datetime.datetime.fromisoformat("2026-03-16T18:00:05+00:00")
                )
            },
        ),
    )

    response = await admin_mod.get_ollama_vram_stats(_make_request(body={}))

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
    scheduler_signals = local_provider["data"][0]["scheduler_signals"]
    assert scheduler_signals["provider"]["nvidia_smi_available"] is True
    assert scheduler_signals["models"]["Qwen/Qwen3-8B"]["queue_waiting_current"] == 3.0
    assert scheduler_signals["models"]["Qwen/Qwen3-8B"]["requests_running_current"] == 2.0
    assert scheduler_signals["models"]["Qwen/Qwen3-8B"]["ttft_p95_seconds"] == pytest.approx(0.875)
    assert scheduler_signals["models"]["Qwen/Qwen3-8B"]["prefix_cache_hit_rate_avg"] == pytest.approx(0.42)
    assert scheduler_signals["models"]["Qwen/Qwen3-8B"]["mtp_acceptance_rate_avg"] == pytest.approx(0.61)
    assert scheduler_signals["lanes"]["qwen-a"]["gpu_cache_usage_percent"] == 66.0
    assert scheduler_signals["lanes"]["qwen-a"]["prefix_cache_hit_rate"] == 0.42
    assert scheduler_signals["lanes"]["qwen-a"]["mtp_acceptance_rate"] == 0.61

    offline_provider = payload["providers"][1]
    assert offline_provider["connected"] is False
    assert offline_provider["connection_state"] == "offline"
    assert offline_provider["data"] == []


@pytest.mark.asyncio
async def test_get_ollama_vram_stats_keeps_connected_provider_without_sample(
    monkeypatch,
):
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
            ],
            stats_payload={"providers": [], "last_snapshot_id": 0},
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
                    lambda cls, tz=None: main.datetime.datetime.fromisoformat("2026-03-16T18:00:05+00:00")
                )
            },
        ),
    )

    response = await admin_mod.get_ollama_vram_stats(_make_request(body={"day": "2026-03-16"}))

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


@pytest.mark.asyncio
async def test_get_ollama_vram_stats_uses_runtime_memory_for_connected_ollama(
    monkeypatch,
):
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
            ],
            stats_payload={"providers": [], "last_snapshot_id": 0},
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
                            "used_memory_mb": 3072,
                            "total_memory_mb": 8192,
                            "free_memory_mb": 5120,
                        },
                        "capacity": {
                            "total_effective_vram_mb": 0,
                        },
                        "lanes": [
                            {
                                "model": "gemma2:2b",
                                "vllm": False,
                                "loaded_models": [
                                    {
                                        "name": "gemma2:2b",
                                        "size": 3368293376,
                                        "size_vram": 0,
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
                    lambda cls, tz=None: main.datetime.datetime.fromisoformat("2026-03-16T18:00:05+00:00")
                )
            },
        ),
    )

    response = await admin_mod.get_ollama_vram_stats(_make_request(body={"day": "2026-03-16"}))

    assert response.status_code == 200
    payload = json.loads(response.body)
    sample = payload["providers"][0]["data"][0]
    assert sample["connection_state"] == "online"
    assert sample["runtime_modes"] == ["ollama"]
    assert sample["used_vram_mb"] == 3072.0
    assert sample["remaining_vram_mb"] == 5120.0
    assert sample["total_vram_mb"] == 8192.0
    assert sample["models_loaded"] == 1


@pytest.mark.asyncio
async def test_get_ollama_vram_stats_merges_persisted_rows_and_recent_buffer(
    monkeypatch,
):
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
                }
            ],
            stats_payload={
                "providers": [
                    {
                        "provider_id": 12,
                        "name": "local-node",
                        "data": [
                            {
                                "snapshot_id": 101,
                                "timestamp": "2026-03-16T17:59:55Z",
                                "used_vram_mb": 2048,
                                "remaining_vram_mb": 6144,
                                "total_vram_mb": 8192,
                                "models_loaded": 1,
                                "loaded_models": [{"name": "gemma2:2b", "size_vram": 2147483648}],
                            }
                        ],
                    }
                ],
                "last_snapshot_id": 101,
            },
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
                            "used_memory_mb": 3072,
                            "total_memory_mb": 8192,
                            "free_memory_mb": 5120,
                        },
                        "capacity": {"total_effective_vram_mb": 0},
                        "lanes": [],
                    },
                }
            },
            recent_samples={
                12: [
                    {
                        "snapshot_id": 102,
                        "timestamp": "2026-03-16T18:00:00Z",
                        "used_vram_mb": 3072,
                        "remaining_vram_mb": 5120,
                        "total_vram_mb": 8192,
                        "models_loaded": 1,
                        "loaded_models": [{"name": "gemma2:2b", "size_vram": 2147483648}],
                    }
                ]
            },
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
                    lambda cls, tz=None: main.datetime.datetime.fromisoformat("2026-03-16T18:00:05+00:00")
                )
            },
        ),
    )

    response = await admin_mod.get_ollama_vram_stats(_make_request(body={"day": "2026-03-16"}))

    assert response.status_code == 200
    payload = json.loads(response.body)
    provider = payload["providers"][0]
    assert [sample["snapshot_id"] for sample in provider["data"]] == [101, 102]
    assert payload["last_snapshot_id"] == 102


def test_scheduler_signals_mtp_acceptance_is_token_weighted_across_lanes() -> None:
    """Per-model MTP rate sums the draft/accepted counters, it is NOT the
    unweighted mean of per-lane rates (regression for the CodeRabbit review)."""

    def _lane(lane_id: str, draft: float, accepted: float) -> dict:
        return {
            "lane_id": lane_id,
            "model": "mtp-model",
            "vllm": True,
            "runtime_state": "running",
            "active_requests": 0,
            "effective_vram_mb": 8000.0,
            "backend_metrics": {
                "engine": "vllm",
                "mtp_acceptance_rate": (accepted / draft) if draft > 0 else None,
                "mtp_draft_tokens_total": draft,
                "mtp_accepted_tokens_total": accepted,
            },
        }

    # Lane A: perfect acceptance but a single draft token.
    # Lane B: zero acceptance over 10,000 draft tokens.
    runtime = {
        "timestamp": "2026-03-16T18:00:00Z",
        "transport": {"connected": True},
        "devices": {},
        "capacity": {},
        "lanes": [
            _lane("lane-a", draft=1, accepted=1),
            _lane("lane-b", draft=10_000, accepted=0),
        ],
    }

    signals = _build_logosnode_scheduler_signals(runtime)
    model = signals["models"]["mtp-model"]

    # Token-weighted: 1 accepted / 10,001 draft. The unweighted lane-rate
    # mean would be 0.5 — exactly the misstatement this regression guards.
    assert model["mtp_acceptance_rate_avg"] == pytest.approx(1 / 10_001)

    # The per-lane signal still carries each lane's own rate.
    assert signals["lanes"]["lane-a"]["mtp_acceptance_rate"] == pytest.approx(1.0)
    assert signals["lanes"]["lane-b"]["mtp_acceptance_rate"] == pytest.approx(0.0)


def test_scheduler_signals_mtp_acceptance_none_without_spec_decode() -> None:
    """Lanes without speculative decoding leave the per-model rate unset."""
    runtime = {
        "timestamp": "2026-03-16T18:00:00Z",
        "transport": {"connected": True},
        "devices": {},
        "capacity": {},
        "lanes": [
            {
                "lane_id": "lane-a",
                "model": "plain-model",
                "vllm": True,
                "runtime_state": "loaded",
                "active_requests": 0,
                "effective_vram_mb": 8000.0,
                "backend_metrics": {"engine": "vllm", "prefix_cache_hit_rate": 0.3},
            }
        ],
    }

    signals = _build_logosnode_scheduler_signals(runtime)
    assert signals["models"]["plain-model"]["mtp_acceptance_rate_avg"] is None
    assert signals["models"]["plain-model"]["prefix_cache_hit_rate_avg"] == pytest.approx(0.3)


# ── Per-lane context window ──────────────────────────────────────────────────
# The statistics page shows the window each lane is serving at. It has to travel
# on the lane, not the model: the planner sizes every lane against the KV cache
# it could get, so two lanes of one model routinely differ.


def _ctx_runtime(lane: dict, profiles: dict | None = None) -> dict:
    return {
        "timestamp": "2026-03-16T18:00:00Z",
        "transport": {"connected": True},
        "devices": {},
        "capacity": {},
        "lanes": [lane],
        "model_profiles": profiles or {},
    }


def test_lane_signal_reports_the_window_vllm_is_running_at() -> None:
    signals = _build_logosnode_scheduler_signals(
        _ctx_runtime(
            {
                "lane_id": "lane-a",
                "model": "big-model",
                "vllm": True,
                "runtime_state": "running",
                "active_requests": 0,
                "effective_vram_mb": 90000.0,
                "backend_metrics": {"engine": "vllm", "max_model_len": 111200},
            }
        )
    )
    assert signals["lanes"]["lane-a"]["max_model_len"] == 111200


def test_two_lanes_of_one_model_report_their_own_windows() -> None:
    """The whole reason this is per lane and not per model."""
    runtime = _ctx_runtime({}, {})
    runtime["lanes"] = [
        {
            "lane_id": "roomy",
            "model": "same-model",
            "vllm": True,
            "runtime_state": "running",
            "active_requests": 0,
            "effective_vram_mb": 90000.0,
            "backend_metrics": {"engine": "vllm", "max_model_len": 262144},
        },
        {
            "lane_id": "cramped",
            "model": "same-model",
            "vllm": True,
            "runtime_state": "running",
            "active_requests": 0,
            "effective_vram_mb": 20000.0,
            "backend_metrics": {"engine": "vllm", "max_model_len": 32768},
        },
    ]

    signals = _build_logosnode_scheduler_signals(runtime)

    assert signals["lanes"]["roomy"]["max_model_len"] == 262144
    assert signals["lanes"]["cramped"]["max_model_len"] == 32768


def test_lane_signal_falls_back_to_the_calibrated_profile() -> None:
    """A vLLM lane started without --max-model-len takes the calibrated value,
    so the number is not on the lane itself."""
    signals = _build_logosnode_scheduler_signals(
        _ctx_runtime(
            {
                "lane_id": "lane-a",
                "model": "calibrated-model",
                "vllm": True,
                "runtime_state": "loaded",
                "active_requests": 0,
                "effective_vram_mb": 8000.0,
                "backend_metrics": {"engine": "vllm"},
            },
            {"calibrated-model": {"calibration_max_model_len": 40960}},
        )
    )
    assert signals["lanes"]["lane-a"]["max_model_len"] == 40960


def test_lane_signal_reports_an_ollama_lanes_configured_window() -> None:
    signals = _build_logosnode_scheduler_signals(
        _ctx_runtime(
            {
                "lane_id": "lane-a",
                "model": "ollama-model",
                "vllm": False,
                "runtime_state": "loaded",
                "active_requests": 0,
                "effective_vram_mb": 4000.0,
                "context_length": 8192,
            }
        )
    )
    assert signals["lanes"]["lane-a"]["max_model_len"] == 8192


def test_lane_signal_omits_a_window_it_cannot_derive() -> None:
    """None rather than 0: the row leaves the badge off instead of claiming a
    size vLLM picked for itself and never reported."""
    signals = _build_logosnode_scheduler_signals(
        _ctx_runtime(
            {
                "lane_id": "lane-a",
                "model": "unknown-model",
                "vllm": True,
                "runtime_state": "loaded",
                "active_requests": 0,
                "effective_vram_mb": 8000.0,
                "backend_metrics": {"engine": "vllm"},
            }
        )
    )
    assert signals["lanes"]["lane-a"]["max_model_len"] is None
