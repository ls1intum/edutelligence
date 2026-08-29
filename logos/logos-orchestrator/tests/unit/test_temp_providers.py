"""
Unit tests for the temporary (volatile) provider registry.

The registry lives purely in orchestrator memory and never touches the
database; the HTTP probe is injected so no network access is needed.
"""

import asyncio

import pytest

from logos.temp_providers import (
    STATUS_HEALTHY,
    STATUS_UNHEALTHY,
    TempProviderError,
    TempProviderRegistry,
    match_model_name,
    normalize_base_url,
)

# ---------------------------------------------------------------------------
# Base URL normalisation
# ---------------------------------------------------------------------------


def test_normalize_base_url_appends_v1():
    assert normalize_base_url("http://192.168.1.10:1234") == "http://192.168.1.10:1234/v1"


def test_normalize_base_url_keeps_existing_v1():
    assert normalize_base_url("https://mac.example.com/v1") == "https://mac.example.com/v1"
    assert normalize_base_url("https://mac.example.com/v1/") == "https://mac.example.com/v1"
    assert normalize_base_url("https://mac.example.com/v2") == "https://mac.example.com/v2"


def test_normalize_base_url_appends_v1_under_path():
    assert normalize_base_url("https://tunnel.example.com/host") == "https://tunnel.example.com/host/v1"


def test_normalize_base_url_rejects_non_http():
    with pytest.raises(TempProviderError):
        normalize_base_url("file:///etc/passwd")
    with pytest.raises(TempProviderError):
        normalize_base_url("localhost:1234")
    with pytest.raises(TempProviderError):
        normalize_base_url("")


# ---------------------------------------------------------------------------
# Model name matching
# ---------------------------------------------------------------------------


def test_match_model_name_exact():
    assert match_model_name("llama-3.1-8b", ["llama-3.1-8b", "mistral-7b"]) == "llama-3.1-8b"


def test_match_model_name_planner_alias():
    canonical = "Qwen/Qwen2.5-0.5B-Instruct"
    assert match_model_name("Qwen_Qwen2.5-0.5B-Instruct", [canonical]) == canonical
    assert match_model_name(f"planner-{canonical.replace('/', '_')}", [canonical]) == canonical


def test_match_model_name_ambiguous_alias_returns_none():
    # Both names share the same underscore alias; the match is ambiguous.
    assert match_model_name("a_b", ["a/b", "a b"]) is None


def test_match_model_name_no_match():
    assert match_model_name("nope", ["llama-3.1-8b"]) is None
    assert match_model_name("", ["llama-3.1-8b"]) is None


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def _registry(probe=None, **kwargs):
    defaults = dict(health_interval_s=3600.0, unhealthy_after=3, expiry_s=86400.0, probe_timeout_s=5.0)
    defaults.update(kwargs)
    if probe is None:

        async def probe(base_url: str, api_key: str):
            return ["llama-3.1-8b", "mistral-7b"]

    return TempProviderRegistry(probe=probe, **defaults)


async def test_add_provider_discovers_models():
    registry = _registry()
    entry = await registry.add_provider(
        base_url="http://192.168.1.10:1234",
        api_key="lm-secret",
        owner_api_key_id=7,
    )
    assert entry.base_url == "http://192.168.1.10:1234/v1"
    assert entry.name == "192.168.1.10:1234"
    assert entry.models == ["llama-3.1-8b", "mistral-7b"]
    assert entry.is_healthy
    assert entry.owner_api_key_id == 7
    assert entry.provider_id.startswith("tmp-")
    assert registry.get(entry.provider_id) is entry
    assert len(registry) == 1


async def test_add_provider_explicit_name():
    registry = _registry()
    entry = await registry.add_provider(
        base_url="http://mac.example.com",
        api_key="k",
        owner_api_key_id=1,
        name="Tobias' Mac",
    )
    assert entry.name == "Tobias' Mac"


async def test_add_provider_fails_when_host_offline():
    async def dead_probe(base_url: str, api_key: str):
        raise TempProviderError("ConnectError: [Errno 61] Connection refused")

    registry = _registry(probe=dead_probe)
    with pytest.raises(TempProviderError, match="Initial model discovery failed"):
        await registry.add_provider(base_url="http://gone.example.com", api_key="k", owner_api_key_id=1)
    assert len(registry) == 0


async def test_add_provider_fails_without_models():
    async def empty_probe(base_url: str, api_key: str):
        return []

    registry = _registry(probe=empty_probe)
    with pytest.raises(TempProviderError, match="No models discovered"):
        await registry.add_provider(base_url="http://empty.example.com", api_key="k", owner_api_key_id=1)


async def test_add_provider_rejects_duplicate_url():
    registry = _registry()
    await registry.add_provider(base_url="http://dup.example.com", api_key="k", owner_api_key_id=1)
    with pytest.raises(TempProviderError, match="already registered"):
        await registry.add_provider(base_url="http://dup.example.com/v1/", api_key="other", owner_api_key_id=2)


async def test_remove_provider():
    registry = _registry()
    entry = await registry.add_provider(base_url="http://rm.example.com", api_key="k", owner_api_key_id=1)
    assert registry.remove_provider(entry.provider_id) is True
    assert registry.remove_provider(entry.provider_id) is False
    assert registry.get(entry.provider_id) is None
    assert len(registry) == 0


async def test_public_dict_never_exposes_api_key():
    registry = _registry()
    entry = await registry.add_provider(base_url="http://secret.example.com", api_key="super-secret", owner_api_key_id=1)
    public = entry.to_public_dict()
    assert "super-secret" not in str(public)
    assert public["base_url"] == "http://secret.example.com/v1"
    assert public["status"] == STATUS_HEALTHY
    assert public["models"] == ["llama-3.1-8b", "mistral-7b"]


# ---------------------------------------------------------------------------
# Lookup and access control
# ---------------------------------------------------------------------------


async def test_find_by_model():
    registry = _registry()
    entry = await registry.add_provider(base_url="http://find.example.com", api_key="k", owner_api_key_id=1)
    assert registry.find_by_model("llama-3.1-8b") == (entry, "llama-3.1-8b")
    assert registry.find_by_model("missing") is None


async def test_list_for_api_key_owner_and_admin():
    registry = _registry()
    mine = await registry.add_provider(base_url="http://mine.example.com", api_key="k", owner_api_key_id=1)
    await registry.add_provider(base_url="http://theirs.example.com", api_key="k", owner_api_key_id=2)

    assert [e.provider_id for e in registry.list_for_api_key(1)] == [mine.provider_id]
    assert len(registry.list_for_api_key(3)) == 0
    assert len(registry.list_for_api_key(3, is_admin=True)) == 2
    assert registry.can_access(mine, 1, False) is True
    assert registry.can_access(mine, 3, False) is False
    assert registry.can_access(mine, 3, True) is True


# ---------------------------------------------------------------------------
# Health probing: failure, recovery, expiry
# ---------------------------------------------------------------------------


async def test_probe_failure_marks_unhealthy_after_threshold():
    registry = _registry(unhealthy_after=2)
    entry = await registry.add_provider(base_url="http://flaky.example.com", api_key="k", owner_api_key_id=1)

    async def dead_probe(base_url: str, api_key: str):
        raise TempProviderError("ConnectError: host down")

    registry._probe = dead_probe

    await registry._probe_entry(entry)  # first failure: still healthy
    assert entry.status == STATUS_HEALTHY
    assert entry.consecutive_failures == 1

    await registry._probe_entry(entry)  # second failure: unhealthy
    assert entry.status == STATUS_UNHEALTHY
    assert entry.is_healthy is False


async def test_probe_success_recovers_and_refreshes_models():
    registry = _registry(unhealthy_after=2)
    entry = await registry.add_provider(base_url="http://recover.example.com", api_key="k", owner_api_key_id=1)

    calls = {"n": 0}

    async def flaky_probe(base_url: str, api_key: str):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise TempProviderError("down")
        # The host came back and loaded a different model meanwhile.
        return ["llama-3.1-8b", "new-model-9b"]

    registry._probe = flaky_probe
    await registry._probe_entry(entry)
    await registry._probe_entry(entry)
    assert entry.status == STATUS_UNHEALTHY

    await registry._probe_entry(entry)
    assert entry.status == STATUS_HEALTHY
    assert entry.consecutive_failures == 0
    assert entry.models == ["llama-3.1-8b", "new-model-9b"]
    assert entry.last_success_at is not None


async def test_unhealthy_provider_expires_and_is_removed():
    registry = _registry(unhealthy_after=1, expiry_s=60.0)
    entry = await registry.add_provider(base_url="http://expire.example.com", api_key="k", owner_api_key_id=1)

    async def dead_probe(base_url: str, api_key: str):
        raise TempProviderError("down")

    registry._probe = dead_probe
    await registry._probe_entry(entry)
    assert entry.status == STATUS_UNHEALTHY
    assert registry.get(entry.provider_id) is not None

    # Simulate the expiry window having elapsed.
    entry.failures_started_mono -= 61.0
    await registry._probe_entry(entry)
    assert registry.get(entry.provider_id) is None
    assert len(registry) == 0


async def test_health_loop_start_stop():
    registry = _registry(health_interval_s=0.01)
    await registry.add_provider(base_url="http://loop.example.com", api_key="k", owner_api_key_id=1)

    await registry.start()
    assert registry._task is not None
    # Double start must not create a second loop.
    await registry.start()
    await registry.stop()
    assert registry._task is None
    # The entry survives the loop stopping — only expiry or delete removes it.
    assert len(registry) == 1


async def test_health_loop_survives_probe_crashes():
    registry = _registry(health_interval_s=0.01)
    entry = await registry.add_provider(base_url="http://crash.example.com", api_key="k", owner_api_key_id=1)

    async def crashing_probe(base_url: str, api_key: str):
        raise RuntimeError("boom")

    registry._probe = crashing_probe
    await registry.start()
    try:
        await asyncio.sleep(0.05)  # a few loop iterations with crashing probes
    finally:
        await registry.stop()
    # The loop is still alive (task finished cleanly via stop) and the entry
    # was only marked unhealthy, not lost.
    assert entry.status == STATUS_UNHEALTHY
    assert registry.get(entry.provider_id) is not None
