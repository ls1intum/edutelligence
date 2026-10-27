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
            / "logos-webservice/src/main/resources/liquibase/changelog/065_nightly_benchmarks.xml"
        )
    )
    tree = ElementTree.parse(migration)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE providers (id integer PRIMARY KEY, name text)"))
        connection.execute(text("CREATE TABLE models (id integer PRIMARY KEY, name text)"))
        connection.execute(text("INSERT INTO providers VALUES (1, 'worker-a'), (2, 'worker-b')"))
        connection.execute(text("INSERT INTO models VALUES (11, 'model-a')"))
        connection.execute(
            text("CREATE TABLE model_provider (id integer PRIMARY KEY, provider_id integer, model_id integer)")
        )
        connection.execute(text("INSERT INTO model_provider VALUES (31, 1, 11), (32, NULL, NULL)"))
        connection.execute(
            text(
                "CREATE TABLE jobs(id integer PRIMARY KEY, environment text, status text, "
                "created_at timestamptz DEFAULT CURRENT_TIMESTAMP, "
                "updated_at timestamptz DEFAULT CURRENT_TIMESTAMP, result_payload jsonb, "
                "request_payload jsonb, error_message text)"
            )
        )

        for sql in tree.findall("{*}changeSet/{*}sql"):
            connection.execute(text(sql.text))

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
            assert not store.manual_admission(db, 20)
    with Database() as db:
        assert store.manual_admission(db, 20)


def test_recovery_journal_blocks_manual_admission_after_lock_release(database):
    _, Database = database
    store.set_enabled(31, True, False)
    store.save(31, "recovery_required", [{"status": "stalled"}], {"provider_id": 20})
    with Database() as db:
        assert not store.manual_admission(db, 20)
    assert store.status(31)["recovery_required"]
    assert "recovery" not in store.status(31)
    store.set_enabled(31, False, True)
    with pytest.raises(ValueError):
        store.set_enabled(31, True, False)
    store.save(31, "recovered", [], None)
    with Database() as db:
        assert store.manual_admission(db, 20)


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


def test_calibration_claim_blocks_manual_admission_and_survives_connections(database):
    engine, Database = database
    with store.cluster_lock():
        store.claim_calibration(20, "owner", automatic=True)
        store.confirm_calibration("owner")
    engine.dispose()
    assert store.calibration_claims()[0]["confirmed"]
    assert store.calibration_claims()[0]["automatic"]
    with Database() as db:
        assert not store.manual_admission(db, 20)
    store.release_calibration("old-owner")
    assert store.calibration_claims()
    store.release_calibration("owner")
    with Database() as db:
        assert store.manual_admission(db, 20)


def test_finished_job_keeps_slot_until_benchmark_cleanup_completes(database):
    engine, Database = database
    with Database() as db:
        assert store.manual_admission(db, 20)
        store.claim_benchmark(db, 7, 20)
    # A second connection must not admit another job, even without a live jobs row.
    with Database() as db:
        assert not store.manual_admission(db, 20)
    assert store.has_active_benchmarks()
    store.release_benchmark(6)
    assert store.has_active_benchmarks()
    store.release_benchmark(7)
    assert not store.has_active_benchmarks()
    with Database() as db:
        assert store.manual_admission(db, 20)


def test_old_running_job_is_not_assumed_finished(database):
    engine, Database = database
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO jobs(id, environment, status, updated_at) VALUES "
                "(7, 'model-provider-benchmark', 'running', CURRENT_TIMESTAMP - INTERVAL '1 day')"
            )
        )
    assert store.has_active_benchmarks()
    with Database() as db:
        assert not store.manual_admission(db, 20)


def test_execution_lease_survives_maintenance_lock_release(database):
    with store.execution_lock(31) as execution:
        assert execution is not None
        assert store.execution_lock_held(execution, 31)
        with store.cluster_lock() as first:
            assert first is not None
        # Another scheduler can hold maintenance, but cannot recover a live run.
        with store.cluster_lock() as recovery:
            assert recovery is not None
            with store.execution_lock(31) as blocked:
                assert blocked is None
    with store.execution_lock(31) as recovered:
        assert recovered is not None


def test_orphan_fencing_targets_only_its_nightly_jobs_and_preserves_manual_claim(database):
    engine, Database = database
    with engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO jobs(id, environment, status, request_payload) VALUES
            (7, 'model-provider-benchmark', 'running', '{"nightly": true, "model_provider_id": 31}'),
            (8, 'model-provider-benchmark', 'running', '{"nightly": false, "model_provider_id": 31}'),
            (9, 'model-provider-benchmark', 'running', '{"nightly": true, "model_provider_id": 32}')
        """))
    assert store.recovery_jobs(31) == [7]
    assert store.has_active_benchmarks(excluding=[7])
    assert store.benchmark_requests_allowed(7)
    store.fence_recovery_jobs([7])
    assert not store.benchmark_requests_allowed(7)
    assert store.benchmark_requests_allowed(8)
    with Database() as db:
        assert not db.touch_model_benchmark_job(7)
        assert db.touch_model_benchmark_job(8)
    store.finish_recovery_jobs([7])
    assert store.recovery_jobs(31) == []
    with engine.connect() as connection:
        assert connection.execute(text("SELECT status FROM jobs WHERE id=7")).scalar() == "failed"
    with Database() as db:
        store.claim_benchmark(db, 8, 20)
    assert store.has_active_benchmarks(excluding=[8, 9])
    store.release_benchmark(8)
    assert not store.has_active_benchmarks(excluding=[8, 9])


def test_parallel_manual_claims_are_durable_bounded_and_provider_exclusive(database, monkeypatch):
    engine, Database = database
    monkeypatch.setenv("LOGOS_MAINTENANCE_MAX_NODES", "2")
    with Database() as db:
        assert store.manual_admission(db, 20)
        store.claim_benchmark(db, 7, 20)
    with Database() as db:
        assert not store.manual_admission(db, 20)
    with Database() as db:
        assert store.manual_admission(db, 21)
        store.claim_benchmark(db, 8, 21)
    engine.dispose()
    with Database() as db:
        assert not store.manual_admission(db, 22)
    store.release_benchmark(7)
    with Database() as db:
        assert store.manual_admission(db, 22)
        store.claim_benchmark(db, 9, 22)
    monkeypatch.setenv("LOGOS_MAINTENANCE_MAX_NODES", "1")
    with Database() as db:
        assert not store.manual_admission(db, 20)


def test_parallel_calibration_rows_survive_restart_and_release_only_matching_token(database):
    engine, Database = database
    with store.cluster_lock():
        store.claim_calibration(20, "first", automatic=True)
        store.claim_calibration(21, "second", automatic=True)
        store.confirm_calibration("first")
        store.confirm_calibration("second")
    engine.dispose()
    assert {claim["provider_id"] for claim in store.calibration_claims()} == {20, 21}
    store.release_calibration("stale-token")
    assert len(store.calibration_claims()) == 2
    store.release_calibration("first")
    assert [claim["provider_id"] for claim in store.calibration_claims()] == [21]
    with Database() as db:
        assert not store.manual_admission(db, 22)


def test_manual_job_and_cleanup_claim_count_once(database, monkeypatch):
    engine, Database = database
    monkeypatch.setenv("LOGOS_MAINTENANCE_MAX_NODES", "2")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO jobs(id, environment, status, request_payload) VALUES "
                "(7, 'model-provider-benchmark', 'running', '{\"provider_id\": 20}')"
            )
        )
    with Database() as db:
        store.claim_benchmark(db, 7, 20)
    with Database() as db:
        assert store.manual_admission(db, 21)
    with Database() as db:
        assert not store.manual_admission(db, 20)


def test_comparison_metadata_survives_database_session_close(database):
    engine, _ = database
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE model_provider_benchmarks (id integer PRIMARY KEY, configuration jsonb)"))
        connection.execute(text('INSERT INTO model_provider_benchmarks VALUES (1, \'{"tool":"guidellm"}\')'))
    store.record_comparison(1, 1, {"max_num_seqs": 16}, {"max_num_seqs": 16})
    with engine.connect() as connection:
        config = connection.execute(
            text("SELECT configuration FROM model_provider_benchmarks WHERE id = 1")
        ).scalar_one()
        assert config["nightly"]["baseline_id"] == 1
        assert config["tool"] == "guidellm"


def test_maintenance_holders_name_every_kind_of_slot_holder(database):
    engine, _ = database
    store.claim_calibration(2, "claim-2", automatic=True)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO jobs (id, environment, status, request_payload) VALUES "
                "(5, 'model-provider-benchmark', 'running', "
                '\'{"provider_id": 1, "model_name": "model-a", "nightly": true}\'), '
                "(6, 'model-provider-benchmark', 'failed', '{\"provider_id\": 2, \"model_name\": \"model-b\"}'), "
                "(7, 'inference', 'running', '{}'), "
                "(8, 'model-provider-benchmark', 'completed', '{\"provider_id\": 2}')"
            )
        )
        # A finished job whose claim is still being cleaned up holds the slot too.
        connection.execute(text("INSERT INTO maintenance_benchmark (job_id, provider_id) VALUES (6, 2)"))
        connection.execute(
            text(
                "INSERT INTO nightly_benchmarks (model_provider_id, status, recovery) "
                'VALUES (31, \'restoring\', \'{"provider_id": 1, "model": "model-a"}\')'
            )
        )
    holders = store.maintenance_holders()
    (claim,) = holders["calibrations"]
    assert (claim["provider_id"], claim["provider_name"], claim["token"], claim["automatic"]) == (
        2,
        "worker-b",
        "claim-2",
        True,
    )
    assert claim["age_s"] >= 0
    benchmarks = {row["job_id"]: row for row in holders["benchmarks"]}
    assert set(benchmarks) == {5, 6}
    assert benchmarks[5]["provider_name"] == "worker-a"
    assert benchmarks[5]["model_name"] == "model-a"
    assert benchmarks[5]["nightly"] is True
    # A cancelled job keeps its status and model name while its claim is cleaned up.
    assert benchmarks[6]["status"] == "failed"
    assert (benchmarks[6]["provider_name"], benchmarks[6]["model_name"]) == ("worker-b", "model-b")
    (recovery,) = holders["recoveries"]
    assert (recovery["model_provider_id"], recovery["provider_name"], recovery["model_name"]) == (
        31,
        "worker-a",
        "model-a",
    )
    assert recovery["status"] == "restoring"
