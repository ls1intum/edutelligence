"""Tests for the short-TTL ref cache ."""

from __future__ import annotations

import time

from logos import auth, refcache


class TestRefCache:
    def test_hit_within_ttl(self):
        cache = refcache.RefCache(ttl_s=10.0)
        calls = []

        def loader():
            calls.append(1)
            return "value"

        assert cache.load(("k",), loader) == "value"
        assert cache.load(("k",), loader) == "value"
        assert calls == [1]

    def test_expiry_reruns_loader(self):
        cache = refcache.RefCache(ttl_s=0.01)
        calls = []
        cache.load(("k",), lambda: calls.append(1) or "v1")
        time.sleep(0.02)
        assert cache.load(("k",), lambda: calls.append(2) or "v2") == "v2"
        assert calls == [1, 2]

    def test_negative_result_is_cached(self):
        """A cached None (no such key/team/model) must not re-run the loader."""
        cache = refcache.RefCache(ttl_s=10.0)
        calls = []

        def loader():
            calls.append(1)
            return None

        assert cache.load(("k",), loader) is None
        assert cache.load(("k",), loader) is None
        assert calls == [1]

    def test_ttl_zero_disables_caching(self):
        cache = refcache.RefCache(ttl_s=0.0)
        calls = []
        cache.load(("k",), lambda: calls.append(1) or "v")
        cache.load(("k",), lambda: calls.append(2) or "v")
        assert calls == [1, 2]

    def test_different_keys_are_independent(self):
        cache = refcache.RefCache(ttl_s=10.0)
        cache.load(("a",), lambda: "A")
        cache.load(("b",), lambda: "B")
        assert cache.get(("a",)) == "A"
        assert cache.get(("b",)) == "B"
        assert cache.get(("c",)) is refcache._MISSING

    def test_clear_drops_entries(self):
        cache = refcache.RefCache(ttl_s=10.0)
        cache.load(("k",), lambda: "v")
        cache.clear()
        assert cache.get(("k",)) is refcache._MISSING

    def test_entry_count_is_bounded(self):
        cache = refcache.RefCache(ttl_s=10.0)
        for i in range(refcache.RefCache.MAX_ENTRIES + 16):
            cache.set((i,), i)
        assert len(cache._entries) <= refcache.RefCache.MAX_ENTRIES

    def test_one_namespace_cannot_evict_the_others(self):
        """Filling a user-controlled namespace (the requested-model name is
        attacker-supplied) must evict within that namespace, not clear the
        other tenants' cached api keys / teams / deployments."""
        cache = refcache.RefCache(ttl_s=10.0)
        cache.set(("api_key", 1), "tenant-1-key")
        cache.set(("team", 1), "tenant-1-team")
        for i in range(refcache.RefCache.MAX_ENTRIES_PER_NAMESPACE + 16):
            cache.set(("resolve_model", 1, f"model-{i}"), "r")
        assert cache.get(("api_key", 1)) == "tenant-1-key"
        assert cache.get(("team", 1)) == "tenant-1-team"
        assert sum(1 for k in cache._entries if k[0] == "resolve_model") <= refcache.RefCache.MAX_ENTRIES_PER_NAMESPACE

    def test_global_eviction_prefers_expired_entries(self):
        cache = refcache.RefCache(ttl_s=0.01)
        cache.set(("stale", 1), "old")
        time.sleep(0.02)
        # Distinct namespaces so only the global cap can trigger.
        for i in range(refcache.RefCache.MAX_ENTRIES):
            cache.set((f"ns-{i}",), "x")
        # The expired entry was swept before any fresh one was evicted.
        assert cache.get(("stale", 1)) is refcache._MISSING
        assert cache.get((f"ns-{refcache.RefCache.MAX_ENTRIES - 1}",)) == "x"


class _AuthKeyRow:
    """Builds the minimal api_keys row shape _auth_context_from_key_row reads."""

    @staticmethod
    def row(key: str) -> dict:
        return {
            "id": 5,
            "key_value": key,
            "name": "My Key",
            "key_type": "application",
            "team_id": 2,
            "user_id": 3,
            "environment": "prod",
            "log": "BILLING",
            "settings": None,
            "default_priority": 0,
        }


class _CountingDBManager:
    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get_api_key_by_value(self, key_value: str):
        self.calls.append(key_value)
        return _AuthKeyRow.row(key_value)


class TestAuthKeyCache:
    """Warm authentication reuses the short-lived in-memory key snapshot."""

    def test_repeated_key_uses_the_cache(self, monkeypatch):
        fake = _CountingDBManager()
        monkeypatch.setattr(auth, "DBManager", lambda: fake)

        first = auth.authenticate_api_key({"logos-key": "lg-test-abc"})
        second = auth.authenticate_api_key({"logos-key": "lg-test-abc"})

        assert fake.calls == ["lg-test-abc"]
        assert first.api_key_id == second.api_key_id == 5

    def test_expired_key_snapshot_is_reloaded(self, monkeypatch):
        fake = _CountingDBManager()
        monkeypatch.setattr(auth, "DBManager", lambda: fake)
        monkeypatch.setattr(refcache.get_ref_cache(), "ttl_s", 0.0)

        auth.authenticate_api_key({"logos-key": "lg-test-abc"})
        auth.authenticate_api_key({"logos-key": "lg-test-abc"})
        assert fake.calls == ["lg-test-abc", "lg-test-abc"]

    def test_context_is_fresh_per_call(self, monkeypatch):
        """The cached row must still produce an independent AuthContext."""
        fake = _CountingDBManager()
        monkeypatch.setattr(auth, "DBManager", lambda: fake)

        first = auth.authenticate_api_key({"logos-key": "lg-test-abc"})
        second = auth.authenticate_api_key({"logos-key": "lg-test-abc"})
        first.cloud_rl = {"rpm": 1, "tpm": 2}

        assert second.cloud_rl is None
