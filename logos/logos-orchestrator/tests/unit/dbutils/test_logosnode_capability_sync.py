"""Tests for DBManager.sync_logosnode_capabilities (worker capabilities -> DB).

Statements are identified by their position in the call sequence and their
bind params (conftest may stub sqlalchemy, so the SQL text itself is not
asserted — same approach as test_api_key_queries.py).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from logos import DBManager


class MockRow:
    def __init__(self, data):
        self._data_dict = data

    def __getattr__(self, name):
        if name in self._data_dict:
            return self._data_dict[name]
        raise AttributeError(f"MockRow has no attribute '{name}'")


def _db_with_execute_side_effects(side_effects):
    db = DBManager.__new__(DBManager)
    session = MagicMock()
    session.execute.side_effect = side_effects
    db.session = session
    return db, session


def _bind_params(session):
    return [call.args[1] for call in session.execute.call_args_list]


def test_sync_empty_capabilities_prunes_existing_link():
    """model_names=[] must delete the provider's stale model_provider links,
    touch no models rows, and return no newly inserted names."""
    existing = MockRow({"model_id": 10, "name": "model-a"})
    side_effects = [
        MagicMock(),  # logosnode_provider_keys upsert
        MagicMock(fetchall=MagicMock(return_value=[existing])),  # existing links
        MagicMock(),  # DELETE stale link
    ]
    db, session = _db_with_execute_side_effects(side_effects)

    result = db.sync_logosnode_capabilities(provider_id=1, model_names=[])

    assert result == []
    params = _bind_params(session)
    assert params == [
        {"pid": 1},  # provider-keys upsert
        {"pid": 1},  # select existing links
        {"pid": 1, "mid": 10},  # delete model-a's link
    ]
    # No models row lookups or inserts: only 3 statements were executed
    assert len(params) == 3
    session.commit.assert_called_once()


def test_sync_replaces_stale_link_and_adds_missing_model():
    """Existing links for [A, B] + announced [B, C]: A's link is deleted, B's
    kept, C gets a new models row (returned) and a model_provider link."""
    existing = [
        MockRow({"model_id": 10, "name": "model-a"}),
        MockRow({"model_id": 11, "name": "model-b"}),
    ]
    side_effects = [
        MagicMock(),  # logosnode_provider_keys upsert
        MagicMock(fetchall=MagicMock(return_value=existing)),  # existing links
        MagicMock(),  # DELETE stale link (model-a)
        MagicMock(fetchone=MagicMock(return_value=None)),  # model-c not in models yet
        MagicMock(fetchone=MagicMock(return_value=MockRow({"id": 12}))),  # INSERT models RETURNING id
        MagicMock(),  # model_provider upsert for model-c
    ]
    db, session = _db_with_execute_side_effects(side_effects)

    result = db.sync_logosnode_capabilities(provider_id=1, model_names=["model-b", "model-c"])

    assert result == ["model-c"]
    params = _bind_params(session)
    assert params == [
        {"pid": 1},  # provider-keys upsert
        {"pid": 1},  # select existing links
        {"pid": 1, "mid": 10},  # delete model-a's link (stale)
        {"name": "model-c"},  # models lookup
        {"name": "model-c"},  # models insert (new row, id 12)
        {"pid": 1, "mid": 12},  # model_provider upsert for model-c
    ]
    # model-b's link (mid 11) is never touched
    assert not any(p.get("mid") == 11 for p in params)
    session.commit.assert_called_once()


def test_sync_empty_capabilities_without_existing_links():
    """model_names=[] with no pre-existing links: no crash, provider-keys row
    is still created (upsert issued), nothing deleted."""
    side_effects = [
        MagicMock(),  # logosnode_provider_keys upsert
        MagicMock(fetchall=MagicMock(return_value=[])),  # no existing links
    ]
    db, session = _db_with_execute_side_effects(side_effects)

    result = db.sync_logosnode_capabilities(provider_id=7, model_names=[])

    assert result == []
    params = _bind_params(session)
    assert params == [
        {"pid": 7},  # provider-keys upsert
        {"pid": 7},  # select existing links (none)
    ]
    # No deletes, no models lookups or inserts
    assert not any("mid" in p for p in params)
    session.commit.assert_called_once()
