from __future__ import annotations


class _FakeSession:

    def __init__(self):
        self.executed_params: list[dict] = []
        self.committed = False

    def execute(self, sql, params=None):
        self.executed_params.append(params or {})

    def commit(self):
        self.committed = True


def _make_db_with_session(session):
    from logos.dbutils import dbmanager

    db = dbmanager.DBManager.__new__(dbmanager.DBManager)
    db.session = session
    return db


def test_prune_team_model_permissions_calls_execute_with_team_id():
    session = _FakeSession()
    db = _make_db_with_session(session)

    db.prune_team_model_permissions_by_providers(team_id=42)

    assert session.executed_params, "execute() was never called"
    assert session.executed_params[0] == {"tid": 42}
    assert session.committed


def test_prune_api_key_model_permissions_calls_execute_with_api_key_id():
    session = _FakeSession()
    db = _make_db_with_session(session)

    db.prune_api_key_model_permissions_by_providers(api_key_id=7)

    assert session.executed_params, "execute() was never called"
    assert session.executed_params[0] == {"aki": 7}
    assert session.committed
