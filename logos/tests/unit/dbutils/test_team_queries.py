from __future__ import annotations
from types import SimpleNamespace
from unittest.mock import MagicMock
from logos.dbutils.dbmanager import DBManager

def _make_db_with_fetchone(row):
    db = DBManager.__new__(DBManager)
    session = MagicMock()
    session.execute.return_value = MagicMock(fetchone=MagicMock(return_value=row))
    db.session = session
    return db

def _make_db_with_fetchall(rows):
    db = DBManager.__new__(DBManager)
    session = MagicMock()
    session.execute.return_value = MagicMock(fetchall=MagicMock(return_value=rows))
    db.session = session
    return db

def test_list_teams_returns_all():
    row = SimpleNamespace(_mapping={
        "id": 1, "name": "Maiß",
        "owners": [{"id": 2, "username": "hen"}],
        "member_count": 3,
    })
    db = _make_db_with_fetchall([row])
    result = db.list_teams()
    assert len(result) == 1
    assert result[0]["id"] == 1
    assert result[0]["member_count"] == 3

def test_list_teams_filtered_by_owner():
    row = SimpleNamespace(_mapping={
        "id": 1, "name": "Maiß",
        "owners": [{"id": 2, "username": "hen"}],
        "member_count": 1,
    })
    db = _make_db_with_fetchall([row])
    result = db.list_teams(owner_user_id=2)
    assert len(result) == 1
    assert result[0]["name"] == "Maiß"

def test_create_team_inserts_team_and_owners():
    db = DBManager.__new__(DBManager)
    session = MagicMock()
    session.execute.return_value = MagicMock(
        fetchone=MagicMock(return_value=SimpleNamespace(id=5))
    )
    db.session = session
    team_id, status = db.create_team("Alpha", [1, 2])
    assert status == 200
    assert team_id == 5
    assert session.execute.call_count == 3
    session.commit.assert_called_once()

def test_create_team_no_owners():
    db = DBManager.__new__(DBManager)
    session = MagicMock()
    session.execute.return_value = MagicMock(
        fetchone=MagicMock(return_value=SimpleNamespace(id=7))
    )
    db.session = session
    team_id, status = db.create_team("Maiß", [])
    assert status == 200
    assert team_id == 7
    assert session.execute.call_count == 1

def test_get_team_returns_team():
    row = SimpleNamespace(_mapping={"id": 1, "name": "Maiß"})
    db = _make_db_with_fetchone(row)
    result = db.get_team(1)
    assert result == {"id": 1, "name": "Maiß"}

def test_get_team_returns_none_when_missing():
    db = _make_db_with_fetchone(None)
    assert db.get_team(99) is None

def test_delete_team_success():
    db = _make_db_with_fetchone(SimpleNamespace(id=1))
    result, status = db.delete_team(1)
    assert status == 200
    assert result == {"result": "Team deleted"}
    db.session.commit.assert_called_once()

def test_delete_team_not_found():
    db = _make_db_with_fetchone(None)
    result, status = db.delete_team(99)
    assert status == 404
    assert "error" in result

def test_add_team_member_success():
    db = DBManager.__new__(DBManager)
    session = MagicMock()
    db.session = session
    result, status = db.add_team_member(1, 5)
    assert status == 200
    assert result == {"result": "Member added"}
    session.commit.assert_called_once()

def test_add_team_member_as_owner():
    db = DBManager.__new__(DBManager)
    session = MagicMock()
    db.session = session
    result, status = db.add_team_member(1, 5, is_owner=True)
    assert status == 200
    call_args = session.execute.call_args
    assert call_args[0][1]["is_owner"] is True
    session.commit.assert_called_once()

def test_remove_team_member_success():
    db = _make_db_with_fetchone(SimpleNamespace(user_id=5))
    result, status = db.remove_team_member(1, 5)
    assert status == 200
    assert result == {"result": "Member removed"}
    db.session.commit.assert_called_once()

def test_remove_team_member_not_found():
    db = _make_db_with_fetchone(None)
    result, status = db.remove_team_member(1, 99)
    assert status == 404
    assert "error" in result