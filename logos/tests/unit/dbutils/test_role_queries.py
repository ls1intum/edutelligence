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
            "username": "hen",
            "email": "hen@example.com",
            "role": "app_developer",
            "teams": [{"id": 10, "name": "Maiß"}],
        }
    )
    db = _make_db_with_execute(row)

    result = db.get_user_by_logos_key("test-key")

    assert result["username"] == "hen"
    assert result["role"] == "app_developer"
    assert result["teams"] == [{"id": 10, "name": "Maiß"}]


def test_get_user_by_logos_key_returns_none_for_invalid_key():
    db = _make_db_with_execute(None)

    result = db.get_user_by_logos_key("service-key")

    assert result is None


def _make_db_with_update(returning_row):
    db = DBManager.__new__(DBManager)
    session = MagicMock()
    session.execute.return_value = MagicMock(fetchone=MagicMock(return_value=returning_row))
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


def _make_db_with_fetchall(rows):
    db = DBManager.__new__(DBManager)
    session = MagicMock()
    session.execute.return_value = MagicMock(fetchall=MagicMock(return_value=rows))
    db.session = session
    return db


def test_list_users_returns_all_users():
    row = SimpleNamespace(
        _mapping={
            "id": 1,
            "username": "hen",
            "prename": "Henriette",
            "name": "Maiß",
            "email": "hen@example.com",
            "role": "app_developer",
            "teams": [{"id": 1, "name": "Maiß"}],
        }
    )
    db = _make_db_with_fetchall([row])
    result = db.list_users()
    assert len(result) == 1
    assert result[0]["username"] == "hen"
    assert result[0]["prename"] == "Henriette"
    assert result[0]["teams"] == [{"id": 1, "name": "Maiß"}]


def test_list_users_returns_empty_list():
    db = _make_db_with_fetchall([])
    result = db.list_users()
    assert result == []


def _make_create_db(existing_email=None, taken_usernames=None):
    db = DBManager.__new__(DBManager)
    session = MagicMock()
    taken = set(taken_usernames or [])

    def fake_execute(sql, params=None):
        result = MagicMock()
        p = params or {}
        if "email" in p and existing_email and p["email"].lower() == existing_email.lower():
            result.fetchone.return_value = (1,)
        elif "username" in p and p["username"] in taken:
            result.fetchone.return_value = (1,)
        else:
            result.fetchone.return_value = None
        return result

    session.execute = fake_execute
    db.session = session

    insert_log = []
    next_id = [10]

    def fake_insert(table, data):
        insert_log.append((table, data))
        result = next_id[0]
        next_id[0] += 1
        return result

    db.insert = fake_insert
    db._insert_log = insert_log
    return db


def test_create_user_returns_user_dict_and_logos_key():
    db = _make_create_db()

    user_dict, logos_key, status = db.create_user("Henriette", "Maiß", "hen@example.com", "app_developer")

    assert status == 200
    assert user_dict["id"] == 10
    assert user_dict["username"] == "hmaiß"
    assert user_dict["prename"] == "Henriette"
    assert user_dict["name"] == "Maiß"
    assert user_dict["email"] == "hen@example.com"
    assert user_dict["role"] == "app_developer"
    if isinstance(logos_key, str):
        assert logos_key.startswith("lg-")

    tables = [t for t, _ in db._insert_log]
    assert "users" in tables


def test_create_user_returns_409_on_duplicate_email():
    db = _make_create_db(existing_email="hen@example.com")

    user_dict, logos_key, status = db.create_user("Henriette", "Maiß", "hen@example.com", "app_developer")

    assert status == 409
    assert "email" in user_dict["error"].lower()
    assert logos_key is None
    assert db._insert_log == []


def test_delete_user_success():
    db = DBManager.__new__(DBManager)
    db.session = MagicMock()

    mock_result = MagicMock()
    mock_result.rowcount = 1
    db.session.execute.return_value = mock_result

    result, status = db.delete_user(1)

    assert status == 200
    assert result == {"result": "User deleted successfully"}
    db.session.commit.assert_called_once()


def test_delete_user_not_found():
    db = DBManager.__new__(DBManager)
    db.session = MagicMock()

    mock_result = MagicMock()
    mock_result.rowcount = 0
    db.session.execute.return_value = mock_result

    result, status = db.delete_user(99)

    assert status == 404
    assert result == {"error": "User not found"}
