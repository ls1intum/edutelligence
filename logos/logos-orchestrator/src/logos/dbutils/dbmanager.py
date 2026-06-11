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


def _reset_metadata():
    # Drop the cached reflection so the next _ensure_metadata() re-reads the
    # live schema. Required after run_migrations() applies DDL — otherwise
    # Table(..., autoload_with=engine) returns the pre-migration cached
    # object and inserts on new columns fail with "Unconsumed column names".
    global _METADATA_REFLECTED
    with _METADATA_LOCK:
        _METADATA.clear()
        _METADATA_REFLECTED = False


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
        api_key_id: int,
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
                 VALUES (:status, :payload::jsonb, :aki, :tid, :uid, :env) RETURNING id
                 """
            ),
            {
                "status": status,
                "payload": json.dumps(payload),
                "aki": api_key_id,
                "tid": team_id,
                "uid": user_id,
                "env": environment,
            },
        ).fetchone()
        self.session.commit()
        return row.id

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
            update_data["result_payload"] = result_payload
        if error_message is not None:
            update_data["error_message"] = error_message
        self.update("jobs", job_id, update_data)

    def get_job(self, job_id: int) -> Optional[Dict[str, Any]]:
        """
        Fetch job state by id.
        """
        return self.fetch_by_id("jobs", job_id)

    def __exec_init(self):
        with open("./logos/db/init.sql", "r", encoding="utf-8") as file:
            sql = file.read()
            for statement in sql.split(";"):
                stmt = statement.strip()
                if stmt:
                    try:
                        self.session.execute(text(stmt))
                    except sqlalchemy.exc.ProgrammingError:
                        pass

        self.session.commit()

    @staticmethod
    def is_initialized():
        return os.path.exists("./logos/db/.env")

    def is_root_initialized(self):
        if sqlalchemy.inspect(self.engine).has_table("users"):
            sql = text(
                """
                       SELECT 1
                       FROM users
                       WHERE username = 'root' LIMIT 1
                       """
            )
            exc = self.session.execute(sql).fetchone()
            if exc is not None:
                with open("./logos/db/.env", "w") as file:
                    file.write("Setup Completed")
                    file.write("\n")
                return True
        return False

    def setup(self) -> dict:
        """
        Sets up the initial database. Creates a root-user.
        :return: Initial API-Key
        """
        # Check if database already exists
        logging.info(".env exists? %s", os.path.exists("./logos/db/.env"))
        if os.path.exists("./logos/db/.env"):
            return {"error": "Database already initialized"}
        logging.info("Is root initialized? %s", self.is_root_initialized())
        if self.is_root_initialized():
            return {"error": "Database already initialized"}
        logging.info("Setting up DB")
        self.__exec_init()
        self.create_all()
        # Create user
        user_id = self.insert(
            "users",
            {
                "username": "root",
                "prename": "postgres",
                "name": "root",
                "role": "logos_admin",
                "email": "admin@logos.local",
            },
        )

        key_info = self.create_api_key(
            name="root",
            key_type="developer",
            team_id=None,
            user_id=user_id,
            environment="",
            log="FULL",
            settings={},
            default_priority=5,
        )

        with open("./logos/db/.env", "w") as file:
            file.write("Setup Completed")
            file.write("\n")
        self.session.commit()
        return {
            "result": f"Created root user. ID: {user_id}",
            "api_key": key_info["key_value"],
        }

    def run_migrations(self, is_fresh_install: bool = False):
        """
        Apply pending database migrations on startup.
        - Fresh install: marks all migrations as applied without executing (init.sql is current)
        - Existing install: executes pending migrations in order, records each

        Args:
            is_fresh_install: If True, assumes init.sql has all current schema and skips execution
        """
        import pathlib

        # Locate the migrations directory. Path differs between dev (running from
        # a repo checkout) and the Docker image (/app/logos/db/migrations).
        _here = pathlib.Path(__file__).resolve().parent
        _candidates = [
            _here.parent.parent.parent / "db" / "migrations",  # dev
            _here.parent.parent.parent / "logos" / "db" / "migrations",  # docker
            pathlib.Path("./logos/db/migrations"),  # CWD fallback
        ]
        migrations_dir = next((p for p in _candidates if p.exists()), _candidates[0])
        # Discover migrations from disk so new SQL files are picked up automatically.
        # Excludes rollback scripts (must be run manually).
        MIGRATION_FILES = [p.name for p in sorted(migrations_dir.glob("*.sql")) if "rollback" not in p.name]

        # Ensure schema_migrations table exists
        try:
            self.session.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    id SERIAL PRIMARY KEY,
                    filename TEXT NOT NULL UNIQUE,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """
                )
            )
            self.session.commit()
        except Exception as e:
            logging.warning("Could not create schema_migrations table: %s", e)
            self.session.rollback()
            return

        # Get list of already-applied migrations
        try:
            existing = set(
                row[0] for row in self.session.execute(text("SELECT filename FROM schema_migrations")).fetchall()
            )
        except Exception as e:
            logging.warning("Could not query schema_migrations: %s", e)
            existing = set()

        # Determine which migrations to apply
        pending = [m for m in MIGRATION_FILES if m not in existing]

        if not pending:
            logging.info("All migrations already applied")
            return

        # Get migrations directory. The path differs between dev (running from a
        # repo checkout) and the Docker image: the Dockerfile copies logos/src
        # flat to /app/src but preserves the logos/ prefix for logos/db, so the
        # files land at /app/logos/db/migrations rather than /app/db/migrations.
        _here = pathlib.Path(__file__).resolve().parent
        _candidates = [
            _here.parent.parent.parent / "db" / "migrations",  # dev: <repo>/logos/db/migrations
            _here.parent.parent.parent / "logos" / "db" / "migrations",  # docker: /app/logos/db/migrations
            pathlib.Path("./logos/db/migrations"),  # CWD fallback
        ]
        migrations_dir = next((p for p in _candidates if p.exists()), _candidates[0])
        if not migrations_dir.exists():
            logging.error(
                "Migrations directory not found. Tried: %s",
                ", ".join(str(p) for p in _candidates),
            )
            return

        if is_fresh_install:
            # Fresh install: just record all migrations without executing
            logging.info(
                "Fresh install detected — recording all %d migrations as applied",
                len(MIGRATION_FILES),
            )
            for migration_file in MIGRATION_FILES:
                try:
                    self.session.execute(
                        text("INSERT INTO schema_migrations (filename) VALUES (:filename) ON CONFLICT DO NOTHING"),
                        {"filename": migration_file},
                    )
                except Exception as e:
                    logging.warning("Could not record migration %s: %s", migration_file, e)
            self.session.commit()
        else:
            # Existing install: execute pending migrations
            logging.info("Applying %d pending migrations", len(pending))
            # Migrations change the live schema; invalidate the reflected
            # metadata so subsequent insert()/update() calls re-reflect.
            _reset_metadata()
            for migration_file in pending:
                migration_path = migrations_dir / migration_file
                if not migration_path.exists():
                    logging.warning("Migration file not found: %s", migration_file)
                    continue

                # Special handling for migration 015 (pg_cron extension)
                is_pg_cron = migration_file == "015_add_snapshot_retention_cron.sql"

                try:
                    migration_sql = migration_path.read_text()

                    # Execute migration in its own transaction
                    try:
                        self.session.execute(text(migration_sql))
                        self.session.commit()
                    except Exception as e:
                        if is_pg_cron:
                            # pg_cron might not be available; log warning but don't block startup
                            logging.warning(
                                "Migration %s skipped (pg_cron may not be installed): %s",
                                migration_file,
                                e,
                            )
                            self.session.rollback()
                        else:
                            raise

                    # Record migration as applied
                    self.session.execute(
                        text("INSERT INTO schema_migrations (filename) VALUES (:filename) ON CONFLICT DO NOTHING"),
                        {"filename": migration_file},
                    )
                    self.session.commit()
                    logging.info("Applied migration: %s", migration_file)
                except Exception as e:
                    logging.error("Error applying migration %s: %s", migration_file, e)
                    self.session.rollback()

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

        provider_type = normalize_provider_type(original_provider_type)

        if provider_type in {"node", "node_controller", "ollama", "logos_worker_node"}:
            provider_type = "logosnode"

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
                                            weight_cost, weight_quality, tags, parallel, description)
                        VALUES (:name, 0, 0, 0, 0, '', 1, '')
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
            ollama_admin_url: Internal admin endpoint for Ollama (e.g., http://gpu-vm-1:11434)
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
        Insert Ollama provider snapshot into monitoring table.

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
            INSERT INTO ollama_provider_snapshots (
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
                "loaded_models": json.dumps(loaded_models),
                "snapshot_source": snapshot_source or "unknown",
                "runtime_payload": json.dumps(runtime_payload or {}),
                "scheduler_signals": json.dumps(scheduler_signals or {}),
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
                residency_source, measurement_count, last_measured_at,
                observed_gpu_memory_utilization, min_gpu_memory_utilization_to_load,
                updated_at
            ) VALUES (
                :provider_id, :model_name,
                :base_residency_mb, :loaded_vram_mb, :sleeping_residual_mb,
                :kv_budget_mb, :disk_size_bytes, :engine,
                :tensor_parallel_size, :kv_per_token_bytes, :max_context_length,
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

    def get_ollama_vram_stats(
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
            FROM ollama_provider_snapshots s
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
            logger.error(f"Failed to query ollama_vram_stats: {e}")
            return {"error": str(e)}, 500

    def get_ollama_vram_deltas(
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
                FROM ollama_provider_snapshots s
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
                FROM ollama_provider_snapshots s
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
            logger.error(f"Failed to query ollama_vram_deltas: {e}")
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
                    UNION
                    SELECT m.id FROM models m
                    WHERE (
                        SELECT u.role FROM users u
                        JOIN api_keys ak ON ak.user_id = u.id
                        WHERE ak.id = :api_key_id
                    ) = 'logos_admin'
                ) em ON em.model_id = m.id
                JOIN (
                    SELECT provider_id FROM api_key_provider_permissions akpp
                    JOIN api_keys ak ON ak.id = akpp.api_key_id
                    WHERE ak.id = :api_key_id AND ak.use_custom_permissions = true
                    UNION
                    SELECT tpp.provider_id FROM team_provider_permissions tpp
                    JOIN api_keys ak ON ak.team_id = tpp.team_id
                    WHERE ak.id = :api_key_id AND ak.use_custom_permissions = false
                    UNION
                    SELECT p.id FROM providers p
                    WHERE (
                        SELECT u.role FROM users u
                        JOIN api_keys ak ON ak.user_id = u.id
                        WHERE ak.id = :api_key_id
                    ) = 'logos_admin'
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
                            SELECT p.id AS provider_id
                            FROM providers p, key_info ki
                            WHERE ki.user_role = 'logos_admin'
                            UNION
                            SELECT akpp.provider_id
                            FROM api_key_provider_permissions akpp, key_info ki
                            WHERE akpp.api_key_id = ki.aki AND ki.custom = true
                            UNION
                            SELECT tpp.provider_id
                            FROM team_provider_permissions tpp, key_info ki
                            WHERE tpp.team_id = ki.tid AND ki.custom = false
                        ),
                        effective_models AS (
                            SELECT m.id AS model_id
                            FROM models m, key_info ki
                            WHERE ki.user_role = 'logos_admin'
                            UNION
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
                          p.privacy_level as privacy_level
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
                SELECT p.id AS provider_id
                FROM providers p, key_info ki
                WHERE ki.user_role = 'logos_admin'
                UNION
                SELECT akpp.provider_id
                FROM api_key_provider_permissions akpp, key_info ki
                WHERE akpp.api_key_id = ki.aki AND ki.custom = true
                UNION
                SELECT tpp.provider_id
                FROM team_provider_permissions tpp, key_info ki
                WHERE tpp.team_id = ki.tid AND ki.custom = false
            ),
            effective_models AS (
                SELECT m.id AS model_id
                FROM models m, key_info ki
                WHERE ki.user_role = 'logos_admin'
                UNION
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
           ORDER BY m.id
       """
        )
        rows = self.session.execute(sql, {"api_key_id": int(api_key_id)}).mappings().all()
        return [dict(row) for row in rows]

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
                SELECT p.id AS provider_id
                FROM providers p, key_info ki
                WHERE ki.user_role = 'logos_admin'
                UNION
                SELECT akpp.provider_id
                FROM api_key_provider_permissions akpp, key_info ki
                WHERE akpp.api_key_id = ki.aki AND ki.custom = true
                UNION
                SELECT tpp.provider_id
                FROM team_provider_permissions tpp, key_info ki
                WHERE tpp.team_id = ki.tid AND ki.custom = false
            ),
            effective_models AS (
                SELECT m.id AS model_id
                FROM models m, key_info ki
                WHERE ki.user_role = 'logos_admin'
                UNION
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
                              m.parallel,
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
                                m.parallel,
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
                "parallel": r.parallel,
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
            "parallel": result.parallel,
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
                'ollama',
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
        ], 200

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
        api_key_id: int,
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
        payload_str = json.dumps(input_payload) if log_level == "FULL" and input_payload else None
        headers_str = json.dumps(dict(headers)) if log_level == "FULL" and headers else None

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
                "payload": json.dumps(payload) if payload else None,
                "provider_id": provider_id,
                "model_id": model_id,
                "timestamp": datetime.datetime.now(datetime.timezone.utc),
                "log_id": log_id,
                "policy_id": policy_id if policy_id != -1 else None,
                "classification_statistics": json.dumps(classified),
                "request_id": kwargs.get("request_id"),
                "queue_depth": kwargs.get("queue_depth_at_arrival"),
                "utilization": kwargs.get("utilization_at_arrival"),
            },
        )
        self.session.commit()
        return {"result": "response_payload set"}, 200

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
        role = data.pop("role", None)

        if role == "logos_admin":
            settings = data.get("settings")
            if isinstance(settings, str):
                try:
                    settings = json.loads(settings)
                except Exception:
                    settings = {}
            elif not settings:
                settings = {}

            limit_keys = [
                "budget_limit_micro_cents",
                "cloud_rpm_limit",
                "cloud_tpm_limit",
                "local_rpm_limit",
                "local_tpm_limit",
                "rpm_limit",
                "tpm_limit",
            ]
            for l_key in limit_keys:
                settings.pop(l_key, None)

            data["settings"] = settings

        return data

    def get_team_budget_usage(self, team_id: int, month_start: str) -> int:
        row = self.session.execute(
            text(
                """
                 SELECT COALESCE(SUM(bu.cost_micro_cents), 0) AS total
                 FROM budget_usage bu
                          JOIN api_keys ak ON ak.id = bu.api_key_id
                 WHERE ak.team_id = :tid
                   AND ak.key_type = 'developer'
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
                "settings": json.dumps(settings) if settings else None,
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
                          t.default_monthly_budget_micro_cents                      AS default_limit,
                          u.role
                   FROM api_keys ak
                            LEFT JOIN teams t ON t.id = ak.team_id
                            LEFT JOIN users u ON u.id = ak.user_id
                   WHERE ak.id = :aki
                   """
        )
        row = self.session.execute(sql, {"aki": api_key_id}).fetchone()

        if not row:
            return None

        if row.role == "logos_admin":
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
