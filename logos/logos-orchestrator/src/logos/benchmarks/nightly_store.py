"""Persistent nightly opt-in, date claims and recovery journal."""

import json
from contextlib import contextmanager

from sqlalchemy import text

from logos.benchmarks.nightly import MAX_PAIRS_PER_NIGHT
from logos.dbutils.dbmanager import DBManager, _init_engine

LOCK_ID = 125500301


@contextmanager
def cluster_lock():
    """Hold a dedicated session lock through execution and restoration."""
    with _init_engine().connect() as connection:
        acquired = connection.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_ID}).scalar()
        connection.commit()
        try:
            yield connection if acquired else None
        finally:
            if acquired:
                try:
                    connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_ID})
                    connection.commit()
                except Exception:
                    connection.invalidate()
                    raise


def rows() -> list[dict]:
    with DBManager() as db:
        return [
            dict(row)
            for row in db.session.execute(
                text("SELECT * FROM nightly_benchmarks ORDER BY last_run_date NULLS FIRST, model_provider_id")
            ).mappings()
        ]


def status(pair_id: int) -> dict:
    with DBManager() as db:
        row = (
            db.session.execute(
                text(
                    "SELECT model_provider_id, enabled, last_run_date, status, report, "
                    "recovery IS NOT NULL AS recovery_required FROM nightly_benchmarks WHERE model_provider_id = :id"
                ),
                {"id": pair_id},
            )
            .mappings()
            .first()
        )
        return (
            dict(row)
            if row
            else {
                "model_provider_id": pair_id,
                "enabled": False,
                "status": "disabled",
                "report": [],
                "recovery_required": False,
            }
        )


def set_enabled(pair_id: int, enabled: bool, expected: bool) -> dict:
    """Compare-and-set prevents a stale confirmation from toggling newer state."""
    with DBManager() as db:
        db.session.execute(
            text("INSERT INTO nightly_benchmarks(model_provider_id) VALUES (:id) ON CONFLICT DO NOTHING"),
            {"id": pair_id},
        )
        changed = db.session.execute(
            text(
                "UPDATE nightly_benchmarks SET enabled = :enabled, updated_at = CURRENT_TIMESTAMP, "
                "status = CASE WHEN recovery IS NOT NULL THEN status "
                "WHEN :enabled THEN 'scheduled' ELSE 'disabled' END "
                "WHERE model_provider_id = :id AND enabled = :expected AND (NOT :enabled OR recovery IS NULL)"
            ),
            {"id": pair_id, "enabled": enabled, "expected": expected},
        )
        if not changed.rowcount:
            raise ValueError("Nightly state changed or recovery is required. Refresh before confirming.")
        db.session.commit()
    return status(pair_id)


def claim(pair_id: int, day) -> bool:
    """Claim one pair under the caller's cluster lock; failures still consume a slot."""
    with DBManager() as db:
        claimed = bool(
            db.session.execute(
                text(
                    "UPDATE nightly_benchmarks SET last_run_date = :day, status = 'running', report = '[]'::jsonb "
                    "WHERE model_provider_id = :id AND enabled AND recovery IS NULL "
                    "AND (last_run_date IS NULL OR last_run_date < :day) "
                    "AND (SELECT COUNT(*) FROM nightly_benchmarks WHERE last_run_date = :day) < :limit"
                ),
                {"id": pair_id, "day": day, "limit": MAX_PAIRS_PER_NIGHT},
            ).rowcount
        )

        db.session.commit()
        return claimed


def claimed_today(day) -> int:
    with DBManager() as db:
        return db.session.execute(
            text("SELECT COUNT(*) FROM nightly_benchmarks WHERE last_run_date = :day"), {"day": day}
        ).scalar_one()


def save(pair_id: int, state: str, report: list, recovery: dict | None) -> None:
    with DBManager() as db:
        db.session.execute(
            text(
                "UPDATE nightly_benchmarks SET status = :state, report = CAST(:report AS jsonb), "
                "recovery = CAST(:recovery AS jsonb), updated_at = CURRENT_TIMESTAMP WHERE model_provider_id = :id"
            ),
            {
                "id": pair_id,
                "state": state,
                "report": json.dumps(report),
                "recovery": json.dumps(recovery) if recovery is not None else None,
            },
        )

        db.session.commit()


def has_active_benchmarks() -> bool:
    with DBManager() as db:
        return bool(
            db.session.execute(
                text(
                    "SELECT EXISTS(SELECT 1 FROM jobs WHERE environment = 'model-provider-benchmark' "
                    "AND status IN ('pending', 'running')) OR EXISTS(SELECT 1 FROM maintenance_benchmark)"
                )
            ).scalar()
        )


def manual_admission(db) -> bool:
    """Serialize admission against nightly execution, including recovery after a crash."""
    acquired = db.session.execute(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": LOCK_ID}).scalar()
    return (
        bool(acquired)
        and not db.session.execute(
            text(
                "SELECT EXISTS(SELECT 1 FROM nightly_benchmarks WHERE recovery IS NOT NULL) "
                "OR EXISTS(SELECT 1 FROM maintenance_calibration) "
                "OR EXISTS(SELECT 1 FROM jobs WHERE environment = 'model-provider-benchmark' "
                "AND status IN ('pending', 'running')) OR EXISTS(SELECT 1 FROM maintenance_benchmark)"
            )
        ).scalar()
    )


def lock_held(connection) -> bool:
    """A reconnected SQL session must not continue under a lost advisory lock."""
    if connection.invalidated or connection.closed:
        return False
    try:
        held = connection.execute(
            text(
                "SELECT EXISTS(SELECT 1 FROM pg_locks WHERE locktype = 'advisory' "
                "AND pid = pg_backend_pid() AND classid = 0 AND objid = :key AND granted)"
            ),
            {"key": LOCK_ID},
        ).scalar()
        connection.commit()
        return bool(held)
    except Exception:
        return False


def write_progress(job_id: int, completed: int, total: int) -> None:
    with DBManager() as db:
        db.session.execute(
            text(
                "UPDATE jobs SET result_payload = COALESCE(result_payload, '{}'::jsonb) || CAST(:progress AS jsonb) "
                "WHERE id = :id AND status = 'running'"
            ),
            {"id": job_id, "progress": json.dumps({"completed_samples": completed, "total_samples": total})},
        )

        db.session.commit()


def disable_missing_target(pair_id: int) -> None:
    with DBManager() as db:
        db.session.execute(
            text("UPDATE nightly_benchmarks SET enabled = false WHERE model_provider_id = :id"), {"id": pair_id}
        )
        db.session.commit()


def has_recovery():
    with DBManager() as db:
        return bool(
            db.session.execute(
                text("SELECT EXISTS(SELECT 1 FROM nightly_benchmarks WHERE recovery IS NOT NULL)")
            ).scalar()
        )


def calibration_claim():
    with DBManager() as db:
        row = db.session.execute(text("SELECT * FROM maintenance_calibration WHERE singleton")).mappings().first()
        return dict(row) if row else None


def claim_calibration(provider_id, token, automatic=False):
    with DBManager() as db:
        db.session.execute(
            text(
                "INSERT INTO maintenance_calibration (provider_id, token, automatic) VALUES (:pid, :token, :automatic)"
            ),
            {"pid": provider_id, "token": token, "automatic": automatic},
        )
        db.session.commit()


def confirm_calibration(token):
    with DBManager() as db:
        db.session.execute(
            text("UPDATE maintenance_calibration SET confirmed = true WHERE token = :token"), {"token": token}
        )
        db.session.commit()


def release_calibration(token):
    with DBManager() as db:
        db.session.execute(text("DELETE FROM maintenance_calibration WHERE token = :token"), {"token": token})
        db.session.commit()


def claim_benchmark(db, job_id):
    db.session.execute(text("INSERT INTO maintenance_benchmark (job_id) VALUES (:job)"), {"job": job_id})
    db.session.commit()


def release_benchmark(job_id):
    with DBManager() as db:
        db.session.execute(text("DELETE FROM maintenance_benchmark WHERE job_id = :job"), {"job": job_id})
        db.session.commit()
