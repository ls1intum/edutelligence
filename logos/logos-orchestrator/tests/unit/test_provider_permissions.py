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

