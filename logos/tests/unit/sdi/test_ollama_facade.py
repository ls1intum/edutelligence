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
