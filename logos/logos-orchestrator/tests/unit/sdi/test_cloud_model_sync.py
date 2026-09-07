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
