"""
Central Manager for all Database-related actions for Logos
"""

import datetime
import json
import logging
import os
import re
import secrets
import threading
from typing import Any, Dict, List, Optional, Tuple, cast

import sqlalchemy.exc
import yaml
from dateutil.parser import isoparse
from sqlalchemy import MetaData, Table, create_engine, text
from sqlalchemy.orm import sessionmaker

from logos.dbutils.dbmodules import *
from logos.dbutils.dbmodules import JobStatus
from logos.dbutils.types import (
    Deployment,
    get_unique_models_from_deployments,
    infer_cloud_provider_type,
    normalize_provider_type,
)

# Backwards-compatible re-export (temporary; remove once all imports are migrated)
__all__ = [
    "DBManager",
    "Deployment",
    "get_unique_models_from_deployments",
]

logger = logging.getLogger(__name__)

_DB_URL = os.getenv("LOGOS_DB_URL", "postgresql://postgres:root@logos-db:5432/logosdb")
_POOL_SIZE = int(os.getenv("LOGOS_DB_POOL_SIZE", "10"))
_MAX_OVERFLOW = int(os.getenv("LOGOS_DB_MAX_OVERFLOW", "20"))
_POOL_RECYCLE = int(os.getenv("LOGOS_DB_POOL_RECYCLE", "1800"))

_ENGINE = None
_SESSION_FACTORY = None
_METADATA = MetaData()
_METADATA_REFLECTED = False
_ENGINE_LOCK = threading.Lock()
_METADATA_LOCK = threading.Lock()

DEFAULT_CLOUD_RPM_LIMIT = 5
DEFAULT_CLOUD_TPM_LIMIT = 10000
DEFAULT_LOCAL_RPM_LIMIT = 5
DEFAULT_LOCAL_TPM_LIMIT = 10000
DEFAULT_MONTHLY_BUDGET_MICRO_CENTS = 100000000
TEAM_MONTHLY_BUDGET_MICRO_CENTS = 500000000

VALID_PRIVACY_LEVELS = {
    "LOCAL",
    "CLOUD_IN_EU_BY_EU_PROVIDER",
    "CLOUD_IN_EU_BY_US_PROVIDER",
    "CLOUD_NOT_IN_EU_BY_US_PROVIDER",
}


def _choose_bucket_seconds(span_seconds: int) -> int:
    day = 86400
    if span_seconds <= day:
        return 3600
    if span_seconds <= 32 * day:
        return 86400
    if span_seconds <= 186 * day:
        return 604800
    return 2592000


_BUCKET_TO_PG_INTERVAL = {
    3600: "hour",
    86400: "day",
    604800: "week",
    2592000: "month",
}


def _bucket_to_pg_interval(bucket_seconds: int) -> str:
    return _BUCKET_TO_PG_INTERVAL.get(bucket_seconds, "day")


def _init_engine():
    global _ENGINE, _SESSION_FACTORY
    if _ENGINE is None:
        with _ENGINE_LOCK:
            if _ENGINE is None:
                _ENGINE = create_engine(
                    _DB_URL,
                    pool_size=_POOL_SIZE,
                    max_overflow=_MAX_OVERFLOW,
                    pool_pre_ping=True,
                    pool_recycle=_POOL_RECYCLE,
                )
                _SESSION_FACTORY = sessionmaker(bind=_ENGINE)
    return _ENGINE


def _ensure_metadata(engine):
    global _METADATA_REFLECTED
    if _METADATA_REFLECTED:
        return
    with _METADATA_LOCK:
        if _METADATA_REFLECTED:
            return
        _METADATA.reflect(bind=engine)
        _METADATA_REFLECTED = True


def load_postgres_env_vars_from_compose(file_path="./logos/docker-compose.yaml"):
    with open(file_path, "r", encoding="utf-8") as f:
        compose = yaml.safe_load(f)

    env = compose.get("services", {}).get("logos-db", {}).get("environment", {})
    return {
        "user": env.get("POSTGRES_USER"),
        "password": env.get("POSTGRES_PASSWORD"),
        "db": env.get("POSTGRES_DB"),
        "host": env.get("POSTGRES_HOST"),
        "port": 5432,  # compose.get("services", {}).get("logos-db", {}).get("ports", ['5432:5432'])[0].split(":")[0]
    }


def generate_logos_api_key(label: str) -> str:
    """
    Generates a logos API key.
    Every key starts with "lg", followed by
    "-" followed by the label followed by a "-".
    :return: A logos API-key for a given user.
    """
    return "lg-" + label + "-" + secrets.token_urlsafe(96)


def _stringify_error_message(value: Any) -> str:
    """Render a non-string error into a value the text column can store.

    Upstream failures arrive as OpenAI-shaped dicts (``{"message": ..., "type":
    ...}``). psycopg2 cannot adapt a dict, so passing one through turned every
    failed cloud request into an unhandled 500 that masked the real status —
    an authentication error upstream surfaced to the client as a Logos crash.
    """
    if isinstance(value, dict):
        message = value.get("message")
        if isinstance(message, str) and message:
            return message
        return json.dumps(value, separators=(",", ":"), default=str)
    if isinstance(value, (list, tuple)):
        return json.dumps(value, separators=(",", ":"), default=str)
    return str(value)


def _strip_nul(value: Any) -> Any:
    """Drop NUL characters from every string nested inside ``value``.

    Stripping has to happen on the object, not on serialised JSON: after
    ``json.dumps`` the escape for a NUL also occurs as a substring of an escaped
    backslash, so replacing it in the text would leave a dangling backslash
    behind and corrupt the document.

    Keys that differ only in NULs collapse into one, and the last one wins —
    a JSON object cannot hold both. That only arises for deliberately crafted
    payloads, and these values feed audit logs rather than behaviour, so losing
    one member of such a pair beats rejecting the request.
    """
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, dict):
        return {_strip_nul(key): _strip_nul(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_strip_nul(item) for item in value]
    return value


def _json_for_jsonb(value: Any) -> str:
    """Serialise ``value`` for a ``jsonb`` column or cast.

    ``json.dumps`` renders a NUL as the one escape sequence Postgres refuses
    inside ``jsonb`` — *unsupported Unicode escape sequence ... cannot be
    converted to text*. A single such byte anywhere in a request body therefore
    turned the logging insert into an unhandled 500, raised from
    ``auth_parse_log`` before the request ever reached a worker: a client
    replaying a conversation that had captured raw binary output got an instant
    server error on every retry, and nothing was logged either.
    """
    return json.dumps(_strip_nul(value))


def derived_reported_context_length(profile: Any) -> int:
    """Widest context window a worker profile dict has reported, in tokens.

    A profile can carry the model's context in up to three places, and any of
    them may be the only one set:

    * ``max_context_length`` — the model's own architectural limit, when the
      operator pinned it (manual override).
    * ``calibration_max_model_len`` — the ``--max-model-len`` calibration
      settled on when the model's default did not fit the pinned KV budget.
    * ``kv_cache_to_max_model_len_pairs`` — the per-KV sweep calibration ran,
      whose largest point is the widest window the node proved reachable.

    The maximum across all of them is "the largest context this model has ever
    been reported to run at" — the number the orchestrator falls back to when
    no live lane says otherwise. 0 when the profile is not a dict or none of
    the fields is a positive length.
    """
    if not isinstance(profile, dict):
        return 0

    def _as_len(value: Any) -> int:
        try:
            value = int(value)
        except (TypeError, ValueError):
            return 0
        return value if value > 0 else 0

    native = _as_len(profile.get("max_context_length"))
    native = max(native, _as_len(profile.get("calibration_max_model_len")))
    pairs = profile.get("kv_cache_to_max_model_len_pairs")
    if isinstance(pairs, list):
        for item in pairs:
            if isinstance(item, dict):
                native = max(native, _as_len(item.get("max_model_len")))
    return native


# noinspection PyUnresolvedReferences
class DBManager:
    def __init__(self):
        pass

    def create_all(self):
        Base.metadata.create_all(self.engine)

    def close(self):
        self.session.close()

    @staticmethod
    def _is_sequence_drift_integrity_error(
        exc: sqlalchemy.exc.IntegrityError,
        *,
        table_name: str,
        data: Dict[str, Any],
        has_id_column: bool,
    ) -> bool:
        if "id" in data or not has_id_column:
            return False

        diag = getattr(getattr(exc, "orig", None), "diag", None)
        constraint_name = getattr(diag, "constraint_name", None)
        if constraint_name is not None:
            return constraint_name == f"{table_name}_pkey"

        message = str(getattr(exc, "orig", exc))
        return (
            "duplicate key value violates unique constraint" in message
            and f'"{table_name}_pkey"' in message
            and "Key (id)=" in message
        )

    def _reset_sequence_for_table(self, table_name: str, *, commit: bool = True) -> bool:
        table = Base.metadata.tables.get(table_name)
        if table is None or "id" not in table.c:
            return False

        sequence_name = self.session.execute(
            text("SELECT pg_get_serial_sequence(:table_name, 'id')"),
            {"table_name": table_name},
        ).scalar()
        if not sequence_name:
            return False

        max_id = self.session.execute(text(f'SELECT MAX(id) FROM "{table_name}"')).scalar()

        if max_id is None:
            self.session.execute(
                text("SELECT setval(:sequence_name, 1, false)"),
                {"sequence_name": sequence_name},
            )
        else:
            # With is_called=true the next nextval() returns max_id + 1, which is
            # exactly what we want after importing or manually inserting rows.
            self.session.execute(
                text("SELECT setval(:sequence_name, :new_value, true)"),
                {"sequence_name": sequence_name, "new_value": int(max_id)},
            )

        if commit:
            self.session.commit()
        return True

    def insert(self, table: str, data: Dict[str, Any]) -> int:
        table_obj = Table(table, self.metadata, autoload_with=self.engine)
        insert_stmt = table_obj.insert().values(**data)
        try:
            result = self.session.execute(insert_stmt)
            self.session.commit()
            return result.inserted_primary_key[0]
        except sqlalchemy.exc.IntegrityError as exc:
            self.session.rollback()
            if self._is_sequence_drift_integrity_error(
                exc,
                table_name=table_obj.name,
                data=data,
                has_id_column="id" in table_obj.c,
            ) and self._reset_sequence_for_table(table_obj.name):
                result = self.session.execute(insert_stmt)
                self.session.commit()
                return result.inserted_primary_key[0]
            raise

    def update_log_entry_metrics(
        self,
        *,
        log_id: Optional[int] = None,
        request_id: Optional[str] = None,
        **fields: Any,
    ) -> None:
        """
        Update scheduler/runtime/completion metrics on a log_entry row.

        The log row can be targeted either by `log_id` or by `request_id`.
        """
        if log_id is None and not request_id:
            raise ValueError("Either log_id or request_id must be provided")

        allowed_fields = {
            "model_id",
            "provider_id",
            "initial_priority",
            "priority_when_scheduled",
            "queue_depth_at_enqueue",
            "queue_depth_at_schedule",
            "timeout_s",
            "scheduled_ts",
            "request_complete_ts",
            "available_vram_mb",
            "azure_rate_remaining_requests",
            "azure_rate_remaining_tokens",
            "cold_start",
            "result_status",
            "error_message",
            "queue_depth_at_arrival",
            "utilization_at_arrival",
            "queue_wait_ms",
            "api_key_id",
            "team_id",
            "user_id",
            "environment",
        }

        payload = {k: v for k, v in fields.items() if k in allowed_fields and v is not None}
        update_data: Dict[str, Any] = {}

        if request_id:
            update_data["request_id"] = request_id

        field_map = {
            "scheduled_ts": "timestamp_forwarding",
            "request_complete_ts": "timestamp_response",
            "cold_start": "was_cold_start",
        }

        for key, value in payload.items():
            db_col = field_map.get(key, key)
            if key == "result_status" and isinstance(value, ResultStatus):
                value = value.value
            if key == "error_message" and not isinstance(value, str):
                value = _stringify_error_message(value)
            update_data[db_col] = value

        if "scheduled_ts" in payload and "queue_wait_ms" not in payload:
            lookup_sql = text(
                "SELECT timestamp_request FROM log_entry "
                + ("WHERE id = :log_id" if log_id is not None else "WHERE request_id = :request_id")
            )
            lookup_params = {"log_id": log_id} if log_id is not None else {"request_id": request_id}
            row = self.session.execute(lookup_sql, lookup_params).mappings().first()
            timestamp_request = row.get("timestamp_request") if row else None
            scheduled_ts = payload.get("scheduled_ts")
            if timestamp_request and isinstance(scheduled_ts, datetime.datetime):
                delta_ms = (scheduled_ts - timestamp_request).total_seconds() * 1000
                update_data["queue_wait_ms"] = max(0.0, delta_ms)

        if not update_data:
            return

        assignments = ", ".join(f"{col} = :{col}" for col in update_data.keys())
        params = dict(update_data)
        if log_id is not None:
            params["log_id"] = log_id
            where_clause = "id = :log_id"
        else:
            params["lookup_request_id"] = request_id
            where_clause = "request_id = :lookup_request_id"

        sql = text(f"UPDATE log_entry SET {assignments} WHERE {where_clause}")
        self.session.execute(sql, params)
        self.session.commit()

    def update_request_log_metrics(
        self,
        *,
        log_id: Optional[int] = None,
        request_id: Optional[str] = None,
        **fields: Any,
    ) -> None:
        """
        Clearer alias for request lifecycle/performance updates on `log_entry`.
        """
        self.update_log_entry_metrics(log_id=log_id, request_id=request_id, **fields)

    def close_orphaned_request_logs(self, error_message: str) -> int:
        """Finalise log rows left open by a previous orchestrator process.

        A request is written on arrival and completed in-process. If the
        orchestrator is restarted (deploy, crash) while requests are in
        flight, nobody ever writes their terminal state: the rows keep a NULL
        `result_status` and no `timestamp_response`, and every "running
        requests" view derived from them shows them forever.

        Only rows that predate this process can be orphans, so this must run
        at startup before the first request is accepted — after that a NULL
        status is a request that is genuinely still running.

        Returns the number of rows closed.
        """
        sql = text(
            """
            UPDATE log_entry
               SET result_status = 'error',
                   timestamp_response = NOW(),
                   error_message = COALESCE(error_message, :error_message)
             WHERE result_status IS NULL
               AND timestamp_response IS NULL
            """
        )
        result = self.session.execute(sql, {"error_message": error_message})
        self.session.commit()
        return int(result.rowcount or 0)

    def update(self, table_name: str, record_id: int, data: Dict[str, Any]) -> None:
        table = Table(table_name, self.metadata, autoload_with=self.engine)
        update_stmt = table.update().where(table.c.id == record_id).values(**data)
        self.session.execute(update_stmt)
        self.session.commit()

    def delete(self, table_name: str, record_id: int) -> None:
        table = Table(table_name, self.metadata, autoload_with=self.engine)
        delete_stmt = table.delete().where(table.c.id == record_id)
        self.session.execute(delete_stmt)
        self.session.commit()

    def fetch_by_id(self, table_name: str, record_id: int) -> Optional[Dict[str, Any]]:
        table = Table(table_name, self.metadata, autoload_with=self.engine)
        result = self.session.execute(table.select().where(table.c.id == record_id)).mappings().first()
        return dict(result) if result else None

    def create_job_record(
        self,
        payload: dict,
        api_key_id: Optional[int],
        team_id: Optional[int],
        user_id: Optional[int],
        environment: Optional[str],
        status: str = JobStatus.PENDING.value,
    ) -> int:
        """
        Persist a new async job with profile isolation.

        Returns:
            Job ID
        """
        row = self.session.execute(
            text(
                """
                 INSERT INTO jobs (status, request_payload, api_key_id, team_id, user_id, environment)
                 VALUES (:status, CAST(:payload AS jsonb), :aki, :tid, :uid, :env) RETURNING id
                 """
            ),
            {
                "status": status,
                "payload": _json_for_jsonb(payload),
                "aki": api_key_id,
                "tid": team_id,
                "uid": user_id,
                "env": environment,
            },
        ).fetchone()
        self.session.commit()
        return row.id

    def get_model_provider_benchmark_target(self, model_provider_id: int) -> Optional[Dict[str, Any]]:
        """Resolve the endpoint and credential for one exact provider-model pair."""
        row = (
            self.session.execute(
                text(
                    """
                SELECT mp.id AS model_provider_id,
                       m.id AS model_id,
                       m.name AS model_name,
                       p.id AS provider_id,
                       p.name AS provider_name,
                       p.provider_type AS provider_type,
                       p.privacy_level AS privacy_level,
                       p.cloud_provider_type AS cloud_provider_type,
                       p.base_url AS base_url,
                       COALESCE(NULLIF(mp.endpoint, ''), NULLIF(p.base_url, '')) AS target,
                       COALESCE(NULLIF(mp.api_key, ''), NULLIF(p.api_key, '')) AS api_key
                FROM model_provider mp
                JOIN models m ON m.id = mp.model_id
                JOIN providers p ON p.id = mp.provider_id
                WHERE mp.id = :model_provider_id
                """
                ),
                {"model_provider_id": int(model_provider_id)},
            )
            .mappings()
            .first()
        )
        return dict(row) if row else None

    def find_active_model_benchmark_job(
        self,
        provider_id: int,
        stale_after_seconds: int = 60,
    ) -> Optional[Dict[str, Any]]:
        """Expire stale benchmark rows, then return the newest active job."""
        stale_after_seconds = max(1, int(stale_after_seconds))
        stale_error = f"Benchmark stopped updating for {stale_after_seconds} seconds"
        expired = self.session.execute(
            text(
                """
                UPDATE jobs
                SET status = 'failed',
                    error_message = :stale_error,
                    updated_at = CURRENT_TIMESTAMP
                WHERE environment = 'model-provider-benchmark'
                  AND status IN ('pending', 'running')
                  AND (request_payload ->> 'provider_id')::integer = :provider_id
                  AND COALESCE(updated_at, created_at)
                      < CURRENT_TIMESTAMP - CAST(:stale_after_seconds AS integer) * INTERVAL '1 second'
                """
            ),
            {
                "provider_id": int(provider_id),
                "stale_after_seconds": stale_after_seconds,
                "stale_error": stale_error,
            },
        )
        if expired.rowcount:
            logger.warning("Expired %d stale benchmark job(s) for provider %d", expired.rowcount, provider_id)

        row = (
            self.session.execute(
                text(
                    """
                SELECT id, status, request_payload, created_at, updated_at
                FROM jobs
                WHERE environment = 'model-provider-benchmark'
                  AND status IN ('pending', 'running')
                  AND (request_payload ->> 'provider_id')::integer = :provider_id
                ORDER BY created_at DESC
                LIMIT 1
                """
                ),
                {"provider_id": int(provider_id)},
            )
            .mappings()
            .first()
        )
        return dict(row) if row else None

    def touch_model_benchmark_job(self, job_id: int) -> bool:
        """Renew one active benchmark lease."""
        updated = self.session.execute(
            text(
                """
                UPDATE jobs SET updated_at = CURRENT_TIMESTAMP
                WHERE id = :job_id
                  AND environment = 'model-provider-benchmark'
                  AND status IN ('pending', 'running')
                """
            ),
            {"job_id": int(job_id)},
        )
        self.session.commit()
        return bool(updated.rowcount)

    def cancel_model_benchmark_job(self, job_id: int, reason: str) -> bool:
        """Fail one active benchmark job and release its logical lease."""
        updated = self.session.execute(
            text(
                """
                UPDATE jobs
                SET status = 'failed', error_message = :reason, updated_at = CURRENT_TIMESTAMP
                WHERE id = :job_id
                  AND environment = 'model-provider-benchmark'
                  AND status IN ('pending', 'running')
                """
            ),
            {"job_id": int(job_id), "reason": reason[:1000]},
        )
        self.session.commit()
        return bool(updated.rowcount)

    def insert_model_provider_benchmark(
        self,
        *,
        model_provider_id: int,
        configuration: Dict[str, Any],
        dataset: str,
        sample_size: int,
        metrics: Dict[str, Any],
        recorded_at: datetime.datetime,
    ) -> int:
        """Persist one complete benchmark summary and return its id."""
        row = self.session.execute(
            text(
                """
                INSERT INTO model_provider_benchmarks
                    (model_provider_id, configuration, dataset, sample_size, metrics, recorded_at)
                VALUES
                    (:model_provider_id, CAST(:configuration AS jsonb), :dataset, :sample_size,
                     CAST(:metrics AS jsonb), :recorded_at)
                RETURNING id
                """
            ),
            {
                "model_provider_id": int(model_provider_id),
                "configuration": _json_for_jsonb(configuration),
                "dataset": dataset,
                "sample_size": int(sample_size),
                "metrics": _json_for_jsonb(metrics),
                "recorded_at": recorded_at,
            },
        ).fetchone()
        self.session.commit()
        return int(row.id)

    def update_job_status(
        self,
        job_id: int,
        status: str,
        result_payload: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """
        Update job status and optional payloads.
        """
        update_data = {
            "status": status,
            "updated_at": datetime.datetime.now(datetime.timezone.utc),
        }
        if result_payload is not None:
            # jobs.result_payload is jsonb and the reflected update binds this
            # dict directly, so SQLAlchemy serialises it — _json_for_jsonb would
            # store its string as a JSON scalar instead of an object. A NUL in a
            # model's answer would otherwise fail the write and leave the job
            # without its result.
            update_data["result_payload"] = _strip_nul(result_payload)
        if error_message is not None:
            update_data["error_message"] = (
                error_message if isinstance(error_message, str) else _stringify_error_message(error_message)
            )
        self.update("jobs", job_id, update_data)

    def record_benchmark_request_started(self, job_id: int) -> None:
        """Atomically advance an active benchmark's visible sample progress."""
        self.session.execute(
            text(
                """
                UPDATE jobs
                SET result_payload = jsonb_set(
                        COALESCE(result_payload, '{}'::jsonb),
                        '{started_samples}',
                        to_jsonb(LEAST(
                            COALESCE((result_payload->>'started_samples')::integer, 0) + 1,
                            COALESCE((result_payload->>'total_samples')::integer, 0)
                        )),
                        true
                    ),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :job_id
                  AND status = 'running'
                  AND result_payload->>'stage' = 'benchmarking'
                """
            ),
            {"job_id": int(job_id)},
        )
        self.session.commit()

    def get_job(self, job_id: int) -> Optional[Dict[str, Any]]:
        """
        Fetch job state by id.
        """
        return self.fetch_by_id("jobs", job_id)

    def add_provider(
        self,
        logos_key: str,
        provider_name: str,
        base_url: str,
        api_key: str,
        auth_name: str,
        auth_format: str,
        provider_type: str,
        cloud_provider_type: str = None,
        privacy_level: str = None,
    ) -> Tuple[dict, int]:

        if not self.check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500

        original_provider_type = provider_type or ""

        # Ollama is no longer a provider type — every worker lane runs vLLM.
        # Refuse it explicitly instead of letting it through as an unknown
        # type the DB enum would reject with a raw constraint error.
        if original_provider_type.strip().lower() == "ollama":
            return (
                {
                    "error": (
                        "provider_type 'ollama' is no longer supported: every worker lane runs vLLM. "
                        "Use 'logosnode' for worker-backed providers."
                    )
                },
                400,
            )

        provider_type = normalize_provider_type(original_provider_type)

        if not provider_type:
            return {"error": "provider_type is required"}, 400

        if not cloud_provider_type:
            cloud_provider_type = infer_cloud_provider_type(original_provider_type, base_url=base_url)

        if not privacy_level or privacy_level not in VALID_PRIVACY_LEVELS:
            return {"error": f"privacy_level is required and must be one of {sorted(VALID_PRIVACY_LEVELS)}"}, 400

        pk = self.insert(
            "providers",
            {
                "name": provider_name,
                "base_url": base_url,
                "auth_name": auth_name,
                "auth_format": auth_format,
                "provider_type": provider_type,
                "api_key": api_key,
                "cloud_provider_type": cloud_provider_type,
                "privacy_level": privacy_level,
            },
        )

        return {"result": "Created Provider.", "provider-id": pk}, 200

    def get_policy(self, logos_key: str, policy_id: int):
        sql = text(
            """
                   SELECT p.*
                   FROM policies p
                            JOIN api_keys ak ON (
                       p.api_key_id = ak.id
                           OR p.team_id = ak.team_id
                       )
                   WHERE ak.key_value = :logos_key
                     AND p.id = :policy_id LIMIT 1
                   """
        )
        result = self.session.execute(sql, {"logos_key": logos_key, "policy_id": int(policy_id)}).mappings().first()
        if result is None:
            if self.check_authorization(logos_key):
                return self.fetch_by_id("policies", policy_id) or {"error": "Not Found"}
            return {"error": "Not Found"}
        return dict(result)

    def add_token_type(self, name: str, description: str = "", exist_ok=True):
        if token_id := self.get_token_name(name):
            if not exist_ok:
                return {"error": "Token name already exists"}, 500
            else:
                return {
                    "result": "Created Token Type.",
                    "token-type-id": token_id,
                }, 200
        pk = self.insert("token_types", {"name": name, "description": description})
        return {"result": "Created Token Type.", "token-type-id": pk}, 200

    def get_token_name(self, name):
        sql = text(
            """
                   SELECT *
                   FROM token_types
                   WHERE name = :name
                   """
        )
        entity = self.session.execute(sql, {"name": name}).fetchone()
        if entity is not None:
            return entity.id
        return None

    def connect_model_provider(
        self,
        logos_key: str,
        model_id: int,
        provider_id: int,
        api_key: str = None,
        endpoint: str = None,
    ):
        if not self.check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500

        upsert_sql = text(
            """
            INSERT INTO model_provider (provider_id, model_id, api_key, endpoint)
            VALUES (:pid, :mid, :api_key, :endpoint) ON CONFLICT (model_id, provider_id)
            DO
            UPDATE SET
               api_key = EXCLUDED.api_key,
               endpoint = EXCLUDED.endpoint
            RETURNING id
            """
        )
        result = self.session.execute(
            upsert_sql,
            {
                "pid": int(provider_id),
                "mid": int(model_id),
                "api_key": api_key,
                "endpoint": endpoint or None,
            },
        ).fetchone()
        self.session.commit()

        return {"result": f"Connected Model to Provider. ID: {result.id}."}, 200

    def sync_logosnode_capabilities(self, provider_id: int, model_names: list[str]) -> list[str]:
        """Auto-sync models announced by a logosnode worker into the DB.

        For each model name the worker advertises:
        1. Ensure a row exists in ``models`` (create if missing).
        2. Ensure a ``model_provider`` link exists for this provider.
        3. Ensure a ``logosnode_provider_keys`` row exists for this provider.

        Team permissions are NOT granted automatically — an admin must assign
        access per team via the models tab.

        Stale ``model_provider`` links (models the worker no longer advertises)
        are removed so that the deployment queries stay in sync with the worker's
        actual capabilities.

        Returns the names of any *newly inserted* models (i.e. names not
        previously present in the ``models`` table). Callers use this to know
        when caches keyed on ``models`` content (e.g. the in-memory classifier)
        are now stale.
        """
        pid = int(provider_id)

        # Ensure logosnode_provider_keys entry exists for this provider
        self.session.execute(
            text(
                """
                INSERT INTO logosnode_provider_keys (provider_id)
                VALUES (:pid)
                ON CONFLICT (provider_id) DO NOTHING
            """
            ),
            {"pid": pid},
        )

        # Get current model_provider links for this logosnode provider
        existing_rows = self.session.execute(
            text(
                """
                SELECT mp.model_id, m.name
                FROM model_provider mp
                JOIN models m ON m.id = mp.model_id
                JOIN providers p ON p.id = mp.provider_id
                WHERE mp.provider_id = :pid AND p.provider_type = 'logosnode'
            """
            ),
            {"pid": pid},
        ).fetchall()
        existing_by_name: dict[str, int] = {row.name: row.model_id for row in existing_rows}

        announced = set(model_names)
        current = set(existing_by_name.keys())
        newly_inserted: list[str] = []

        # Remove stale links (models no longer announced)
        for stale_name in current - announced:
            stale_mid = existing_by_name[stale_name]
            self.session.execute(
                text("DELETE FROM model_provider WHERE provider_id = :pid AND model_id = :mid"),
                {"pid": pid, "mid": stale_mid},
            )

        # Add missing models & links
        for model_name in announced - current:
            # Upsert model row
            row = self.session.execute(
                text("SELECT id FROM models WHERE name = :name"),
                {"name": model_name},
            ).fetchone()
            if row is not None:
                mid = row.id
            else:
                mid = (
                    self.session.execute(
                        text(
                            """
                        INSERT INTO models (name, weight_latency, weight_accuracy,
                                            weight_cost, weight_quality, tags, description)
                        VALUES (:name, 0, 0, 0, 0, '', '')
                        RETURNING id
                    """
                        ),
                        {"name": model_name},
                    )
                    .fetchone()
                    .id
                )
                newly_inserted.append(model_name)

            # Upsert model_provider link
            self.session.execute(
                text(
                    """
                    INSERT INTO model_provider (provider_id, model_id)
                    VALUES (:pid, :mid)
                    ON CONFLICT DO NOTHING
                """
                ),
                {"pid": pid, "mid": mid},
            )

        self.session.commit()
        return newly_inserted

    def get_azure_providers(self) -> list[Dict[str, Any]]:
        """Return all Azure cloud providers with the fields needed to query Azure.

        Used by the Azure deployment auto-sync to discover which resources to
        poll. ``api_key`` is the provider-level resource key.
        """
        rows = self.session.execute(
            text(
                """
                SELECT id, name, base_url, api_key
                FROM providers
                WHERE provider_type = 'cloud' AND cloud_provider_type = 'azure'
                """
            )
        ).fetchall()
        return [{"id": r.id, "name": r.name, "base_url": r.base_url, "api_key": r.api_key} for r in rows]

    def sync_azure_deployments(self, provider_id: int, deployments: list[Dict[str, str]]) -> Dict[str, Any]:
        """Auto-sync the live Azure deployment list into the DB.

        ``deployments`` is a list of ``{"model_name": str, "endpoint": str}`` —
        one entry per model that should be reachable through this provider, with
        the fully-qualified Azure endpoint URL (deployment name + api-version
        already baked in).

        For each entry:
        1. Ensure a row exists in ``models`` (create if missing).
        2. Upsert the ``model_provider`` link, refreshing the ``endpoint`` (this
           also corrects drift, e.g. a deployment now serving a different model).
           The per-model ``api_key`` override is left untouched.

        ``model_provider`` links for this Azure provider whose model is no longer
        in the live list are pruned, so the DB mirrors the resource. Team
        permissions are NOT granted automatically — an admin assigns access per
        team via the models tab.

        Returns ``{"new_models": [names of newly inserted model rows],
        "changed": bool}``. ``changed`` is True when anything that affects
        routing changed (a link was inserted, an endpoint updated, or a stale
        link pruned) so the caller can refresh runtime state; ``new_models``
        drives the (more expensive) classifier rebuild.
        """
        pid = int(provider_id)
        desired = {d["model_name"]: d["endpoint"] for d in deployments}

        existing_rows = self.session.execute(
            text(
                """
                SELECT mp.model_id, m.name, mp.endpoint
                FROM model_provider mp
                JOIN models m ON m.id = mp.model_id
                WHERE mp.provider_id = :pid
                """
            ),
            {"pid": pid},
        ).fetchall()
        existing_by_name = {row.name: row.model_id for row in existing_rows}
        existing_endpoint = {row.name: row.endpoint for row in existing_rows}

        changed = False

        # Prune links for models no longer deployed on this Azure resource.
        for stale_name in set(existing_by_name) - set(desired):
            self.session.execute(
                text("DELETE FROM model_provider WHERE provider_id = :pid AND model_id = :mid"),
                {"pid": pid, "mid": existing_by_name[stale_name]},
            )
            changed = True

        newly_inserted: list[str] = []
        for model_name, endpoint in desired.items():
            row = self.session.execute(
                text("SELECT id FROM models WHERE name = :name"),
                {"name": model_name},
            ).fetchone()
            if row is not None:
                mid = row.id
            else:
                mid = (
                    self.session.execute(
                        text(
                            """
                            INSERT INTO models (name, weight_latency, weight_accuracy,
                                                weight_cost, weight_quality, tags, description)
                            VALUES (:name, 0, 0, 0, 0, '', '')
                            RETURNING id
                            """
                        ),
                        {"name": model_name},
                    )
                    .fetchone()
                    .id
                )
                newly_inserted.append(model_name)

            # A new link for this provider, or an endpoint that drifted, changes
            # routing and must be reflected in the runtime registry.
            if model_name not in existing_by_name or existing_endpoint.get(model_name) != endpoint:
                changed = True

            # Upsert the link and refresh the endpoint; preserve any api_key override.
            self.session.execute(
                text(
                    """
                    INSERT INTO model_provider (provider_id, model_id, endpoint)
                    VALUES (:pid, :mid, :endpoint)
                    ON CONFLICT (model_id, provider_id)
                    DO UPDATE SET endpoint = EXCLUDED.endpoint
                    """
                ),
                {"pid": pid, "mid": mid, "endpoint": endpoint},
            )

        self.session.commit()
        return {"new_models": newly_inserted, "changed": changed or bool(newly_inserted)}

    def get_provider_config(self, provider_id: int) -> Optional[Dict[str, Any]]:
        """
        Retrieve SDI provider-level configuration from providers table.

        Args:
            provider_id: Provider ID to query

        Returns:
            Dictionary with configuration fields if found, None otherwise
        """
        sql = text(
            """
            SELECT id, ollama_admin_url, total_vram_mb, parallel_capacity,
                   keep_alive_seconds, max_loaded_models, updated_at
            FROM providers
            WHERE id = :provider_id
        """
        )

        result = self.session.execute(sql, {"provider_id": provider_id}).fetchone()

        if result:
            return {
                "provider_id": result[0],
                "ollama_admin_url": result[1],
                "total_vram_mb": result[2],
                "parallel_capacity": result[3],
                "keep_alive_seconds": result[4],
                "max_loaded_models": result[5],
                "updated_at": result[6],
            }
        return None

    def get_provider_auth(self, provider_id: int) -> Optional[Dict[str, Any]]:
        """
        Retrieve provider auth header formatting and API key.

        Returns:
            Dict with auth_name, auth_format, api_key (may be None) or None if provider not found.
        """
        sql = text(
            """
            SELECT id,
                   auth_name,
                   auth_format,
                   api_key
            FROM providers
            WHERE id = :provider_id
        """
        )

        result = self.session.execute(sql, {"provider_id": provider_id}).fetchone()
        if not result:
            return None

        return {
            "provider_id": result[0],
            "auth_name": result[1],
            "auth_format": result[2],
            "api_key": result[3],
        }

    def update_provider_sdi_config(
        self,
        logos_key: str,
        provider_id: int,
        ollama_admin_url: str = None,
        total_vram_mb: int = None,
        parallel_capacity: int = None,
        keep_alive_seconds: int = None,
        max_loaded_models: int = None,
    ) -> Tuple[dict, int]:
        """
        Update SDI configuration fields in providers table.

        Args:
            logos_key: Authorization key (root user only)
            provider_id: Provider ID to configure
            ollama_admin_url: Internal admin endpoint of the worker (e.g., http://gpu-vm-1:5000).
                Legacy column name — the value is the worker's base URL.
            total_vram_mb: Total VRAM capacity in MB (e.g., 49152 for 48GB)
            parallel_capacity: Max concurrent requests per model
            keep_alive_seconds: How long models stay loaded when idle
            max_loaded_models: Max models that can be loaded simultaneously

        Returns:
            Tuple of (result dict, status code)
        """
        if not self.check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500

        # Build UPDATE SET clauses for non-None fields
        updates = []
        params = {"provider_id": int(provider_id)}

        if ollama_admin_url is not None:
            updates.append("ollama_admin_url = :ollama_admin_url")
            params["ollama_admin_url"] = ollama_admin_url
        if total_vram_mb is not None:
            updates.append("total_vram_mb = :total_vram_mb")
            params["total_vram_mb"] = int(total_vram_mb)
        if parallel_capacity is not None:
            updates.append("parallel_capacity = :parallel_capacity")
            params["parallel_capacity"] = int(parallel_capacity)
        if keep_alive_seconds is not None:
            updates.append("keep_alive_seconds = :keep_alive_seconds")
            params["keep_alive_seconds"] = int(keep_alive_seconds)
        if max_loaded_models is not None:
            updates.append("max_loaded_models = :max_loaded_models")
            params["max_loaded_models"] = int(max_loaded_models)

        if not updates:
            return {"error": "No fields to update"}, 400

        updates.append("updated_at = CURRENT_TIMESTAMP")
        update_clause = ", ".join(updates)

        sql = text(
            f"""
            UPDATE providers
            SET {update_clause}
            WHERE id = :provider_id
            RETURNING id
        """
        )

        result = self.session.execute(sql, params)
        self.session.commit()
        row = result.fetchone()

        if not row:
            return {"error": "Provider not found"}, 404

        return {
            "result": "Updated provider SDI configuration",
            "provider_id": row[0],
        }, 200

    def insert_provider_snapshot(
        self,
        provider_id: int,
        total_models_loaded: int,
        total_vram_used_bytes: int,
        loaded_models: List[Dict[str, Any]],
        snapshot_ts: Optional[datetime.datetime] = None,
        total_memory_bytes: Optional[int] = None,
        free_memory_bytes: Optional[int] = None,
        snapshot_source: Optional[str] = None,
        runtime_payload: Optional[Dict[str, Any]] = None,
        scheduler_signals: Optional[Dict[str, Any]] = None,
        poll_success: bool = True,
        error_message: Optional[str] = None,
    ) -> int:
        """
        Insert provider snapshot into the monitoring table.

        Args:
            provider_id: Provider ID (FK to providers.id)
            total_models_loaded: Number of models currently loaded
            total_vram_used_bytes: Total VRAM used by all loaded models (in bytes)
            loaded_models: List of model details (name, size_vram, expires_at)
            snapshot_ts: Snapshot timestamp from worker/runtime
            total_memory_bytes: Total runtime memory capacity in bytes
            free_memory_bytes: Free runtime memory in bytes
            snapshot_source: Telemetry source label
            poll_success: Whether the poll was successful
            error_message: Error message if poll failed
        """
        sql = text(
            """
            INSERT INTO provider_snapshots (
                provider_id,
                snapshot_ts,
                total_models_loaded,
                total_vram_used_bytes,
                total_memory_bytes,
                free_memory_bytes,
                loaded_models,
                snapshot_source,
                runtime_payload,
                scheduler_signals,
                poll_success,
                error_message
            ) VALUES (
                :provider_id,
                COALESCE(:snapshot_ts, CURRENT_TIMESTAMP),
                :total_models_loaded,
                :total_vram_used_bytes,
                :total_memory_bytes,
                :free_memory_bytes,
                :loaded_models,
                :snapshot_source,
                :runtime_payload,
                :scheduler_signals,
                :poll_success,
                :error_message
            )
            RETURNING id
        """
        )

        result = self.session.execute(
            sql,
            {
                "provider_id": provider_id,
                "snapshot_ts": snapshot_ts,
                "total_models_loaded": total_models_loaded,
                "total_vram_used_bytes": total_vram_used_bytes,
                "total_memory_bytes": (int(total_memory_bytes) if total_memory_bytes is not None else None),
                "free_memory_bytes": (int(free_memory_bytes) if free_memory_bytes is not None else None),
                "loaded_models": _json_for_jsonb(loaded_models),
                "snapshot_source": snapshot_source or "unknown",
                "runtime_payload": _json_for_jsonb(runtime_payload or {}),
                "scheduler_signals": _json_for_jsonb(scheduler_signals or {}),
                "poll_success": poll_success,
                "error_message": error_message,
            },
        ).fetchone()
        self.session.commit()
        return int(result[0]) if result is not None else 0

    def upsert_model_profiles(
        self,
        provider_id: int,
        profiles: Dict[str, Dict[str, Any]],
    ) -> int:
        """Upsert model profiles from worker runtime into the model_profiles table.

        ``max_reported_context_length`` is maintained as the historic maximum:
        the ON CONFLICT clause keeps the larger of the stored value and the
        freshly derived one, so a later calibration that reports a narrower
        window (e.g. on a node with less VRAM) cannot shrink the widest window
        this model has ever been reported at. That high-water mark is what the
        orchestrator falls back to for a model's context when every workernode
        is offline. Rows created before the column existed hold NULL, and
        GREATEST with a NULL argument returns NULL in Postgres — hence the
        COALESCE, so one upsert after the migration settles the mark instead
        of leaving it NULL forever.

        Args:
            provider_id: Provider ID (FK to providers.id)
            profiles: Dict of model_name -> profile dict (from runtime_payload.model_profiles)

        Returns:
            Number of profiles upserted.
        """
        if not profiles:
            return 0

        sql = text(
            """
            INSERT INTO model_profiles (
                provider_id, model_name,
                base_residency_mb, loaded_vram_mb, sleeping_residual_mb,
                kv_budget_mb, disk_size_bytes, engine,
                tensor_parallel_size, kv_per_token_bytes, max_context_length,
                max_reported_context_length,
                residency_source, measurement_count, last_measured_at,
                observed_gpu_memory_utilization, min_gpu_memory_utilization_to_load,
                updated_at
            ) VALUES (
                :provider_id, :model_name,
                :base_residency_mb, :loaded_vram_mb, :sleeping_residual_mb,
                :kv_budget_mb, :disk_size_bytes, :engine,
                :tensor_parallel_size, :kv_per_token_bytes, :max_context_length,
                :max_reported_context_length,
                :residency_source, :measurement_count, :last_measured_at,
                :observed_gpu_memory_utilization, :min_gpu_memory_utilization_to_load,
                CURRENT_TIMESTAMP
            )
            ON CONFLICT (provider_id, model_name) DO UPDATE SET
                base_residency_mb = EXCLUDED.base_residency_mb,
                loaded_vram_mb = EXCLUDED.loaded_vram_mb,
                sleeping_residual_mb = EXCLUDED.sleeping_residual_mb,
                kv_budget_mb = EXCLUDED.kv_budget_mb,
                disk_size_bytes = EXCLUDED.disk_size_bytes,
                engine = EXCLUDED.engine,
                tensor_parallel_size = EXCLUDED.tensor_parallel_size,
                kv_per_token_bytes = EXCLUDED.kv_per_token_bytes,
                max_context_length = EXCLUDED.max_context_length,
                max_reported_context_length = GREATEST(
                    COALESCE(model_profiles.max_reported_context_length, 0),
                    EXCLUDED.max_reported_context_length
                ),
                residency_source = EXCLUDED.residency_source,
                measurement_count = EXCLUDED.measurement_count,
                last_measured_at = EXCLUDED.last_measured_at,
                observed_gpu_memory_utilization = EXCLUDED.observed_gpu_memory_utilization,
                min_gpu_memory_utilization_to_load = EXCLUDED.min_gpu_memory_utilization_to_load,
                updated_at = CURRENT_TIMESTAMP
        """
        )

        count = 0
        for model_name, data in profiles.items():
            if not isinstance(data, dict):
                continue
            epoch = data.get("last_measured_epoch")
            last_measured_at = (
                datetime.datetime.fromtimestamp(epoch, tz=datetime.timezone.utc) if epoch and float(epoch) > 0 else None
            )
            self.session.execute(
                sql,
                {
                    "provider_id": provider_id,
                    "model_name": str(model_name),
                    "base_residency_mb": data.get("base_residency_mb"),
                    "loaded_vram_mb": data.get("loaded_vram_mb"),
                    "sleeping_residual_mb": data.get("sleeping_residual_mb"),
                    "kv_budget_mb": data.get("kv_budget_mb"),
                    "disk_size_bytes": data.get("disk_size_bytes"),
                    "engine": data.get("engine"),
                    "tensor_parallel_size": data.get("tensor_parallel_size"),
                    "kv_per_token_bytes": data.get("kv_per_token_bytes"),
                    "max_context_length": data.get("max_context_length"),
                    "max_reported_context_length": derived_reported_context_length(data),
                    "residency_source": data.get("residency_source"),
                    "measurement_count": int(data.get("measurement_count", 0) or 0),
                    "last_measured_at": last_measured_at,
                    "observed_gpu_memory_utilization": data.get("observed_gpu_memory_utilization"),
                    "min_gpu_memory_utilization_to_load": data.get("min_gpu_memory_utilization_to_load"),
                },
            )
            count += 1
        self.session.commit()
        return count

    def get_historic_max_context_by_model(self) -> Dict[str, int]:
        """Model name -> widest context ever reported for it, across providers.

        Reads the ``max_reported_context_length`` high-water mark
        :meth:`upsert_model_profiles` maintains and reduces each model to the
        maximum over every provider that has ever reported it. Only models with
        a positive (i.e. actually reported) window are returned; a model that
        was never calibrated to a known context is absent, so callers treat a
        missing entry as "unknown" rather than zero.

        This is the orchestrator's durable view of a model's context: it
        survives every workernode going offline and an orchestrator restart,
        which is exactly when a live runtime snapshot would say nothing.
        """
        sql = text(
            """
            SELECT model_name, MAX(max_reported_context_length) AS max_context
            FROM model_profiles
            WHERE max_reported_context_length > 0
            GROUP BY model_name
        """
        )
        result = self.session.execute(sql)
        historic: Dict[str, int] = {}
        for model_name, max_context in result:
            value = int(max_context or 0)
            if value > 0:
                historic[str(model_name)] = value
        return historic

    def upsert_calibration_probe_log(
        self,
        provider_id: int,
        model_name: str,
        recorded_at: Optional[datetime.datetime],
        payload: Dict[str, Any],
        log_text: Optional[str] = None,
    ) -> None:
        """Upsert a calibration probe log from a worker's calibration_probe_log event.

        Keeps only the most recent row per (provider_id, model_name) — same
        ON CONFLICT DO UPDATE pattern as upsert_model_profiles above.

        Args:
            provider_id: Provider ID (FK to providers.id) — the worker node.
            model_name: The model the probe attempted to load.
            recorded_at: Timestamp the worker emitted the event, if known.
            payload: Structured probe summary (see LogosBridgeClient.
                _record_calibration_probe_log on the worker side for the
                exact shape) — must NOT contain "log_text" (caller pops it
                before calling, so it isn't duplicated into the summary
                JSONB column below).
            log_text: Full raw calibration log for this (provider, model),
                stored separately so it doesn't bloat/duplicate `summary`.
        """
        sql = text(
            """
            INSERT INTO calibration_probe_logs (
                provider_id, model_name,
                success, probe_command, error,
                unsupported_reason, node_unhealthy_reason,
                summary, log_text, recorded_at, updated_at
            ) VALUES (
                :provider_id, :model_name,
                :success, :probe_command, :error,
                :unsupported_reason, :node_unhealthy_reason,
                :summary, :log_text, :recorded_at, CURRENT_TIMESTAMP
            )
            ON CONFLICT (provider_id, model_name) DO UPDATE SET
                success = EXCLUDED.success,
                probe_command = EXCLUDED.probe_command,
                error = EXCLUDED.error,
                unsupported_reason = EXCLUDED.unsupported_reason,
                node_unhealthy_reason = EXCLUDED.node_unhealthy_reason,
                summary = EXCLUDED.summary,
                log_text = EXCLUDED.log_text,
                recorded_at = EXCLUDED.recorded_at,
                updated_at = CURRENT_TIMESTAMP
            WHERE calibration_probe_logs.recorded_at IS NULL
               OR EXCLUDED.recorded_at IS NULL
               OR EXCLUDED.recorded_at > calibration_probe_logs.recorded_at
        """
        )
        self.session.execute(
            sql,
            {
                "provider_id": provider_id,
                "model_name": model_name,
                "success": bool(payload.get("success", False)),
                "probe_command": payload.get("probe_command") or None,
                "error": payload.get("error") or None,
                "unsupported_reason": payload.get("unsupported_reason"),
                "node_unhealthy_reason": payload.get("node_unhealthy_reason"),
                "summary": _json_for_jsonb(payload),
                "log_text": log_text or None,
                "recorded_at": recorded_at,
            },
        )
        self.session.commit()

    def get_calibration_probe_logs_by_model(self, model_name: str) -> list[Dict[str, Any]]:
        """Every node's most recent calibration probe log for one model.

        Used by the webservice's model-error-report page to show real
        per-node log text instead of mocked fixtures.
        """
        sql = text(
            """
            SELECT cpl.provider_id, p.name AS provider_name, cpl.success,
                   cpl.probe_command, cpl.error, cpl.log_text,
                   cpl.recorded_at, cpl.updated_at
            FROM calibration_probe_logs cpl
            JOIN providers p ON p.id = cpl.provider_id
            WHERE cpl.model_name = :model_name
            ORDER BY cpl.provider_id
        """
        )
        rows = self.session.execute(sql, {"model_name": model_name}).fetchall()
        return [dict(row._mapping) for row in rows]

    def get_provider_vram_stats(
        self,
        logos_key: str,
        day: str,
        bucket_seconds: int = 5,  # kept for signature compatibility; ignored
    ) -> Tuple[Dict[str, Any], int]:
        """
        Return per-provider VRAM snapshots for a single UTC day. No bucketing/zero-fill; raw rows only.

        `day` is required (YYYY-MM-DD or ISO date). If no rows exist for that day, return
        an empty payload instead of an HTTP error so dashboards can render an empty state.
        """
        if not self.user_authorization(logos_key):
            return {"error": "Unknown user."}, 500

        tz_utc = datetime.timezone.utc

        # Date range resolution: required day
        try:
            parsed_day = isoparse(day)
        except Exception:
            return {"error": f"Invalid day format: {day}"}, 400

        day_date = parsed_day.date()
        start_dt = datetime.datetime.combine(day_date, datetime.time.min, tzinfo=tz_utc)
        end_dt = start_dt + datetime.timedelta(days=1)

        now = datetime.datetime.now(tz_utc)
        if start_dt > now:
            return {"error": "Requested day is in the future."}, 400
        # Clamp end to "now" if requesting today
        if end_dt > now:
            end_dt = now

        params = {
            "start_ts": start_dt,
            "end_ts": end_dt,
        }

        sql = text(
            """
            SELECT
                s.id,
                s.provider_id,
                p.name AS provider_name,
                s.snapshot_ts,
                s.total_vram_used_bytes,
                s.total_memory_bytes,
                s.free_memory_bytes,
                s.total_models_loaded,
                s.loaded_models,
                s.scheduler_signals,
                p.total_vram_mb,
                MAX(COALESCE(s.total_memory_bytes, s.total_vram_used_bytes))
                    OVER (PARTITION BY s.provider_id) AS capacity_bytes
            FROM provider_snapshots s
            LEFT JOIN providers p
              ON p.id = s.provider_id
            WHERE s.poll_success = TRUE
              AND s.snapshot_ts >= :start_ts
              AND s.snapshot_ts < :end_ts
            ORDER BY s.provider_id, s.snapshot_ts
        """
        )

        try:
            rows = self.session.execute(sql, params).fetchall()
            if not rows:
                return {"providers": []}, 200

            providers_data: Dict[int, Dict[str, Any]] = {}

            for (
                snapshot_id,
                pid,
                provider_name,
                ts,
                used_bytes,
                total_memory_bytes,
                free_memory_bytes,
                models_loaded,
                loaded_models,
                scheduler_signals,
                total_vram_mb,
                capacity_bytes,
            ) in rows:
                used = int(used_bytes or 0)
                configured_bytes = int(total_vram_mb or 0) * 1024 * 1024
                cap = int(total_memory_bytes or 0) or configured_bytes or int(capacity_bytes or 0) or used
                remaining_bytes = int(free_memory_bytes) if free_memory_bytes is not None else max(cap - used, 0)
                if pid not in providers_data:
                    providers_data[pid] = {
                        "name": provider_name or f"Provider {pid}",
                        "data": [],
                    }
                parsed_scheduler_signals = (
                    json.loads(scheduler_signals) if isinstance(scheduler_signals, str) else scheduler_signals
                )
                providers_data[pid]["data"].append(
                    {
                        "snapshot_id": int(snapshot_id or 0),
                        "timestamp": ts.isoformat() if ts else None,
                        "vram_mb": used // (1024 * 1024),
                        "vram_bytes": used,
                        "used_vram_mb": used // (1024 * 1024),
                        "remaining_vram_mb": remaining_bytes // (1024 * 1024),
                        "total_vram_mb": cap // (1024 * 1024) if cap > 0 else None,
                        "models_loaded": models_loaded,
                        "loaded_models": (
                            json.loads(loaded_models) if isinstance(loaded_models, str) else loaded_models
                        ),
                        "scheduler_signals": (
                            parsed_scheduler_signals if isinstance(parsed_scheduler_signals, dict) else {}
                        ),
                    }
                )

            providers_list = [
                {"provider_id": pid, "name": info["name"], "data": info["data"]} for pid, info in providers_data.items()
            ]
            return {"providers": providers_list}, 200

        except Exception as e:
            logger.error(f"Failed to query provider_vram_stats: {e}")
            return {"error": str(e)}, 500

    def get_provider_vram_deltas(
        self,
        logos_key: str,
        day: str,
        after_snapshot_id: int = 0,
        since: Optional[datetime.datetime] = None,
    ) -> Tuple[Dict[str, Any], int]:
        """
        Return incremental per-provider VRAM snapshots for a single UTC day.

        Args:
            logos_key: Auth key
            day: UTC day (YYYY-MM-DD / ISO date) or "all" for full history
            after_snapshot_id: Only rows with id > this cursor are returned
            since: Optional lower bound on snapshot_ts. Used to cap the size
                of "all"-history initial loads to a recent window so the WS
                init payload doesn't balloon to hundreds of MB on long-lived
                deployments.
        """
        if not self.user_authorization(logos_key):
            return {"error": "Unknown user."}, 500

        tz_utc = datetime.timezone.utc

        full_history = isinstance(day, str) and day.strip().lower() == "all"
        if full_history:
            start_dt = None
            end_dt = None
        else:
            try:
                parsed_day = isoparse(day)
            except Exception:
                return {"error": f"Invalid day format: {day}"}, 400

            day_date = parsed_day.date()
            start_dt = datetime.datetime.combine(day_date, datetime.time.min, tzinfo=tz_utc)
            end_dt = start_dt + datetime.timedelta(days=1)

        now = datetime.datetime.now(tz_utc)
        if not full_history:
            if start_dt > now:
                return {"error": "Requested day is in the future."}, 400
            if end_dt > now:
                end_dt = now

        params = {
            "after_snapshot_id": int(after_snapshot_id or 0),
        }
        since_clause = ""
        if since is not None:
            params["since_ts"] = since
            since_clause = " AND s.snapshot_ts >= :since_ts"

        if full_history:
            sql = text(
                f"""
                SELECT
                    s.id,
                    s.provider_id,
                    p.name AS provider_name,
                    s.snapshot_ts,
                    s.total_vram_used_bytes,
                    s.total_memory_bytes,
                    s.free_memory_bytes,
                    s.total_models_loaded,
                    s.loaded_models,
                    s.scheduler_signals,
                    p.total_vram_mb,
                    MAX(COALESCE(s.total_memory_bytes, s.total_vram_used_bytes))
                        OVER (PARTITION BY s.provider_id) AS capacity_bytes
                FROM provider_snapshots s
                LEFT JOIN providers p
                  ON p.id = s.provider_id
                WHERE s.poll_success = TRUE
                  AND s.id > :after_snapshot_id
                  {since_clause}
                ORDER BY s.id
            """
            )
        else:
            params["start_ts"] = start_dt
            params["end_ts"] = end_dt
            sql = text(
                f"""
                SELECT
                    s.id,
                    s.provider_id,
                    p.name AS provider_name,
                    s.snapshot_ts,
                    s.total_vram_used_bytes,
                    s.total_memory_bytes,
                    s.free_memory_bytes,
                    s.total_models_loaded,
                    s.loaded_models,
                    s.scheduler_signals,
                    p.total_vram_mb,
                    MAX(COALESCE(s.total_memory_bytes, s.total_vram_used_bytes))
                        OVER (PARTITION BY s.provider_id) AS capacity_bytes
                FROM provider_snapshots s
                LEFT JOIN providers p
                  ON p.id = s.provider_id
                WHERE s.poll_success = TRUE
                  AND s.snapshot_ts >= :start_ts
                  AND s.snapshot_ts < :end_ts
                  AND s.id > :after_snapshot_id
                  {since_clause}
                ORDER BY s.id
            """
            )

        try:
            rows = self.session.execute(sql, params).fetchall()
            if not rows:
                return {
                    "providers": [],
                    "last_snapshot_id": int(after_snapshot_id or 0),
                }, 200

            providers_data: Dict[int, Dict[str, Any]] = {}
            last_snapshot_id = int(after_snapshot_id or 0)

            for (
                snapshot_id,
                pid,
                provider_name,
                ts,
                used_bytes,
                total_memory_bytes,
                free_memory_bytes,
                models_loaded,
                loaded_models,
                scheduler_signals,
                total_vram_mb,
                capacity_bytes,
            ) in rows:
                snapshot_id_int = int(snapshot_id or 0)
                if snapshot_id_int > last_snapshot_id:
                    last_snapshot_id = snapshot_id_int

                used = int(used_bytes or 0)
                configured_bytes = int(total_vram_mb or 0) * 1024 * 1024
                cap = int(total_memory_bytes or 0) or configured_bytes or int(capacity_bytes or 0) or used
                remaining_bytes = int(free_memory_bytes) if free_memory_bytes is not None else max(cap - used, 0)

                if pid not in providers_data:
                    providers_data[pid] = {
                        "name": provider_name or f"Provider {pid}",
                        "data": [],
                    }
                parsed_scheduler_signals = (
                    json.loads(scheduler_signals) if isinstance(scheduler_signals, str) else scheduler_signals
                )

                providers_data[pid]["data"].append(
                    {
                        "snapshot_id": snapshot_id_int,
                        "timestamp": ts.isoformat() if ts else None,
                        "vram_mb": used // (1024 * 1024),
                        "vram_bytes": used,
                        "used_vram_mb": used // (1024 * 1024),
                        "remaining_vram_mb": remaining_bytes // (1024 * 1024),
                        "total_vram_mb": cap // (1024 * 1024) if cap > 0 else None,
                        "models_loaded": models_loaded,
                        "loaded_models": (
                            json.loads(loaded_models) if isinstance(loaded_models, str) else loaded_models
                        ),
                        "scheduler_signals": (
                            parsed_scheduler_signals if isinstance(parsed_scheduler_signals, dict) else {}
                        ),
                    }
                )

            providers_list = [
                {"provider_id": pid, "name": info["name"], "data": info["data"]} for pid, info in providers_data.items()
            ]

            return {
                "providers": providers_list,
                "last_snapshot_id": last_snapshot_id,
            }, 200

        except Exception as e:
            logger.error(f"Failed to query provider_vram_deltas: {e}")
            return {"error": str(e)}, 500

    def get_auth_info_to_deployment(
        self, model_id: int, provider_id: int, api_key_id: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Resolve auth + routing info for a model/provider pair, optionally scoped to a api-key.
        """
        permission_join = ""
        filters = "WHERE m.id = :model_id AND p.id = :provider_id"
        params: Dict[str, Any] = {
            "model_id": int(model_id),
            "provider_id": int(provider_id),
        }

        if api_key_id is not None:
            permission_join = """
                JOIN (
                    SELECT model_id FROM api_key_model_permissions akmp
                    JOIN api_keys ak ON ak.id = akmp.api_key_id
                    WHERE ak.id = :api_key_id AND ak.use_custom_permissions = true
                    UNION
                    SELECT tmp.model_id FROM team_model_permissions tmp
                    JOIN api_keys ak ON ak.team_id = tmp.team_id
                    WHERE ak.id = :api_key_id AND ak.use_custom_permissions = false
                ) em ON em.model_id = m.id
                JOIN (
                    SELECT provider_id FROM api_key_provider_permissions akpp
                    JOIN api_keys ak ON ak.id = akpp.api_key_id
                    WHERE ak.id = :api_key_id AND ak.use_custom_permissions = true
                    UNION
                    SELECT tpp.provider_id FROM team_provider_permissions tpp
                    JOIN api_keys ak ON ak.team_id = tpp.team_id
                    WHERE ak.id = :api_key_id AND ak.use_custom_permissions = false
                ) ep ON ep.provider_id = p.id
            """
            params["api_key_id"] = int(api_key_id)

        sql = text(
            f"""
            SELECT m.id          AS model_id,
                   m.name        AS model_name,
                   mp.endpoint   AS endpoint,
                   p.id          AS provider_id,
                   p.name        AS provider_name,
                   p.provider_type AS provider_type,
                   p.base_url    AS base_url,
                   p.auth_name   AS auth_name,
                   p.auth_format AS auth_format,
                   COALESCE(NULLIF(mp.api_key, ''), p.api_key, '') AS api_key
            FROM models m
            JOIN model_provider mp ON m.id = mp.model_id
            JOIN providers p ON mp.provider_id = p.id
            {permission_join}
            {filters}
            LIMIT 1
        """
        )

        row = self.session.execute(sql, params).mappings().first()
        return dict(row) if row else None

    def get_endpoint_for_deployment(self, model_id: int, provider_id: int) -> Optional[str]:
        """Get the endpoint for a specific model-provider deployment from model_provider."""
        sql = text(
            """
            SELECT endpoint FROM model_provider
            WHERE model_id = :model_id AND provider_id = :provider_id
        """
        )
        row = self.session.execute(sql, {"model_id": int(model_id), "provider_id": int(provider_id)}).fetchone()
        return row.endpoint if row else None

    def get_deployments_for_api_key(self, api_key_id: int) -> list[Deployment]:
        """
        Get a list of all authorized model deployments for an api key.
        """
        sql = text(
            """
                   WITH key_info AS (
                            SELECT ak.id AS aki,
                                   ak.team_id AS tid,
                                   u.role AS user_role,
                                   ak.use_custom_permissions AS custom
                            FROM api_keys ak
                                LEFT JOIN users u ON ak.user_id = u.id
                            WHERE ak.id = :api_key_id
                                AND ak.is_active = true
                        ),
                        effective_providers AS (
                            SELECT akpp.provider_id
                            FROM api_key_provider_permissions akpp, key_info ki
                            WHERE akpp.api_key_id = ki.aki AND ki.custom = true
                            UNION
                            SELECT tpp.provider_id
                            FROM team_provider_permissions tpp, key_info ki
                            WHERE tpp.team_id = ki.tid AND ki.custom = false
                        ),
                        effective_models AS (
                            SELECT akmp.model_id
                            FROM api_key_model_permissions akmp, key_info ki
                            WHERE akmp.api_key_id = ki.aki AND ki.custom = true
                            UNION
                            SELECT tmp.model_id
                            FROM team_model_permissions tmp, key_info ki
                            WHERE tmp.team_id = ki.tid AND ki.custom = false
                        )
                   SELECT m.id               as model_id,
                          p.id               as provider_id,
                          p.provider_type    as type,
                          p.privacy_level    as privacy_level,
                          p.cloud_provider_type as cloud_provider_type,
                          p.base_url         as base_url
                   FROM models m
                        JOIN model_provider mp ON m.id = mp.model_id
                        JOIN providers p ON mp.provider_id = p.id
                        JOIN effective_models em ON m.id = em.model_id
                        JOIN effective_providers ep ON p.id = ep.provider_id
                   ORDER BY model_id, provider_id
                   """
        )
        rows = self.session.execute(sql, {"api_key_id": api_key_id}).mappings().all()
        return [cast(Deployment, dict(row)) for row in rows]

    # ADMIN ONLY
    def get_all_deployments(self) -> list[Deployment]:
        """
        Get a list of ALL model deployments.

        For cloud/azure providers: requires model_provider + model_api_keys (per-model credentials).
        For logosnode providers: requires model_provider + logosnode_provider_keys (per-provider key).

        Returns: List of complete deployment dicts with:
            - model_id
            - provider_id
            - type
        """
        sql = text(
            """
                   SELECT m.id               as model_id,
                          p.id               as provider_id,
                          p.provider_type    as type,
                          p.privacy_level    as privacy_level
                   FROM models m
                            JOIN model_provider mp ON m.id = mp.model_id
                            JOIN providers p ON mp.provider_id = p.id
                   WHERE p.provider_type != 'logosnode'
                   UNION
                   SELECT m.id               as model_id,
                          p.id               as provider_id,
                          p.provider_type    as type,
                          p.privacy_level    as privacy_level
                   FROM models m
                            JOIN model_provider mp ON m.id = mp.model_id
                            JOIN providers p ON mp.provider_id = p.id
                            JOIN logosnode_provider_keys lpk ON p.id = lpk.provider_id
                   WHERE p.provider_type = 'logosnode'
                   ORDER BY model_id, provider_id
                   """
        )
        rows = self.session.execute(sql, {}).mappings().all()
        return [cast(Deployment, dict(row)) for row in rows]

    def get_all_deployments_with_names(self) -> list[Dict[str, Any]]:
        """
        Get all model deployments with model and provider names.

        Same deployment set as get_all_deployments() — cloud/azure providers
        need model_provider + model_api_keys, logosnode providers need
        model_provider + logosnode_provider_keys — plus the display names the
        model-level health check reports per deployment.
        """
        sql = text(
            """
                   SELECT m.id               as model_id,
                          m.name             as model_name,
                          p.id               as provider_id,
                          p.name             as provider_name,
                          p.provider_type    as type
                   FROM models m
                            JOIN model_provider mp ON m.id = mp.model_id
                            JOIN providers p ON mp.provider_id = p.id
                   WHERE p.provider_type != 'logosnode'
                   UNION
                   SELECT m.id               as model_id,
                          m.name             as model_name,
                          p.id               as provider_id,
                          p.name             as provider_name,
                          p.provider_type    as type
                   FROM models m
                            JOIN model_provider mp ON m.id = mp.model_id
                            JOIN providers p ON mp.provider_id = p.id
                            JOIN logosnode_provider_keys lpk ON p.id = lpk.provider_id
                   WHERE p.provider_type = 'logosnode'
                   ORDER BY model_id, provider_id
                   """
        )
        rows = self.session.execute(sql, {}).mappings().all()
        return [dict(row) for row in rows]

    def get_models_for_api_key(self, api_key_id: int) -> list[Dict[str, Any]]:
        """
        Get all models that an api key has access to.

        Returns:
            List of dicts with model id, name, and description.
        """
        sql = text(
            """
           WITH key_info AS (
                SELECT ak.id AS aki,
                       ak.team_id AS tid,
                       u.role AS user_role,
                       ak.use_custom_permissions AS custom
                FROM api_keys ak
                LEFT JOIN users u ON ak.user_id = u.id
                WHERE ak.id = :api_key_id
                  AND ak.is_active = true
            ),
            effective_providers AS (
                SELECT akpp.provider_id
                FROM api_key_provider_permissions akpp, key_info ki
                WHERE akpp.api_key_id = ki.aki AND ki.custom = true
                UNION
                SELECT tpp.provider_id
                FROM team_provider_permissions tpp, key_info ki
                WHERE tpp.team_id = ki.tid AND ki.custom = false
            ),
            effective_models AS (
                SELECT akmp.model_id
                FROM api_key_model_permissions akmp, key_info ki
                WHERE akmp.api_key_id = ki.aki AND ki.custom = true
                UNION
                SELECT tmp.model_id
                FROM team_model_permissions tmp, key_info ki
                WHERE tmp.team_id = ki.tid AND ki.custom = false
            )
           SELECT DISTINCT m.id, m.name, m.description,
           (SELECT string_agg(a.alias, ', ' ORDER BY a.alias)
            FROM model_aliases a
            WHERE a.model_id = m.id
           ) AS aliases
           FROM models m
           JOIN effective_models em ON m.id = em.model_id
           JOIN model_provider mp ON m.id = mp.model_id
           JOIN effective_providers ep ON mp.provider_id = ep.provider_id
           ORDER BY m.id
       """
        )
        rows = self.session.execute(sql, {"api_key_id": int(api_key_id)}).mappings().all()
        models = []
        for row in rows:
            model = dict(row)
            model["aliases"] = self._split_alias_list(model.get("aliases"))
            models.append(model)
        return models

    @staticmethod
    def _split_alias_list(raw: Optional[str]) -> list[str]:
        """Turn the comma-joined aliases column of a model row into a list."""
        if not raw:
            return []
        return [alias.strip() for alias in str(raw).split(",") if alias.strip()]

    def get_model_for_api_key(self, api_key_id: int, model_name: str) -> Optional[Dict[str, Any]]:
        """
        Get a single model by name if the api-key has access to it.

        Returns:
            Dict with model id, name, and description, or None if not found.
        """
        sql = text(
            """
           WITH key_info AS (
                SELECT ak.id AS aki,
                       ak.team_id AS tid,
                       u.role AS user_role,
                       ak.use_custom_permissions AS custom
                FROM api_keys ak
                LEFT JOIN users u ON ak.user_id = u.id
                WHERE ak.id = :api_key_id
                  AND ak.is_active = true
            ),
            effective_providers AS (
                SELECT akpp.provider_id
                FROM api_key_provider_permissions akpp, key_info ki
                WHERE akpp.api_key_id = ki.aki AND ki.custom = true
                UNION
                SELECT tpp.provider_id
                FROM team_provider_permissions tpp, key_info ki
                WHERE tpp.team_id = ki.tid AND ki.custom = false
            ),
            effective_models AS (
                SELECT akmp.model_id
                FROM api_key_model_permissions akmp, key_info ki
                WHERE akmp.api_key_id = ki.aki AND ki.custom = true
                UNION
                SELECT tmp.model_id
                FROM team_model_permissions tmp, key_info ki
                WHERE tmp.team_id = ki.tid AND ki.custom = false
            )
            SELECT DISTINCT m.id, m.name, m.description
            FROM models m
            JOIN effective_models em ON m.id = em.model_id
            JOIN model_provider mp ON m.id = mp.model_id
            JOIN effective_providers ep ON mp.provider_id = ep.provider_id
            WHERE m.name = :name
            ORDER BY m.id LIMIT 1
        """
        )
        row = self.session.execute(sql, {"api_key_id": int(api_key_id), "name": model_name}).mappings().first()
        return dict(row) if row else None

    # TODO: Remove these methods if not needed anymore
    # def get_models_by_profile(self, logos_key: str, profile_id: int):
    #     """
    #     Get a list of models accessible by a given profile-ID.
    #     """
    #     sql = text("""
    #                SELECT models.id
    #                FROM models,
    #                     process,
    #                     profiles,
    #                     profile_model_permissions,
    #                     model_provider,
    #                     providers
    #                WHERE process.logos_key = :logos_key
    #                     and process.id = profiles.process_id
    #                     and profiles.id = profile_model_permissions.profile_id
    #                     and profile_model_permissions.model_id = models.id
    #                     and model_provider.model_id = models.id
    #                     and providers.id = model_provider.provider_id
    #                     and profiles.id = :profile_id
    #                     and EXISTS (
    #                         SELECT 1
    #                         FROM model_api_keys
    #                         WHERE model_api_keys.profile_id = profiles.id
    #                           and model_api_keys.provider_id = providers.id
    #                     )
    #                """)
    #     result = self.session.execute(sql, {"logos_key": logos_key, "profile_id": profile_id}).fetchall()
    #     return [i.id for i in result]
    #
    # def get_models_with_key(self, logos_key: str):
    #     """
    #     Get a list of models accessible by a given key.
    #     """
    #     sql = text("""
    #         SELECT models.id
    #         FROM models, process, profiles, profile_model_permissions, model_provider, providers
    #         WHERE process.logos_key = :logos_key
    #             and process.id = profiles.process_id
    #             and profiles.id = profile_model_permissions.profile_id
    #             and profile_model_permissions.model_id = models.id
    #             and model_provider.model_id = models.id
    #             and providers.id = model_provider.provider_id
    #             and EXISTS (
    #                 SELECT 1
    #                 FROM model_api_keys
    #                 WHERE model_api_keys.profile_id = profiles.id
    #                   and model_api_keys.provider_id = providers.id
    #             )
    #     """)
    #     result = self.session.execute(sql, {"logos_key": logos_key}).fetchall()
    #     return [i.id for i in result]

    def get_all_models(self):
        """
        Get a list of all models. ONLY FOR INTERNAL USE.
        """
        sql = text(
            """
            SELECT models.id
            FROM models
        """
        )
        result = self.session.execute(sql).fetchall()
        return [i.id for i in result]

    def get_models_info(self, logos_key: str):
        """
        Get a list of models accessible by a given key.
        """
        is_admin = self.check_authorization(logos_key)

        if not is_admin:
            role_row = self.session.execute(
                text(
                    """
                    SELECT u.role FROM api_keys ak
                    JOIN users u ON ak.user_id = u.id
                    WHERE ak.key_value = :logos_key AND ak.is_active = true
                """
                ),
                {"logos_key": logos_key},
            ).fetchone()
            if role_row is not None and role_row.role == "app_admin":
                is_admin = True

        if is_admin:
            sql = text(
                """
                       SELECT m.id,
                              m.name,
                              m.weight_latency,
                              m.weight_accuracy,
                              m.weight_cost,
                              m.weight_quality,
                              m.tags,
                              (
                                  SELECT string_agg(a.alias, ', ' ORDER BY a.alias)
                                  FROM model_aliases a
                                  WHERE a.model_id = m.id
                              ) AS aliases,
                              m.description,
                              (
                                  SELECT ROUND(price_per_k_token::NUMERIC / 100000, 4)
                                  FROM token_prices tp
                                  JOIN token_types tt ON tt.id = tp.type_id
                                  WHERE (tp.model_id = m.id OR tp.model_id IS NULL)
                                    AND tt.name = 'prompt_tokens'
                                    AND valid_from <= NOW()
                                  ORDER BY
                                      (tp.model_id = m.id) DESC NULLS LAST,
                                      valid_from DESC
                                  LIMIT 1
                              ) AS input_usd_per_million,
                            (
                                SELECT ROUND(price_per_k_token::NUMERIC / 100000, 4)
                                FROM token_prices tp
                                JOIN token_types tt ON tt.id = tp.type_id
                                WHERE (tp.model_id = m.id OR tp.model_id IS NULL)
                                    AND tt.name = 'completion_tokens'
                                    AND valid_from <= NOW()
                                ORDER BY
                                    (tp.model_id = m.id) DESC NULLS LAST,
                                    valid_from DESC
                                LIMIT 1
                            ) AS output_usd_per_million
                       FROM models m
                       ORDER BY m.id
                       """
            )
            params = {}
        else:
            sql = text(
                """
                WITH key_info AS (
                    SELECT ak.id AS aki,
                           ak.team_id AS tid,
                           ak.use_custom_permissions AS custom
                    FROM api_keys ak
                    WHERE ak.key_value = :logos_key
                      AND ak.is_active = true
                ),
                effective_providers AS (
                    SELECT akpp.provider_id
                    FROM api_key_provider_permissions akpp, key_info ki
                    WHERE akpp.api_key_id = ki.aki AND ki.custom = true
                    UNION
                    SELECT tpp.provider_id
                    FROM team_provider_permissions tpp, key_info ki
                    WHERE tpp.team_id = ki.tid AND ki.custom = false
                ),
                effective_models AS (
                    SELECT akmp.model_id
                    FROM api_key_model_permissions akmp, key_info ki
                    WHERE akmp.api_key_id = ki.aki AND ki.custom = true
                    UNION
                    SELECT tmp.model_id
                    FROM team_model_permissions tmp, key_info ki
                    WHERE tmp.team_id = ki.tid AND ki.custom = false
                )
                SELECT DISTINCT m.id,
                                m.name,
                                m.weight_latency,
                                m.weight_accuracy,
                                m.weight_cost,
                                m.weight_quality,
                                m.tags,
                                (
                                    SELECT string_agg(a.alias, ', ' ORDER BY a.alias)
                                    FROM model_aliases a
                                    WHERE a.model_id = m.id
                                ) AS aliases,
                                m.description,
                                (
                                    SELECT ROUND(price_per_k_token::NUMERIC / 100000, 4)
                                    FROM token_prices tp
                                             JOIN token_types tt ON tt.id = tp.type_id
                                    WHERE (tp.model_id = m.id OR tp.model_id IS NULL)
                                      AND tt.name = 'prompt_tokens'
                                      AND valid_from <= NOW()
                                    ORDER BY
                                        (tp.model_id = m.id) DESC NULLS LAST,
                                        valid_from DESC
                                    LIMIT 1
                                ) AS input_usd_per_million,
                       (
                            SELECT ROUND(price_per_k_token::NUMERIC / 100000, 4)
                            FROM token_prices tp
                                JOIN token_types tt ON tt.id = tp.type_id
                            WHERE (tp.model_id = m.id OR tp.model_id IS NULL)
                                AND tt.name = 'completion_tokens'
                                AND valid_from <= NOW()
                            ORDER BY
                                (tp.model_id = m.id) DESC NULLS LAST,
                                 valid_from DESC
                            LIMIT 1
                        ) AS output_usd_per_million
                FROM models m
                JOIN effective_models em ON m.id = em.model_id
                JOIN model_provider mp ON m.id = mp.model_id
                JOIN effective_providers ep ON mp.provider_id = ep.provider_id
                ORDER BY m.id
            """
            )
            params = {"logos_key": logos_key}

        result = self.session.execute(sql, params).fetchall()
        return [
            {
                "id": r.id,
                "name": r.name or f"Model {r.id}",
                "weight_latency": r.weight_latency,
                "weight_accuracy": r.weight_accuracy,
                "weight_cost": r.weight_cost,
                "weight_quality": r.weight_quality,
                "tags": r.tags,
                "aliases": self._split_alias_list(r.aliases),
                "description": r.description,
                "input_usd_per_million": r.input_usd_per_million,
                "output_usd_per_million": r.output_usd_per_million,
            }
            for r in result
        ]

    def get_model(self, model_id: int):
        sql = text(
            """
            SELECT *
            FROM models
            WHERE id = :model_id
        """
        )
        result = self.session.execute(sql, {"model_id": int(model_id)}).fetchone()
        if result is None:
            return None
        return {
            "id": result.id,
            "name": result.name,
            "weight_latency": result.weight_latency,
            "weight_accuracy": result.weight_accuracy,
            "weight_cost": result.weight_cost,
            "weight_quality": result.weight_quality,
            "tags": result.tags,
            "description": result.description,
        }

    def get_provider(self, provider_id: int):
        sql = text(
            """
            SELECT *
            FROM providers
            WHERE id = :provider_id
        """
        )
        result = self.session.execute(sql, {"provider_id": int(provider_id)}).fetchone()
        if result is None:
            return None
        return {
            "id": result.id,
            "name": result.name,
            "base_url": result.base_url,
            "provider_type": result.provider_type,
            "cloud_provider_type": result.cloud_provider_type,
            "privacy_level": result.privacy_level,
            "auth_name": result.auth_name,
            "auth_format": result.auth_format,
            "api_key": result.api_key,
        }

    def get_logosnode_provider_by_api_key(self, api_key: str):
        """Look up a logosnode provider by its shared API key."""
        sql = text(
            """
            SELECT *
            FROM providers
            WHERE api_key = :api_key
              AND provider_type = 'logosnode'
        """
        )
        result = self.session.execute(sql, {"api_key": api_key}).fetchone()
        if result is None:
            return None
        return {
            "id": result.id,
            "name": result.name,
            "base_url": result.base_url,
            "provider_type": result.provider_type,
            "auth_name": result.auth_name,
            "auth_format": result.auth_format,
            "api_key": result.api_key,
        }

    def get_local_provider_inventory(self, logos_key: str) -> Tuple[Any, int]:
        """
        Return all local/self-hosted providers for dashboards and operator tooling.

        Local provider types were historically named in several ways. Normalize them at the
        query layer so statistics views can reason about all worker-backed providers uniformly.
        """
        if not self.user_authorization(logos_key):
            return {"error": "Unknown user."}, 500

        return self.list_local_providers(), 200

    def list_local_providers(self) -> list[dict]:
        """Unauthenticated variant of get_local_provider_inventory for internal
        (secret-gated) endpoints that have no user logos_key."""
        sql = text(
            """
            SELECT
                id,
                name,
                provider_type,
                base_url,
                ollama_admin_url,
                total_vram_mb,
                parallel_capacity
            FROM providers
            WHERE LOWER(provider_type::text) IN (
                'logosnode',
                'node',
                'node_controller',
                'logos_worker_node'
            )
            ORDER BY LOWER(name), id
        """
        )

        rows = self.session.execute(sql).fetchall()
        return [
            {
                "provider_id": row.id,
                "name": row.name,
                "provider_type": row.provider_type,
                "base_url": row.base_url,
                "ollama_admin_url": row.ollama_admin_url,
                "total_vram_mb": row.total_vram_mb,
                "parallel_capacity": row.parallel_capacity,
            }
            for row in rows
        ]

    def find_ollama_typed_providers(self) -> list[dict]:
        """Provider rows still typed 'ollama' — the engine Logos dropped.

        Used as a startup gate: such rows point at servers the deployment no
        longer runs, so they must be fixed by hand rather than silently left
        unservable.
        """
        sql = text(
            """
            SELECT id, name, provider_type
            FROM providers
            WHERE LOWER(provider_type::text) = 'ollama'
            ORDER BY id
        """
        )
        rows = self.session.execute(sql).fetchall()
        return [{"id": row.id, "name": row.name, "provider_type": row.provider_type} for row in rows]

    def log(self, api_key_id: int):
        sql = text(
            """
                   SELECT log
                   FROM api_keys
                   WHERE id = :api_key_id
                   """
        )
        result = self.session.execute(sql, {"api_key_id": int(api_key_id)}).fetchone()
        if result is None:
            return False
        return result.log

    def log_usage(
        self,
        api_key_id: Optional[int],
        team_id: Optional[int],
        user_id: Optional[int],
        environment: Optional[str],
        log_level: str,
        client_ip: Optional[str] = None,
        input_payload=None,
        headers=None,
        request_id: Optional[str] = None,
    ) -> tuple[dict, int]:
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        payload_str = _json_for_jsonb(input_payload) if log_level == "FULL" and input_payload else None
        headers_str = _json_for_jsonb(dict(headers)) if log_level == "FULL" and headers else None

        row = self.session.execute(
            text(
                """
                 INSERT INTO log_entry (timestamp_request, api_key_id, team_id, user_id,
                                        environment, client_ip,
                                        input_payload, headers, privacy_level, request_id)
                 VALUES (:ts, :aki, :tid, :uid, :env,
                         :ip, :payload, :headers, CAST(:privacy AS logging_enum), :rid) RETURNING id
                 """
            ),
            {
                "ts": timestamp,
                "aki": api_key_id,
                "tid": team_id,
                "uid": user_id,
                "env": environment,
                "ip": client_ip if log_level == "FULL" else None,
                "payload": payload_str,
                "headers": headers_str,
                "privacy": log_level,
                "rid": request_id,
            },
        ).fetchone()
        self.session.commit()
        return {"result": "Created log entry.", "log-id": row.id}, 200

    def set_time_at_first_token(self, log_id: int):
        sql = text(
            """
                   UPDATE log_entry
                   SET time_at_first_token = :timestamp
                   WHERE id = :log_id
                   """
        )
        self.session.execute(
            sql,
            {
                "timestamp": datetime.datetime.now(datetime.timezone.utc),
                "log_id": log_id,
            },
        )
        self.session.commit()
        return {"result": "time_at_first_token set"}, 200

    def set_response_payload(
        self,
        log_id: int,
        payload: dict,
        provider_id=None,
        model_id=None,
        usage=None,
        policy_id=-1,
        classified=None,
        **kwargs,
    ):
        # Hole Privacy-Level
        if classified is None:
            classified = dict()
        if usage is None:
            usage = dict()
        if not isinstance(log_id, int):
            return {"error": "Invalid log_id"}, 400
        result = self.session.execute(
            text("SELECT privacy_level FROM log_entry WHERE id = :log_id"),
            {"log_id": log_id},
        ).fetchone()

        if result is None:
            return {"error": "Log entry not found"}, 404

        if result[0] != "FULL":
            payload = None

        type_ids = dict()
        for token_type, token_count in usage.items() if usage is not None else dict().items():
            r, c = self.add_token_type(token_type, "")
            if "error" in r:
                return r, c
            type_ids[token_type] = r["token-type-id"]

        for token_type in type_ids:
            if usage[token_type]:
                _ = self.insert(
                    "usage_tokens",
                    {
                        "log_entry_id": log_id,
                        "type_id": type_ids[token_type],
                        "token_count": usage[token_type],
                    },
                )

        sql = text(
            """
                   UPDATE log_entry
                   SET response_payload = :payload,
                       provider_id      = COALESCE(:provider_id, provider_id),
                       model_id         = COALESCE(:model_id, model_id),
                       timestamp_response = :timestamp,
                       policy_id        = COALESCE(:policy_id, policy_id),
                       classification_statistics = :classification_statistics,
                       request_id = COALESCE(:request_id, request_id),
                       queue_depth_at_arrival = COALESCE(:queue_depth, queue_depth_at_arrival),
                       utilization_at_arrival = COALESCE(:utilization, utilization_at_arrival)
                   WHERE id = :log_id
                   """
        )
        self.session.execute(
            sql,
            {
                "payload": _json_for_jsonb(payload) if payload else None,
                "provider_id": provider_id,
                "model_id": model_id,
                "timestamp": datetime.datetime.now(datetime.timezone.utc),
                "log_id": log_id,
                "policy_id": policy_id if policy_id != -1 else None,
                "classification_statistics": _json_for_jsonb(classified),
                "request_id": kwargs.get("request_id"),
                "queue_depth": kwargs.get("queue_depth_at_arrival"),
                "utilization": kwargs.get("utilization_at_arrival"),
            },
        )
        self.session.commit()
        return {"result": "response_payload set"}, 200

    def get_usage_cost_micro_cents(
        self,
        model_id: int,
        provider_id: int,
        usage: Dict[str, int],
        response_at: datetime.datetime,
    ) -> Optional[int]:
        """Return the configured cloud cost for one response in micro-cents.

        The lookup mirrors the ``budget_usage`` view: model/provider-specific
        prices take precedence over generic prices and only prices valid at
        ``response_at`` are considered. ``None`` identifies a local provider;
        cloud providers without a matching price retain the existing billing
        semantics and cost zero.
        """
        billable_usage = {
            token_type: token_count
            for token_type, token_count in usage.items()
            if isinstance(token_type, str)
            and isinstance(token_count, int)
            and not isinstance(token_count, bool)
            and token_count >= 0
        }
        if not billable_usage:
            return None

        row = self.session.execute(
            text(
                """
                WITH response_usage AS (
                    SELECT usage.key AS token_type,
                           usage.value::BIGINT AS token_count
                    FROM jsonb_each_text(CAST(:usage AS JSONB)) AS usage
                ),
                cloud_provider AS (
                    SELECT id
                    FROM providers
                    WHERE id = :provider_id
                      AND LOWER(provider_type::text) = 'cloud'
                )
                SELECT CASE
                    WHEN EXISTS (SELECT 1 FROM cloud_provider)
                    THEN COALESCE(SUM(
                        CASE WHEN price.price_per_k_token IS NOT NULL
                             THEN (ru.token_count * price.price_per_k_token / 1000)::BIGINT
                             ELSE 0
                        END
                    ), 0)
                    ELSE NULL
                END AS cost_micro_cents
                FROM response_usage ru
                LEFT JOIN token_types tt ON tt.name = ru.token_type
                LEFT JOIN LATERAL (
                    SELECT tp.price_per_k_token
                    FROM token_prices tp
                    WHERE tp.type_id = tt.id
                      AND (tp.model_id = :model_id OR tp.model_id IS NULL)
                      AND (tp.provider_id = :provider_id OR tp.provider_id IS NULL)
                      AND tp.valid_from <= :response_at
                    ORDER BY (tp.model_id = :model_id) DESC NULLS LAST,
                             (tp.provider_id = :provider_id) DESC NULLS LAST,
                             tp.valid_from DESC
                    LIMIT 1
                ) price ON true
                """
            ),
            {
                "usage": _json_for_jsonb(billable_usage),
                "model_id": int(model_id),
                "provider_id": int(provider_id),
                "response_at": response_at,
            },
        ).fetchone()
        if row is None or row.cost_micro_cents is None:
            return None
        return int(row.cost_micro_cents)

    def check_authorization(self, logos_key: str):
        sql = text(
            """
                                SELECT *
                                FROM api_keys ak
                                    JOIN users u ON ak.user_id = u.id
                                WHERE ak.key_value = :logos_key
                                    AND u.role = 'logos_admin'
                                    AND ak.is_active = true
                            """
        )
        return self.session.execute(sql, {"logos_key": logos_key}).fetchone() is not None

    def user_authorization(self, logos_key: str):
        sql = text(
            """
                                SELECT *
                                FROM api_keys
                                WHERE key_value = :logos_key
                                  AND is_active = true
                            """
        )
        return self.session.execute(sql, {"logos_key": logos_key}).fetchone() is not None

    def get_team(self, team_id: int) -> dict | None:
        row = self.session.execute(
            text(
                """
                 SELECT id, name,
                        default_cloud_rpm_limit, default_cloud_tpm_limit,
                        default_local_rpm_limit, default_local_tpm_limit,
                        default_monthly_budget_micro_cents,
                        team_monthly_budget_micro_cents
                 FROM teams
                 WHERE id = :team_id
                 """
            ),
            {"team_id": team_id},
        ).fetchone()
        if row is None:
            return None
        return dict(row._mapping)

    def is_team_owner(self, team_id: int, user_id: int) -> bool:
        row = self.session.execute(
            text(
                """
                 SELECT *
                 FROM team_members
                 WHERE team_id = :team_id
                   AND user_id = :user_id
                   AND is_owner = true
                 """
            ),
            {"team_id": team_id, "user_id": user_id},
        ).fetchone()
        return row is not None

    def get_api_key_by_value(self, key_value: str) -> Optional[Dict[str, Any]]:
        row = self.session.execute(
            text(
                """
                 SELECT ak.id,
                        ak.key_value,
                        ak.name,
                        ak.key_type,
                        ak.team_id,
                        ak.user_id,
                        ak.environment,
                        ak.log,
                        ak.settings,
                        ak.default_priority,
                        ak.is_active,
                        ak.use_custom_permissions,
                        u.role
                 FROM api_keys ak
                          LEFT JOIN users u ON u.id = ak.user_id
                 WHERE ak.key_value = :kv
                   AND ak.is_active = true
                 """
            ),
            {"kv": key_value},
        ).fetchone()

        if not row:
            return None

        data = dict(row._mapping)
        # Admin keys are no longer special-cased: a logos_admin's key resolves
        # its rate limits and budget from its team / key settings like any other
        # key. Drop the joined role column so callers see a plain api_key row.
        data.pop("role", None)

        return data

    def get_team_budget_usage(self, team_id: int, month_start: str) -> int:
        row = self.session.execute(
            text(
                """
                 SELECT COALESCE(SUM(bu.cost_micro_cents), 0) AS total
                 FROM budget_usage bu
                 WHERE bu.api_key_id = ANY(
                         ARRAY(SELECT id FROM api_keys WHERE team_id = :tid AND key_type = 'developer')
                       )
                   AND bu.month = :month
                 """
            ),
            {"tid": team_id, "month": month_start},
        ).fetchone()
        return int(row._mapping["total"] or 0) if row else 0

    def create_api_key(
        self,
        name: str,
        key_type: str,
        team_id: Optional[int],
        user_id: Optional[int],
        environment: Optional[str],
        log: str,
        settings: Optional[dict],
        default_priority: int = 1,
        use_custom_permissions: bool = False,
    ) -> Dict[str, Any]:

        if name == "root":
            label = "root"
        else:
            label_parts = []

            if team_id:
                t_row = self.session.execute(
                    text("SELECT name FROM teams WHERE id = :tid"), {"tid": team_id}
                ).fetchone()
                if t_row:
                    label_parts.append(t_row[0])
            if not label_parts:
                label_parts.append("noteam")

            if key_type == "application":
                if environment and environment != "-":
                    label_parts.append(environment)
            else:
                if user_id:
                    u_row = self.session.execute(
                        text("SELECT username FROM users WHERE id = :uid"),
                        {"uid": user_id},
                    ).fetchone()
                    if u_row:
                        label_parts.append(u_row[0])

            label = "-".join(label_parts).lower()
            label = re.sub(r"[^a-z0-9\-]", "-", label)
            label = re.sub(r"\-+", "-", label).strip("-")[:35]

        key_value = generate_logos_api_key(label)

        row = self.session.execute(
            text(
                """
                 INSERT INTO api_keys
                 (key_value, name, key_type, team_id, user_id,
                  environment, log, settings, default_priority, is_active, use_custom_permissions)
                 VALUES (:kv,
                         :name,
                         CAST(:kt AS api_key_type_enum),
                         :tid,
                         :uid,
                         :env,
                         CAST(:log AS logging_enum),
                         CAST(:settings AS jsonb),
                         :dprio,
                         true,
                         :custom) RETURNING id, key_value
                 """
            ),
            {
                "kv": key_value,
                "name": name,
                "kt": key_type,
                "tid": team_id,
                "uid": user_id,
                "env": environment,
                "log": log,
                "settings": _json_for_jsonb(settings) if settings else None,
                "dprio": default_priority,
                "custom": use_custom_permissions,
            },
        ).fetchone()
        self.session.commit()
        return {"id": row.id, "key_value": row.key_value}

    def get_user_by_api_key(self, key_value: str):
        row = self.session.execute(
            text(
                """
                 SELECT u.id,
                        u.username,
                        u.prename,
                        u.name,
                        u.role,
                        u.email,
                        ak.id AS api_key_id
                 FROM api_keys ak
                          LEFT JOIN users u ON u.id = ak.user_id
                 WHERE ak.key_value = :kv
                   AND ak.is_active = true
                 """
            ),
            {"kv": key_value},
        ).fetchone()
        if row is None:
            return None
        return dict(row._mapping)

    def get_api_key_budget_limit(self, api_key_id: int) -> Optional[int]:
        sql = text(
            """
                   SELECT CAST(ak.settings ->>'budget_limit_micro_cents' AS BIGINT) AS specific_limit,
                          t.default_monthly_budget_micro_cents                      AS default_limit
                   FROM api_keys ak
                            LEFT JOIN teams t ON t.id = ak.team_id
                   WHERE ak.id = :aki
                   """
        )
        row = self.session.execute(sql, {"aki": api_key_id}).fetchone()

        if not row:
            return None

        if row.specific_limit is not None:
            return int(row.specific_limit)
        return row.default_limit

    def get_api_key_budget_usage(self, api_key_id: int, month_start: str) -> int:
        row = self.session.execute(
            text(
                """
                 SELECT cost_micro_cents
                 FROM budget_usage
                 WHERE api_key_id = :aki AND month = :month
                 """
            ),
            {"aki": api_key_id, "month": month_start},
        ).fetchone()
        return int(row[0]) if row else 0

    def __enter__(self):
        self.engine = _init_engine()
        _ensure_metadata(self.engine)
        self.metadata = _METADATA
        if _SESSION_FACTORY is None:
            raise RuntimeError("Database session factory was not initialized.")
        self.Session = _SESSION_FACTORY
        self.session = self.Session()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if exc_type is not None:
                self.session.rollback()
        finally:
            self.session.close()
