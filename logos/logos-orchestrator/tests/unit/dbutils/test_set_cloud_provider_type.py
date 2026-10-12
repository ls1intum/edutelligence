"""Discovery type writes must use the locked cost-invalidation protocol.

``conftest`` stubs ``sqlalchemy.text`` to a no-op that returns ``None``, so
the statement has to be captured through an identity stand-in to be readable.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from logos import DBManager
from logos.dbutils import dbmanager as dbmanager_module


@pytest.fixture(autouse=True)
def _readable_sql(monkeypatch):
    monkeypatch.setattr(dbmanager_module, "text", lambda statement: statement)


def test_set_cloud_provider_type_locks_closes_invalidates_and_queues(monkeypatch):
    db = DBManager.__new__(DBManager)
    db.session = MagicMock()
    queued = []
    monkeypatch.setattr(db, "_queue_discovery_notifications", queued.extend)

    execute = db.session.execute
    execute.side_effect = [
        MagicMock(),  # advisory lock
        MagicMock(fetchone=MagicMock(return_value=SimpleNamespace(cloud_provider_type=None))),
        MagicMock(),  # close prices
        MagicMock(),  # invalidate costs
        MagicMock(),  # set type
        MagicMock(fetchall=MagicMock(return_value=[SimpleNamespace(model_id=11), SimpleNamespace(model_id=22)])),
    ]

    assert db.set_cloud_provider_type(7, "logos") == [11, 22]
    assert queued == [11, 22]
    db.session.commit.assert_called_once()

    sql_texts = [call.args[0] for call in execute.call_args_list]
    assert len(sql_texts) == 6
    assert "pg_advisory_xact_lock" in sql_texts[0]
    assert execute.call_args_list[0].args[1] == {"key": 0x50524F564944 + 7}
    assert "SELECT cloud_provider_type" in sql_texts[1]
    assert "token_prices" in sql_texts[2] and "statement_timestamp()" in sql_texts[2]
    assert "derived_cost_usd = NULL" in sql_texts[3]
    assert "cloud_provider_type = CAST" in sql_texts[4]
    assert "SELECT DISTINCT model_id" in sql_texts[5]


def test_set_cloud_provider_type_skips_when_already_set(monkeypatch):
    db = DBManager.__new__(DBManager)
    db.session = MagicMock()
    queued = []
    monkeypatch.setattr(db, "_queue_discovery_notifications", queued.extend)

    db.session.execute.side_effect = [
        MagicMock(),  # advisory lock
        MagicMock(fetchone=MagicMock(return_value=SimpleNamespace(cloud_provider_type="openai"))),
    ]

    assert db.set_cloud_provider_type(7, "logos") == []
    assert queued == []
    db.session.commit.assert_called_once()
    assert db.session.execute.call_count == 2
