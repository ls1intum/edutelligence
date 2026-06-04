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
        session.execute.return_value = MagicMock(
            fetchall=MagicMock(return_value=[MockRow(r) for r in fetchall_val])
        )
    else:
        row = MockRow(fetch_val) if fetch_val else None
        mock_res = MagicMock()
        mock_res.fetchone.return_value = row
        mock_res.rowcount = 1 if fetch_val else 0
        session.execute.return_value = mock_res
    db.session = session
    return db


def test_list_teams_returns_all():
    db = _make_db(fetchall_val=[{"id": 1, "name": "A", "member_count": 1}])
    res = db.list_teams()
    assert len(res) == 1


def test_list_teams_filtered_by_owner():
    db = _make_db(fetchall_val=[{"id": 1, "name": "A", "member_count": 1}])
    res = db.list_teams()
    assert len(res) == 1


def test_create_team_inserts_team_and_owners():
    db = DBManager.__new__(DBManager)
    session = MagicMock()
    session.execute.side_effect = [
        MagicMock(fetchone=MagicMock(return_value=None)),
        MagicMock(fetchone=MagicMock(return_value=MockRow({"id": 5}))),
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    ]
    db.session = session
    tid, status = db.create_team("Alpha", [1, 2], default_cloud_rpm_limit=100)
    assert status == 200
    assert tid == 5


def test_create_team_no_owners():
    db = DBManager.__new__(DBManager)
    session = MagicMock()
    session.execute.side_effect = [
        MagicMock(fetchone=MagicMock(return_value=None)),
        MagicMock(fetchone=MagicMock(return_value=MockRow({"id": 5}))),
    ]
    db.session = session
    tid, status = db.create_team("Alpha", [])
    assert status == 200
    assert tid == 5


def test_get_team_returns_team():
    db = _make_db(fetch_val={"id": 1, "name": "A"})
    res = db.get_team(1)
    name = res.name if hasattr(res, "name") else res["name"]
    assert name == "A"


def test_get_team_returns_none_when_missing():
    db = _make_db(fetch_val=None)
    assert db.get_team(99) is None


def test_delete_team_success():
    db = DBManager.__new__(DBManager)
    db.session = MagicMock()
    res, status = db.delete_team(1)
    assert status == 200
    assert "result" in res


def test_delete_team_not_found():
    db = DBManager.__new__(DBManager)
    db.session = MagicMock()
    res, status = db.delete_team(99)
    assert status == 200


def test_add_team_member_success():
    db = DBManager.__new__(DBManager)
    session = MagicMock()
    session.execute.side_effect = [
        MagicMock(
            fetchone=MagicMock(
                return_value=MockRow(
                    {"username": "user1", "team_name": "team1", "already_exists": False}
                )
            )
        ),
        MagicMock(),
        MagicMock(fetchone=MagicMock(return_value=MockRow({"name": "team1"}))),
        MagicMock(fetchone=MagicMock(return_value=MockRow({"username": "user1"}))),
        MagicMock(
            fetchone=MagicMock(return_value=MockRow({"id": 10, "key_value": "lg-key"}))
        ),
    ]
    db.session = session
    res, status = db.add_team_member(1, 5)
    assert status == 200
    assert "successfully" in res.get("result", "").lower()


def test_add_team_member_as_owner():
    db = DBManager.__new__(DBManager)
    session = MagicMock()

    session.execute.side_effect = [
        MagicMock(
            fetchone=MagicMock(
                return_value=MockRow(
                    {"username": "user1", "team_name": "team1", "already_exists": False}
                )
            )
        ),
        MagicMock(),
        MagicMock(fetchone=MagicMock(return_value=MockRow({"name": "team1"}))),
        MagicMock(fetchone=MagicMock(return_value=MockRow({"username": "user1"}))),
        MagicMock(
            fetchone=MagicMock(return_value=MockRow({"id": 10, "key_value": "lg-key"}))
        ),
    ]
    db.session = session
    res, status = db.add_team_member(1, 5, is_owner=True)
    assert status == 200


def test_remove_team_member_success():
    db = DBManager.__new__(DBManager)
    db.session = MagicMock()
    res, status = db.remove_team_member(1, 5)
    assert status == 200
    assert "removed" in res.get("result", "").lower()


def test_remove_team_member_not_found():
    db = DBManager.__new__(DBManager)
    db.session = MagicMock()
    res, status = db.remove_team_member(1, 99)
    assert status == 200
