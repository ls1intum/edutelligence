"""Persistent nightly opt-in, date claims and recovery journal."""

import json
from contextlib import contextmanager

from sqlalchemy import text

from logos.benchmarks.nightly import MAX_PAIRS_PER_NIGHT
from logos.dbutils.dbmanager import DBManager, _init_engine
from logos.maintenance_window import maintenance_node_limit

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


def overview_rows() -> list[dict]:
    """Return public schedule metadata in the scheduler's rotation order."""
    with DBManager() as db:
        return [
            dict(row)
            for row in db.session.execute(
                text(
                    "SELECT n.*, mp.model_id, p.name AS provider_name FROM nightly_benchmarks n "
                    "JOIN model_provider mp ON mp.id = n.model_provider_id "
                    "JOIN providers p ON p.id = mp.provider_id "
                    "ORDER BY n.last_run_date NULLS FIRST, n.model_provider_id"
                )
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


def has_active_benchmarks(excluding: list[int] | None = None) -> bool:
    with DBManager() as db:
        return bool(
            db.session.execute(
                text(
                    "SELECT EXISTS(SELECT 1 FROM jobs WHERE environment = 'model-provider-benchmark' "
                    "AND status IN ('pending', 'running') AND NOT (id = ANY(CAST(:excluded AS integer[])))) "
                    "OR EXISTS(SELECT 1 FROM maintenance_benchmark)"
                ),
                {"excluded": excluding or []},
            ).scalar()
        )


def manual_admission(db, provider_id: int) -> bool:
    """Serialize admission against nightly execution, including recovery after a crash."""
    acquired = db.session.execute(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": LOCK_ID}).scalar()
    return (
        bool(acquired)
        and not db.session.execute(
            text(
                "SELECT EXISTS(SELECT 1 FROM nightly_benchmarks WHERE recovery IS NOT NULL) "
                "OR EXISTS(SELECT 1 FROM maintenance_calibration) "
                "OR EXISTS(SELECT 1 FROM maintenance_benchmark WHERE provider_id = :provider OR provider_id IS NULL) "
                "OR EXISTS(SELECT 1 FROM jobs WHERE environment = 'model-provider-benchmark' "
                "AND status IN ('pending', 'running') AND request_payload->>'provider_id' = :provider_text) "
                "OR (SELECT COUNT(*) FROM ("
                "SELECT id FROM jobs WHERE environment = 'model-provider-benchmark' "
                "AND status IN ('pending', 'running') UNION SELECT job_id FROM maintenance_benchmark"
                ") AS active_jobs) >= :limit"
            ),
            {"limit": maintenance_node_limit(), "provider": provider_id, "provider_text": str(provider_id)},
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


def calibration_claims():
    with DBManager() as db:
        return [
            dict(row)
            for row in db.session.execute(
                # The age by the database clock, the one created_at was set by.
                text(
                    "SELECT *, EXTRACT(EPOCH FROM now() - created_at) AS age_s "
                    "FROM maintenance_calibration ORDER BY provider_id"
                )
            ).mappings()
        ]


def maintenance_holders():
    """Calibration claims, maintenance benchmarks and nightly recoveries, with names for display."""
    with DBManager() as db:
        calibrations = db.session.execute(
            text(
                "SELECT c.*, EXTRACT(EPOCH FROM now() - c.created_at) AS age_s, p.name AS provider_name "
                "FROM maintenance_calibration c LEFT JOIN providers p ON p.id = c.provider_id ORDER BY c.provider_id"
            )
        ).mappings()
        calibrations = [dict(row) for row in calibrations]
        # The same jobs and claims has_active_benchmarks counts. A claimed job
        # that already ended keeps its metadata while its cleanup runs.
        benchmarks = db.session.execute(
            text(
                "SELECT COALESCE(j.id, b.job_id) AS job_id, j.status, "
                "COALESCE(b.created_at, j.created_at) AS since, "
                "EXTRACT(EPOCH FROM now() - COALESCE(b.created_at, j.created_at)) AS age_s, "
                "COALESCE(b.provider_id, (j.request_payload->>'provider_id')::integer) AS provider_id, "
                "COALESCE(p.name, j.request_payload->>'provider_name') AS provider_name, "
                "j.request_payload->>'model_name' AS model_name, "
                "COALESCE(j.request_payload->>'nightly', 'false') = 'true' AS nightly "
                "FROM (SELECT * FROM jobs WHERE environment = 'model-provider-benchmark' "
                "AND (status IN ('pending', 'running') OR id IN (SELECT job_id FROM maintenance_benchmark))) AS j "
                "FULL OUTER JOIN maintenance_benchmark AS b ON b.job_id = j.id "
                "LEFT JOIN providers p ON p.id = COALESCE(b.provider_id, (j.request_payload->>'provider_id')::integer) "
                "ORDER BY since, job_id"
            )
        ).mappings()
        benchmarks = [dict(row) for row in benchmarks]
        recoveries = db.session.execute(
            text(
                "SELECT n.model_provider_id, n.status, n.updated_at AS since, "
                "EXTRACT(EPOCH FROM now() - n.updated_at) AS age_s, "
                "COALESCE(mp.provider_id, (n.recovery->>'provider_id')::integer) AS provider_id, "
                "p.name AS provider_name, COALESCE(m.name, n.recovery->>'model') AS model_name "
                "FROM nightly_benchmarks n LEFT JOIN model_provider mp ON mp.id = n.model_provider_id "
                "LEFT JOIN providers p ON p.id = mp.provider_id LEFT JOIN models m ON m.id = mp.model_id "
                "WHERE n.recovery IS NOT NULL ORDER BY n.model_provider_id"
            )
        ).mappings()
        recoveries = [dict(row) for row in recoveries]
    return {"calibrations": calibrations, "benchmarks": benchmarks, "recoveries": recoveries}


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


def claim_benchmark(db, job_id, provider_id):
    db.session.execute(
        text("INSERT INTO maintenance_benchmark (job_id, provider_id) VALUES (:job, :provider)"),
        {"job": job_id, "provider": provider_id},
    )
    db.session.commit()


def release_benchmark(job_id):
    with DBManager() as db:
        db.session.execute(text("DELETE FROM maintenance_benchmark WHERE job_id = :job"), {"job": job_id})
        db.session.commit()


@contextmanager
def execution_lock(pair_id: int):
    """Hold a separate execution lease until the nightly task has finished cleanup."""
    with _init_engine().connect() as connection:
        acquired = connection.execute(
            text("SELECT pg_try_advisory_lock(:namespace, :pair)"), {"namespace": LOCK_ID, "pair": pair_id}
        ).scalar()
        connection.commit()
        try:
            yield connection if acquired else None
        finally:
            if acquired:
                try:
                    connection.execute(
                        text("SELECT pg_advisory_unlock(:namespace, :pair)"),
                        {"namespace": LOCK_ID, "pair": pair_id},
                    )
                    connection.commit()
                except Exception:
                    connection.invalidate()
                    raise


def execution_lock_held(connection, pair_id: int) -> bool:
    if connection.invalidated or connection.closed:
        return False
    try:
        held = connection.execute(
            text(
                "SELECT EXISTS(SELECT 1 FROM pg_locks WHERE locktype = 'advisory' "
                "AND pid = pg_backend_pid() AND classid = :namespace AND objid = :pair AND objsubid = 2 AND granted)"
            ),
            {"namespace": LOCK_ID, "pair": pair_id},
        ).scalar()
        connection.commit()
        return bool(held)
    except Exception:
        return False


def recovery_jobs(pair_id: int) -> list[int]:
    """Only jobs explicitly owned by this nightly schedule are recovery candidates."""
    with DBManager() as db:
        return list(
            db.session.execute(
                text(
                    "SELECT id FROM jobs WHERE environment = 'model-provider-benchmark' "
                    "AND status IN ('pending', 'running') AND request_payload->>'nightly' = 'true' "
                    "AND request_payload->>'model_provider_id' = :pair"
                ),
                {"pair": str(pair_id)},
            ).scalars()
        )


def fence_recovery_jobs(job_ids: list[int]) -> None:
    """Stop old runners and queued inference from admitting further worker requests."""
    with DBManager() as db:
        db.session.execute(
            text(
                "UPDATE jobs SET request_payload = request_payload || jsonb_build_object('recovery_fenced', true) "
                "WHERE id = ANY(CAST(:ids AS integer[]))"
            ),
            {"ids": job_ids},
        )
        db.session.commit()


def benchmark_requests_allowed(job_id: int) -> bool:
    with DBManager() as db:
        return bool(
            db.session.execute(
                text(
                    "SELECT EXISTS(SELECT 1 FROM jobs WHERE id = :id AND status = 'running' "
                    "AND COALESCE(request_payload->>'recovery_fenced', 'false') <> 'true')"
                ),
                {"id": job_id},
            ).scalar()
        )


def finish_recovery_jobs(job_ids: list[int]) -> None:
    with DBManager() as db:
        db.session.execute(
            text(
                "UPDATE jobs SET status = 'failed', error_message = 'Nightly execution interrupted; worker drained', "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ANY(CAST(:ids AS integer[])) "
                "AND request_payload->>'recovery_fenced' = 'true'"
            ),
            {"ids": job_ids},
        )
        db.session.commit()


def record_comparison(benchmark_id, baseline_id, parameters, original):
    """Attach an explicit same-night baseline; never infer a comparison from dates."""
    with DBManager() as db:
        db.session.execute(
            text(
                "UPDATE model_provider_benchmarks SET configuration = configuration || CAST(:comparison AS jsonb) "
                "WHERE id = :id"
            ),
            {
                "id": benchmark_id,
                "comparison": json.dumps(
                    {
                        "nightly": {
                            "baseline_id": baseline_id,
                            "parameters": parameters,
                            "original": {key: original.get(key) for key in parameters},
                        }
                    }
                ),
            },
        )
        db.session.commit()
