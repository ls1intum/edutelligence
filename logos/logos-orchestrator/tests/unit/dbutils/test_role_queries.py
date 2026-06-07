from __future__ import annotations

from unittest.mock import MagicMock

from logos import DBManager


def _make_db_with_execute(row):
    db = DBManager.__new__(DBManager)
    session = MagicMock()
    fetchone = MagicMock(return_value=row)
    session.execute.return_value = MagicMock(fetchone=fetchone)
    db.session = session
    return db


def _make_db_with_update(returning_row):
    db = DBManager.__new__(DBManager)
    session = MagicMock()
    session.execute.return_value = MagicMock(
        fetchone=MagicMock(return_value=returning_row)
    )
    db.session = session
    return db


def _make_db_with_fetchall(rows):
    db = DBManager.__new__(DBManager)
    session = MagicMock()
    session.execute.return_value = MagicMock(fetchall=MagicMock(return_value=rows))
    db.session = session
    return db


def _make_create_db(existing_email=None, taken_usernames=None):
    db = DBManager.__new__(DBManager)
    session = MagicMock()
    taken = set(taken_usernames or [])

    def fake_execute(sql, params=None):
        result = MagicMock()
        p = params or {}
        if (
            "email" in p
            and existing_email
            and p["email"].lower() == existing_email.lower()
        ):
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
