"""resolve_proxy_model : one permission-scoped query + the shared resolver.

Proxy mode used to call get_models_info (up to two queries) and re-implement
name matching in a Python loop. resolve_proxy_model collapses that into a
single query and delegates matching to _resolve_requested_model_name, so the
alias/case/replica semantics cannot drift from the user-facing endpoints.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from logos import DBManager


def _db(rows):
    db = DBManager.__new__(DBManager)
    db.session = MagicMock()
    db.session.execute.return_value.fetchall.return_value = rows
    return db


def _row(model_id: int, name: str, aliases: str | None = None):
    return SimpleNamespace(id=model_id, name=name, aliases=aliases)


def test_exact_name_match_returns_id_and_canonical_name():
    db = _db([_row(27, "gemma2:2b")])

    assert db.resolve_proxy_model(7, "gemma2:2b") == (27, "gemma2:2b")


def test_match_is_case_insensitive():
    db = _db([_row(27, "GPT-4")])

    assert db.resolve_proxy_model(7, "gpt-4") == (27, "GPT-4")


def test_planner_sanitized_alias_resolves():
    db = _db([_row(32, "Qwen/Qwen2.5-0.5B-Instruct")])

    assert db.resolve_proxy_model(7, "Qwen_Qwen2.5-0.5B-Instruct") == (32, "Qwen/Qwen2.5-0.5B-Instruct")
    assert db.resolve_proxy_model(7, "planner-Qwen_Qwen2.5-0.5B-Instruct") == (32, "Qwen/Qwen2.5-0.5B-Instruct")


def test_stored_alias_resolves_to_the_model_carrying_it():
    db = _db([_row(32, "llama-3.1-70b", aliases="local-most-powerful")])

    assert db.resolve_proxy_model(7, "local-most-powerful") == (32, "llama-3.1-70b")


def test_ambiguous_stored_alias_resolves_to_none():
    db = _db(
        [
            _row(1, "llama-a", aliases="fast"),
            _row(2, "llama-b", aliases="fast"),
        ]
    )

    assert db.resolve_proxy_model(7, "fast") is None


def test_unknown_model_resolves_to_none():
    db = _db([_row(27, "gemma2:2b")])

    assert db.resolve_proxy_model(7, "nope") is None


def test_empty_permission_set_resolves_to_none():
    db = _db([])

    assert db.resolve_proxy_model(7, "gemma2:2b") is None


def test_exactly_one_query_on_the_hot_path():
    db = _db([_row(27, "gemma2:2b")])

    db.resolve_proxy_model(7, "gemma2:2b")

    assert db.session.execute.call_count == 1


def test_query_is_bound_to_the_key_id():
    # The unit-test conftest stubs sqlalchemy, so the SQL text is not
    # inspectable here; the access contract (admin bypass, LEFT JOIN users,
    # effective model/provider scopes) is exercised end-to-end by the
    # benchmark harness against a real Postgres.
    db = _db([_row(27, "gemma2:2b")])

    db.resolve_proxy_model(7, "gemma2:2b")

    args, kwargs = db.session.execute.call_args
    assert not kwargs
    assert args[1] == {"api_key_id": 7}
