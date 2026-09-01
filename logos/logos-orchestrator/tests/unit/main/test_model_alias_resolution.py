"""Case-insensitive model-name matching and stored alias (alt tag) resolution.

Alt tags let applications pin a logical name such as ``local-most-powerful``
that can later be re-pointed at a different model; capitalization of model
names and aliases is ignored when matching.
"""

import json
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
    """Minimal DBManager stub used via monkeypatch.

    ``get_model_for_api_key`` mirrors the real SQL: an exact-name lookup,
    with alias and case-insensitive resolution happening in the
    ``_resolve_requested_model_name`` fallback the endpoints use after a
    miss.
    """

    def __init__(self, models=None):
        self._models = models if models is not None else []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get_models_for_api_key(self, _api_key_id: int):
        return self._models

    def get_model_for_api_key(self, _api_key_id: int, model_name: str):
        return next((m for m in self._models if m["name"] == model_name), None)


# ---------------------------------------------------------------------------
# _resolve_requested_model_name — direct unit tests
# ---------------------------------------------------------------------------


def test_resolver_matches_canonical_name_case_insensitively():
    models = [{"name": "GPT-4", "aliases": []}]

    assert main._resolve_requested_model_name("GPT-4", models) == "GPT-4"
    assert main._resolve_requested_model_name("gpt-4", models) == "GPT-4"
    assert main._resolve_requested_model_name("Gpt-4", models) == "GPT-4"


def test_resolver_matches_planner_alias_case_insensitively():
    models = [{"name": "Qwen/Qwen2.5-0.5B", "aliases": []}]

    assert main._resolve_requested_model_name("Qwen_Qwen2.5-0.5B", models) == "Qwen/Qwen2.5-0.5B"
    assert main._resolve_requested_model_name("qwen_qwen2.5-0.5b", models) == "Qwen/Qwen2.5-0.5B"
    assert main._resolve_requested_model_name("planner-Qwen_Qwen2.5-0.5B", models) == "Qwen/Qwen2.5-0.5B"


def test_resolver_matches_stored_alias_case_insensitively():
    models = [{"name": "llama-3.1-70b", "aliases": ["local-most-powerful"]}]

    assert main._resolve_requested_model_name("local-most-powerful", models) == "llama-3.1-70b"
    assert main._resolve_requested_model_name("Local-Most-Powerful", models) == "llama-3.1-70b"


def test_resolver_prefers_canonical_name_over_alias():
    # The name itself wins over another model's alias with the same spelling.
    models = [
        {"name": "fast", "aliases": []},
        {"name": "other-model", "aliases": ["Fast"]},
    ]

    assert main._resolve_requested_model_name("fast", models) == "fast"


def test_resolver_rejects_an_ambiguous_alias():
    # The same alias (up to case) on two models is ambiguous, not a match.
    models = [
        {"name": "model-a", "aliases": ["local-most-powerful"]},
        {"name": "model-b", "aliases": ["LOCAL-MOST-POWERFUL"]},
    ]

    assert main._resolve_requested_model_name("local-most-powerful", models) is None


def test_resolver_prefers_stored_alias_over_planner_alias():
    # A stored alias is an explicit assignment and must win over the
    # planner-sanitized form of a model whose name happens to normalize to
    # the same string — previously both landed in one match set and the
    # request 404ed instead of resolving the stored alias.
    models = [
        {"name": "acme/foo", "aliases": []},
        {"name": "other-model", "aliases": ["acme_foo"]},
    ]

    assert main._resolve_requested_model_name("acme_foo", models) == "other-model"


def test_resolver_ambiguous_stored_alias_does_not_fall_through_to_planner():
    # Several stored aliases match: that is ambiguous even though a planner
    # alias of a third model would also match — stored names are evaluated
    # as a level, not merged into one pool.
    models = [
        {"name": "model-a", "aliases": ["acme_foo"]},
        {"name": "model-b", "aliases": ["ACME_FOO"]},
        {"name": "Acme Foo", "aliases": []},
    ]

    assert main._resolve_requested_model_name("acme_foo", models) is None


def test_resolver_rejects_duplicate_normalized_model_names():
    # The schema does not enforce case-insensitive uniqueness of model names,
    # so two models differing only in case make a canonical request
    # ambiguous — picking the first row would be arbitrary.
    models = [
        {"name": "Foo", "aliases": []},
        {"name": "FOO", "aliases": []},
    ]

    assert main._resolve_requested_model_name("foo", models) is None
    assert main._resolve_requested_model_name("Foo", models) is None
    assert main._resolve_requested_model_name("foo", [{"name": "Foo", "aliases": []}]) == "Foo"


def test_resolver_returns_none_for_unknown_or_empty_names():
    models = [{"name": "gpt-4", "aliases": ["fast"]}]

    assert main._resolve_requested_model_name("nope", models) is None
    assert main._resolve_requested_model_name("", models) is None
    assert main._resolve_requested_model_name(None, models) is None
    assert main._resolve_requested_model_name("   ", models) is None


def test_resolver_tolerates_entries_without_an_aliases_key():
    models = [{"name": "gpt-4"}, {"name": "other", "aliases": None}]

    assert main._resolve_requested_model_name("GPT-4", models) == "gpt-4"


# ---------------------------------------------------------------------------
# GET /v1/models — aliases are advertised as model ids
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_models_includes_stored_aliases(monkeypatch):
    """Each alias of an accessible model appears right after its model."""
    fake_models = [
        {"id": 1, "name": "llama-3.1-70b", "description": None, "aliases": ["local-most-powerful", "local-fast"]},
        {"id": 2, "name": "gpt-4o", "description": None, "aliases": []},
    ]

    monkeypatch.setattr(user_facing_mod, "DBManager", lambda: DummyDB(models=fake_models))

    with patch("logos.routers.user_facing.authenticate_api_key") as mock_auth:
        mock_auth.return_value = MagicMock(api_key_id=1, key_value="test-key")
        response = await user_facing_mod.list_models(_make_request())

    ids = [entry["id"] for entry in json.loads(response.body)["data"]]
    assert ids == ["llama-3.1-70b", "local-most-powerful", "local-fast", "gpt-4o"]


@pytest.mark.asyncio
async def test_list_models_aliased_entry_carries_the_model_context(monkeypatch):
    """An alias id reports the context window of the lanes serving its model."""
    models = [
        {"id": 1, "name": "qwen-14b", "description": None, "aliases": ["local-big"]},
    ]
    registry = MagicMock()
    registry.active_provider_ids = lambda: [7]
    registry.peek_runtime_snapshot = lambda pid: {
        "runtime": {
            "lanes": [
                {"model": "qwen-14b", "vllm": True, "context_length": 4096, "backend_metrics": {"max_model_len": 40960}}
            ],
            "model_profiles": {},
        }
    }

    monkeypatch.setattr(user_facing_mod, "DBManager", lambda: DummyDB(models=models))
    monkeypatch.setattr(main, "_logosnode_registry", registry)

    with patch("logos.routers.user_facing.authenticate_api_key") as mock_auth:
        mock_auth.return_value = MagicMock(api_key_id=1, key_value="test-key")
        response = await user_facing_mod.list_models(_make_request())

    entries = {entry["id"]: entry for entry in json.loads(response.body)["data"]}
    assert entries["local-big"]["max_model_len"] == 40960


# ---------------------------------------------------------------------------
# GET /v1/models/{model_id} — retrieve by alias and case variant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retrieve_model_by_stored_alias(monkeypatch):
    fake_models = [
        {"id": 1, "name": "llama-3.1-70b", "description": None, "aliases": ["local-most-powerful"]},
    ]
    monkeypatch.setattr(user_facing_mod, "DBManager", lambda: DummyDB(models=fake_models))

    with patch("logos.routers.user_facing.authenticate_api_key") as mock_auth:
        mock_auth.return_value = MagicMock(api_key_id=1, key_value="test-key")
        response = await user_facing_mod.retrieve_model("local-most-powerful", _make_request())

    data = json.loads(response.body)
    assert data["id"] == "llama-3.1-70b"


@pytest.mark.asyncio
async def test_retrieve_model_by_case_variant(monkeypatch):
    fake_models = [
        {"id": 1, "name": "Qwen/Qwen2.5-0.5B-Instruct", "description": None, "aliases": []},
    ]
    monkeypatch.setattr(user_facing_mod, "DBManager", lambda: DummyDB(models=fake_models))

    with patch("logos.routers.user_facing.authenticate_api_key") as mock_auth:
        mock_auth.return_value = MagicMock(api_key_id=1, key_value="test-key")
        response = await user_facing_mod.retrieve_model("qwen/qwen2.5-0.5b-instruct", _make_request())

    data = json.loads(response.body)
    assert data["id"] == "Qwen/Qwen2.5-0.5B-Instruct"


@pytest.mark.asyncio
async def test_retrieve_model_alias_of_inaccessible_model_is_denied(monkeypatch):
    """An alias only resolves if the key may access the model behind it."""
    fake_models = [
        {"id": 1, "name": "gpt-4o", "description": None, "aliases": []},
    ]
    monkeypatch.setattr(user_facing_mod, "DBManager", lambda: DummyDB(models=fake_models))

    with patch("logos.routers.user_facing.authenticate_api_key") as mock_auth:
        mock_auth.return_value = MagicMock(api_key_id=1, key_value="test-key")
        with pytest.raises(HTTPException) as exc:
            await user_facing_mod.retrieve_model("local-most-powerful", _make_request())

    assert exc.value.status_code == 404
