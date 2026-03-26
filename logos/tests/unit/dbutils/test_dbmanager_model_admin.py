from __future__ import annotations

from types import SimpleNamespace

import sqlalchemy.exc

import logos.dbutils.dbmanager as dbmanager_mod
from logos.dbutils.dbmanager import DBManager


def test_add_model_seeds_explicit_weight_columns(monkeypatch):
    db = DBManager()
    captured: dict[str, object] = {}

    monkeypatch.setattr(db, "check_authorization", lambda logos_key: logos_key == "root-key")

    def _fake_insert(table: str, data: dict[str, object]) -> int:
        captured["table"] = table
        captured["data"] = data
        return 41

    monkeypatch.setattr(db, "insert", _fake_insert)

    payload, status = db.add_model("root-key", "openai/gpt-oss-20b")

    assert status == 200
    assert payload == {"result": "Created Model", "model_id": 41}
    assert captured["table"] == "models"
    assert captured["data"] == {
        "name": "openai/gpt-oss-20b",
        "weight_privacy": "LOCAL",
        "weight_latency": 0,
        "weight_accuracy": 0,
        "weight_cost": 0,
        "weight_quality": 0,
        "tags": "",
        "parallel": 1,
        "description": "",
    }


def test_add_full_model_seeds_weight_columns_before_rebalance(monkeypatch):
    db = DBManager()
    captured: dict[str, object] = {}

    monkeypatch.setattr(db, "check_authorization", lambda logos_key: logos_key == "root-key")

    def _fake_insert(table: str, data: dict[str, object]) -> int:
        captured["table"] = table
        captured["data"] = data
        return 55

    monkeypatch.setattr(db, "insert", _fake_insert)
    monkeypatch.setattr(
        db,
        "rebalance_added_model",
        lambda new_model_id, worse_accuracy, worse_quality, worse_latency, worse_cost: (
            {
                "result": "Created Model",
                "model_id": new_model_id,
                "worse_accuracy": worse_accuracy,
                "worse_quality": worse_quality,
                "worse_latency": worse_latency,
                "worse_cost": worse_cost,
            },
            200,
        ),
    )

    payload, status = db.add_full_model(
        "root-key",
        "openai/gpt-oss-20b",
        weight_privacy="LOCAL",
        worse_accuracy=30,
        worse_quality=31,
        worse_latency=None,
        worse_cost=32,
        tags="#local #coding",
        parallel=2,
        description="GPT OSS 20B",
    )

    assert status == 200
    assert payload["model_id"] == 55
    assert captured["table"] == "models"
    assert captured["data"] == {
        "name": "openai/gpt-oss-20b",
        "weight_privacy": "LOCAL",
        "weight_latency": 0,
        "weight_accuracy": 0,
        "weight_cost": 0,
        "weight_quality": 0,
        "tags": "#local #coding",
        "parallel": 2,
        "description": "GPT OSS 20B",
    }


def test_insert_retries_after_sequence_drift(monkeypatch):
    db = DBManager()

    class _FakeInsertStmt:
        def values(self, **kwargs):
            self.kwargs = kwargs
            return self

    insert_stmt = _FakeInsertStmt()
    fake_table = SimpleNamespace(name="models", c={"id": object()}, insert=lambda: insert_stmt)

    class _FakeResult:
        inserted_primary_key = [41]

    class _FakeSession:
        def __init__(self):
            self.insert_attempts = 0
            self.rollbacks = 0
            self.commits = 0

        def execute(self, stmt, params=None):  # noqa: ARG002
            if stmt is insert_stmt:
                self.insert_attempts += 1
                if self.insert_attempts == 1:
                    orig = SimpleNamespace(diag=SimpleNamespace(constraint_name="models_pkey"))
                    raise sqlalchemy.exc.IntegrityError("INSERT", {"name": "openai/gpt-oss-20b"}, orig)
                return _FakeResult()
            raise AssertionError("unexpected execute call")

        def rollback(self):
            self.rollbacks += 1

        def commit(self):
            self.commits += 1

    db.metadata = object()
    db.engine = object()
    db.session = _FakeSession()

    healed = []

    monkeypatch.setattr(dbmanager_mod, "Table", lambda *args, **kwargs: fake_table)
    monkeypatch.setattr(db, "_reset_sequence_for_table", lambda table_name: healed.append(table_name) or True)

    inserted_pk = db.insert("models", {"name": "openai/gpt-oss-20b"})

    assert inserted_pk == 41
    assert healed == ["models"]
    assert db.session.rollbacks == 1
    assert db.session.commits == 1
