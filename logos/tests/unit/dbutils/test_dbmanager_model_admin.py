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
