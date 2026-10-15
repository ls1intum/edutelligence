"""Run against an explicitly supplied disposable PostgreSQL database."""

import os
import uuid
from datetime import date
from pathlib import Path
from xml.etree import ElementTree

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from logos.benchmarks import nightly_store as store

pytestmark = pytest.mark.integration


@pytest.fixture
def database(monkeypatch):
    url = os.getenv("NIGHTLY_TEST_DB_URL")
    if not url:
        pytest.skip("Set NIGHTLY_TEST_DB_URL to an isolated PostgreSQL test database")
    schema = "nightly_test_" + uuid.uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    migration = Path(
        os.getenv("NIGHTLY_SCHEMA_FILE")
        or (
            Path(__file__).resolve().parents[4]
            / "logos-webservice/src/main/resources/liquibase/changelog/060_nightly_benchmarks.xml"
        )
    )
    tree = ElementTree.parse(migration)
    sql = tree.find("{*}changeSet/{*}sql").text
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE model_provider (id integer PRIMARY KEY)"))
        connection.execute(text("INSERT INTO model_provider VALUES (31), (32)"))
        connection.execute(text(sql))
        connection.execute(
            text(
                "CREATE TABLE jobs(id integer PRIMARY KEY, environment text, status text, "
                "updated_at timestamptz DEFAULT CURRENT_TIMESTAMP, result_payload jsonb)"
            )
        )

    class Database(store.DBManager):
        def __enter__(self):
            self.session = Session(engine)
            return self

    monkeypatch.setattr(store, "DBManager", Database)
    monkeypatch.setattr(store, "_init_engine", lambda: engine)
    yield engine, Database
    engine.dispose()
    with admin.begin() as connection:
        connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))
    admin.dispose()


def test_opt_in_compare_and_set_and_persistent_daily_claim(database):
    assert store.status(31)["enabled"] is False
    assert store.set_enabled(31, True, False)["enabled"] is True
    with pytest.raises(ValueError):
        store.set_enabled(31, True, False)
    assert store.claim(31, date(2026, 10, 13))
    assert not store.claim(31, date(2026, 10, 13))
    assert not store.claim(31, date(2026, 10, 12))
    assert store.claim(31, date(2026, 10, 14))
    store.set_enabled(31, False, True)
    assert not store.claim(31, date(2026, 10, 15))


def test_cluster_lock_excludes_other_scheduler_and_manual_runs(database):
    _, Database = database
    with store.cluster_lock() as first:
        assert first is not None
        assert store.lock_held(first)
        with store.cluster_lock() as second:
            assert second is None
        with Database() as db:
            assert not store.manual_admission(db)
    with Database() as db:
        assert store.manual_admission(db)


def test_recovery_journal_blocks_manual_admission_after_lock_release(database):
    _, Database = database
    store.set_enabled(31, True, False)
    store.save(31, "recovery_required", [{"status": "stalled"}], {"provider_id": 20})
    with Database() as db:
        assert not store.manual_admission(db)
    assert store.status(31)["recovery_required"]
    assert "recovery" not in store.status(31)
    store.set_enabled(31, False, True)
    with pytest.raises(ValueError):
        store.set_enabled(31, True, False)
    store.save(31, "recovered", [], None)
    with Database() as db:
        assert store.manual_admission(db)


def test_progress_does_not_replace_job_result_or_renew_a_failed_job(database):
    engine, _ = database
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO jobs(id, status, result_payload) VALUES "
                "(1, 'running', '{\"stage\":\"benchmarking\"}'), (2, 'failed', '{}')"
            )
        )
    store.write_progress(1, 25, 50)
    store.write_progress(2, 25, 50)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT result_payload FROM jobs WHERE id=1")).scalar() == {
            "stage": "benchmarking",
            "completed_samples": 25,
            "total_samples": 50,
        }
        assert connection.execute(text("SELECT result_payload FROM jobs WHERE id=2")).scalar() == {}


def test_deleted_deployment_keeps_recovery_and_disables_future_runs(database):
    engine, _ = database
    store.set_enabled(31, True, False)
    store.save(31, "recovery_required", [], {"provider_id": 20})
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM model_provider WHERE id = 31"))
    store.disable_missing_target(31)
    assert store.status(31)["enabled"] is False
    assert store.rows()[0]["recovery"] == {"provider_id": 20}


def test_two_pair_rotation_persists_across_restart_failure_and_disable(database):
    engine, _ = database
    for pair in (31, 32, 33, 34):
        store.set_enabled(pair, True, False)
    first = date(2026, 10, 13)
    with store.cluster_lock():
        assert store.claim(31, first)
        assert store.claim(32, first)
        assert not store.claim(33, first)
    store.save(31, "failed", [], None)
    store.set_enabled(31, False, True)
    engine.dispose()  # New connections must see the consumed nightly quota.
    assert store.claimed_today(first) == 2
    with store.cluster_lock():
        assert not store.claim(33, first)
    second = date(2026, 10, 14)
    waiting = [row["model_provider_id"] for row in store.rows() if row["enabled"]]
    assert waiting == [33, 34, 32]
    with store.cluster_lock():
        assert store.claim(waiting[0], second)
        assert store.claim(waiting[1], second)
        assert not store.claim(waiting[2], second)
    store.set_enabled(31, True, False)
    assert [row["model_provider_id"] for row in store.rows()] == [31, 32, 33, 34]
