"""Unit tests for DBManager.lookup_workflow_tag (workflow-tag request attribution).

The unit-test environment stubs ``sqlalchemy.text`` to a no-op that returns
``None``, so the statement has to be captured through an identity stand-in on
``dbmanager`` to be readable (same idiom as the other dbutils query tests).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from logos import DBManager
from logos.dbutils import dbmanager


class MockRow:
    def __init__(self, data):
        self._data = data or {}
        self._mapping = self._data


@pytest.fixture(autouse=True)
def _identity_text(monkeypatch):
    """Stand ``text`` back in as the identity so session.execute receives the raw SQL string."""
    monkeypatch.setattr(dbmanager, "text", lambda sql: sql)


def _make_db(rows):
    """DBManager whose session.execute returns ``rows`` in order, recording calls."""
    db = DBManager.__new__(DBManager)
    session = MagicMock()
    calls = []

    def fake_execute(sql, params=None):
        calls.append((str(sql), dict(params or {})))
        row = rows.pop(0) if rows else None
        result = MagicMock()
        result.fetchone.return_value = MockRow(row) if row is not None else None
        return result

    session.execute = fake_execute
    db.session = session
    return db, calls


def test_lookup_requires_team_id():
    db, calls = _make_db([None])
    assert db.lookup_workflow_tag("checkout", None) is None
    assert db.lookup_workflow_tag("", 7) is None
    assert calls == []


def test_lookup_scopes_by_team_and_latest_succeeded_analysis():
    rows = [{"workflow_id": 5, "step_id": 9, "sla": "ux-critical"}]
    db, calls = _make_db(rows)
    info = db.lookup_workflow_tag("checkout", 7)

    assert info == {"workflow_id": 5, "step_id": 9, "sla": "ux-critical"}
    assert len(calls) == 1
    sql, params = calls[0]
    assert "ai_workflow_steps" in sql
    # A guessed tag must not match another team's workflow.
    assert "a.team_id = :team_id" in sql
    assert params["team_id"] == 7
    # Only the repository's latest succeeded analysis may match, so a
    # superseded analysis cannot resurrect a renamed or removed tag.
    assert "latest.status = 'succeeded'" in sql
    assert "ORDER BY w.id DESC, s.id" in sql


def test_lookup_falls_back_to_workflow_tag_without_sla():
    rows = [
        None,
        {"workflow_id": 3, "step_id": None, "sla": None},
    ]
    db, calls = _make_db(rows)
    info = db.lookup_workflow_tag("checkout", 7)

    assert info == {"workflow_id": 3, "step_id": None, "sla": None}
    assert len(calls) == 2
    step_sql, _ = calls[0]
    workflow_sql, _ = calls[1]
    assert "ai_workflow_steps" in step_sql
    assert "ai_workflows" in workflow_sql
    assert "a.team_id = :team_id" in workflow_sql
    assert "ORDER BY w.id DESC" in workflow_sql


def test_lookup_returns_none_when_no_match():
    db, calls = _make_db([None, None])
    assert db.lookup_workflow_tag("missing", 7) is None
    assert len(calls) == 2
