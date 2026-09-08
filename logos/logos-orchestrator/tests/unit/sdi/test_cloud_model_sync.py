"""Cloud model auto-sync: model discovery and context-window capture.

Before this existed, every non-Azure cloud provider's catalogue had to be
typed in by hand, and the context window an upstream reported was thrown away
— which is what made a Logos instance hide the window its own upstream had
measured.
"""

from typing import Any, Dict, List

import pytest

from logos.sdi import cloud_model_sync
from logos.sdi.cloud_model_sync import CloudModelSyncService, models_url, parse_model_list

LOGOS_LISTING = {
    "object": "list",
    "data": [
        {
            "id": "Qwen/Qwen3.8-27B",
            "object": "model",
            "owned_by": "logos",
            "max_model_len": 262144,
            "max_model_len_current_min": 262144,
            "max_model_len_current_max": 262144,
            "max_model_len_overall": 262144,
        },
        # A cloud model on the upstream: catalogued, but it reports no window.
        {"id": "gpt-4.1-nano", "object": "model", "owned_by": "logos"},
    ],
}


# ── URL construction ────────────────────────────────────────────────────────


def test_models_url_appends_v1_when_missing():
    assert models_url("https://api.example.test") == "https://api.example.test/v1/models"


def test_models_url_does_not_duplicate_an_existing_version():
    # ".../v1/v1/models" is a 404 on every upstream that has the first /v1.
    assert models_url("https://logos.aet.cit.tum.de/v1/") == "https://logos.aet.cit.tum.de/v1/models"
    assert models_url("https://api.cohere.test/v2") == "https://api.cohere.test/v2/models"


def test_models_url_rejects_an_empty_base_url():
    with pytest.raises(ValueError):
        models_url("")


def test_models_url_keeps_a_path_that_only_ends_in_something_else():
    assert models_url("https://gw.test/openai") == "https://gw.test/openai/v1/models"


# ── listing parser ──────────────────────────────────────────────────────────


def test_logos_listing_yields_models_windows_and_the_logos_marker():
    names, contexts, looks_like_logos = parse_model_list(LOGOS_LISTING)
    assert names == ["Qwen/Qwen3.8-27B", "gpt-4.1-nano"]
    assert contexts == {"Qwen/Qwen3.8-27B": {"current_min": 262144, "current_max": 262144, "overall": 262144}}
    assert looks_like_logos is True


def test_a_plain_openai_listing_is_not_mistaken_for_logos():
    names, contexts, looks_like_logos = parse_model_list(
        {"data": [{"id": "gpt-4o", "owned_by": "openai"}, {"id": "gpt-4.1", "owned_by": "system"}]}
    )
    assert names == ["gpt-4o", "gpt-4.1"]
    assert contexts == {}
    assert looks_like_logos is False


def test_a_vllm_listing_contributes_its_max_model_len():
    # A model with only max_model_len still gets all three numbers: it is the
    # one window that upstream serves, so it is min, max and ceiling alike.
    _, contexts, _ = parse_model_list({"data": [{"id": "m", "max_model_len": 32768}]})
    assert contexts["m"] == {"current_min": 32768, "current_max": 32768, "overall": 32768}


def test_alternative_context_field_names_are_recognised():
    _, contexts, _ = parse_model_list({"data": [{"id": "m", "context_window": 8192}]})
    assert contexts["m"]["current_min"] == 8192


def test_zero_and_non_numeric_windows_count_as_unknown():
    _, contexts, _ = parse_model_list({"data": [{"id": "a", "max_model_len": 0}, {"id": "b", "max_model_len": "n/a"}]})
    assert contexts == {}


def test_entries_without_an_id_are_skipped():
    names, _, _ = parse_model_list({"data": [{"object": "model"}, {"id": "  "}, {"id": "ok"}]})
    assert names == ["ok"]


def test_a_non_list_body_yields_nothing():
    assert parse_model_list({"error": "nope"}) == ([], {}, False)
    assert parse_model_list(None) == ([], {}, False)


# ── sync service ────────────────────────────────────────────────────────────


class DummyDB:
    """Records what the sync would write."""

    instances: List["DummyDB"] = []

    def __init__(self):
        self.synced: Dict[int, List[str]] = {}
        self.contexts: Dict[int, Dict[str, Dict[str, int]]] = {}
        self.types: Dict[int, str] = {}
        DummyDB.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def get_cloud_sync_providers(self):
        return DummyDB.providers

    def sync_cloud_models(self, provider_id, model_names):
        self.synced[provider_id] = list(model_names)
        return {"new_models": list(model_names), "changed": True}

    def replace_cloud_model_context(self, provider_id, contexts):
        self.contexts[provider_id] = contexts
        return True

    def set_cloud_provider_type(self, provider_id, value):
        self.types[provider_id] = value


def _run(monkeypatch, providers, fetch, **service_kwargs):
    DummyDB.instances = []
    DummyDB.providers = providers
    monkeypatch.setattr(cloud_model_sync, "DBManager", DummyDB)

    class DummyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

    monkeypatch.setattr(cloud_model_sync.httpx, "AsyncClient", DummyClient)

    async def fake_fetch(url, headers, client):  # noqa: ARG001
        return fetch(url, headers)

    monkeypatch.setattr(cloud_model_sync, "fetch_models", fake_fetch)
    return CloudModelSyncService(enabled=True, **service_kwargs)


def _provider(**overrides: Any) -> Dict[str, Any]:
    provider = {
        "id": 4,
        "name": "Logos PROD",
        "base_url": "https://logos.aet.cit.tum.de/v1",
        "api_key": "lg-secret",
        "auth_name": "",
        "auth_format": "",
        "cloud_provider_type": None,
    }
    provider.update(overrides)
    return provider


@pytest.mark.asyncio
async def test_sync_mirrors_models_and_stores_the_reported_windows(monkeypatch):
    seen = {}

    def fetch(url, headers):
        seen["url"] = url
        seen["headers"] = headers
        return LOGOS_LISTING

    refreshed = {}

    async def on_models_changed(*, rebuild_classifier):
        refreshed["rebuild_classifier"] = rebuild_classifier

    service = _run(monkeypatch, [_provider()], fetch, on_models_changed=on_models_changed)
    await service.run_once()

    assert seen["url"] == "https://logos.aet.cit.tum.de/v1/models"
    # The empty auth fields fall back to the convention the provider form
    # advertises, exactly as the forwarding path does.
    assert seen["headers"]["Authorization"] == "Bearer lg-secret"

    db = DummyDB.instances[-1]
    assert db.synced[4] == ["Qwen/Qwen3.8-27B", "gpt-4.1-nano"]
    assert db.contexts[4]["Qwen/Qwen3.8-27B"]["current_min"] == 262144
    assert refreshed == {"rebuild_classifier": True}


@pytest.mark.asyncio
async def test_an_unreachable_upstream_leaves_the_catalogue_untouched(monkeypatch):
    def fetch(url, headers):  # noqa: ARG001
        raise RuntimeError("connection refused")

    service = _run(monkeypatch, [_provider()], fetch)
    await service.run_once()

    # No sync_cloud_models call: pruning links because an upstream is down
    # would make its models unroutable until it comes back.
    assert all(not db.synced for db in DummyDB.instances)


@pytest.mark.asyncio
async def test_an_empty_listing_does_not_wipe_the_catalogue(monkeypatch):
    service = _run(monkeypatch, [_provider()], lambda url, headers: {"data": []})
    await service.run_once()
    assert all(not db.synced for db in DummyDB.instances)


@pytest.mark.asyncio
async def test_an_unconfigured_logos_upstream_is_identified(monkeypatch):
    service = _run(monkeypatch, [_provider(cloud_provider_type=None)], lambda url, headers: LOGOS_LISTING)
    await service.run_once()
    assert DummyDB.instances[-1].types == {4: "logos"}


@pytest.mark.asyncio
async def test_an_operator_chosen_type_is_never_overwritten(monkeypatch):
    service = _run(monkeypatch, [_provider(cloud_provider_type="openai")], lambda url, headers: LOGOS_LISTING)
    await service.run_once()
    assert DummyDB.instances[-1].types == {}


@pytest.mark.asyncio
async def test_a_provider_without_a_base_url_is_skipped(monkeypatch):
    called = []
    service = _run(monkeypatch, [_provider(base_url="")], lambda url, headers: called.append(url) or LOGOS_LISTING)
    await service.run_once()
    assert called == []


@pytest.mark.asyncio
async def test_an_unauthenticated_upstream_sends_no_auth_header(monkeypatch):
    seen = {}
    service = _run(
        monkeypatch,
        [_provider(api_key=None)],
        lambda url, headers: seen.setdefault("headers", headers) or LOGOS_LISTING,
    )
    await service.run_once()
    assert "Authorization" not in seen["headers"]


@pytest.mark.asyncio
async def test_disabled_service_never_touches_the_database(monkeypatch):
    service = _run(monkeypatch, [_provider()], lambda url, headers: LOGOS_LISTING)
    service._enabled = False
    await service.start()
    assert DummyDB.instances == []


@pytest.mark.asyncio
async def test_a_cleartext_upstream_never_receives_the_key(monkeypatch):
    # An http:// provider with a key would put that key on the wire in the
    # clear; the benchmark path refuses the same combination.
    called = []
    service = _run(
        monkeypatch,
        [_provider(base_url="http://upstream.example/v1")],
        lambda url, headers: called.append(url) or LOGOS_LISTING,
    )
    await service.run_once()
    assert called == []
    assert all(not db.synced for db in DummyDB.instances)


@pytest.mark.asyncio
async def test_loopback_http_is_still_allowed(monkeypatch):
    # Local development runs the upstream on localhost over plain HTTP.
    called = []
    service = _run(
        monkeypatch,
        [_provider(base_url="http://localhost:8080/v1")],
        lambda url, headers: called.append(url) or LOGOS_LISTING,
    )
    await service.run_once()
    assert called == ["http://localhost:8080/v1/models"]


@pytest.mark.asyncio
async def test_an_unauthenticated_cleartext_upstream_is_synced(monkeypatch):
    # Nothing secret goes over the wire, so the transport rule does not apply.
    called = []
    service = _run(
        monkeypatch,
        [_provider(base_url="http://upstream.example/v1", api_key=None)],
        lambda url, headers: called.append(url) or LOGOS_LISTING,
    )
    await service.run_once()
    assert called == ["http://upstream.example/v1/models"]


@pytest.mark.asyncio
async def test_start_returns_before_the_first_sync_completes(monkeypatch):
    """Startup readiness must not wait on the upstreams.

    run_once() contacts every provider in turn with a request timeout each, so
    one unreachable upstream would otherwise hold up the orchestrator.
    """
    import asyncio

    release = asyncio.Event()
    started = asyncio.Event()

    async def blocking_run_once():
        started.set()
        await release.wait()

    service = _run(monkeypatch, [_provider()], lambda url, headers: LOGOS_LISTING)
    service.run_once = blocking_run_once

    await service.start()  # must not block on the pass below
    await asyncio.wait_for(started.wait(), timeout=1)
    assert not release.is_set()

    release.set()
    await service.stop()


def test_malformed_env_values_fall_back_to_the_defaults(monkeypatch):
    # Both settings are read at import time, so a typo would otherwise stop the
    # orchestrator from starting at all.
    monkeypatch.setenv("LOGOS_CLOUD_MODEL_SYNC_INTERVAL_S", "not-a-number")
    assert cloud_model_sync._env_number("LOGOS_CLOUD_MODEL_SYNC_INTERVAL_S", 900, minimum=1) == 900


def test_non_positive_env_values_are_clamped(monkeypatch):
    # A zero interval would spin the loop; a zero timeout would fail every fetch.
    monkeypatch.setenv("LOGOS_CLOUD_MODEL_SYNC_INTERVAL_S", "0")
    assert cloud_model_sync._env_number("LOGOS_CLOUD_MODEL_SYNC_INTERVAL_S", 900, minimum=1) == 1
    monkeypatch.setenv("LOGOS_CLOUD_MODEL_SYNC_TIMEOUT_S", "-5")
    assert cloud_model_sync._env_number("LOGOS_CLOUD_MODEL_SYNC_TIMEOUT_S", 30.0, minimum=0.1) == 0.1


def test_unset_env_keeps_the_default(monkeypatch):
    monkeypatch.delenv("LOGOS_CLOUD_MODEL_SYNC_INTERVAL_S", raising=False)
    assert cloud_model_sync._env_number("LOGOS_CLOUD_MODEL_SYNC_INTERVAL_S", 900, minimum=1) == 900


@pytest.mark.parametrize("raw", ["nan", "inf", "-inf", "NaN", "Infinity"])
def test_non_finite_env_values_fall_back(monkeypatch, raw):
    # float() accepts these; the int() the interval goes through does not, so
    # letting them past would crash the orchestrator at import — the very
    # failure the fallback exists to prevent.
    monkeypatch.setenv("LOGOS_CLOUD_MODEL_SYNC_INTERVAL_S", raw)
    value = cloud_model_sync._env_number("LOGOS_CLOUD_MODEL_SYNC_INTERVAL_S", 900, minimum=1)
    assert value == 900
    assert int(value) == 900  # what module import actually does


@pytest.mark.parametrize("auth_format", ["Bearer {", "Bearer {name}", "Bearer {1}"])
@pytest.mark.asyncio
async def test_a_malformed_auth_format_only_skips_its_own_provider(monkeypatch, auth_format):
    """auth_format is free text applied with str.format.

    "Bearer {" raises ValueError, "{name}" KeyError, "{1}" IndexError. Before
    this was caught, the first such provider aborted the whole pass, so every
    provider after it stopped syncing on every cycle.
    """
    called = []
    service = _run(
        monkeypatch,
        [
            _provider(id=4, name="broken", auth_name="Authorization", auth_format=auth_format),
            _provider(id=5, name="healthy", base_url="https://good.example/v1"),
        ],
        lambda url, headers: called.append(url) or LOGOS_LISTING,
    )
    await service.run_once()

    assert called == ["https://good.example/v1/models"]
    assert DummyDB.instances[-1].synced == {5: ["Qwen/Qwen3.8-27B", "gpt-4.1-nano"]}


@pytest.mark.asyncio
async def test_an_unexpected_provider_failure_does_not_stop_the_others(monkeypatch):
    """The cycle only runs on an interval, so it must survive one bad provider."""

    def fetch(url, headers):  # noqa: ARG001
        if "broken" in url:
            raise RuntimeError("boom")
        return LOGOS_LISTING

    service = _run(
        monkeypatch,
        [
            _provider(id=4, name="broken", base_url="https://broken.example/v1"),
            _provider(id=5, name="healthy", base_url="https://good.example/v1"),
        ],
        fetch,
    )
    await service.run_once()
    assert 5 in DummyDB.instances[-1].synced
