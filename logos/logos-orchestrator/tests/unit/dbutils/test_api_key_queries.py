from __future__ import annotations

import datetime
from unittest.mock import MagicMock

from logos import DBManager


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


def test_get_usage_cost_micro_cents_returns_cloud_billing_amount():
    db = _db_fetchone({"cost_micro_cents": 4321})
    response_at = datetime.datetime(2026, 8, 17, 20, 21, 52, tzinfo=datetime.timezone.utc)

    result = db.get_usage_cost_micro_cents(
        model_id=7,
        provider_id=9,
        usage={"prompt_tokens": 12, "completion_tokens": 3, "ignored": -1},
        response_at=response_at,
    )

    assert result == 4321
    params = db.session.execute.call_args.args[1]
    assert params["model_id"] == 7
    assert params["provider_id"] == 9
    assert params["usage"] == '{"prompt_tokens": 12, "completion_tokens": 3}'
    assert params["response_at"] == response_at


def test_get_usage_cost_micro_cents_returns_none_for_local_provider():
    db = _db_fetchone({"cost_micro_cents": None})

    response_at = datetime.datetime(2026, 8, 17, tzinfo=datetime.timezone.utc)
    assert db.get_usage_cost_micro_cents(7, 9, {"prompt_tokens": 12}, response_at) is None


def _db_execute_many(return_values):
    db = DBManager.__new__(DBManager)
    session = MagicMock()
    session.execute.side_effect = [
        MagicMock(fetchall=MagicMock(return_value=[MockRow(r) for r in rv])) for rv in return_values
    ]
    db.session = session
    return db
