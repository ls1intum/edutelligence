from logos.queue import PriorityQueueManager
from logos.queue.models import Priority
from logos.sdi.ollama_facade import OllamaSchedulingDataFacade

from tests.scheduling_data.sdi_test_utils import build_ollama_ps_payload


def test_ollama_facade_updates_status_from_ps(monkeypatch):
    queue_mgr = PriorityQueueManager()
    facade = OllamaSchedulingDataFacade(queue_mgr)
    facade.register_model(1, "ollama", "http://fake", "llama3.3:latest", 65536, provider_id=4)
    facade.register_model(14, "ollama", "http://fake", "deepseek-r1:70b", 65536, provider_id=4)

    payload = build_ollama_ps_payload({1: True, 14: False})

    def fake_fetch(self):
        return payload

    def fake_load_config(self):
        return {}

    monkeypatch.setattr("logos.sdi.providers.ollama_provider.OllamaDataProvider._fetch_ps_via_http", fake_fetch)
    monkeypatch.setattr("logos.sdi.providers.ollama_provider.OllamaDataProvider._load_provider_config", fake_load_config)

    facade._providers["ollama"].refresh_data()

    status_warm = facade.get_model_status(1)
    status_cold = facade.get_model_status(14)
    assert status_warm.is_loaded is True
    assert status_warm.vram_mb == 8192
    assert status_cold.is_loaded is False
    assert status_cold.vram_mb == 0

    cap = facade.get_capacity_info("ollama")
    assert cap.total_vram_mb == 65536
    assert cap.available_vram_mb == 65536 - 8192
    assert "llama3.3:latest" in cap.loaded_models


def test_queue_state_from_facade(monkeypatch):
    queue_mgr = PriorityQueueManager()
    facade = OllamaSchedulingDataFacade(queue_mgr)
    facade.register_model(1, "ollama", "http://fake", "llama3.3:latest", 65536, provider_id=4)

    payload = build_ollama_ps_payload({1: True})

    monkeypatch.setattr("logos.sdi.providers.ollama_provider.OllamaDataProvider._fetch_ps_via_http", lambda self: payload)
    monkeypatch.setattr("logos.sdi.providers.ollama_provider.OllamaDataProvider._load_provider_config", lambda self: {})

    facade._providers["ollama"].refresh_data()

    # Push some requests into queue_mgr to reflect queue_state
    for _ in range(2):
        facade.queue_manager.enqueue("task", model_id=1, priority=Priority.LOW)
    for _ in range(3):
        facade.queue_manager.enqueue("task", model_id=1, priority=Priority.NORMAL)
    for _ in range(1):
        facade.queue_manager.enqueue("task", model_id=1, priority=Priority.HIGH)

    status = facade.get_model_status(1)
    assert status.queue_state.low == 2
    assert status.queue_state.normal == 3
    assert status.queue_state.high == 1
