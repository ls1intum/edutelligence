from __future__ import annotations

from unittest.mock import MagicMock

from logos.dbutils.dbmanager import DBManager


class MockRow:
    def __init__(self, data):
        self._data_dict = data
        self._data_list = list(data.values())
        self._mapping = data

    def __getattr__(self, name):
        if name in self._data_dict:
            return self._data_dict[name]
        raise AttributeError(f"MockRow has no attribute '{name}'")

    def __getitem__(self, index):
        return self._data_list[index]

    def __iter__(self):
        return iter(self._data_list)


def _db_fetchone(row_data):
    db = DBManager.__new__(DBManager)
    session = MagicMock()
    row = MockRow(row_data) if row_data else None
    session.execute.return_value = MagicMock(fetchone=MagicMock(return_value=row))
    db.session = session
    return db


def _db_fetchall(rows_data):
    db = DBManager.__new__(DBManager)
    session = MagicMock()
    rows = [MockRow(r) for r in rows_data]
    session.execute.return_value = MagicMock(fetchall=MagicMock(return_value=rows))
    db.session = session
    return db


def test_get_api_key_by_value_found():
    data = {
        "id": 1,
        "key_value": "lg-test-abc",
        "name": "My Key",
        "key_type": "developer",
        "team_id": 2,
        "user_id": 3,
        "environment": None,
        "log": "BILLING",
        "settings": {},
        "is_active": True,
        "default_priority": 1,
    }
    db = _db_fetchone(data)
    result = db.get_api_key_by_value("lg-test-abc")
    assert result is not None
    assert result["id"] == 1


def test_create_api_key_returns_dict():
    db = DBManager.__new__(DBManager)
    session = MagicMock()

    team_row = MockRow({"name": "testteam"})
    key_row = MockRow({"id": 5, "key_value": "lg-test-xyz"})

    session.execute.side_effect = [
        MagicMock(fetchone=MagicMock(return_value=team_row)),
        MagicMock(fetchone=MagicMock(return_value=key_row)),
    ]
    db.session = session

    result = db.create_api_key(
        name="Test Key",
        key_type="application",
        team_id=1,
        user_id=None,
        environment="prod",
        log="BILLING",
        settings={},
    )
    assert result["id"] == 5
    assert result["key_value"] == "lg-test-xyz"


def test_get_team_budget_usage_returns_int():
    db = _db_fetchone({"total": 12345})
    assert db.get_team_budget_usage(1, "2026-05-01") == 12345


def test_deactivate_api_key_commits():
    db = DBManager.__new__(DBManager)
    session = MagicMock()
    db.session = session
    db.deactivate_api_key(api_key_id=3)
    assert session.commit.called


def _db_execute_many(return_values):
    db = DBManager.__new__(DBManager)
    session = MagicMock()
    session.execute.side_effect = [
        MagicMock(fetchall=MagicMock(return_value=[MockRow(r) for r in rv])) for rv in return_values
    ]
    db.session = session
    return db
