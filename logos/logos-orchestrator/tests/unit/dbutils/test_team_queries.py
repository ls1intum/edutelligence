from __future__ import annotations

from unittest.mock import MagicMock

from logos import DBManager


class MockRow:
    def __init__(self, data):
        self._data = data or {}
        self._mapping = self._data

    def __getattr__(self, name):
        if name in self._data:
            return self._data[name]
        raise AttributeError(f"MockRow has no attribute '{name}'")

    def __getitem__(self, key):
        if isinstance(key, str):
            return self._data[key]
        return list(self._data.values())[key]

    def keys(self):
        return self._data.keys()


def _make_db(fetch_val=None, fetchall_val=None):
    db = DBManager.__new__(DBManager)
    session = MagicMock()
    if fetchall_val is not None:
        session.execute.return_value = MagicMock(fetchall=MagicMock(return_value=[MockRow(r) for r in fetchall_val]))
    else:
        row = MockRow(fetch_val) if fetch_val else None
        mock_res = MagicMock()
        mock_res.fetchone.return_value = row
        mock_res.rowcount = 1 if fetch_val else 0
        session.execute.return_value = mock_res
    db.session = session
    return db


def test_get_team_returns_team():
    db = _make_db(fetch_val={"id": 1, "name": "A"})
    res = db.get_team(1)
    name = res.name if hasattr(res, "name") else res["name"]
    assert name == "A"


def test_get_team_returns_none_when_missing():
    db = _make_db(fetch_val=None)
    assert db.get_team(99) is None
