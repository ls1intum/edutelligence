from logos.queue import PriorityQueueManager
from logos.queue.models import Priority
from logos.sdi.logosnode_facade import LogosNodeSchedulingDataFacade

from tests.scheduling_data.sdi_test_utils import build_ollama_ps_payload


def test_logosnode_facade_updates_status_from_ps(monkeypatch):
    queue_mgr = PriorityQueueManager()
    facade = LogosNodeSchedulingDataFacade(queue_mgr)
    facade.register_model(1, "logosnode", "http://fake", "llama3.3:latest", 65536, provider_id=4)
    facade.register_model(14, "logosnode", "http://fake", "deepseek-r1:70b", 65536, provider_id=4)

    payload = build_ollama_ps_payload({1: True, 14: False})

    def fake_fetch(self):
        return payload

    def fake_load_config(self):
        return {}

    monkeypatch.setattr("logos.sdi.providers.logosnode_provider.LogosNodeDataProvider._fetch_ps_data", fake_fetch)
    monkeypatch.setattr("logos.sdi.providers.logosnode_provider.LogosNodeDataProvider._load_provider_config", fake_load_config)

    facade._providers[4].refresh_data()

    status_warm = facade.get_model_status(1, provider_id=4)
    status_cold = facade.get_model_status(14, provider_id=4)
    assert status_warm.is_loaded is True
    assert status_warm.vram_mb == 8192
    assert status_cold.is_loaded is False
    assert status_cold.vram_mb == 0

    cap = facade.get_capacity_info(4)
    assert cap.total_vram_mb == 65536
    assert cap.available_vram_mb == 65536 - 8192
    assert "llama3.3:latest" in cap.loaded_models


def test_queue_state_from_facade(monkeypatch):
    queue_mgr = PriorityQueueManager()
    facade = LogosNodeSchedulingDataFacade(queue_mgr)
    facade.register_model(1, "logosnode", "http://fake", "llama3.3:latest", 65536, provider_id=4)

    payload = build_ollama_ps_payload({1: True})

    monkeypatch.setattr("logos.sdi.providers.logosnode_provider.LogosNodeDataProvider._fetch_ps_data", lambda self: payload)
    monkeypatch.setattr("logos.sdi.providers.logosnode_provider.LogosNodeDataProvider._load_provider_config", lambda self: {})

    facade._providers[4].refresh_data()

    # Push some requests into queue_mgr to reflect queue_state
    for _ in range(2):
        facade.queue_manager.enqueue("task", model_id=1, provider_id=4, priority=Priority.LOW)
    for _ in range(3):
        facade.queue_manager.enqueue("task", model_id=1, provider_id=4, priority=Priority.NORMAL)
    for _ in range(1):
        facade.queue_manager.enqueue("task", model_id=1, provider_id=4, priority=Priority.HIGH)

    status = facade.get_model_status(1, provider_id=4)
    assert status.queue_state.low == 2
    assert status.queue_state.normal == 3
    assert status.queue_state.high == 1


def test_logosnode_runtime_parallel_capacity_overrides_static_config(monkeypatch):
    class _FakeRegistry:
        @staticmethod
        def peek_runtime_snapshot(provider_id: int):  # noqa: ARG004
            return {
                "runtime": {
                    "lanes": [
                        {
                            "lane_id": "lane-1",
                            "model": "llama3.1:latest",
                            "runtime_state": "loaded",
                            "vllm": False,
                            "num_parallel": 4,
                        }
                    ]
                }
            }

    queue_mgr = PriorityQueueManager()
    facade = LogosNodeSchedulingDataFacade(queue_mgr, runtime_registry=_FakeRegistry())

    monkeypatch.setattr(
        "logos.sdi.providers.logosnode_provider.LogosNodeDataProvider._load_provider_config",
        lambda self: {"parallel_capacity": 1},
    )
    monkeypatch.setattr(
        "logos.sdi.providers.logosnode_provider.LogosNodeDataProvider._fetch_ps_data",
        lambda self: {"models": []},
    )

    facade.register_model(101, "logosnode", "http://fake", "llama3.1:latest", 65536, provider_id=12)
    provider = facade._providers[12]

    debug_state = provider.get_debug_state()
    assert debug_state[101]["max_capacity"] == 4
    assert debug_state[101]["capacity_source"] == "runtime"

    assert provider.try_reserve_capacity(101, "req-1") is True
    assert provider.try_reserve_capacity(101, "req-2") is True
    assert provider.try_reserve_capacity(101, "req-3") is True
    assert provider.try_reserve_capacity(101, "req-4") is True
    assert provider.try_reserve_capacity(101, "req-5") is False


def test_logosnode_try_reserve_allows_unregistered_model_for_cold_start(monkeypatch):
    queue_mgr = PriorityQueueManager()
    facade = LogosNodeSchedulingDataFacade(queue_mgr)

    monkeypatch.setattr(
        "logos.sdi.providers.logosnode_provider.LogosNodeDataProvider._load_provider_config",
        lambda self: {},
    )
    monkeypatch.setattr(
        "logos.sdi.providers.logosnode_provider.LogosNodeDataProvider._fetch_ps_data",
        lambda self: {"models": []},
    )

    facade.register_model(101, "logosnode", "http://fake", "llama3.1:latest", 65536, provider_id=12)
    provider = facade._providers[12]

    assert provider.try_reserve_capacity(999, "req-unknown") is True


def test_logosnode_capacity_uses_runtime_free_memory_when_nvidia_metrics_present(monkeypatch):
    class _FakeRegistry:
        @staticmethod
        def peek_runtime_snapshot(provider_id: int):  # noqa: ARG004
            return {
                "runtime": {
                    "devices": {
                        "nvidia_smi_available": True,
                        "total_memory_mb": 32768,
                        "free_memory_mb": 24576,
                    },
                    "lanes": [],
                }
            }

    queue_mgr = PriorityQueueManager()
    facade = LogosNodeSchedulingDataFacade(queue_mgr, runtime_registry=_FakeRegistry())

    monkeypatch.setattr(
        "logos.sdi.providers.logosnode_provider.LogosNodeDataProvider._load_provider_config",
        lambda self: {},
    )
    monkeypatch.setattr(
        "logos.sdi.providers.logosnode_provider.LogosNodeDataProvider._fetch_ps_data",
        lambda self: {"models": []},
    )

    facade.register_model(101, "logosnode", "http://fake", "llama3.1:latest", 65536, provider_id=12)
    cap = facade.get_capacity_info(12)
    assert cap.total_vram_mb == 32768
    assert cap.available_vram_mb == 24576


def test_logosnode_capacity_falls_back_to_static_total_when_runtime_is_derived(monkeypatch):
    class _FakeRegistry:
        @staticmethod
        def peek_runtime_snapshot(provider_id: int):  # noqa: ARG004
            return {
                "runtime": {
                    "devices": {
                        "mode": "derived",
                        "nvidia_smi_available": False,
                        "free_memory_mb": 0,
                    },
                    "lanes": [
                        {
                            "lane_id": "lane-1",
                            "model": "llama3.1:latest",
                            "runtime_state": "loaded",
                            "vllm": False,
                            "num_parallel": 4,
                            "effective_vram_mb": 8192,
                            "loaded_models": [{"name": "llama3.1:latest"}],
                        }
                    ],
                }
            }

    queue_mgr = PriorityQueueManager()
    facade = LogosNodeSchedulingDataFacade(queue_mgr, runtime_registry=_FakeRegistry())

    monkeypatch.setattr(
        "logos.sdi.providers.logosnode_provider.LogosNodeDataProvider._load_provider_config",
        lambda self: {},
    )

    facade.register_model(101, "logosnode", "http://fake", "llama3.1:latest", 65536, provider_id=12)
    cap = facade.get_capacity_info(12)
    assert cap.available_vram_mb == 65536 - 8192
    assert cap.loaded_models == ["llama3.1:latest"]


def test_logosnode_runtime_vllm_lane_uses_lane_config_capacity_hint(monkeypatch):
    class _FakeRegistry:
        @staticmethod
        def peek_runtime_snapshot(provider_id: int):  # noqa: ARG004
            return {
                "runtime": {
                    "lanes": [
                        {
                            "lane_id": "lane-1",
                            "model": "Qwen/Qwen3-8B",
                            "runtime_state": "loaded",
                            "vllm": True,
                            "num_parallel": 0,
                            "lane_config": {"num_parallel": 6},
                            "effective_vram_mb": 12288,
                            "loaded_models": [{"name": "Qwen/Qwen3-8B"}],
                        }
                    ]
                }
            }

    queue_mgr = PriorityQueueManager()
    facade = LogosNodeSchedulingDataFacade(queue_mgr, runtime_registry=_FakeRegistry())

    monkeypatch.setattr(
        "logos.sdi.providers.logosnode_provider.LogosNodeDataProvider._load_provider_config",
        lambda self: {"parallel_capacity": 1},
    )
    monkeypatch.setattr(
        "logos.sdi.providers.logosnode_provider.LogosNodeDataProvider._fetch_ps_data",
        lambda self: {"models": []},
    )

    facade.register_model(202, "logosnode", "http://fake", "Qwen/Qwen3-8B", 65536, provider_id=12)
    provider = facade._providers[12]

    status = provider.get_model_status(202)
    debug_state = provider.get_debug_state()

    assert status.is_loaded is True
    assert status.vram_mb == 12288
    assert debug_state[202]["max_capacity"] == 6
    assert debug_state[202]["capacity_source"] == "runtime"


def test_logosnode_provider_config_parallel_capacity_overrides_runtime_hint(monkeypatch):
    class _FakeRegistry:
        @staticmethod
        def peek_runtime_snapshot(provider_id: int):  # noqa: ARG004
            return {
                "runtime": {
                    "lanes": [
                        {
                            "lane_id": "lane-1",
                            "model": "Qwen/Qwen2.5-Coder-7B-Instruct",
                            "runtime_state": "loaded",
                            "vllm": True,
                            "num_parallel": 0,
                            "lane_config": {"num_parallel": 1},
                        }
                    ]
                }
            }

    queue_mgr = PriorityQueueManager()
    facade = LogosNodeSchedulingDataFacade(queue_mgr, runtime_registry=_FakeRegistry())

    monkeypatch.setattr(
        "logos.sdi.providers.logosnode_provider.LogosNodeDataProvider._load_provider_config",
        lambda self: {"parallel_capacity": 16},
    )
    monkeypatch.setattr(
        "logos.sdi.providers.logosnode_provider.LogosNodeDataProvider._fetch_ps_data",
        lambda self: {"models": []},
    )

    facade.register_model(303, "logosnode", "http://fake", "Qwen/Qwen2.5-Coder-7B-Instruct", 65536, provider_id=13)
    provider = facade._providers[13]

    debug_state = provider.get_debug_state()
    assert debug_state[303]["max_capacity"] == 16
    assert debug_state[303]["capacity_source"] == "config"


def test_logosnode_debug_state_includes_recent_scheduler_signals(monkeypatch):
    class _FakeRegistry:
        @staticmethod
        def peek_runtime_snapshot(provider_id: int):  # noqa: ARG004
            return {
                "last_heartbeat": "2026-03-17T10:00:10Z",
                "capabilities_models": ["Qwen/Qwen2.5-Coder-7B-Instruct"],
                "runtime": {
                    "lanes": [
                        {
                            "lane_id": "lane-1",
                            "model": "Qwen/Qwen2.5-Coder-7B-Instruct",
                            "runtime_state": "running",
                            "vllm": True,
                            "num_parallel": 0,
                            "lane_config": {"num_parallel": 8},
                        }
                    ]
                },
            }

        @staticmethod
        def peek_recent_samples(provider_id: int, *, after_snapshot_id: int = 0):  # noqa: ARG004
            return [
                {
                    "snapshot_id": 1,
                    "timestamp": "2026-03-17T10:00:00Z",
                    "scheduler_signals": {
                        "provider": {"active_requests": 2},
                        "models": {
                            "Qwen/Qwen2.5-Coder-7B-Instruct": {
                                "active_requests": 2,
                                "queue_waiting_current": 3,
                                "requests_running_current": 2,
                                "prompt_tokens_total": 1200,
                                "generation_tokens_total": 2400,
                                "ttft_p95_seconds": 0.8,
                            }
                        },
                    },
                },
                {
                    "snapshot_id": 2,
                    "timestamp": "2026-03-17T10:00:10Z",
                    "scheduler_signals": {
                        "provider": {"active_requests": 1},
                        "models": {
                            "Qwen/Qwen2.5-Coder-7B-Instruct": {
                                "active_requests": 1,
                                "queue_waiting_current": 1,
                                "requests_running_current": 1,
                                "prompt_tokens_total": 1800,
                                "generation_tokens_total": 3600,
                                "ttft_p95_seconds": 0.4,
                            }
                        },
                    },
                },
            ]

    queue_mgr = PriorityQueueManager()
    facade = LogosNodeSchedulingDataFacade(queue_mgr, runtime_registry=_FakeRegistry())

    monkeypatch.setattr(
        "logos.sdi.providers.logosnode_provider.LogosNodeDataProvider._load_provider_config",
        lambda self: {},
    )
    monkeypatch.setattr(
        "logos.sdi.providers.logosnode_provider.LogosNodeDataProvider._fetch_ps_data",
        lambda self: {"models": []},
    )

    facade.register_model(404, "logosnode", "http://fake", "Qwen/Qwen2.5-Coder-7B-Instruct", 65536, provider_id=13)
    debug_state = facade.debug_state()

    provider_debug = debug_state["providers"]["13"]
    model_debug = provider_debug["models"][404]

    assert provider_debug["runtime"]["recent_sample_count"] == 2
    assert provider_debug["runtime"]["provider_signals"]["active_requests"] == 1
    assert model_debug["scheduler_signals"]["sample_count"] == 2
    assert model_debug["scheduler_signals"]["queue_waiting_peak"] == 3.0
    assert model_debug["scheduler_signals"]["requests_running_peak"] == 2.0
    assert model_debug["scheduler_signals"]["prompt_tokens_per_second"] == 60.0
    assert model_debug["scheduler_signals"]["generation_tokens_per_second"] == 120.0
