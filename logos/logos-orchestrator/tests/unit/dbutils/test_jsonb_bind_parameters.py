"""Regression tests for JSONB parameters in textual SQL statements."""

import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from logos import DBManager


def _db() -> DBManager:
    db = DBManager.__new__(DBManager)
    db.session = MagicMock()
    db.session.execute.return_value.fetchone.return_value = SimpleNamespace(id=1)
    return db


def _executed_statement(db: DBManager) -> str:
    return str(db.session.execute.call_args.args[0])


def test_create_job_record_casts_bound_payload_to_jsonb():
    db = _db()

    with patch("logos.dbutils.dbmanager.text", side_effect=lambda sql: sql):
        db.create_job_record({}, None, None, None, "model-provider-benchmark")

    statement = _executed_statement(db)
    assert "CAST(:payload AS jsonb)" in statement
    assert ":payload::jsonb" not in statement


def test_insert_model_provider_benchmark_casts_bound_json_to_jsonb():
    db = _db()

    with patch("logos.dbutils.dbmanager.text", side_effect=lambda sql: sql):
        db.insert_model_provider_benchmark(
            model_provider_id=1,
            configuration={},
            dataset="openai/gsm8k",
            sample_size=5,
            metrics={},
            recorded_at=datetime.datetime.now(datetime.timezone.utc),
        )

    statement = _executed_statement(db)
    assert "CAST(:configuration AS jsonb)" in statement
    assert "CAST(:metrics AS jsonb)" in statement
    assert ":configuration::jsonb" not in statement
    assert ":metrics::jsonb" not in statement


def test_model_benchmark_provider_lock_is_transaction_scoped():
    db = _db()

    with patch("logos.dbutils.dbmanager.text", side_effect=lambda sql: sql):
        db.lock_model_benchmark_provider(23)

    statement = _executed_statement(db)
    assert "pg_advisory_xact_lock" in statement
    assert db.session.execute.call_args.args[1]["provider_id"] == 23
    db.session.commit.assert_not_called()


def test_active_benchmark_lookup_expires_stale_rows_before_selecting():
    db = _db()
    expired_result = SimpleNamespace(rowcount=1)
    select_result = MagicMock()
    select_result.mappings.return_value.first.return_value = None
    db.session.execute.side_effect = [expired_result, select_result]

    with patch("logos.dbutils.dbmanager.text", side_effect=lambda sql: sql):
        result = db.find_active_model_benchmark_job(23)

    assert result is None
    expire_statement = str(db.session.execute.call_args_list[0].args[0])
    expire_params = db.session.execute.call_args_list[0].args[1]
    assert "UPDATE jobs" in expire_statement
    assert "COALESCE(updated_at, created_at)" in expire_statement
    assert expire_params["provider_id"] == 23
    assert expire_params["stale_after_seconds"] == 60
    db.session.commit.assert_not_called()
