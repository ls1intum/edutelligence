"""Unit tests for DBManager.lookup_workflow_tag (workflow-tag request attribution)."""

from __future__ import annotations

from unittest.mock import MagicMock

from logos import DBManager


class MockRow:
    def __init__(self, data):
        self._data = data or {}
        self._mapping = self._data


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


def test_lookup_prefers_step_match_and_scopes_by_team():
    rows = [{"workflow_id": 5, "step_id": 9, "sla": "ux-critical", "team_id": 7}]
    db, calls = _make_db(rows)
    info = db.lookup_workflow_tag("checkout", team_id=7)

    assert info == {"workflow_id": 5, "step_id": 9, "sla": "ux-critical", "team_id": 7}
    assert len(calls) == 1
    sql, params = calls[0]
    assert "ai_workflow_steps" in sql
    # A shared tag must not let another team's row hide the caller's own match.
    assert "a.team_id = :team_id" in sql
    assert params["team_id"] == 7


def test_lookup_falls_back_to_workflow_tag_without_sla():
    rows = [
        None,
        {"workflow_id": 3, "step_id": None, "sla": None, "team_id": 7},
    ]
    db, calls = _make_db(rows)
    info = db.lookup_workflow_tag("checkout", team_id=7)

    assert info == {"workflow_id": 3, "step_id": None, "sla": None, "team_id": 7}
    assert len(calls) == 2
    step_sql, _ = calls[0]
    workflow_sql, _ = calls[1]
    assert "ai_workflow_steps" in step_sql
    assert "ai_workflows" in workflow_sql
    assert "a.team_id = :team_id" in workflow_sql


def test_lookup_returns_none_when_no_match():
    db, calls = _make_db([None, None])
    assert db.lookup_workflow_tag("missing", team_id=7) is None
    assert len(calls) == 2


def test_lookup_without_team_id_applies_no_team_filter():
    db, calls = _make_db([None, None])
    assert db.lookup_workflow_tag("checkout") is None
    sql, params = calls[0]
    assert "a.team_id = :team_id" not in sql
    assert params["team_id"] is None
