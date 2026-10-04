"""The orphan sweep must touch exactly the rows a dead process left behind.

Too wide and it rewrites finished requests' outcomes; too narrow and the
"running forever" rows it exists to clear survive it.

``conftest`` stubs ``sqlalchemy.text`` to a no-op that returns ``None``, so
the statement has to be captured through an identity stand-in to be readable.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from logos import DBManager
from logos.dbutils import dbmanager as dbmanager_module


@pytest.fixture(autouse=True)
def _readable_sql(monkeypatch):
    """Make ``text(...)`` hand back the raw SQL so it can be asserted on."""
    monkeypatch.setattr(dbmanager_module, "text", lambda statement: statement)


def _db(rowcount: int = 0):
    db = DBManager.__new__(DBManager)
    session = MagicMock()
    session.execute.return_value = MagicMock(rowcount=rowcount)
    db.session = session
    return db


def _executed_sql(db) -> str:
    return " ".join(str(db.session.execute.call_args[0][0]).split())


def test_only_rows_with_no_outcome_and_no_response_are_touched():
    db = _db()
    db.close_orphaned_request_logs("restarted")
    sql = _executed_sql(db)
    assert "WHERE result_status IS NULL" in sql
    assert "AND timestamp_response IS NULL" in sql


def test_the_row_is_given_a_terminal_state_and_a_response_time():
    db = _db()
    db.close_orphaned_request_logs("restarted")
    sql = _executed_sql(db)
    assert "result_status = 'error'" in sql
    assert "timestamp_response = NOW()" in sql


def test_an_existing_error_message_is_preserved():
    """A request that recorded why it failed but never got its terminal
    status must keep the more specific reason."""
    db = _db()
    db.close_orphaned_request_logs("restarted")
    assert "COALESCE(error_message, :error_message)" in _executed_sql(db)


def test_the_message_is_passed_as_a_bound_parameter():
    db = _db()
    db.close_orphaned_request_logs("restarted while in flight")
    params = db.session.execute.call_args[0][1]
    assert params == {"error_message": "restarted while in flight"}


def test_the_number_of_closed_rows_is_returned():
    db = _db(rowcount=5)
    assert db.close_orphaned_request_logs("restarted") == 5


def test_a_driver_without_a_rowcount_reports_zero():
    db = DBManager.__new__(DBManager)
    session = MagicMock()
    session.execute.return_value = MagicMock(rowcount=None)
    db.session = session
    assert db.close_orphaned_request_logs("restarted") == 0


def test_the_sweep_is_committed():
    db = _db(rowcount=1)
    db.close_orphaned_request_logs("restarted")
    db.session.commit.assert_called_once()
