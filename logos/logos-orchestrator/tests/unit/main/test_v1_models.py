"""
Tests for the OpenAI-compatible /v1/models endpoints.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

import logos as main
from logos.routers import user_facing as user_facing_mod

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(headers: dict | None = None):
    """Create a mock FastAPI Request with the given headers."""
    req = MagicMock()
    if headers is None:
        req.headers = {"authorization": "Bearer test-key"}
    else:
        req.headers = headers
    return req


class DummyDB:
    """Minimal DBManager stub used via monkeypatch."""

    def __init__(self, models=None, historic=None, cloud=None, catalog=None, hidden=None):
        self._models = models if models is not None else []
        # Models this key cannot see (but an administrator key's resolver can).
        self._hidden = hidden if hidden is not None else []
        # Model name -> widest context ever reported (model_profiles high-water mark).
        self._historic = historic if historic is not None else {}
        # Model name -> the windows cloud upstreams report (cloud_model_context).
        self._cloud = cloud if cloud is not None else {}
        # Model name -> the input context window the model catalog publishes (model_capabilities).
        self._catalog = catalog if catalog is not None else {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get_models_for_api_key(self, _api_key_id: int):
        return self._models

    def get_all_model_names_with_aliases(self):
        return self._models + self._hidden

    def get_model_for_api_key(self, _api_key_id: int, model_name: str):
        return next((m for m in self._models if m["name"] == model_name), None)

    def get_historic_max_context_by_model(self):
        return self._historic

    def get_cloud_context_by_model(self):
        return self._cloud

    def get_catalog_context_by_model(self):
        return self._catalog


# ---------------------------------------------------------------------------
# GET /v1/models — list models
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_models_returns_openai_format(monkeypatch):
    """Successful request returns the OpenAI list format."""
    fake_models = [
        {"id": 1, "name": "gpt-4o", "description": "GPT-4o"},
        {"id": 2, "name": "gpt-3.5-turbo", "description": None},
    ]

    monkeypatch.setattr(user_facing_mod, "DBManager", lambda: DummyDB(models=fake_models))

    with patch("logos.routers.user_facing.authenticate_api_key") as mock_auth:
        mock_auth.return_value = MagicMock(api_key_id=1, key_value="test-key")

        response = await user_facing_mod.list_models(_make_request())

    body = response.body
    import json

    data = json.loads(body)

    assert data["object"] == "list"
    assert len(data["data"]) == 2

    first = data["data"][0]
    assert first["id"] == "gpt-4o"
    assert first["object"] == "model"
    assert isinstance(first["created"], int)
    assert first["created"] > 0
    assert first["owned_by"] == "logos"

    second = data["data"][1]
    assert second["id"] == "gpt-3.5-turbo"


@pytest.mark.asyncio
async def test_list_models_empty(monkeypatch):
    """When a profile has no models, returns an empty list."""
    monkeypatch.setattr(user_facing_mod, "DBManager", lambda: DummyDB(models=[]))

    with patch("logos.routers.user_facing.authenticate_api_key") as mock_auth:
        mock_auth.return_value = MagicMock(api_key_id=1, key_value="test-key")

        response = await user_facing_mod.list_models(_make_request())

    import json

    data = json.loads(response.body)
    assert data["object"] == "list"
    assert data["data"] == []


@pytest.mark.asyncio
async def test_list_models_auth_failure():
    """Missing/invalid key returns 401."""
    with patch("logos.routers.user_facing.authenticate_api_key") as mock_auth:
        mock_auth.side_effect = HTTPException(status_code=401, detail="Invalid logos key")

        with pytest.raises(HTTPException) as exc:
            await user_facing_mod.list_models(_make_request(headers={}))

        assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# GET /v1/models/{model_id} — retrieve single model
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retrieve_model_success(monkeypatch):
    """Retrieve an accessible model returns the OpenAI model object."""
    fake_models = [
        {"id": 1, "name": "gpt-4o", "description": "GPT-4o"},
        {"id": 2, "name": "gpt-3.5-turbo", "description": None},
    ]

    monkeypatch.setattr(user_facing_mod, "DBManager", lambda: DummyDB(models=fake_models))

    with patch("logos.routers.user_facing.authenticate_api_key") as mock_auth:
        mock_auth.return_value = MagicMock(api_key_id=1, key_value="test-key")

        response = await user_facing_mod.retrieve_model("gpt-4o", _make_request())

    import json

    data = json.loads(response.body)

    assert data["id"] == "gpt-4o"
    assert data["object"] == "model"
    assert isinstance(data["created"], int)
    assert data["created"] > 0
    assert data["owned_by"] == "logos"


@pytest.mark.asyncio
async def test_retrieve_model_not_found(monkeypatch):
    """Requesting a model that doesn't exist returns 404."""
    monkeypatch.setattr(user_facing_mod, "DBManager", lambda: DummyDB(models=[]))

    with patch("logos.routers.user_facing.authenticate_api_key") as mock_auth:
        mock_auth.return_value = MagicMock(api_key_id=1, key_value="test-key")

        with pytest.raises(HTTPException) as exc:
            await user_facing_mod.retrieve_model("nonexistent-model", _make_request())

        assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_retrieve_model_no_access(monkeypatch):
    """User has models but not the requested one → 404."""
    fake_models = [
        {"id": 1, "name": "gpt-4o", "description": "GPT-4o"},
    ]
    monkeypatch.setattr(user_facing_mod, "DBManager", lambda: DummyDB(models=fake_models))

    with patch("logos.routers.user_facing.authenticate_api_key") as mock_auth:
        mock_auth.return_value = MagicMock(api_key_id=1, key_value="test-key")

        with pytest.raises(HTTPException) as exc:
            await user_facing_mod.retrieve_model("gpt-3.5-turbo", _make_request())

        assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_retrieve_model_with_slashes(monkeypatch):
    """Model IDs containing slashes (e.g. meta-llama/Llama-3-8B) work correctly."""
    slash_model = "meta-llama/Llama-3-8B"
    fake_models = [
        {"id": 1, "name": slash_model, "description": "Llama 3 8B"},
    ]
    monkeypatch.setattr(user_facing_mod, "DBManager", lambda: DummyDB(models=fake_models))

    with patch("logos.routers.user_facing.authenticate_api_key") as mock_auth:
        mock_auth.return_value = MagicMock(api_key_id=1, key_value="test-key")

        response = await user_facing_mod.retrieve_model(slash_model, _make_request())

    import json

    data = json.loads(response.body)

    assert data["id"] == slash_model
    assert data["object"] == "model"
    assert isinstance(data["created"], int)
    assert data["created"] > 0
    assert data["owned_by"] == "logos"


@pytest.mark.asyncio
async def test_retrieve_model_with_planner_sanitized_alias(monkeypatch):
    """Planner-safe aliases with underscores resolve back to canonical model ids."""
    canonical_model = "Qwen/Qwen2.5-0.5B-Instruct"
    alias_model = "Qwen_Qwen2.5-0.5B-Instruct"
    fake_models = [
        {"id": 1, "name": canonical_model, "description": "Qwen 0.5B"},
    ]
    monkeypatch.setattr(user_facing_mod, "DBManager", lambda: DummyDB(models=fake_models))

    with patch("logos.routers.user_facing.authenticate_api_key") as mock_auth:
        mock_auth.return_value = MagicMock(api_key_id=1, key_value="test-key")

        response = await user_facing_mod.retrieve_model(alias_model, _make_request())

    import json

    data = json.loads(response.body)

    assert data["id"] == canonical_model
    assert data["object"] == "model"


@pytest.mark.asyncio
async def test_retrieve_model_auth_failure():
    """Missing/invalid key on retrieve returns 401."""
    with patch("logos.routers.user_facing.authenticate_api_key") as mock_auth:
        mock_auth.side_effect = HTTPException(status_code=401, detail="Invalid logos key")

        with pytest.raises(HTTPException) as exc:
            await user_facing_mod.retrieve_model("gpt-4o", _make_request(headers={}))

        assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# max_model_len enrichment from logosnode runtime snapshots
# ---------------------------------------------------------------------------


class DummyRegistry:
    """Registry stub exposing runtime snapshots keyed by provider id."""

    def __init__(self, snapshots=None):
        self._snapshots = snapshots or {}

    def active_provider_ids(self):
        return list(self._snapshots.keys())

    def peek_runtime_snapshot(self, provider_id):
        return self._snapshots.get(provider_id)


def _snapshot(lanes, model_profiles=None):
    return {"runtime": {"lanes": lanes, "model_profiles": model_profiles or {}}}


def _vllm_lane(model, max_model_len=0, context_length=4096):
    return {
        "model": model,
        "vllm": True,
        "context_length": context_length,
        "backend_metrics": {"max_model_len": max_model_len},
    }


async def _list_ids_to_entries(monkeypatch, models, registry, historic=None, cloud=None, catalog=None):
    import json

    # The handler reads DBManager from its router module; the historic-max,
    # cloud-window and catalog lookups it goes through read it from main's
    # globals — both need the fake.
    monkeypatch.setattr(
        main, "DBManager", lambda: DummyDB(models=models, historic=historic, cloud=cloud, catalog=catalog)
    )
    monkeypatch.setattr(
        user_facing_mod, "DBManager", lambda: DummyDB(models=models, historic=historic, cloud=cloud, catalog=catalog)
    )
    monkeypatch.setattr(main, "_logosnode_registry", registry)
    with patch("logos.routers.user_facing.authenticate_api_key") as mock_auth:
        mock_auth.return_value = MagicMock(api_key_id=1, key_value="test-key")
        response = await user_facing_mod.list_models(_make_request())
    return {entry["id"]: entry for entry in json.loads(response.body)["data"]}


@pytest.mark.asyncio
async def test_list_models_includes_served_context_window(monkeypatch):
    """Models with a live lane report max_model_len; others omit the key."""
    models = [
        {"id": 1, "name": "qwen-14b", "description": None},
        {"id": 2, "name": "gpt-4o", "description": None},
    ]
    registry = DummyRegistry({7: _snapshot([_vllm_lane("qwen-14b", max_model_len=40960)])})

    entries = await _list_ids_to_entries(monkeypatch, models, registry)

    assert entries["qwen-14b"]["max_model_len"] == 40960
    assert "max_model_len" not in entries["gpt-4o"]


@pytest.mark.asyncio
async def test_list_models_lane_configured_context_length(monkeypatch):
    """A lane whose engine has not reported a window falls back to its
    configured context_length (the 4096 sentinel means "unset")."""
    models = [{"id": 1, "name": "mistral-7b", "description": None}]
    lane = _vllm_lane("mistral-7b", max_model_len=0, context_length=16384)
    registry = DummyRegistry({7: _snapshot([lane])})

    entries = await _list_ids_to_entries(monkeypatch, models, registry)

    assert entries["mistral-7b"]["max_model_len"] == 16384


@pytest.mark.asyncio
async def test_list_models_min_across_workers(monkeypatch):
    """When workers serve the same model with different windows, the smallest wins."""
    models = [{"id": 1, "name": "qwen-14b", "description": None}]
    registry = DummyRegistry(
        {
            7: _snapshot([_vllm_lane("qwen-14b", max_model_len=40960)]),
            8: _snapshot([_vllm_lane("qwen-14b", max_model_len=32768)]),
        }
    )

    entries = await _list_ids_to_entries(monkeypatch, models, registry)

    assert entries["qwen-14b"]["max_model_len"] == 32768


@pytest.mark.asyncio
async def test_list_models_vllm_calibration_fallback(monkeypatch):
    """Without an explicit max_model_len (and the sentinel 4096 lane context),
    the calibrated profile value is used."""
    models = [{"id": 1, "name": "gemma-12b", "description": None}]
    registry = DummyRegistry(
        {
            7: _snapshot(
                [_vllm_lane("gemma-12b")],
                model_profiles={"gemma-12b": {"calibration_max_model_len": 24576}},
            )
        }
    )

    entries = await _list_ids_to_entries(monkeypatch, models, registry)

    assert entries["gemma-12b"]["max_model_len"] == 24576


@pytest.mark.asyncio
async def test_list_models_vllm_explicit_lane_context(monkeypatch):
    """A non-sentinel lane context_length acts as the explicit override."""
    models = [{"id": 1, "name": "qwen-7b", "description": None}]
    registry = DummyRegistry({7: _snapshot([_vllm_lane("qwen-7b", context_length=20480)])})

    entries = await _list_ids_to_entries(monkeypatch, models, registry)

    assert entries["qwen-7b"]["max_model_len"] == 20480


@pytest.mark.asyncio
async def test_list_models_unknown_window_omitted(monkeypatch):
    """A vLLM lane with no explicit config, sentinel context, and no profile
    yields no max_model_len rather than a wrong one."""
    models = [{"id": 1, "name": "qwen-7b", "description": None}]
    registry = DummyRegistry({7: _snapshot([_vllm_lane("qwen-7b")])})

    entries = await _list_ids_to_entries(monkeypatch, models, registry)

    assert "max_model_len" not in entries["qwen-7b"]


@pytest.mark.asyncio
async def test_retrieve_model_includes_served_context_window(monkeypatch):
    """The single-model endpoint carries the same enrichment."""
    import json

    models = [{"id": 1, "name": "qwen-14b", "description": None}]
    monkeypatch.setattr(user_facing_mod, "DBManager", lambda: DummyDB(models=models))
    monkeypatch.setattr(
        main,
        "_logosnode_registry",
        DummyRegistry({7: _snapshot([_vllm_lane("qwen-14b", max_model_len=40960)])}),
    )

    with patch("logos.routers.user_facing.authenticate_api_key") as mock_auth:
        mock_auth.return_value = MagicMock(api_key_id=1, key_value="test-key")
        response = await user_facing_mod.retrieve_model("qwen-14b", _make_request())

    assert json.loads(response.body)["max_model_len"] == 40960


@pytest.mark.asyncio
async def test_list_models_reports_best_and_native_next_to_the_minimum(monkeypatch):
    """Three figures, because one number cannot serve every client.

    ``max_model_len_current_min`` is the smallest window being served (holds
    whichever deployment answers) and ``max_model_len`` repeats it under the
    name vLLM uses. A client that would rather advertise the ceiling gets
    ``max_model_len_current_max`` (widest served right now) and
    ``max_model_len_overall`` (the widest it is ever served with).
    """
    models = [{"id": 1, "name": "qwen-27b", "description": None}]
    registry = DummyRegistry(
        {
            7: _snapshot(
                [_vllm_lane("qwen-27b", max_model_len=262144)],
                model_profiles={"qwen-27b": {"max_context_length": 262144}},
            ),
            8: _snapshot([_vllm_lane("qwen-27b", max_model_len=33000)]),
        }
    )

    entries = await _list_ids_to_entries(monkeypatch, models, registry)

    assert entries["qwen-27b"]["max_model_len"] == 33000
    assert entries["qwen-27b"]["max_model_len_current_min"] == 33000
    assert entries["qwen-27b"]["max_model_len_current_max"] == 262144
    assert entries["qwen-27b"]["max_model_len_overall"] == 262144


@pytest.mark.asyncio
async def test_list_models_native_length_without_a_live_lane(monkeypatch):
    """A model with a profile but nothing loaded still reports its own limit.

    That is the number a config file has to be written from, and it does not
    depend on what happens to be running at the time the page is opened.
    """
    models = [{"id": 1, "name": "cold-model", "description": None}]
    registry = DummyRegistry({7: _snapshot([], model_profiles={"cold-model": {"max_context_length": 131072}})})

    entries = await _list_ids_to_entries(monkeypatch, models, registry)

    assert entries["cold-model"]["max_model_len_overall"] == 131072
    assert "max_model_len" not in entries["cold-model"]
    assert "max_model_len_current_min" not in entries["cold-model"]
    assert "max_model_len_current_max" not in entries["cold-model"]


@pytest.mark.asyncio
async def test_list_models_omits_every_context_field_when_unknown(monkeypatch):
    """Cloud models keep the exact object they had before these fields existed."""
    models = [{"id": 1, "name": "gpt-4o", "description": None}]
    entries = await _list_ids_to_entries(monkeypatch, models, DummyRegistry({}))

    assert set(entries["gpt-4o"]) == {"id", "object", "created", "owned_by"}


# ---------------------------------------------------------------------------
# Historic maximum from the database — the all-workernodes-offline fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_models_reports_historic_max_when_all_workernodes_offline(monkeypatch):
    """With no node connected, the historic maximum the database keeps is what
    /v1/models can still promise.

    Only ``max_model_len_overall`` comes back: no lane is up that would make
    any of the current_* figures true, and claiming one would size the client
    against a window nothing actually serves. The claude-logos wrapper's
    cascade (current_max → current_min → overall) is built for exactly this:
    it now lands on the historic max instead of its blind fallback constant.
    """
    models = [{"id": 1, "name": "qwen-27b", "description": None}]
    entries = await _list_ids_to_entries(monkeypatch, models, DummyRegistry({}), historic={"qwen-27b": 262144})

    assert entries["qwen-27b"]["max_model_len_overall"] == 262144
    assert "max_model_len" not in entries["qwen-27b"]
    assert "max_model_len_current_min" not in entries["qwen-27b"]
    assert "max_model_len_current_max" not in entries["qwen-27b"]


@pytest.mark.asyncio
async def test_list_models_historic_max_tops_up_a_narrower_live_overall(monkeypatch):
    """A re-calibration on a node with less VRAM reports a narrower window than
    an earlier calibration on a bigger node. The live profile says 33000, but
    the model has been served at 262144 before — that is what "overall" means,
    so the historic mark stands."""
    models = [{"id": 1, "name": "qwen-27b", "description": None}]
    registry = DummyRegistry({7: _snapshot([], model_profiles={"qwen-27b": {"max_context_length": 33000}})})
    entries = await _list_ids_to_entries(monkeypatch, models, registry, historic={"qwen-27b": 262144})

    assert entries["qwen-27b"]["max_model_len_overall"] == 262144
    assert "max_model_len" not in entries["qwen-27b"]


@pytest.mark.asyncio
async def test_list_models_historic_max_never_shrinks_a_live_overall(monkeypatch):
    """The top-up only ever raises: a live figure the nodes report now is never
    lowered by a stale historic one."""
    models = [{"id": 1, "name": "qwen-27b", "description": None}]
    registry = DummyRegistry({7: _snapshot([], model_profiles={"qwen-27b": {"max_context_length": 262144}})})
    entries = await _list_ids_to_entries(monkeypatch, models, registry, historic={"qwen-27b": 33000})

    assert entries["qwen-27b"]["max_model_len_overall"] == 262144


@pytest.mark.asyncio
async def test_list_models_reports_a_cloud_upstreams_context_window(monkeypatch):
    """A model reachable only through a cloud provider used to be published with
    no window at all, because the numbers came solely from the workernode
    snapshots. A downstream Logos instance therefore hid the very window its
    upstream had measured, and claude-logos fell back to a guess."""
    models = [{"id": 1, "name": "Qwen/Qwen3.8-27B", "description": None}]
    entries = await _list_ids_to_entries(
        monkeypatch,
        models,
        DummyRegistry({}),
        cloud={"Qwen/Qwen3.8-27B": {"current_min": 262144, "current_max": 262144, "overall": 262144}},
    )

    assert entries["Qwen/Qwen3.8-27B"]["max_model_len"] == 262144
    assert entries["Qwen/Qwen3.8-27B"]["max_model_len_current_min"] == 262144
    assert entries["Qwen/Qwen3.8-27B"]["max_model_len_current_max"] == 262144
    assert entries["Qwen/Qwen3.8-27B"]["max_model_len_overall"] == 262144


@pytest.mark.asyncio
async def test_list_models_cloud_window_does_not_widen_the_guaranteed_minimum(monkeypatch):
    """A model served both locally and through a cloud upstream keeps the
    smallest window as its guaranteed one: the request may be routed to either,
    so only the narrower number holds unconditionally."""
    models = [{"id": 1, "name": "qwen-27b", "description": None}]
    registry = DummyRegistry({7: _snapshot([_vllm_lane("qwen-27b", max_model_len=33000)])})
    entries = await _list_ids_to_entries(
        monkeypatch, models, registry, cloud={"qwen-27b": {"current_min": 262144, "overall": 262144}}
    )

    assert entries["qwen-27b"]["max_model_len"] == 33000
    assert entries["qwen-27b"]["max_model_len_current_max"] == 262144
    assert entries["qwen-27b"]["max_model_len_overall"] == 262144


@pytest.mark.asyncio
async def test_list_models_cloud_model_without_a_reported_window_stays_bare(monkeypatch):
    """Most OpenAI-shaped upstreams report no window; those models keep the
    object they had before any of this existed."""
    models = [{"id": 1, "name": "gpt-4.1-nano", "description": None}]
    entries = await _list_ids_to_entries(monkeypatch, models, DummyRegistry({}), cloud={})

    assert "max_model_len" not in entries["gpt-4.1-nano"]


# ---------------------------------------------------------------------------
# Catalog windows — the last resort for models no source has measured
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_models_reports_the_catalog_window_for_a_cloud_model(monkeypatch):
    """A cloud model whose upstream publishes no window of its own used to reach
    /v1/models without a size, and a wrapper sizing a session from the listing
    fell back to a blind constant. The window the model catalog records for the
    model is the best knowledge there is: a provider serves a catalog model at
    its full published size, so the single number is the minimum, the maximum
    and the ceiling alike."""
    models = [{"id": 1, "name": "gpt-5.6-luna", "description": None}]
    entries = await _list_ids_to_entries(monkeypatch, models, DummyRegistry({}), catalog={"gpt-5.6-luna": 1050000})

    assert entries["gpt-5.6-luna"]["max_model_len"] == 1050000
    assert entries["gpt-5.6-luna"]["max_model_len_current_min"] == 1050000
    assert entries["gpt-5.6-luna"]["max_model_len_current_max"] == 1050000
    assert entries["gpt-5.6-luna"]["max_model_len_overall"] == 1050000


@pytest.mark.asyncio
async def test_list_models_measured_window_wins_over_the_catalog(monkeypatch):
    """A lane running the model narrower than the published size is the truth
    for what Logos serves: the catalog must not widen any figure a source
    measured, whichever of the three fields it would reach."""
    models = [{"id": 1, "name": "gpt-oss-120b", "description": None}]
    registry = DummyRegistry(
        {
            7: _snapshot(
                [_vllm_lane("gpt-oss-120b", max_model_len=33000)],
                model_profiles={"gpt-oss-120b": {"max_context_length": 33000}},
            )
        }
    )
    entries = await _list_ids_to_entries(monkeypatch, models, registry, catalog={"gpt-oss-120b": 131072})

    assert entries["gpt-oss-120b"]["max_model_len"] == 33000
    assert entries["gpt-oss-120b"]["max_model_len_current_max"] == 33000
    assert entries["gpt-oss-120b"]["max_model_len_overall"] == 33000


@pytest.mark.asyncio
async def test_list_models_cloud_self_report_wins_over_the_catalog(monkeypatch):
    """What an upstream publishes about itself is a measurement and beats the
    catalog's published limit, narrow or wide."""
    models = [{"id": 1, "name": "some-cloud-model", "description": None}]
    entries = await _list_ids_to_entries(
        monkeypatch,
        models,
        DummyRegistry({}),
        cloud={"some-cloud-model": {"current_min": 65536, "current_max": 65536, "overall": 65536}},
        catalog={"some-cloud-model": 131072},
    )

    assert entries["some-cloud-model"]["max_model_len"] == 65536
    assert entries["some-cloud-model"]["max_model_len_overall"] == 65536


@pytest.mark.asyncio
async def test_list_models_catalog_window_never_added_for_an_unlisted_model(monkeypatch):
    """The catalog only sizes models this key may actually use: a catalog
    entry for a model outside the listing must not surface in /v1/models."""
    models = [{"id": 1, "name": "qwen-14b", "description": None}]
    entries = await _list_ids_to_entries(monkeypatch, models, DummyRegistry({}), catalog={"other-model": 131072})

    assert set(entries) == {"qwen-14b"}
    assert "max_model_len" not in entries["qwen-14b"]


# ---------------------------------------------------------------------------
# GET /v1/models — Anthropic shape (the ``anthropic-version`` header gate)
# ---------------------------------------------------------------------------


def _anthropic_request(query_params: dict | None = None):
    """A mock request the way an Anthropic SDK / Claude Code call arrives:
    with the mandatory ``anthropic-version`` header and a real query string."""
    req = _make_request(headers={"authorization": "Bearer test-key", "anthropic-version": "2023-06-01"})
    # The OpenAI path never reads query params, but the Anthropic one does —
    # a bare MagicMock would hand back a truthy .get() result for after_id.
    req.query_params = query_params if query_params is not None else {}
    return req


async def _list_anthropic_body(
    monkeypatch,
    models,
    registry,
    historic=None,
    cloud=None,
    catalog=None,
    query_params=None,
    hidden=None,
):
    """Call list_models the way an Anthropic client does and return the body."""
    import json

    monkeypatch.setattr(
        main,
        "DBManager",
        lambda: DummyDB(models=models, historic=historic, cloud=cloud, catalog=catalog, hidden=hidden),
    )
    monkeypatch.setattr(
        user_facing_mod,
        "DBManager",
        lambda: DummyDB(models=models, historic=historic, cloud=cloud, catalog=catalog, hidden=hidden),
    )
    monkeypatch.setattr(main, "_logosnode_registry", registry)
    with patch("logos.routers.user_facing.authenticate_api_key") as mock_auth:
        mock_auth.return_value = MagicMock(api_key_id=1, key_value="test-key")
        response = await user_facing_mod.list_models(_anthropic_request(query_params))
    return json.loads(response.body)


@pytest.mark.asyncio
async def test_list_models_anthropic_shape(monkeypatch):
    """With the header, the same endpoint returns the Anthropic models shape."""
    models = [
        {"id": 1, "name": "qwen-27b", "description": "Qwen 27B"},
        {"id": 2, "name": "gpt-4o", "description": None},
    ]
    registry = DummyRegistry({7: _snapshot([_vllm_lane("qwen-27b", max_model_len=33000)])})
    body = await _list_anthropic_body(monkeypatch, models, registry)

    assert body["first_id"] == "claude-qwen-27b"
    assert body["last_id"] == "claude-gpt-4o"
    assert body["has_more"] is False
    assert [entry["id"] for entry in body["data"]] == ["claude-qwen-27b", "claude-gpt-4o"]

    first = body["data"][0]
    assert first["type"] == "model"
    assert first["display_name"] == "Qwen 27B"
    # RFC 3339 timestamp, rendered from the same server start the OpenAI shape uses.
    assert first["created_at"].endswith("Z") and "T" in first["created_at"]
    assert first["max_input_tokens"] == 33000
    assert first["max_tokens"] is None
    assert first["capabilities"] is None
    assert first["allowed_fallback_models"] is None

    second = body["data"][1]
    # No description: the plain name is the display name. No known window: null.
    assert second["display_name"] == "gpt-4o"
    assert second["max_input_tokens"] is None


@pytest.mark.asyncio
async def test_list_models_anthropic_lists_only_claude_prefixed_ids(monkeypatch):
    """Claude Code drops gateway models whose id lacks "claude"/"anthropic",
    so every other id is listed as claude-<id> and only so. An id that already
    contains either word is listed unchanged."""
    models = [
        {"id": 1, "name": "Qwen/Qwen3.8-27B", "description": None},
        {"id": 2, "name": "claude-native", "description": None},
        {"id": 3, "name": "my-Anthropic-proxy", "description": None},
    ]
    body = await _list_anthropic_body(monkeypatch, models, DummyRegistry({}))
    assert [entry["id"] for entry in body["data"]] == [
        "claude-Qwen/Qwen3.8-27B",
        "claude-native",
        "my-Anthropic-proxy",
    ]
    assert body["data"][0]["display_name"] == "Qwen/Qwen3.8-27B"


@pytest.mark.asyncio
async def test_list_models_anthropic_never_advertises_a_colliding_id(monkeypatch):
    """foo next to claude-foo, or a model whose alias is claude-foo: the
    prefixed id belongs to the other model, so foo is listed under its own
    name rather than under an id that would select the wrong model."""
    models = [
        {"id": 1, "name": "foo", "description": None},
        {"id": 2, "name": "claude-foo", "description": None},
        {"id": 3, "name": "bar", "description": None},
        {"id": 4, "name": "baz", "description": None, "aliases": ["claude-bar"]},
    ]
    body = await _list_anthropic_body(monkeypatch, models, DummyRegistry({}))
    assert [entry["id"] for entry in body["data"]] == ["foo", "claude-foo", "bar", "claude-baz"]


@pytest.mark.asyncio
async def test_list_models_anthropic_checks_collisions_against_hidden_models(monkeypatch):
    """The proxy resolver searches every model for administrator keys, so a
    claude-foo this key cannot see would still capture foo's prefixed id."""
    models = [{"id": 1, "name": "foo", "description": None}]
    hidden = [{"name": "claude-foo", "aliases": []}]
    body = await _list_anthropic_body(monkeypatch, models, DummyRegistry({}), hidden=hidden)
    assert [entry["id"] for entry in body["data"]] == ["foo"]


@pytest.mark.asyncio
async def test_list_models_anthropic_max_input_prefers_the_guaranteed_window(monkeypatch):
    """max_input_tokens is the window a request is sure to get (smallest
    served), not the widest one."""
    models = [{"id": 1, "name": "qwen-27b", "description": None}]
    registry = DummyRegistry(
        {
            7: _snapshot([_vllm_lane("qwen-27b", max_model_len=262144)]),
            8: _snapshot([_vllm_lane("qwen-27b", max_model_len=33000)]),
        }
    )
    body = await _list_anthropic_body(monkeypatch, models, registry)
    assert body["data"][0]["max_input_tokens"] == 33000


@pytest.mark.asyncio
async def test_list_models_anthropic_max_input_falls_back_to_overall(monkeypatch):
    """A model that nothing serves right now but that has a known ceiling
    reports it — a config file can still be written from the listing."""
    models = [{"id": 1, "name": "cold-model", "description": None}]
    registry = DummyRegistry({7: _snapshot([], model_profiles={"cold-model": {"max_context_length": 131072}})})
    body = await _list_anthropic_body(monkeypatch, models, registry)
    assert body["data"][0]["max_input_tokens"] == 131072


@pytest.mark.asyncio
async def test_list_models_anthropic_max_input_unknown_is_null(monkeypatch):
    """No source knows the window: null rather than a made-up number."""
    models = [{"id": 1, "name": "mystery", "description": None}]
    body = await _list_anthropic_body(monkeypatch, models, DummyRegistry({}))
    assert body["data"][0]["max_input_tokens"] is None


@pytest.mark.asyncio
async def test_list_models_anthropic_without_header_stays_openai_shape(monkeypatch):
    """The gate is the header alone: a request without it sees the OpenAI
    shape exactly as before (this is what the claude-logos wrapper probes)."""
    models = [{"id": 1, "name": "qwen-27b", "description": None}]
    monkeypatch.setattr(user_facing_mod, "DBManager", lambda: DummyDB(models=models))
    monkeypatch.setattr(main, "_logosnode_registry", DummyRegistry({}))
    with patch("logos.routers.user_facing.authenticate_api_key") as mock_auth:
        mock_auth.return_value = MagicMock(api_key_id=1, key_value="test-key")
        response = await user_facing_mod.list_models(_make_request())

    import json

    body = json.loads(response.body)
    assert body["object"] == "list"
    assert set(body) == {"object", "data"}
    assert set(body["data"][0]) == {"id", "object", "created", "owned_by"}


@pytest.mark.asyncio
async def test_list_models_anthropic_limit_caps_the_page(monkeypatch):
    """limit=2 yields two models and tells the client more remain."""
    models = [{"id": i, "name": f"model-{i}", "description": None} for i in range(5)]
    body = await _list_anthropic_body(monkeypatch, models, DummyRegistry({}), query_params={"limit": "2"})

    assert [entry["id"] for entry in body["data"]] == ["claude-model-0", "claude-model-1"]
    assert body["first_id"] == "claude-model-0"
    assert body["last_id"] == "claude-model-1"
    assert body["has_more"] is True


@pytest.mark.asyncio
async def test_list_models_anthropic_limit_without_a_remainder(monkeypatch):
    """A limit that covers the whole list still says has_more: false."""
    models = [{"id": i, "name": f"model-{i}", "description": None} for i in range(3)]
    body = await _list_anthropic_body(monkeypatch, models, DummyRegistry({}), query_params={"limit": "10"})
    assert len(body["data"]) == 3
    assert body["has_more"] is False


@pytest.mark.asyncio
async def test_list_models_anthropic_after_id_cursors_past_a_model(monkeypatch):
    """after_id starts the page after the named model, so pagination walks
    the listing without repeating entries."""
    models = [{"id": i, "name": f"model-{i}", "description": None} for i in range(3)]
    body = await _list_anthropic_body(
        monkeypatch, models, DummyRegistry({}), query_params={"after_id": "claude-model-1"}
    )

    assert [entry["id"] for entry in body["data"]] == ["claude-model-2"]
    assert body["first_id"] == "claude-model-2"
    assert body["last_id"] == "claude-model-2"
    assert body["has_more"] is False


@pytest.mark.asyncio
async def test_list_models_anthropic_stale_after_id_starts_over(monkeypatch):
    """A cursor that matches nothing (renamed model, other key) degrades to
    the full listing rather than an error."""
    models = [{"id": 1, "name": "model-a", "description": None}]
    body = await _list_anthropic_body(monkeypatch, models, DummyRegistry({}), query_params={"after_id": "gone"})
    assert [entry["id"] for entry in body["data"]] == ["claude-model-a"]


@pytest.mark.asyncio
async def test_list_models_anthropic_leaves_aliases_out(monkeypatch):
    """Aliases are not listed (they only confuse the picker) but still carry
    the model's window through the model they belong to."""
    models = [
        {"id": 1, "name": "qwen-27b", "description": "Qwen 27B", "aliases": ["local-most-powerful"]},
        {"id": 2, "name": "other-model", "description": None, "aliases": []},
    ]
    registry = DummyRegistry({7: _snapshot([_vllm_lane("qwen-27b", max_model_len=33000)])})
    body = await _list_anthropic_body(monkeypatch, models, registry)

    assert [entry["id"] for entry in body["data"]] == ["claude-qwen-27b", "claude-other-model"]
    assert body["data"][0]["max_input_tokens"] == 33000
    assert body["data"][0]["display_name"] == "Qwen 27B"


@pytest.mark.asyncio
async def test_list_models_anthropic_empty_listing(monkeypatch):
    """A key without models gets an empty Anthropic envelope, not an error."""
    body = await _list_anthropic_body(monkeypatch, [], DummyRegistry({}))
    assert body == {"data": [], "first_id": None, "last_id": None, "has_more": False}
