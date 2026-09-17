"""Tests for the ``new_model_ids`` result of the cloud/Azure discovery syncs.

The webservice refreshes prices and capabilities for every announced ID, so
the list must cover every model that receives a NEW link to the provider in
this pass — including model rows that already existed globally, whose
per-provider price rows are created only on first link.

Statements are identified by their position in the call sequence and their
bind params (conftest may stub sqlalchemy, so the SQL text itself is not
asserted — same approach as test_logosnode_capability_sync.py).
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


def test_sync_azure_deployments_reports_ids_for_newly_inserted_models():
    """A brand-new model row yields its ID in new_model_ids (regression: the
    ID list was never declared in this method, so the return raised NameError
    after the pass had already committed)."""
    side_effects = [
        MagicMock(fetchall=MagicMock(return_value=[])),  # existing links
        MagicMock(fetchone=MagicMock(return_value=None)),  # SELECT id m1
        MagicMock(fetchone=MagicMock(return_value=MockRow({"id": 42}))),  # INSERT models
        MagicMock(),  # link upsert
        MagicMock(),  # queue discovery notification
    ]
    db, session = _db_with_execute_side_effects(side_effects)

    result = db.sync_azure_deployments(provider_id=1, deployments=[{"model_name": "m1", "endpoint": "https://e/m1"}])

    assert result == {
        "new_models": ["m1"],
        "new_model_ids": [42],
        "changed": True,
    }
    # The notification is queued in the same transaction as the link, so it
    # is retried on a later pass if the webservice was down.
    assert session.execute.call_args_list[-1].args[1] == {"id": 42}


def test_sync_azure_deployments_reports_ids_for_existing_model_new_link():
    """A model row that already exists globally but gets a fresh link to this
    provider must be announced too — otherwise its per-provider price rows
    stay missing until the daily refresh."""
    side_effects = [
        MagicMock(fetchall=MagicMock(return_value=[])),  # existing links
        MagicMock(fetchone=MagicMock(return_value=MockRow({"id": 7}))),  # SELECT id m2
        MagicMock(),  # link upsert
        MagicMock(),  # queue discovery notification
    ]
    db, _ = _db_with_execute_side_effects(side_effects)

    result = db.sync_azure_deployments(provider_id=1, deployments=[{"model_name": "m2", "endpoint": "https://e/m2"}])

    assert result == {
        "new_models": [],
        "new_model_ids": [7],
        "changed": True,
    }


def test_sync_cloud_models_reports_ids_for_existing_model_new_link():
    """Same link semantics as the Azure sync: an existing global model row
    linked for the first time to this provider is announced by ID."""
    side_effects = [
        MagicMock(fetchall=MagicMock(return_value=[])),  # existing links
        MagicMock(fetchone=MagicMock(return_value=MockRow({"id": 9}))),  # SELECT id m3
        MagicMock(),  # link insert
        MagicMock(),  # queue discovery notification
    ]
    db, _ = _db_with_execute_side_effects(side_effects)

    result = db.sync_cloud_models(provider_id=1, model_names=["m3"])

    assert result == {
        "new_models": [],
        "new_model_ids": [9],
        "changed": True,
    }
