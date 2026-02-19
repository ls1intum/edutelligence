"""Tests for TempProviderRegistry — CRUD, thread safety, auth tokens."""

import threading
import time

import pytest

from logos.temp_providers.discovery import DiscoveredModel
from logos.temp_providers.registry import TempProviderRegistry


@pytest.fixture(autouse=True)
def _reset_registry():
    """Ensure each test starts with a clean singleton."""
    TempProviderRegistry.reset_singleton()
    yield
    TempProviderRegistry.reset_singleton()


def _sample_models():
    return [DiscoveredModel(id="llama3", owned_by="ollama")]


# ------------------------------------------------------------------
# Registration
# ------------------------------------------------------------------


class TestRegister:
    def test_register_returns_provider_with_auth_token(self):
        reg = TempProviderRegistry()
        prov = reg.register(
            url="http://localhost:1234",
            name="my-mac",
            owner_process_id=1,
            models=_sample_models(),
        )
        assert prov.id.startswith("tmp-")
        assert prov.auth_token.startswith("tpk-")
        assert prov.is_healthy is True
        assert len(prov.models) == 1
        assert prov.name == "my-mac"

    def test_register_strips_trailing_slash(self):
        reg = TempProviderRegistry()
        prov = reg.register(
            url="http://localhost:1234/",
            name="test",
            owner_process_id=1,
            models=[],
        )
        assert prov.url == "http://localhost:1234"

    def test_list_all(self):
        reg = TempProviderRegistry()
        reg.register(url="http://a", name="a", owner_process_id=1, models=[])
        reg.register(url="http://b", name="b", owner_process_id=2, models=[])
        assert len(reg.list_all()) == 2

    def test_list_for_process(self):
        reg = TempProviderRegistry()
        reg.register(url="http://a", name="a", owner_process_id=1, models=[])
        reg.register(url="http://b", name="b", owner_process_id=2, models=[])
        assert len(reg.list_for_process(1)) == 1
        assert reg.list_for_process(1)[0].name == "a"

    def test_get_existing(self):
        reg = TempProviderRegistry()
        prov = reg.register(url="http://x", name="x", owner_process_id=1, models=[])
        assert reg.get(prov.id) is prov

    def test_get_nonexistent(self):
        reg = TempProviderRegistry()
        assert reg.get("does-not-exist") is None


# ------------------------------------------------------------------
# Unregistration
# ------------------------------------------------------------------


class TestUnregister:
    def test_unregister_existing(self):
        reg = TempProviderRegistry()
        prov = reg.register(url="http://x", name="x", owner_process_id=1, models=[])
        assert reg.unregister(prov.id) is True
        assert reg.get(prov.id) is None

    def test_unregister_nonexistent(self):
        reg = TempProviderRegistry()
        assert reg.unregister("nope") is False


# ------------------------------------------------------------------
# Model updates
# ------------------------------------------------------------------


class TestUpdateModels:
    def test_update_existing(self):
        reg = TempProviderRegistry()
        prov = reg.register(url="http://x", name="x", owner_process_id=1, models=[])
        new_models = [DiscoveredModel(id="gpt-4o")]
        assert reg.update_models(prov.id, new_models) is True
        assert reg.get(prov.id).models == new_models

    def test_update_nonexistent(self):
        reg = TempProviderRegistry()
        assert reg.update_models("nope", []) is False


# ------------------------------------------------------------------
# Health state
# ------------------------------------------------------------------


class TestHealthState:
    def test_mark_unhealthy_then_healthy(self):
        reg = TempProviderRegistry()
        prov = reg.register(url="http://x", name="x", owner_process_id=1, models=[])
        reg.mark_unhealthy(prov.id)
        assert reg.get(prov.id).is_healthy is False
        assert reg.get(prov.id).unhealthy_since is not None

        reg.mark_healthy(prov.id)
        assert reg.get(prov.id).is_healthy is True
        assert reg.get(prov.id).unhealthy_since is None

    def test_list_healthy_excludes_unhealthy(self):
        reg = TempProviderRegistry()
        p1 = reg.register(url="http://a", name="a", owner_process_id=1, models=[])
        p2 = reg.register(url="http://b", name="b", owner_process_id=1, models=[])
        reg.mark_unhealthy(p1.id)
        healthy = reg.list_healthy()
        assert len(healthy) == 1
        assert healthy[0].id == p2.id


# ------------------------------------------------------------------
# Stale removal
# ------------------------------------------------------------------


class TestStaleRemoval:
    def test_remove_stale(self):
        reg = TempProviderRegistry()
        prov = reg.register(url="http://x", name="x", owner_process_id=1, models=[])
        reg.mark_unhealthy(prov.id)
        # Simulate being unhealthy for a long time
        reg.get(prov.id).unhealthy_since = time.time() - 600
        removed = reg.remove_stale(max_unhealthy_seconds=300)
        assert prov.id in removed
        assert reg.get(prov.id) is None

    def test_recently_unhealthy_not_removed(self):
        reg = TempProviderRegistry()
        prov = reg.register(url="http://x", name="x", owner_process_id=1, models=[])
        reg.mark_unhealthy(prov.id)
        removed = reg.remove_stale(max_unhealthy_seconds=300)
        assert removed == []
        assert reg.get(prov.id) is not None


# ------------------------------------------------------------------
# find_provider_for_model
# ------------------------------------------------------------------


class TestFindProviderForModel:
    def test_finds_healthy_provider(self):
        reg = TempProviderRegistry()
        models = [DiscoveredModel(id="llama3")]
        prov = reg.register(url="http://x", name="x", owner_process_id=1, models=models)
        found = reg.find_provider_for_model("llama3")
        assert found is not None
        assert found.id == prov.id

    def test_skips_unhealthy(self):
        reg = TempProviderRegistry()
        prov = reg.register(
            url="http://x", name="x", owner_process_id=1,
            models=[DiscoveredModel(id="llama3")],
        )
        reg.mark_unhealthy(prov.id)
        assert reg.find_provider_for_model("llama3") is None

    def test_auth_token_filter(self):
        reg = TempProviderRegistry()
        prov = reg.register(
            url="http://x", name="x", owner_process_id=1,
            models=[DiscoveredModel(id="llama3")],
        )
        # Correct token → found
        assert reg.find_provider_for_model("llama3", auth_token=prov.auth_token) is prov
        # Wrong token → not found
        assert reg.find_provider_for_model("llama3", auth_token="wrong") is None

    def test_model_not_served(self):
        reg = TempProviderRegistry()
        reg.register(
            url="http://x", name="x", owner_process_id=1,
            models=[DiscoveredModel(id="llama3")],
        )
        assert reg.find_provider_for_model("gpt-4o") is None


# ------------------------------------------------------------------
# Singleton + clear
# ------------------------------------------------------------------


class TestSingleton:
    def test_singleton_identity(self):
        a = TempProviderRegistry()
        b = TempProviderRegistry()
        assert a is b

    def test_clear(self):
        reg = TempProviderRegistry()
        reg.register(url="http://x", name="x", owner_process_id=1, models=[])
        reg.clear()
        assert reg.list_all() == []


# ------------------------------------------------------------------
# Thread safety (basic smoke test)
# ------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_register_unregister(self):
        reg = TempProviderRegistry()
        errors = []

        def worker(i):
            try:
                prov = reg.register(url=f"http://{i}", name=f"p{i}", owner_process_id=i, models=[])
                reg.unregister(prov.id)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []

    def test_to_dict(self):
        reg = TempProviderRegistry()
        prov = reg.register(
            url="http://x", name="test", owner_process_id=7,
            models=[DiscoveredModel(id="m1", owned_by="ob")],
        )
        d = prov.to_dict()
        assert d["id"] == prov.id
        assert d["models"] == [{"id": "m1", "owned_by": "ob"}]
        assert d["auth_token"] == prov.auth_token
        assert d["is_healthy"] is True
