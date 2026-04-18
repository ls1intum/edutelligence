from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from logos.dbutils.dbmanager import DBManager

def _make_db_with_execute(row):
    db = DBManager.__new__(DBManager)
    session = MagicMock()
    fetchone = MagicMock(return_value=row)
    session.execute.return_value = MagicMock(fetchone=fetchone)
    db.session = session
    return db

def test_get_user_by_logos_key_returns_user_dict():
    row = SimpleNamespace(
        _mapping={
            "id": 1,
            "username": "alice",
            "email": "alice@example.com",
            "role": "app_developer",
            "teams": [{"id": 10, "name": "Artemis"}],
        }
    )
    db = _make_db_with_execute(row)

    result = db.get_user_by_logos_key("test-key")

    assert result["username"] == "alice"
    assert result["role"] == "app_developer"
    assert result["teams"] == [{"id": 10, "name": "Artemis"}]

def test_get_user_by_logos_key_returns_none_for_service_key():
    db = _make_db_with_execute(None)

    result = db.get_user_by_logos_key("service-key")

    assert result is None

def _make_db_with_update(returning_row):
    db = DBManager.__new__(DBManager)
    session = MagicMock()
    session.execute.return_value = MagicMock(
        fetchone=MagicMock(return_value=returning_row)
    )
    db.session = session
    return db

def test_set_user_role_success():
    db = _make_db_with_update(SimpleNamespace(id=1))

    result, status = db.set_user_role(1, "app_admin")

    assert status == 200
    assert result == {"result": "Role updated"}
    db.session.commit.assert_called_once()

def test_set_user_role_not_found():
    db = _make_db_with_update(None)

    result, status = db.set_user_role(99, "app_admin")

    assert status == 404
    assert "error" in result

def test_set_user_role_invalid_role():
    db = DBManager.__new__(DBManager)
    db.session = MagicMock()

    result, status = db.set_user_role(1, "superuser")

    assert status == 400
    assert "error" in result
    db.session.execute.assert_not_called()