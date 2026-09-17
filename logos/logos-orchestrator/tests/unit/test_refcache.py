"""Tests for the short-TTL ref cache (#980 O12)."""

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
    def test_repeated_key_is_served_from_cache(self, monkeypatch):
        fake = _CountingDBManager()
        monkeypatch.setattr(auth, "DBManager", lambda: fake)

        first = auth.authenticate_api_key({"logos-key": "lg-test-abc"})
        second = auth.authenticate_api_key({"logos-key": "lg-test-abc"})

        # One DB call for both authentications: the second hit is cached.
        assert fake.calls == ["lg-test-abc"]
        assert first.api_key_id == second.api_key_id == 5

    def test_invalid_key_negative_cache_still_401(self, monkeypatch):
        fake = _CountingDBManager()
        fake.get_api_key_by_value = lambda key: (fake.calls.append(key), None)[1]
        monkeypatch.setattr(auth, "DBManager", lambda: fake)

        import pytest
        from fastapi import HTTPException

        with pytest.raises(HTTPException):
            auth.authenticate_api_key({"logos-key": "lg-missing"})
        with pytest.raises(HTTPException):
            auth.authenticate_api_key({"logos-key": "lg-missing"})

        # The negative result is cached too: one lookup, two 401s.
        assert fake.calls == ["lg-missing"]

    def test_context_is_fresh_per_call(self, monkeypatch):
        """The cached row is shared, but the AuthContext must not be — the
        request path mutates cloud_rl/local_rl on it."""
        fake = _CountingDBManager()
        monkeypatch.setattr(auth, "DBManager", lambda: fake)

        first = auth.authenticate_api_key({"logos-key": "lg-test-abc"})
        second = auth.authenticate_api_key({"logos-key": "lg-test-abc"})
        first.cloud_rl = {"rpm": 1, "tpm": 2}

        assert second.cloud_rl is None
