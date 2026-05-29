"""
Central Manager for all Database-related actions for Logos
"""

import csv
import datetime
import io
import json
import logging
import os
import re
import secrets
import threading
from typing import Any, Dict, List, Optional, Tuple, Union, cast

import sqlalchemy.exc
import yaml
from dateutil.parser import isoparse
from sqlalchemy import MetaData, Table, create_engine, func, text
from sqlalchemy.orm import sessionmaker

from logos.classification.model_handler import ModelHandler
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

    def drop_all(self):
        Base.metadata.drop_all(self.engine)

    def add_user(self, username, prename, name):
        user = User(username=username, prename=prename, name=name)
        self.session.add(user)
        self.session.commit()
        return user

    def get_users(self):
        return self.session.query(User).all()

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

    def upsert_request_log(self, request_id: str, **fields: Any) -> None:
        """
        Canonical upsert helper for request lifecycle/performance data on `log_entry`.
        """
        self.update_request_log_metrics(request_id=request_id, **fields)

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

    def fetch_all(self, table_name: str) -> list[Dict[str, Any]]:
        table = Table(table_name, self.metadata, autoload_with=self.engine)
        result = self.session.execute(table.select()).mappings().all()
        return [dict(row) for row in result]

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

    def fetch_llm_key(self, logos_key: str):
        sql = text(
            """
                   WITH key_info AS (
                       SELECT ak.id AS aki, ak.team_id AS tid, u.role AS user_role
                       FROM api_keys ak
                       LEFT JOIN users u ON ak.user_id = u.id
                       WHERE ak.key_value = :logos_key
                         AND ak.is_active = true
                   ),
                        effective_permissions AS (
                            SELECT m.id AS model_id
                            FROM models m,
                                 key_info ki
                            WHERE ki.user_role = 'logos_admin'

                            UNION

                            SELECT model_id
                            FROM api_key_model_permissions
                            WHERE api_key_id = (SELECT aki FROM key_info)

                            UNION

                            SELECT tmp.model_id
                            FROM team_model_permissions tmp
                            JOIN key_info ki ON ki.tid = tmp.team_id
                        )
                   SELECT mp.api_key,
                          p.name as name,
                          p.base_url,
                          p.id   as provider_id,
                          p.auth_name,
                          p.auth_format,
                          ki.aki as api_key_id
                   FROM key_info ki
                            JOIN effective_permissions ep ON 1 = 1
                            JOIN models m ON m.id = ep.model_id
                            JOIN model_provider mp ON mp.model_id = m.id
                            JOIN providers p ON p.id = mp.provider_id
                   WHERE ki.aki IS NOT NULL LIMIT 1
                   """
        )

        result = self.session.execute(sql, {"logos_key": logos_key}).fetchone()
        if result:
            return {
                "api_key": result.api_key,
                "provider_name": result.name,
                "base_url": result.base_url,
                "provider_id": result.provider_id,
                "auth_name": result.auth_name,
                "auth_format": result.auth_format,
                "api_key_id": result.api_key_id,
            }
        return None

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

    def add_model(self, logos_key: str, name: str):
        if not self.check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500
        pk = self.insert(
            "models",
            {
                "name": name,
                # Some deployed databases enforce non-null model weight columns even though the
                # local ORM marks them optional. Seed a neutral baseline so admin model creation
                # works before any explicit ranking/rebalancing happens.
                "weight_latency": 0,
                "weight_accuracy": 0,
                "weight_cost": 0,
                "weight_quality": 0,
                "tags": "",
                "parallel": 1,
                "description": "",
            },
        )
        return {"result": "Created Model", "model_id": pk}, 200

    def add_full_model(
        self,
        logos_key: str,
        name: str,
        worse_accuracy: int = None,
        worse_quality: int = None,
        worse_latency: int = None,
        worse_cost: int = None,
        tags: str = "",
        parallel: int = 1,
        description: str = "",
    ):
        if not self.check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500
        pk = self.insert(
            "models",
            {
                "name": name,
                # Seed explicit numeric weights before the rebalance step so stricter live
                # schemas do not reject the initial insert.
                "weight_latency": 0,
                "weight_accuracy": 0,
                "weight_cost": 0,
                "weight_quality": 0,
                "tags": tags,
                "parallel": parallel,
                "description": description,
            },
        )
        return self.rebalance_added_model(pk, worse_accuracy, worse_quality, worse_latency, worse_cost)

    def update_model_weights(self, logos_key: str, id: int, category: str, value: int):
        if not self.check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500
        if category not in {"latency", "accuracy", "quality", "cost"}:
            return {"error": f"Invalid category '{category}'"}, 500
        return self.rebalance_updated_model(id, category, value)

    def delete_model(self, logos_key: str, id: int):
        if not self.check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500
        return self.rebalance_deleted_model(id)

    def rebuild_model_weights(
        self,
        accuracy: ModelHandler,
        quality: ModelHandler,
        latency: ModelHandler,
        cost: ModelHandler,
    ):
        models = dict()
        for model in accuracy.get_models():
            if model[1] not in models:
                models[model[1]] = {
                    "accuracy": model[0],
                    "quality": -1,
                    "latency": -1,
                    "cost": -1,
                }
            else:
                models[model[1]]["accuracy"] = model[0]
        for model in quality.get_models():
            if model[1] not in models:
                models[model[1]] = {
                    "accuracy": -1,
                    "quality": model[0],
                    "latency": -1,
                    "cost": -1,
                }
            else:
                models[model[1]]["quality"] = model[0]
        for model in latency.get_models():
            if model[1] not in models:
                models[model[1]] = {
                    "accuracy": -1,
                    "quality": -1,
                    "latency": model[0],
                    "cost": -1,
                }
            else:
                models[model[1]]["latency"] = model[0]
        for model in cost.get_models():
            if model[1] not in models:
                models[model[1]] = {
                    "accuracy": -1,
                    "quality": -1,
                    "latency": -1,
                    "cost": model[0],
                }
            else:
                models[model[1]]["cost"] = model[0]
        for model in models:
            self.update(
                "models",
                model,
                {
                    "weight_accuracy": models[model]["accuracy"],
                    "weight_quality": models[model]["quality"],
                    "weight_latency": models[model]["latency"],
                    "weight_cost": models[model]["cost"],
                },
            )

    def rebalance_updated_model(self, updated_model_id: int, category: str, feedback: Union[str, int]):
        data = self.get_all_models_data()
        accuracy_data = list()
        quality_data = list()
        latency_data = list()
        cost_data = list()
        for model in data:
            mid, l, a, c, q = model[0], model[2], model[3], model[4], model[5]
            accuracy_data.append((a, mid))
            quality_data.append((q, mid))
            latency_data.append((l, mid))
            cost_data.append((c, mid))
        accuracy_data = list(sorted(accuracy_data, key=lambda x: x[0]))
        quality_data = list(sorted(quality_data, key=lambda x: x[0]))
        latency_data = list(sorted(latency_data, key=lambda x: x[0]))
        cost_data = list(sorted(cost_data, key=lambda x: x[0]))
        accuracy = ModelHandler(accuracy_data)
        quality = ModelHandler(quality_data)
        latency = ModelHandler(latency_data)
        cost = ModelHandler(cost_data)
        if category == "accuracy":
            accuracy.give_feedback(updated_model_id, feedback)
        elif category == "quality":
            quality.give_feedback(updated_model_id, feedback)
        elif category == "latency":
            latency.give_feedback(updated_model_id, feedback)
        elif category == "cost":
            cost.give_feedback(updated_model_id, feedback)
        logging.debug(f"Accuracy-Models: {accuracy.get_models()}")
        logging.debug(f"Quality-Models: {quality.get_models()}")
        logging.debug(f"Latency-Models: {latency.get_models()}")
        logging.debug(f"Cost-Models: {cost.get_models()}")
        self.rebuild_model_weights(accuracy, quality, latency, cost)
        return {"result": "Updated Model"}, 200

    def rebalance_deleted_model(self, deleted_model_id: int):
        data = self.get_all_models_data()
        accuracy_data = list()
        quality_data = list()
        latency_data = list()
        cost_data = list()
        for model in data:
            mid, l, a, c, q = model[0], model[2], model[3], model[4], model[5]
            accuracy_data.append((a, mid))
            quality_data.append((q, mid))
            latency_data.append((l, mid))
            cost_data.append((c, mid))
        accuracy_data = list(sorted(accuracy_data, key=lambda x: x[0]))
        quality_data = list(sorted(quality_data, key=lambda x: x[0]))
        latency_data = list(sorted(latency_data, key=lambda x: x[0]))
        cost_data = list(sorted(cost_data, key=lambda x: x[0]))
        accuracy = ModelHandler(accuracy_data)
        accuracy.remove_model(deleted_model_id)
        quality = ModelHandler(quality_data)
        quality.remove_model(deleted_model_id)
        latency = ModelHandler(latency_data)
        latency.remove_model(deleted_model_id)
        cost = ModelHandler(cost_data)
        cost.remove_model(deleted_model_id)
        logging.debug(f"Accuracy-Models: {accuracy.get_models()}")
        logging.debug(f"Quality-Models: {quality.get_models()}")
        logging.debug(f"Latency-Models: {latency.get_models()}")
        logging.debug(f"Cost-Models: {cost.get_models()}")
        self.rebuild_model_weights(accuracy, quality, latency, cost)
        self.delete("models", deleted_model_id)
        return {"result": "Deleted Model"}, 200

    def rebalance_added_model(
        self,
        new_model_id: int,
        worse_accuracy: int,
        worse_quality: int,
        worse_latency: int,
        worse_cost: int,
    ):
        data = self.get_all_models_data()
        accuracy_data = list()
        quality_data = list()
        latency_data = list()
        cost_data = list()
        for model in data:
            mid, l, a, c, q = model[0], model[2], model[3], model[4], model[5]
            if mid == new_model_id:
                continue
            accuracy_data.append((a, mid))
            quality_data.append((q, mid))
            latency_data.append((l, mid))
            cost_data.append((c, mid))
        accuracy_data = list(sorted(accuracy_data, key=lambda x: x[0]))
        quality_data = list(sorted(quality_data, key=lambda x: x[0]))
        latency_data = list(sorted(latency_data, key=lambda x: x[0]))
        cost_data = list(sorted(cost_data, key=lambda x: x[0]))
        accuracy = ModelHandler(accuracy_data)
        accuracy.add_model(worse_accuracy, new_model_id)
        quality = ModelHandler(quality_data)
        quality.add_model(worse_quality, new_model_id)
        latency = ModelHandler(latency_data)
        latency.add_model(worse_latency, new_model_id)
        cost = ModelHandler(cost_data)
        cost.add_model(worse_cost, new_model_id)
        logging.debug(f"Accuracy-Models: {accuracy.get_models()}")
        logging.debug(f"Quality-Models: {quality.get_models()}")
        logging.debug(f"Latency-Models: {latency.get_models()}")
        logging.debug(f"Cost-Models: {cost.get_models()}")
        # Collect rebalanced model weights
        self.rebuild_model_weights(accuracy, quality, latency, cost)
        return {"result": "Created Model", "model_id": new_model_id}, 200

    def add_policy(
        self,
        logos_key: str,
        name: str,
        description: str,
        threshold_privacy: str,
        threshold_latency: int,
        threshold_accuracy: int,
        threshold_cost: int,
        threshold_quality: int,
        priority: int,
        topic: str,
        api_key_id: int = None,
        team_id: int = None,
    ):
        if not self.check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500
        pk = self.insert(
            "policies",
            {
                "name": name,
                "description": description,
                "threshold_privacy": threshold_privacy,
                "threshold_latency": threshold_latency,
                "threshold_accuracy": threshold_accuracy,
                "threshold_cost": threshold_cost,
                "threshold_quality": threshold_quality,
                "priority": priority,
                "topic": topic,
                "api_key_id": api_key_id,
                "team_id": team_id,
            },
        )
        return {"result": "Created Policy", "policy-id": pk}, 200

    def update_policy(
        self,
        logos_key: str,
        id: int,
        name: str,
        description: str,
        threshold_privacy: str,
        threshold_latency: int,
        threshold_accuracy: int,
        threshold_cost: int,
        threshold_quality: int,
        priority: int,
        topic: str,
        api_key_id: Optional[int] = None,
        team_id: Optional[int] = None,
    ):
        if not self.check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500
        self.update(
            "policies",
            id,
            {
                "name": name,
                "description": description,
                "threshold_privacy": threshold_privacy,
                "threshold_latency": threshold_latency,
                "threshold_accuracy": threshold_accuracy,
                "threshold_cost": threshold_cost,
                "threshold_quality": threshold_quality,
                "priority": priority,
                "topic": topic,
                "api_key_id": api_key_id,
                "team_id": team_id,
            },
        )
        return {"result": "Created Policy"}, 200

    def delete_policy(self, logos_key: str, id: int):
        if not self.check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500
        self.delete("policies", id)
        return {"result": "Deleted Policy"}, 200

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

    def add_billing(
        self, logos_key: str, type_name: str, type_cost: float, valid_from: str, model_id: int | None = None
    ):
        if not self.check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500
        if (token_id := self.get_token_name(type_name)) is None:
            return {"error": "Token name not found"}, 500
        try:
            timestamp_clean = valid_from.rstrip("Z")
            timestamp = isoparse(timestamp_clean)
        except ValueError as e:
            return {"error": f"Invalid timestamp format: {str(e)}"}, 500

        billing_id = self.insert(
            "token_prices",
            {"type_id": token_id, "valid_from": timestamp, "price_per_k_token": round(type_cost), "model_id": model_id},
        )
        return {"result": "Successfully added billing", "billing-id": billing_id}, 200

    def generalstats(self, logos_key: str):
        if not self.user_authorization(logos_key):
            return {"error": "Unknown user."}, 500
        model_count = self.session.query(func.count(Model.id)).scalar()
        key_count = self.session.execute(text("SELECT COUNT(*) FROM api_keys WHERE is_active = true")).scalar()
        request_count = self.session.query(func.count(LogEntry.id)).scalar()

        return {
            "models": model_count,
            "api_keys": key_count,
            "requests": request_count,
        }, 200

    def get_request_log_stats(
        self,
        logos_key: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        target_buckets: int = 120,
    ):
        """
        Aggregate request performance metrics for a given time range.

        Args:
            logos_key: authentication key
            start_date: ISO timestamp (inclusive). Defaults to 30 days before end_date.
            end_date: ISO timestamp (inclusive). Defaults to now (UTC).
            target_buckets: Desired number of buckets for time-series aggregation (auto-adjusted).
        """
        if not self.user_authorization(logos_key):
            return {"error": "Unknown user."}, 500

        # Resolve date range
        now = datetime.datetime.now(datetime.timezone.utc)
        end_dt = isoparse(end_date).astimezone(datetime.timezone.utc) if end_date else now
        start_dt = (
            isoparse(start_date).astimezone(datetime.timezone.utc)
            if start_date
            else end_dt - datetime.timedelta(days=30)
        )
        if start_dt > end_dt:
            return {"error": "start_date must be before end_date"}, 400

        # Bucket sizing: tighter buckets for narrow ranges, looser for broad ranges
        duration_seconds = max((end_dt - start_dt).total_seconds(), 1)
        target_buckets = max(int(target_buckets or 120), 1)
        raw_bucket = max(duration_seconds / target_buckets, 60)  # never below 1 minute
        nice_candidates = [
            60,
            300,
            900,
            1800,
            3600,
            10800,
            21600,
            43200,
            86400,
        ]  # 1m .. 24h
        bucket_seconds = min(nice_candidates, key=lambda b: abs(b - raw_bucket))

        params = {
            "start_ts": start_dt,
            "end_ts": end_dt,
            "bucket_seconds": bucket_seconds,
        }
        ts_expr = "COALESCE(timestamp_forwarding, timestamp_request, timestamp_response)"

        # Last event timestamp
        last_ts = self.session.execute(
            text(f"SELECT MAX({ts_expr}) AS last_ts FROM log_entry WHERE {ts_expr} BETWEEN :start_ts AND :end_ts"),
            params,
        ).scalar()
        last_event_ts = last_ts.isoformat() if last_ts else None

        # Totals and averages
        totals_row = (
            self.session.execute(
                text(
                    f"""
            SELECT
                COUNT(*) AS requests,
                COUNT(*) FILTER (WHERE is_cloud) AS cloud_requests,
                COUNT(*) FILTER (WHERE NOT is_cloud) AS local_requests,
                COUNT(*) FILTER (WHERE cold_start IS TRUE) AS cold_starts,
                COUNT(*) FILTER (WHERE cold_start IS NOT TRUE) AS warm_starts,
                AVG(queue_seconds) AS avg_queue_seconds,
                AVG(run_seconds) AS avg_run_seconds
            FROM (
                SELECT
                    le.was_cold_start AS cold_start,
                    CASE WHEN p.privacy_level = 'LOCAL' OR p.privacy_level IS NULL THEN FALSE ELSE TRUE END AS is_cloud,
                    CASE WHEN le.timestamp_request IS NOT NULL AND le.timestamp_forwarding IS NOT NULL
                        THEN EXTRACT(EPOCH FROM (le.timestamp_forwarding - le.timestamp_request)) END AS queue_seconds,
                    CASE WHEN le.timestamp_forwarding IS NOT NULL AND le.timestamp_response IS NOT NULL
                        THEN EXTRACT(EPOCH FROM (le.timestamp_response - le.timestamp_forwarding)) END AS run_seconds
                FROM log_entry le
                LEFT JOIN models m ON m.id = le.model_id
                LEFT JOIN providers p ON p.id = le.provider_id
                WHERE {ts_expr} BETWEEN :start_ts AND :end_ts
            ) stats
        """
                ),
                params,
            )
            .mappings()
            .first()
            or {}
        )

        totals = {
            "requests": int(totals_row.get("requests") or 0),
            "cloudRequests": int(totals_row.get("cloud_requests") or 0),
            "localRequests": int(totals_row.get("local_requests") or 0),
            "coldStarts": int(totals_row.get("cold_starts") or 0),
            "warmStarts": int(totals_row.get("warm_starts") or 0),
            "avgQueueSeconds": (
                float(totals_row["avg_queue_seconds"]) if totals_row.get("avg_queue_seconds") is not None else None
            ),
            "avgRunSeconds": (
                float(totals_row["avg_run_seconds"]) if totals_row.get("avg_run_seconds") is not None else None
            ),
        }

        # Status counts
        status_rows = (
            self.session.execute(
                text(
                    f"""
            SELECT COALESCE(result_status::text, 'unknown') AS status, COUNT(*) AS count
            FROM log_entry
            WHERE {ts_expr} BETWEEN :start_ts AND :end_ts
            GROUP BY COALESCE(result_status::text, 'unknown')
        """
                ),
                params,
            )
            .mappings()
            .all()
        )
        status_counts = {row["status"].lower(): int(row["count"]) for row in status_rows}

        # Model breakdown
        model_rows = (
            self.session.execute(
                text(
                    f"""
            SELECT
                re.model_id,
                COALESCE(m.name, CONCAT('Model ', re.model_id::text)) AS model_name,
                re.provider_id,
                COALESCE(p.name, CONCAT('Provider ', re.provider_id::text)) AS provider_name,
                COUNT(*) AS request_count,
                AVG(queue_seconds) AS avg_queue_seconds,
                AVG(run_seconds) AS avg_run_seconds,
                SUM(CASE WHEN re.was_cold_start IS TRUE THEN 1 ELSE 0 END) AS cold_starts,
                SUM(CASE WHEN re.was_cold_start IS NOT TRUE THEN 1 ELSE 0 END) AS warm_starts,
                SUM(CASE
                    WHEN re.result_status IS DISTINCT FROM 'success'
                         OR (re.error_message IS NOT NULL AND re.error_message != '')
                    THEN 1 ELSE 0 END) AS error_count
            FROM (
                SELECT
                    le.*,
                    CASE WHEN le.timestamp_request IS NOT NULL AND le.timestamp_forwarding IS NOT NULL
                        THEN EXTRACT(EPOCH FROM (le.timestamp_forwarding - le.timestamp_request)) END AS queue_seconds,
                    CASE WHEN le.timestamp_forwarding IS NOT NULL AND le.timestamp_response IS NOT NULL
                        THEN EXTRACT(EPOCH FROM (le.timestamp_response - le.timestamp_forwarding)) END AS run_seconds
                FROM log_entry le
                WHERE {ts_expr} BETWEEN :start_ts AND :end_ts
            ) re
            LEFT JOIN models m ON m.id = re.model_id
            LEFT JOIN providers p ON p.id = re.provider_id
            GROUP BY re.model_id, model_name, re.provider_id, provider_name
            ORDER BY request_count DESC
        """
                ),
                params,
            )
            .mappings()
            .all()
        )
        model_breakdown = [
            {
                "modelId": row["model_id"] if row["model_id"] is not None else -1,
                "modelName": row["model_name"],
                "providerName": row["provider_name"],
                "requestCount": int(row["request_count"] or 0),
                "avgQueueSeconds": (float(row["avg_queue_seconds"]) if row["avg_queue_seconds"] is not None else None),
                "avgRunSeconds": (float(row["avg_run_seconds"]) if row["avg_run_seconds"] is not None else None),
                "coldStarts": int(row["cold_starts"] or 0),
                "warmStarts": int(row["warm_starts"] or 0),
                "errorCount": int(row["error_count"] or 0),
            }
            for row in model_rows
        ]

        # Time series bucketed by bucket_seconds, with gap filling for idle periods
        time_rows = (
            self.session.execute(
                text(
                    f"""
            WITH bucket_series AS (
                SELECT generate_series(
                    to_timestamp(FLOOR(EXTRACT(EPOCH FROM :start_ts) / :bucket_seconds) * :bucket_seconds),
                    to_timestamp(FLOOR(EXTRACT(EPOCH FROM :end_ts) / :bucket_seconds) * :bucket_seconds),
                    (:bucket_seconds || ' seconds')::interval
                ) AS bucket_ts
            ),
            agg AS (
                SELECT
                    to_timestamp(FLOOR(EXTRACT(EPOCH FROM {ts_expr}) / :bucket_seconds) * :bucket_seconds) AS bucket_ts,
                    COUNT(*) AS total,
                    SUM(CASE WHEN p.privacy_level = 'LOCAL' OR p.privacy_level IS NULL THEN 0 ELSE 1 END) AS cloud,
                    SUM(CASE WHEN p.privacy_level = 'LOCAL' OR p.privacy_level IS NULL THEN 1 ELSE 0 END) AS local,
                    AVG(CASE WHEN re.timestamp_forwarding IS NOT NULL AND re.timestamp_response IS NOT NULL
                        THEN EXTRACT(
                            EPOCH FROM (re.timestamp_response - re.timestamp_forwarding)
                        ) END
                    ) AS avg_run_seconds,
                    AVG(re.available_vram_mb) AS avg_vram
                FROM log_entry re
                LEFT JOIN models m ON m.id = re.model_id
                LEFT JOIN providers p ON p.id = re.provider_id
                WHERE {ts_expr} BETWEEN :start_ts AND :end_ts
                GROUP BY 1
            )
            SELECT
                EXTRACT(EPOCH FROM bs.bucket_ts) AS bucket_ts,
                COALESCE(agg.total, 0) AS total,
                COALESCE(agg.cloud, 0) AS cloud,
                COALESCE(agg.local, 0) AS local,
                agg.avg_run_seconds,
                agg.avg_vram
            FROM bucket_series bs
            LEFT JOIN agg ON agg.bucket_ts = bs.bucket_ts
            ORDER BY bs.bucket_ts
        """
                ),
                params,
            )
            .mappings()
            .all()
        )
        time_series = [
            {
                "timestamp": (int(row["bucket_ts"]) * 1000 if row["bucket_ts"] is not None else None),
                "label": "",
                "cloud": int(row["cloud"] or 0),
                "local": int(row["local"] or 0),
                "total": int(row["total"] or 0),
                "avgRunSeconds": (float(row["avg_run_seconds"]) if row["avg_run_seconds"] is not None else None),
                "avgVram": (float(row["avg_vram"]) if row["avg_vram"] is not None else None),
            }
            for row in time_rows
            if row["bucket_ts"] is not None
        ]

        # Per-model time series (bucketed by time AND model).
        # We only return rows for actual model traffic, so avoid joining against
        # a generated empty bucket series (saves DB work for wide windows).
        model_ts_rows = (
            self.session.execute(
                text(
                    f"""
            SELECT
                EXTRACT(
                    EPOCH FROM to_timestamp(
                        FLOOR(EXTRACT(EPOCH FROM {ts_expr}) / :bucket_seconds) * :bucket_seconds
                    )
                ) AS bucket_ts,
                re.model_id,
                COALESCE(m.name, CONCAT('Model ', re.model_id::text)) AS model_name,
                COUNT(*) AS count
            FROM log_entry re
            LEFT JOIN models m ON m.id = re.model_id
            WHERE {ts_expr} BETWEEN :start_ts AND :end_ts
              AND re.model_id IS NOT NULL
            GROUP BY 1, re.model_id, m.name
            ORDER BY 1, model_name
        """
                ),
                params,
            )
            .mappings()
            .all()
        )
        model_time_series: list[dict] = []
        for row in model_ts_rows:
            if row["bucket_ts"] is None:
                continue
            model_time_series.append(
                {
                    "timestamp": int(row["bucket_ts"]) * 1000,
                    "modelId": row["model_id"],
                    "modelName": row["model_name"],
                    "count": int(row["count"] or 0),
                }
            )

        # Queue depth
        queue_row = (
            self.session.execute(
                text(
                    f"""
            SELECT
                AVG(queue_depth_at_enqueue) AS avg_enqueue,
                AVG(queue_depth_at_schedule) AS avg_schedule,
                PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY queue_depth_at_enqueue) AS p95_enqueue,
                PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY queue_depth_at_schedule) AS p95_schedule
            FROM log_entry re
            WHERE {ts_expr} BETWEEN :start_ts AND :end_ts
              AND (queue_depth_at_enqueue IS NOT NULL OR queue_depth_at_schedule IS NOT NULL)
        """
                ),
                params,
            )
            .mappings()
            .first()
        )
        queue_depth = None
        if queue_row:
            queue_depth = {
                "avgEnqueueDepth": (
                    float(queue_row["avg_enqueue"]) if queue_row.get("avg_enqueue") is not None else None
                ),
                "avgScheduleDepth": (
                    float(queue_row["avg_schedule"]) if queue_row.get("avg_schedule") is not None else None
                ),
                "p95EnqueueDepth": (
                    float(queue_row["p95_enqueue"]) if queue_row.get("p95_enqueue") is not None else None
                ),
                "p95ScheduleDepth": (
                    float(queue_row["p95_schedule"]) if queue_row.get("p95_schedule") is not None else None
                ),
            }

        # Runtime by cold/warm
        runtime_rows = (
            self.session.execute(
                text(
                    f"""
            SELECT
                CASE WHEN was_cold_start IS TRUE THEN 'cold' ELSE 'warm' END AS kind,
                COUNT(*) AS count,
                AVG(CASE WHEN re.timestamp_forwarding IS NOT NULL AND re.timestamp_response IS NOT NULL
                    THEN EXTRACT(EPOCH FROM (re.timestamp_response - re.timestamp_forwarding)) END) AS avg_run_seconds
            FROM log_entry re
            WHERE {ts_expr} BETWEEN :start_ts AND :end_ts
            GROUP BY kind
        """
                ),
                params,
            )
            .mappings()
            .all()
        )
        runtime_by_cold = [
            {
                "type": row["kind"],
                "avgRunSeconds": (float(row["avg_run_seconds"]) if row["avg_run_seconds"] is not None else None),
                "count": int(row["count"] or 0),
            }
            for row in runtime_rows
        ]

        payload = {
            "range": {
                "start": start_dt.isoformat(),
                "end": end_dt.isoformat(),
            },
            "bucketSeconds": bucket_seconds,
            "stats": {
                "lastEventTs": last_event_ts,
                "totals": totals,
                "statusCounts": status_counts,
                "modelBreakdown": model_breakdown,
                "timeSeries": time_series,
                "modelTimeSeries": model_time_series,
                "queueDepth": queue_depth,
                "runtimeByColdStart": runtime_by_cold,
            },
        }
        return payload, 200

    def get_latest_requests(self, logos_key: str, limit: int = 10):
        """
        Fetch the most recent request logs with scheduling/performance metadata.
        """
        if not self.user_authorization(logos_key):
            return {"error": "Unknown user."}, 500

        sql = text(
            """
            SELECT
                le.request_id,
                COALESCE(m.name, CONCAT('Model ', le.model_id::text)) AS model_name,
                COALESCE(p.name, CONCAT('Provider ', le.provider_id::text)) AS provider_name,
                le.result_status,
                le.timestamp_request AS enqueue_ts,
                le.timestamp_forwarding AS scheduled_ts,
                le.timestamp_response AS request_complete_ts,
                CASE WHEN le.timestamp_forwarding IS NOT NULL AND le.timestamp_response IS NOT NULL
                     THEN EXTRACT(EPOCH FROM (le.timestamp_response - le.timestamp_forwarding))
                     ELSE NULL
                END AS run_seconds,
                CASE WHEN le.timestamp_request IS NOT NULL AND le.timestamp_forwarding IS NOT NULL
                     THEN EXTRACT(EPOCH FROM (le.timestamp_forwarding - le.timestamp_request))
                     ELSE NULL
                END AS queue_seconds,
                CASE WHEN le.timestamp_request IS NOT NULL AND le.timestamp_response IS NOT NULL
                     THEN EXTRACT(EPOCH FROM (le.timestamp_response - le.timestamp_request))
                     ELSE NULL
                END AS total_seconds,
                le.was_cold_start AS cold_start,
                le.initial_priority,
                le.priority_when_scheduled,
                le.queue_depth_at_enqueue,
                le.error_message
            FROM log_entry le
            LEFT JOIN models m ON m.id = le.model_id
            LEFT JOIN providers p ON p.id = le.provider_id
            WHERE le.request_id IS NOT NULL
            ORDER BY le.timestamp_request DESC NULLS LAST
            LIMIT :limit
        """
        )

        rows = self.session.execute(sql, {"limit": limit}).mappings().all()

        results = []
        for row in rows:
            results.append(
                {
                    "request_id": row["request_id"],
                    "model_name": row["model_name"],
                    "provider_name": row["provider_name"],
                    "status": (row["result_status"] if row["result_status"] else "pending"),
                    "timestamp": (row["enqueue_ts"].isoformat() if row["enqueue_ts"] else None),
                    "duration": (float(row["run_seconds"]) if row["run_seconds"] is not None else None),
                    "cold_start": row["cold_start"],
                    "enqueue_ts": (row["enqueue_ts"].isoformat() if row["enqueue_ts"] else None),
                    "scheduled_ts": (row["scheduled_ts"].isoformat() if row["scheduled_ts"] else None),
                    "request_complete_ts": (
                        row["request_complete_ts"].isoformat() if row["request_complete_ts"] else None
                    ),
                    "queue_seconds": (float(row["queue_seconds"]) if row["queue_seconds"] is not None else None),
                    "total_seconds": (float(row["total_seconds"]) if row["total_seconds"] is not None else None),
                    "initial_priority": row["initial_priority"],
                    "priority_when_scheduled": row["priority_when_scheduled"],
                    "queue_depth_at_enqueue": row["queue_depth_at_enqueue"],
                    "error_message": row["error_message"],
                }
            )

        return {"requests": results}, 200

    def get_paginated_requests(
        self,
        logos_key: str,
        page: int = 1,
        per_page: int = 20,
    ):
        """
        Fetch paginated request logs with provider type for Cloud/Local classification.
        """
        if not self.user_authorization(logos_key):
            return {"error": "Unknown user."}, 500

        page = max(1, int(page))
        per_page = max(1, min(100, int(per_page)))
        offset = (page - 1) * per_page

        count_sql = text(
            """
            SELECT COUNT(*) AS total
            FROM log_entry le
            WHERE le.request_id IS NOT NULL
              AND le.api_key_id = (
                  SELECT id FROM api_keys WHERE key_value = :logos_key LIMIT 1
              )
        """
        )
        total_row = self.session.execute(count_sql, {"logos_key": logos_key}).fetchone()
        total = int(total_row[0]) if total_row else 0
        total_pages = max(1, (total + per_page - 1) // per_page)

        sql = text(
            """
            SELECT
                le.request_id,
                COALESCE(m.name, CONCAT('Model ', le.model_id::text)) AS model_name,
                COALESCE(p.name, CONCAT('Provider ', le.provider_id::text)) AS provider_name,
                p.provider_type,
                le.result_status,
                le.timestamp_request     AS enqueue_ts,
                le.timestamp_forwarding  AS scheduled_ts,
                le.timestamp_response    AS request_complete_ts,
                CASE WHEN le.timestamp_forwarding IS NOT NULL AND le.timestamp_response IS NOT NULL
                     THEN EXTRACT(EPOCH FROM (le.timestamp_response - le.timestamp_forwarding))
                     ELSE NULL END AS run_seconds,
                CASE WHEN le.timestamp_request IS NOT NULL AND le.timestamp_forwarding IS NOT NULL
                     THEN EXTRACT(EPOCH FROM (le.timestamp_forwarding - le.timestamp_request))
                     ELSE NULL END AS queue_seconds,
                CASE WHEN le.timestamp_request IS NOT NULL AND le.timestamp_response IS NOT NULL
                     THEN EXTRACT(EPOCH FROM (le.timestamp_response - le.timestamp_request))
                     ELSE NULL END AS total_seconds,
                le.was_cold_start  AS cold_start,
                le.initial_priority,
                le.priority_when_scheduled,
                le.queue_depth_at_enqueue,
                le.error_message
            FROM log_entry le
            LEFT JOIN models    m ON m.id = le.model_id
            LEFT JOIN providers p ON p.id = le.provider_id
            WHERE le.request_id IS NOT NULL
              AND le.api_key_id = (
                  SELECT id FROM api_keys WHERE key_value = :logos_key LIMIT 1
              )
            ORDER BY le.timestamp_request DESC NULLS LAST
            LIMIT :per_page OFFSET :offset
        """
        )

        rows = (
            self.session.execute(sql, {"logos_key": logos_key, "per_page": per_page, "offset": offset}).mappings().all()
        )

        results = []
        for row in rows:
            pt = str(row["provider_type"] or "").lower()
            is_cloud = pt not in ("logosnode", "ollama", "")
            results.append(
                {
                    "request_id": row["request_id"],
                    "model_name": row["model_name"],
                    "provider_name": row["provider_name"],
                    "is_cloud": is_cloud,
                    "status": (row["result_status"] if row["result_status"] else "pending"),
                    "timestamp": (row["enqueue_ts"].isoformat() if row["enqueue_ts"] else None),
                    "duration": (float(row["run_seconds"]) if row["run_seconds"] is not None else None),
                    "cold_start": row["cold_start"],
                    "enqueue_ts": (row["enqueue_ts"].isoformat() if row["enqueue_ts"] else None),
                    "scheduled_ts": (row["scheduled_ts"].isoformat() if row["scheduled_ts"] else None),
                    "request_complete_ts": (
                        row["request_complete_ts"].isoformat() if row["request_complete_ts"] else None
                    ),
                    "queue_seconds": (float(row["queue_seconds"]) if row["queue_seconds"] is not None else None),
                    "total_seconds": (float(row["total_seconds"]) if row["total_seconds"] is not None else None),
                    "initial_priority": row["initial_priority"],
                    "priority_when_scheduled": row["priority_when_scheduled"],
                    "queue_depth_at_enqueue": row["queue_depth_at_enqueue"],
                    "error_message": row["error_message"],
                }
            )

        return {
            "requests": results,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
        }, 200

    def get_request_logs(self, logos_key: str, request_ids: list[str]):
        """
        Fetch request logs by request_id for the authenticated api_key.
        """
        if not self.user_authorization(logos_key):
            return {"error": "Unknown user."}, 500

        normalized_ids = []
        seen_ids = set()
        for request_id in request_ids:
            if not isinstance(request_id, str):
                continue
            value = request_id.strip()
            if not value or value in seen_ids:
                continue
            normalized_ids.append(value)
            seen_ids.add(value)

        if not normalized_ids:
            return {"requests": [], "missing_request_ids": []}, 200

        api_key_row = self.session.execute(
            text("SELECT id FROM api_keys WHERE key_value = :logos_key AND is_active = true"),
            {"logos_key": logos_key},
        ).fetchone()
        if api_key_row is None:
            return {"error": "Unknown or inactive api key."}, 500

        sql = text(
            """
            SELECT
                le.request_id,
                COALESCE(m.name, CONCAT('Model ', le.model_id::text)) AS model_name,
                COALESCE(p.name, CONCAT('Provider ', le.provider_id::text)) AS provider_name,
                le.result_status,
                le.timestamp_request AS enqueue_ts,
                le.timestamp_forwarding AS scheduled_ts,
                le.timestamp_response AS request_complete_ts,
                le.time_at_first_token,
                CASE WHEN le.timestamp_request IS NOT NULL AND le.time_at_first_token IS NOT NULL
                     THEN EXTRACT(EPOCH FROM (le.time_at_first_token - le.timestamp_request)) * 1000
                     ELSE NULL
                END AS ttft_ms,
                CASE WHEN le.timestamp_request IS NOT NULL AND le.timestamp_response IS NOT NULL
                     THEN EXTRACT(EPOCH FROM (le.timestamp_response - le.timestamp_request)) * 1000
                     ELSE NULL
                END AS total_latency_ms,
                CASE WHEN le.timestamp_request IS NOT NULL AND le.timestamp_forwarding IS NOT NULL
                     THEN EXTRACT(EPOCH FROM (le.timestamp_forwarding - le.timestamp_request)) * 1000
                     ELSE NULL
                END AS queue_wait_ms,
                CASE WHEN le.timestamp_forwarding IS NOT NULL AND le.timestamp_response IS NOT NULL
                     THEN EXTRACT(EPOCH FROM (le.timestamp_response - le.timestamp_forwarding)) * 1000
                     ELSE NULL
                END AS processing_ms,
                CASE WHEN le.timestamp_request IS NOT NULL AND le.timestamp_response IS NOT NULL
                     THEN EXTRACT(EPOCH FROM (le.timestamp_response - le.timestamp_request)) * 1000
                     ELSE NULL
                END AS scheduler_total_ms,
                le.was_cold_start AS cold_start,
                le.queue_depth_at_arrival,
                le.utilization_at_arrival,
                le.queue_depth_at_schedule,
                le.priority_when_scheduled,
                le.load_duration_ms,
                le.available_vram_mb,
                le.azure_rate_remaining_requests,
                le.azure_rate_remaining_tokens,
                le.error_message,
                MAX(CASE WHEN tt.name = 'prompt_tokens' THEN ut.token_count END) AS prompt_tokens,
                MAX(CASE WHEN tt.name = 'completion_tokens' THEN ut.token_count END) AS completion_tokens,
                MAX(CASE WHEN tt.name = 'total_tokens' THEN ut.token_count END) AS total_tokens
            FROM log_entry le
            LEFT JOIN models m ON m.id = le.model_id
            LEFT JOIN providers p ON p.id = le.provider_id
            LEFT JOIN usage_tokens ut ON ut.log_entry_id = le.id
            LEFT JOIN token_types tt ON tt.id = ut.type_id
           WHERE le.api_key_id = :api_key_id
              AND le.request_id = ANY (:request_ids)
            GROUP BY
                le.request_id, m.name, le.model_id, p.name, le.provider_id, le.result_status,
                le.timestamp_request, le.timestamp_forwarding, le.timestamp_response,
                le.time_at_first_token, le.was_cold_start, le.queue_depth_at_arrival,
                le.utilization_at_arrival, le.queue_depth_at_schedule, le.priority_when_scheduled,
                le.load_duration_ms, le.available_vram_mb, le.azure_rate_remaining_requests,
                le.azure_rate_remaining_tokens, le.error_message
            ORDER BY le.timestamp_request ASC NULLS LAST
        """
        )

        rows = (
            self.session.execute(
                sql,
                {"api_key_id": int(api_key_row.id), "request_ids": normalized_ids},
            )
            .mappings()
            .all()
        )

        results = []
        found_ids = set()
        for row in rows:
            request_id = row["request_id"]
            found_ids.add(request_id)
            results.append(
                {
                    "request_id": request_id,
                    "status": (row["result_status"] if row["result_status"] else "pending"),
                    "provider_name": row["provider_name"],
                    "model_name": row["model_name"],
                    "enqueue_ts": (row["enqueue_ts"].isoformat() if row["enqueue_ts"] else None),
                    "scheduled_ts": (row["scheduled_ts"].isoformat() if row["scheduled_ts"] else None),
                    "request_complete_ts": (
                        row["request_complete_ts"].isoformat() if row["request_complete_ts"] else None
                    ),
                    "ttft_ms": (float(row["ttft_ms"]) if row["ttft_ms"] is not None else None),
                    "total_latency_ms": (
                        float(row["total_latency_ms"]) if row["total_latency_ms"] is not None else None
                    ),
                    "queue_wait_ms": (float(row["queue_wait_ms"]) if row["queue_wait_ms"] is not None else None),
                    "processing_ms": (float(row["processing_ms"]) if row["processing_ms"] is not None else None),
                    "scheduler_total_ms": (
                        float(row["scheduler_total_ms"]) if row["scheduler_total_ms"] is not None else None
                    ),
                    "cold_start": row["cold_start"],
                    "queue_depth_at_arrival": (
                        int(row["queue_depth_at_arrival"]) if row["queue_depth_at_arrival"] is not None else None
                    ),
                    "utilization_at_arrival": (
                        float(row["utilization_at_arrival"]) if row["utilization_at_arrival"] is not None else None
                    ),
                    "queue_depth_at_schedule": (
                        int(row["queue_depth_at_schedule"]) if row["queue_depth_at_schedule"] is not None else None
                    ),
                    "priority_when_scheduled": row["priority_when_scheduled"],
                    "load_duration_ms": (
                        float(row["load_duration_ms"]) if row["load_duration_ms"] is not None else None
                    ),
                    "available_vram_mb": (
                        int(row["available_vram_mb"]) if row["available_vram_mb"] is not None else None
                    ),
                    "azure_rate_remaining_requests": (
                        int(row["azure_rate_remaining_requests"])
                        if row["azure_rate_remaining_requests"] is not None
                        else None
                    ),
                    "azure_rate_remaining_tokens": (
                        int(row["azure_rate_remaining_tokens"])
                        if row["azure_rate_remaining_tokens"] is not None
                        else None
                    ),
                    "error_message": row["error_message"],
                    "prompt_tokens": (int(row["prompt_tokens"]) if row["prompt_tokens"] is not None else None),
                    "completion_tokens": (
                        int(row["completion_tokens"]) if row["completion_tokens"] is not None else None
                    ),
                    "total_tokens": (int(row["total_tokens"]) if row["total_tokens"] is not None else None),
                }
            )

        missing_request_ids = [request_id for request_id in normalized_ids if request_id not in found_ids]
        return {"requests": results, "missing_request_ids": missing_request_ids}, 200

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

    def get_role(self, logos_key: str):
        sql = text(
            """
            SELECT 1
            FROM api_keys
            WHERE key_value = :logos_key
                and is_active = true
        """
        )
        entity = self.session.execute(sql, {"logos_key": logos_key}).fetchone() is not None
        admin = self.check_authorization(logos_key)
        if admin:
            return {"role": "root"}, 200
        elif entity:
            return {"role": "entity"}, 200
        return {"error": "unknown key"}, 500

    def connect_api_key_provider(self, logos_key: str, api_key_id: int, provider_id: int):
        """
        Grant an API Key access to all models served by a provider.
        """
        if not self.check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500

        if self.get_api_key_by_id(api_key_id) is None:
            return {"error": f"API Key {api_key_id} not found."}, 404
        if self.get_provider(provider_id) is None:
            return {"error": f"Provider {provider_id} not found."}, 404

        model_rows = self.session.execute(
            text("SELECT model_id FROM model_provider WHERE provider_id = :provider_id"),
            {"provider_id": int(provider_id)},
        ).fetchall()

        created = 0
        for row in model_rows:
            upsert_sql = text(
                """
                              INSERT INTO api_key_model_permissions (api_key_id, model_id)
                              VALUES (:api_key_id, :model_id) ON CONFLICT DO NOTHING
                              RETURNING api_key_id
                              """
            )
            result = self.session.execute(
                upsert_sql,
                {"api_key_id": int(api_key_id), "model_id": int(row.model_id)},
            ).fetchone()
            if result:
                created += 1
        self.session.commit()
        return {"result": f"Granted access to {created} model(s) for provider {provider_id}."}, 200

    def connect_api_key_model(self, logos_key: str, api_key_id: int, model_id: int):
        if not self.check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500

        sql = text(
            """
                   INSERT INTO api_key_model_permissions (api_key_id, model_id)
                   VALUES (:api_key_id, :model_id) ON CONFLICT DO NOTHING
                   RETURNING api_key_id
                   """
        )
        result = self.session.execute(sql, {"api_key_id": int(api_key_id), "model_id": int(model_id)}).fetchone()
        self.session.commit()

        if result:
            return {"result": "Connected api key to model."}, 200
        return {"result": "Already connected."}, 200

    def create_application_key(self, logos_key: str, team_id: int, key_name: str, environment: str = "-"):
        if not self.check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500

        existing = self.session.execute(
            text(
                """
                SELECT id FROM api_keys
                WHERE team_id = :tid
                  AND key_type = 'application'
                  AND environment = :env
                  AND is_active = true
            """
            ),
            {"tid": int(team_id), "env": environment},
        ).fetchone()

        if existing:
            return {"error": f"This team already has an active application key for environment '{environment}'."}, 400

        res = self.create_api_key(
            name=key_name,
            key_type="application",
            team_id=int(team_id),
            user_id=None,
            environment=environment,
            log="BILLING",
            settings={},
        )
        return {
            "result": f"Created App Key. ID: {res['id']}.",
            "api-key": res["key_value"],
        }, 200

    def connect_model_provider(
        self, logos_key: str, model_id: int, provider_id: int, api_key: str = None, endpoint: str = None
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
            {"pid": int(provider_id), "mid": int(model_id), "api_key": api_key, "endpoint": endpoint or None},
        ).fetchone()
        self.session.commit()

        return {"result": f"Connected Model to Provider. ID: {result.id}."}, 200

    def disconnect_model_provider(self, logos_key: str, model_id: int, provider_id: int):
        if not self.check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500

        sql = text(
            """
                   DELETE
                   FROM model_provider
                   WHERE model_id = :mid
                     AND provider_id = :pid RETURNING id
                   """
        )

        result = self.session.execute(sql, {"mid": int(model_id), "pid": int(provider_id)}).fetchone()

        self.session.commit()

        if result:
            return {"result": "Disconnected model from provider."}, 200
        return {"error": "Connection not found."}, 404

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

    def get_ollama_providers(self) -> List[Dict[int, str]]:
        """
        Get all ollama providers IDs from providers table.

        Returns:
            List of:
            - provider ID
            - ollama_admin_url
        """
        sql = text(
            """
            SELECT id, ollama_admin_url, name
            FROM providers
            WHERE provider_type = 'logosnode'
              AND ollama_admin_url IS NOT NULL
              AND ollama_admin_url != ''
            ORDER BY id
        """
        )

        result = self.session.execute(sql).fetchall()
        providers: List[Dict[int, str]] = []
        for row in result:
            providers.append(
                {
                    "id": row.id,
                    "ollama_admin_url": row.ollama_admin_url,
                    "name": row.name,
                }
            )
        return providers

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

    def get_request_enqueues_deltas(
        self,
        logos_key: str,
        after_enqueue_ts: Optional[str],
        after_request_id: Optional[str],
        until_ts: Optional[str] = None,
        limit: int = 5000,
    ) -> Tuple[Dict[str, Any], int]:
        """
        Return enqueue-event deltas after a tuple cursor (enqueue_ts, request_id).

        Args:
            logos_key: Auth key
            after_enqueue_ts: Cursor timestamp (ISO) or None for full start
            after_request_id: Cursor request_id for tie-breaking identical timestamps
            until_ts: Optional upper bound timestamp (ISO), defaults to now UTC
            limit: Max rows returned
        """
        if not self.user_authorization(logos_key):
            return {"error": "Unknown user."}, 500

        tz_utc = datetime.timezone.utc
        cursor_request_id = str(after_request_id or "")
        row_limit = max(1, int(limit or 5000))

        cursor_dt: Optional[datetime.datetime] = None
        if after_enqueue_ts:
            try:
                cursor_dt = isoparse(after_enqueue_ts).astimezone(tz_utc)
            except Exception:
                return {"error": f"Invalid after_enqueue_ts format: {after_enqueue_ts}"}, 400

        if until_ts:
            try:
                until_dt = isoparse(until_ts).astimezone(tz_utc)
            except Exception:
                return {"error": f"Invalid until_ts format: {until_ts}"}, 400
        else:
            until_dt = datetime.datetime.now(tz_utc)

        if cursor_dt and cursor_dt > until_dt:
            return {"error": "after_enqueue_ts must be <= until_ts"}, 400

        if cursor_dt is None:
            sql = text(
                """
                SELECT
                    re.request_id,
                    re.timestamp_request AS enqueue_ts,
                    p.privacy_level
                FROM log_entry re
                LEFT JOIN models m ON m.id = re.model_id
                LEFT JOIN providers p ON p.id = re.provider_id
                WHERE re.timestamp_request IS NOT NULL
                  AND re.request_id IS NOT NULL
                  AND re.timestamp_request <= :until_ts
                ORDER BY re.timestamp_request, re.request_id
                LIMIT :limit
            """
            )
            params = {
                "until_ts": until_dt,
                "limit": row_limit,
            }
        else:
            sql = text(
                """
                SELECT
                    re.request_id,
                    re.timestamp_request AS enqueue_ts,
                    p.privacy_level
                FROM log_entry re
                LEFT JOIN models m ON m.id = re.model_id
                LEFT JOIN providers p ON p.id = re.provider_id
                WHERE re.timestamp_request IS NOT NULL
                  AND re.request_id IS NOT NULL
                  AND (re.timestamp_request, re.request_id) > (:cursor_ts, :cursor_request_id)
                  AND re.timestamp_request <= :until_ts
                ORDER BY re.timestamp_request, re.request_id
                LIMIT :limit
            """
            )
            params = {
                "cursor_ts": cursor_dt,
                "cursor_request_id": cursor_request_id,
                "until_ts": until_dt,
                "limit": row_limit,
            }

        try:
            rows = self.session.execute(sql, params).mappings().all()

            events: List[Dict[str, Any]] = []
            next_cursor_ts = after_enqueue_ts
            next_cursor_id = cursor_request_id

            for row in rows:
                enqueue_ts = row.get("enqueue_ts")
                request_id = str(row.get("request_id") or "")
                if not enqueue_ts or not request_id:
                    continue

                privacy_level = row.get("privacy_level")
                is_cloud = privacy_level is not None and privacy_level != "LOCAL"
                ts_iso = enqueue_ts.astimezone(tz_utc).isoformat()
                ts_ms = int(enqueue_ts.timestamp() * 1000)

                events.append(
                    {
                        "request_id": request_id,
                        "enqueue_ts": ts_iso,
                        "timestamp_ms": ts_ms,
                        "is_cloud": bool(is_cloud),
                    }
                )
                next_cursor_ts = ts_iso
                next_cursor_id = request_id

            return {
                "events": events,
                "cursor": {
                    "enqueue_ts": next_cursor_ts,
                    "request_id": next_cursor_id,
                },
            }, 200
        except Exception as e:
            logger.error(f"Failed to query request enqueue deltas: {e}")
            return {"error": str(e)}, 500

    def get_request_enqueues_in_range(
        self,
        logos_key: str,
        start_ts: str,
        end_ts: str,
        limit: int = 200000,
    ) -> Tuple[Dict[str, Any], int]:
        """
        Return enqueue events for a fixed time window.

        Args:
            logos_key: Auth key
            start_ts: Inclusive range start (ISO timestamp)
            end_ts: Inclusive range end (ISO timestamp)
            limit: Max rows returned
        """
        if not self.user_authorization(logos_key):
            return {"error": "Unknown user."}, 500

        tz_utc = datetime.timezone.utc
        row_limit = max(1, int(limit or 200000))

        try:
            start_dt = isoparse(start_ts).astimezone(tz_utc)
        except Exception:
            return {"error": f"Invalid start_ts format: {start_ts}"}, 400

        try:
            end_dt = isoparse(end_ts).astimezone(tz_utc)
        except Exception:
            return {"error": f"Invalid end_ts format: {end_ts}"}, 400

        if start_dt > end_dt:
            return {"error": "start_ts must be <= end_ts"}, 400

        sql = text(
            """
            SELECT
                re.request_id,
                re.timestamp_request AS enqueue_ts,
                p.privacy_level
            FROM log_entry re
            LEFT JOIN models m ON m.id = re.model_id
            LEFT JOIN providers p ON p.id = re.provider_id
            WHERE re.timestamp_request IS NOT NULL
              AND re.request_id IS NOT NULL
              AND re.timestamp_request >= :start_ts
              AND re.timestamp_request <= :end_ts
            ORDER BY re.timestamp_request, re.request_id
            LIMIT :limit
        """
        )
        params = {
            "start_ts": start_dt,
            "end_ts": end_dt,
            "limit": row_limit,
        }

        try:
            rows = self.session.execute(sql, params).mappings().all()
            events: List[Dict[str, Any]] = []
            last_cursor_ts: Optional[str] = None
            last_cursor_id = ""

            for row in rows:
                enqueue_ts = row.get("enqueue_ts")
                request_id = str(row.get("request_id") or "")
                if not enqueue_ts or not request_id:
                    continue

                privacy_level = row.get("privacy_level")
                is_cloud = privacy_level is not None and privacy_level != "LOCAL"
                ts_iso = enqueue_ts.astimezone(tz_utc).isoformat()
                ts_ms = int(enqueue_ts.timestamp() * 1000)

                events.append(
                    {
                        "request_id": request_id,
                        "enqueue_ts": ts_iso,
                        "timestamp_ms": ts_ms,
                        "is_cloud": bool(is_cloud),
                    }
                )
                last_cursor_ts = ts_iso
                last_cursor_id = request_id

            return {
                "events": events,
                "cursor": {
                    "enqueue_ts": last_cursor_ts,
                    "request_id": last_cursor_id,
                },
            }, 200
        except Exception as e:
            logger.error(f"Failed to query request enqueue range: {e}")
            return {"error": str(e)}, 500

    def add_model_provider_api_key(
        self,
        logos_key: str,
        model_name: str,
        model_endpoint: str,
        provider_id: int,
        api_key_id: int,
        api_key: str,
    ):
        if not self.check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500
        r, c = self.add_model(logos_key, model_name)
        if c != 200:
            return r, c
        model_id = r["model_id"]
        r, c = self.connect_model_provider(logos_key, model_id, provider_id, api_key=api_key, endpoint=model_endpoint)
        if c != 200:
            return r, c
        r, c = self.connect_api_key_model(logos_key, api_key_id, model_id)
        if c != 200:
            return r, c
        return {"result": f"Successfully added model and connected to api_key_id {api_key_id}"}, 200

    def set_api_key_log(self, api_key_id: int, log_level: str):
        if log_level not in {"BILLING", "FULL"}:
            return {"error": "Invalid logging level. Choose between 'BILLING' and 'FULL'"}, 400

        sql = text(
            """
                   UPDATE api_keys
                   SET log = :log_level
                   WHERE id = :api_key_id
                   """
        )
        self.session.execute(sql, {"log_level": log_level, "api_key_id": int(api_key_id)})
        self.session.commit()
        return {"result": f"Updated log level to {log_level}"}, 200

    def get_api_key_id(self, logos_key: str):
        sql = text(
            """
                   SELECT id
                   FROM api_keys
                   WHERE key_value = :logos_key
                     AND is_active = true
                   """
        )
        exc = self.session.execute(sql, {"logos_key": logos_key}).fetchone()
        if exc is None:
            return {"error": "Key not found"}, 500
        return {"result": exc[0]}, 200

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
                    SELECT model_id FROM api_key_model_permissions WHERE api_key_id = :api_key_id
                    UNION
                    SELECT tmp.model_id FROM team_model_permissions tmp
                    JOIN api_keys ak ON ak.team_id = tmp.team_id WHERE ak.id = :api_key_id
                    UNION
                    SELECT m.id FROM models m
                    WHERE (
                        SELECT u.role FROM users u
                        JOIN api_keys ak ON ak.user_id = u.id
                        WHERE ak.id = :api_key_id
                    ) = 'logos_admin'
                ) ep ON ep.model_id = m.id
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
                   WITH key_info AS (SELECT ak.id AS aki, ak.team_id AS tid, u.role AS user_role
                                     FROM api_keys ak
                                              LEFT JOIN users u ON ak.user_id = u.id
                                     WHERE ak.id = :api_key_id
                                       AND ak.is_active = true),
                        effective_permissions AS (
                            SELECT m.id AS model_id
                            FROM models m,
                                 key_info ki
                            WHERE ki.user_role = 'logos_admin'
                            UNION
                            SELECT model_id
                            FROM api_key_model_permissions
                            WHERE api_key_id = (SELECT aki FROM key_info)
                            UNION
                            SELECT tmp.model_id
                            FROM team_model_permissions tmp
                                     JOIN key_info ki ON ki.tid = tmp.team_id)
                   SELECT m.id               as model_id,
                          p.id               as provider_id,
                          p.provider_type    as type,
                          p.privacy_level    as privacy_level
                   FROM models m
                            JOIN model_provider mp ON m.id = mp.model_id
                            JOIN providers p ON mp.provider_id = p.id
                            JOIN effective_permissions ep ON m.id = ep.model_id
                   WHERE p.provider_type NOT IN ('logosnode')
                   UNION
                   SELECT m.id               as model_id,
                          p.id               as provider_id,
                          p.provider_type    as type,
                          p.privacy_level as privacy_level
                   FROM models m
                            JOIN model_provider mp ON m.id = mp.model_id
                            JOIN providers p ON mp.provider_id = p.id
                            JOIN effective_permissions ep ON m.id = ep.model_id
                   WHERE p.provider_type IN ('logosnode')
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
           WITH key_info AS (SELECT ak.id AS aki, ak.team_id AS tid, u.role AS user_role
                             FROM api_keys ak
                                      LEFT JOIN users u ON ak.user_id = u.id
                             WHERE ak.id = :api_key_id
                               AND ak.is_active = true),
                effective_permissions AS (SELECT m.id AS model_id
                                          FROM models m,
                                               key_info ki
                                          WHERE ki.user_role = 'logos_admin'

                                          UNION

                                          SELECT model_id
                                          FROM api_key_model_permissions
                                          WHERE api_key_id = :api_key_id

                                          UNION

                                          SELECT tmp.model_id
                                          FROM team_model_permissions tmp
                                                   JOIN key_info ki ON ki.tid = tmp.team_id)
           SELECT DISTINCT m.id, m.name, m.description
           FROM models m
                JOIN effective_permissions ep ON m.id = ep.model_id
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
           WITH key_info AS (SELECT ak.id AS aki, ak.team_id AS tid, u.role AS user_role
                             FROM api_keys ak
                                      LEFT JOIN users u ON ak.user_id = u.id
                             WHERE ak.id = :api_key_id
                               AND ak.is_active = true),
                effective_permissions AS (
                    SELECT m.id AS model_id
                    FROM models m,
                         key_info ki
                    WHERE ki.user_role = 'logos_admin'

                    UNION

                    SELECT model_id
                    FROM api_key_model_permissions
                    WHERE api_key_id = (SELECT aki FROM key_info)

                    UNION

                    SELECT tmp.model_id
                    FROM team_model_permissions tmp
                             JOIN key_info ki ON ki.tid = tmp.team_id)
           SELECT DISTINCT m.id, m.name, m.description
           FROM models m
                JOIN effective_permissions ep ON m.id = ep.model_id
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

    def get_all_model_provider_pairs(self) -> list[dict]:
        rows = (
            self.session.execute(
                text(
                    """
                SELECT m.id AS model_id,
                       m.name AS model_name,
                       p.id AS provider_id,
                       p.cloud_provider_type
                FROM models m
                JOIN model_provider mp ON mp.model_id = m.id
                JOIN providers p ON p.id = mp.provider_id
                WHERE p.cloud_provider_type IS NOT NULL
                ORDER BY m.id, p.id
            """
                )
            )
            .mappings()
            .all()
        )
        return [dict(r) for r in rows]

    def get_cloud_providers_for_model(self, model_id: int) -> list[dict]:
        rows = (
            self.session.execute(
                text(
                    """
                SELECT p.id AS provider_id, p.cloud_provider_type
                FROM model_provider mp
                JOIN providers p ON p.id = mp.provider_id
                WHERE mp.model_id = :model_id
                  AND p.cloud_provider_type IS NOT NULL
            """
                ),
                {"model_id": model_id},
            )
            .mappings()
            .all()
        )
        return [dict(r) for r in rows]

    def upsert_model_token_price(
        self, model_id: int, token_type_name: str, price_per_k: int, valid_from, provider_id: int | None = None
    ) -> None:
        r, _ = self.add_token_type(token_type_name)
        type_id = r["token-type-id"]
        existing = self.session.execute(
            text(
                """
            SELECT price_per_k_token FROM token_prices
            WHERE model_id = :model_id AND type_id = :type_id
              AND (provider_id = :provider_id OR (provider_id IS NULL AND :provider_id IS NULL))
            ORDER BY valid_from DESC LIMIT 1
        """
            ),
            {"model_id": model_id, "type_id": type_id, "provider_id": provider_id},
        ).fetchone()
        if existing and existing[0] == price_per_k:
            return
        actual_valid_from = (
            datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc) if existing is None else valid_from
        )
        self.insert(
            "token_prices",
            {
                "type_id": type_id,
                "model_id": model_id,
                "provider_id": provider_id,
                "valid_from": actual_valid_from,
                "price_per_k_token": price_per_k,
            },
        )
        self.session.commit()

    def update_model_info(self, logos_key: str, model_id: int, **fields) -> tuple:
        if not self.check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500
        allowed = {
            "name",
            "description",
            "tags",
            "parallel",
            "weight_latency",
            "weight_accuracy",
            "weight_cost",
            "weight_quality",
        }
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not updates:
            return {"error": "No updatable fields provided"}, 400
        self.update("models", model_id, updates)
        return {"result": "Model updated"}, 200

    def get_providers(self, logos_key: str):
        """
        Get a list of providers accessible by a given key.
        """
        sql = text(
            """
            WITH key_info AS (SELECT ak.id AS aki, ak.team_id AS tid, u.role AS user_role
                              FROM api_keys ak
                                       LEFT JOIN users u ON ak.user_id = u.id
                              WHERE ak.key_value = :logos_key
                                AND ak.is_active = true),
                 effective_permissions AS (
                     SELECT m.id AS model_id
                     FROM models m,
                          key_info ki
                     WHERE ki.user_role = 'logos_admin'

                     UNION

                     SELECT model_id
                     FROM api_key_model_permissions
                     WHERE api_key_id = (SELECT aki FROM key_info)

                     UNION

                     SELECT tmp.model_id
                     FROM team_model_permissions tmp
                          JOIN key_info ki ON ki.tid = tmp.team_id)
            SELECT DISTINCT p.id
            FROM providers p
                 JOIN model_provider mp ON p.id = mp.provider_id
                 JOIN effective_permissions ep ON mp.model_id = ep.model_id
        """
        )
        result = self.session.execute(sql, {"logos_key": logos_key}).fetchall()
        return [i.id for i in result]

    def get_provider_info(self, logos_key: str):
        """
        Get a list of providers accessible by a given key.
        """
        if self.check_authorization(logos_key):
            sql = text(
                """
                SELECT id, name, base_url, api_key, provider_type, cloud_provider_type,
                       privacy_level, auth_name, auth_format
                FROM providers
                ORDER BY name ASC, id ASC
            """
            )
            result = self.session.execute(sql).fetchall()
        else:
            sql = text(
                """
                WITH key_info AS (
                    SELECT id AS aki, team_id AS tid
                    FROM api_keys
                    WHERE key_value = :logos_key
                      AND is_active = true
                ),
                effective_permissions AS (
                    SELECT model_id
                    FROM api_key_model_permissions
                    WHERE api_key_id = (SELECT aki FROM key_info)
                    UNION
                    SELECT tmp.model_id
                    FROM team_model_permissions tmp
                    JOIN key_info ki ON ki.tid = tmp.team_id
                )
                SELECT DISTINCT p.id, p.name, p.base_url, p.api_key, p.provider_type,
                                p.cloud_provider_type, p.privacy_level,
                                p.auth_name, p.auth_format
                FROM providers p
                JOIN model_provider mp ON p.id = mp.provider_id
                JOIN effective_permissions ep ON mp.model_id = ep.model_id
                ORDER BY p.name ASC
            """
            )
            result = self.session.execute(sql, {"logos_key": logos_key}).fetchall()
        return [
            {
                "id": r.id,
                "name": r.name,
                "base_url": r.base_url,
                "api_key": r.api_key,
                "provider_type": r.provider_type,
                "cloud_provider_type": r.cloud_provider_type,
                "privacy_level": r.privacy_level,
                "auth_name": r.auth_name,
                "auth_format": r.auth_format,
            }
            for r in result
        ]

    def get_general_provider_stats(self, logos_key: str):
        if not self.user_authorization(logos_key):
            return {"error": "Unknown user."}, 500
        provider_count = self.session.query(func.count(Provider.id)).scalar()
        return {
            "totalProviders": provider_count,
        }, 200

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
                       WITH key_info AS (SELECT id AS aki, team_id AS tid
                                         FROM api_keys
                                         WHERE key_value = :logos_key
                                           AND is_active = true),
                            effective_permissions AS (SELECT model_id
                                                      FROM api_key_model_permissions
                                                      WHERE api_key_id = (SELECT aki FROM key_info)
                                                      UNION
                                                      SELECT tmp.model_id
                                                      FROM team_model_permissions tmp
                                                               JOIN key_info ki ON ki.tid = tmp.team_id)
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
                           JOIN effective_permissions ep
                       ON m.id = ep.model_id
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

    def get_all_models_data(self):
        """
        Get a list of models and their data in the database. Used for rebalancing.
        """
        sql = text(
            """
            SELECT
                models.id,
                models.name,
                models.weight_latency,
                models.weight_accuracy,
                models.weight_cost,
                models.weight_quality,
                models.tags,
                models.parallel,
                models.description
            FROM models
        """
        )
        result = self.session.execute(sql).fetchall()
        return [
            (
                i.id,
                i.name,
                i.weight_latency,
                i.weight_accuracy,
                i.weight_cost,
                i.weight_quality,
                i.tags,
                i.parallel,
                i.description,
            )
            for i in result
        ]

    def get_policy_info(self, logos_key: str):
        """
        Get a list of policies accessible by a given key.
        """
        sql = text(
            """
            SELECT DISTINCT
                policies.id,
                policies.api_key_id,
                policies.team_id,
                policies.name,
                policies.description,
                policies.threshold_privacy,
                policies.threshold_latency,
                policies.threshold_accuracy,
                policies.threshold_cost,
                policies.threshold_quality,
                policies.priority,
                policies.topic
            FROM policies
                JOIN api_keys ON (
                policies.api_key_id = api_keys.id OR
                policies.team_id = api_keys.team_id
                )
           WHERE api_keys.key_value = :logos_key
                AND api_keys.is_active = true
        """
        )
        result = self.session.execute(sql, {"logos_key": logos_key}).fetchall()
        return [
            (
                i.id,
                i.api_key_id,
                i.team_id,
                i.name,
                i.description,
                i.threshold_privacy,
                i.threshold_latency,
                i.threshold_accuracy,
                i.threshold_cost,
                i.threshold_quality,
                i.priority,
                i.topic,
            )
            for i in result
        ]

    def get_general_model_stats(self, logos_key: str):
        if not self.user_authorization(logos_key):
            return {"error": "Unknown user."}, 500
        model_count = self.session.query(func.count(Model.id)).scalar()
        return {
            "totalModels": model_count,
        }, 200

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

    def get_connections_for_provider(self, provider_id: int) -> list[dict]:
        sql = text(
            """
                   SELECT m.id AS model_id,
                          m.name AS model_name,
                          mp.endpoint,
                          mp.api_key
                   FROM model_provider mp
                          JOIN models m ON m.id = mp.model_id
                   WHERE mp.provider_id = :pid
                   ORDER BY m.name ASC
                   """
        )
        rows = self.session.execute(sql, {"pid": int(provider_id)}).fetchall()
        return [
            {
                "model_id": r.model_id,
                "model_name": r.model_name,
                "endpoint": r.endpoint or "",
                "api_key": r.api_key or "",
            }
            for r in rows
        ]

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

    def update_provider_info(self, logos_key: str, provider_id: int, **kwargs) -> Tuple[dict, int]:
        if not self.check_authorization(logos_key):
            return {"error": "Provider changes only allowed for logos admin."}, 500
        allowed = {
            "name",
            "base_url",
            "api_key",
            "auth_name",
            "auth_format",
            "provider_type",
            "cloud_provider_type",
            "privacy_level",
        }
        updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
        if "provider_type" in updates:
            original_pt = updates["provider_type"]
            updates["provider_type"] = normalize_provider_type(original_pt)
            if "cloud_provider_type" not in updates:
                inferred = infer_cloud_provider_type(original_pt)
                if inferred:
                    updates["cloud_provider_type"] = inferred
        if "privacy_level" in updates and updates["privacy_level"] not in VALID_PRIVACY_LEVELS:
            return {"error": "Invalid privacy_level"}, 400
        if not updates:
            return {"error": "No valid fields to update"}, 400
        self.update("providers", provider_id, updates)
        return {"result": "Updated Provider."}, 200

    def delete_provider(self, logos_key: str, provider_id: int) -> Tuple[dict, int]:
        if not self.check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500
        self.delete("providers", provider_id)
        return {"result": "Deleted Provider."}, 200

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

    def get_provider_to_model(self, model_id: int):
        sql = text(
            """
                   SELECT provider_id
                   FROM model_provider
                   WHERE model_id = :model_id
                   """
        )
        result = self.session.execute(sql, {"model_id": int(model_id)}).fetchone()
        if result is None:
            return None
        return self.get_provider(result.provider_id)

    def get_key_to_model_provider(self, model_id: Optional[int], provider_id: int):
        if model_id is None:
            return None
        sql = text(
            """
                   SELECT api_key
                   FROM model_provider
                   WHERE model_provider.model_id = :model_id
                       and model_provider.provider_id = :provider_id
                   """
        )
        result = self.session.execute(sql, {"model_id": int(model_id), "provider_id": int(provider_id)}).fetchone()
        if result is None:
            return None
        return result.api_key

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

    def set_forward_timestamp(self, log_id: int):
        sql = text(
            """
                   UPDATE log_entry
                   SET timestamp_forwarding = :timestamp
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
        return {"result": "time_timestamp_forwarding set"}, 200

    def set_response_timestamp(self, log_id: int):
        sql = text(
            """
                   UPDATE log_entry
                   SET timestamp_response = :timestamp
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
        return {"result": "timestamp_response set"}, 200

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

    def export(self, logos_key: str):
        if not self.check_authorization(logos_key):
            return {"error": "Database exports only allowed for root user."}, 403

        data = {}
        for table in Base.metadata.sorted_tables:
            rows = self.session.execute(table.select()).fetchall()
            data[table.name] = [dict(row._mapping) for row in rows]

        return {"result": data}, 200

    def reset_sequences(self):
        # Adjust ID's after importing data
        for table_name in [
            "users",
            "teams",
            "api_keys",
            "providers",
            "models",
            "model_provider",
            "policies",
            "log_entry",
            "token_types",
            "usage_tokens",
            "token_prices",
            "jobs",
        ]:
            self._reset_sequence_for_table(table_name, commit=False)
        self.session.commit()

    def import_from_json(self, logos_key: str, json_data: dict):
        if not self.check_authorization(logos_key):
            return {"error": "Database changes only allowed for root user."}, 500
        # Store table names to prevent silent errors on foreign key insertions
        table_names = [
            "users",
            "teams",
            "team_members",
            "api_keys",
            "providers",
            "models",
            "model_provider",
            "team_model_permissions",
            "api_key_model_permissions",
            "policies",
            "log_entry",
            "token_types",
            "usage_tokens",
            "token_prices",
            "jobs",
        ]
        for table_name in table_names:
            if table_name not in json_data:
                return {"error": f"Missing table in json: {table_name}"}, 500
            rows = json_data[table_name]
            table = Base.metadata.tables.get(table_name)
            if table is not None:
                if rows:
                    self.session.execute(table.delete())
                    self.session.execute(table.insert(), rows)
                else:
                    self.session.execute(table.delete())
            if table_name == "users":
                found = False
                for row in rows:
                    if row.get("username") == "root" or row.get("role") == "logos_admin":
                        found = True
                        break
                if not found:
                    return {"error": "Try to delete root user detected. Aborting"}, 500
        self.session.commit()
        self.reset_sequences()
        return {"result": "Imported data"}, 200

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

    def get_user_by_logos_key(self, logos_key: str):
        """Return user info for given logos_key. Returns None when the key is an application key (no linked user)"""
        sql = text(
            """
                   SELECT u.id,
                          u.username,
                          u.email,
                          u.role,
                          COALESCE(
                                  json_agg(
                                          json_build_object('id', t.id, 'name', t.name)
                                  ) FILTER(WHERE t.id IS NOT NULL),
                                  '[]' ::json
                          ) AS teams
                   FROM api_keys ak
                            JOIN users u ON ak.user_id = u.id
                            LEFT JOIN team_members tm ON u.id = tm.user_id
                            LEFT JOIN teams t ON tm.team_id = t.id
                   WHERE ak.key_value = :logos_key
                     AND ak.is_active = true
                   GROUP BY u.id, u.username, u.email, u.role
                   """
        )
        row = self.session.execute(sql, {"logos_key": logos_key}).fetchone()
        if row is None:
            return None

        data = dict(row._mapping)

        teams = data.get("teams", [])
        if isinstance(teams, str):
            import json

            teams = json.loads(teams)
        data["teams"] = teams

        return data

    def set_user_role(self, user_id: int, role: str):
        valid = {"app_developer", "app_admin", "logos_admin"}
        if role not in valid:
            return {"error": f"Invalid role '{role}'. Must be one of: {sorted(valid)}"}, 400
        sql = text(
            """
                   UPDATE users
                   SET role = :role
                   WHERE id = :user_id RETURNING id
                   """
        )
        row = self.session.execute(sql, {"role": role, "user_id": user_id}).fetchone()
        if row is None:
            return {"error": f"User {user_id} not found"}, 404
        self.session.commit()
        return {"result": "Role updated"}, 200

    def list_users(self) -> list[dict]:
        sql = text(
            """
                   SELECT u.id,
                          u.username,
                          u.prename,
                          u.name,
                          u.email,
                          u.role,
                          COALESCE(
                                  json_agg(
                                          json_build_object('id', t.id, 'name', t.name)
                                  ) FILTER(WHERE t.id IS NOT NULL),
                                  '[]' ::json
                          ) AS teams
                   FROM users u
                            LEFT JOIN team_members tm ON u.id = tm.user_id
                            LEFT JOIN teams t ON tm.team_id = t.id
                   GROUP BY u.id, u.username, u.prename, u.name, u.email, u.role
                   ORDER BY u.id DESC
                   """
        )
        rows = self.session.execute(sql).fetchall()
        result = []
        for row in rows:
            data = dict(row._mapping)
            teams = data.get("teams", [])
            if isinstance(teams, str):
                import json as _json

                teams = _json.loads(teams)
            data["teams"] = teams
            result.append(data)
        return result

    def create_user(
        self,
        prename: str,
        name: str,
        email: str | None,
        role: str,
        team_ids: list[int] = None,
    ) -> tuple:
        email = email or None
        if (
            email
            and self.session.execute(
                text("SELECT id FROM users WHERE lower(email) = lower(:email)"),
                {"email": email},
            ).fetchone()
        ):
            return {"error": "Email already in use"}, None, 409

        for _ in range(10):
            username = self._generate_username(prename, name)
            try:
                user_id = self.insert(
                    "users",
                    {
                        "username": username,
                        "prename": prename,
                        "name": name,
                        "email": email,
                        "role": role,
                    },
                )
                break
            except sqlalchemy.exc.IntegrityError:
                continue
        else:
            return {"error": "Could not generate a unique username"}, None, 500

        final_team_ids = team_ids if team_ids else []
        assigned_teams = []
        generated_keys = []

        for t_id in final_team_ids:
            t_row = self.session.execute(text("SELECT name FROM teams WHERE id = :tid"), {"tid": t_id}).fetchone()
            if not t_row:
                continue

            t_name = t_row.name

            self.insert("team_members", {"user_id": user_id, "team_id": t_id, "is_owner": False})
            assigned_teams.append({"id": t_id, "name": t_name})

            if username == "root":
                continue

            key_info = self.create_api_key(
                name=f"{username}-{t_name}-key",
                key_type="developer",
                team_id=t_id,
                user_id=user_id,
                environment="-",
                log="BILLING",
                settings={},
                default_priority=1,
            )
            generated_keys.append(key_info["key_value"])

        return (
            {
                "id": user_id,
                "username": username,
                "prename": prename,
                "name": name,
                "email": email,
                "role": role,
                "teams": assigned_teams,
            },
            generated_keys,
            200,
        )

    def _generate_username(self, prename: str, name: str) -> str:
        p = "".join(prename.strip().lower().split())
        n = "".join(name.strip().lower().split())

        if not p and not n:
            raise ValueError("First name and last name cannot both be empty.")

        candidates: list[str] = []

        for i in range(1, len(p) + 1):
            candidates.append(p[:i] + n)

        if not candidates:
            candidates.append(n)

        for candidate in candidates:
            exists = self.session.execute(
                text("SELECT id FROM users WHERE username = :username"),
                {"username": candidate},
            ).fetchone()

            if not exists:
                return candidate

        base = p + n if p else n
        i = 2

        while True:
            candidate = f"{base}{i}"

            exists = self.session.execute(
                text("SELECT id FROM users WHERE username = :username"),
                {"username": candidate},
            ).fetchone()

            if not exists:
                return candidate

            i += 1

    def _get_user_by_email(self, email: str) -> dict | None:
        row = self.session.execute(
            text("SELECT id, username FROM users WHERE lower(email) = lower(:email)"),
            {"email": email},
        ).fetchone()
        return dict(row._mapping) if row else None

    def update_user_info(
        self,
        user_id: int,
        prename: Optional[str],
        name: Optional[str],
        email: Optional[str],
    ) -> tuple[dict, int]:
        updates = []
        params = {"user_id": user_id}

        if prename is not None and prename.strip():
            updates.append("prename = :prename")
            params["prename"] = prename.strip()

        if name is not None and name.strip():
            updates.append("name = :name")
            params["name"] = name.strip()

        if email is not None and email.strip():
            existing = self.session.execute(
                text("SELECT id FROM users WHERE lower(email) = lower(:email) AND id != :user_id"),
                {"email": email.strip(), "user_id": user_id},
            ).fetchone()

            if existing:
                return {"error": "Email already in use by another user"}, 409

            updates.append("email = :email")
            params["email"] = email.strip()

        if not updates:
            return {"result": "No changes requested"}, 200

        sql_str = f"UPDATE users SET {', '.join(updates)} WHERE id = :user_id RETURNING id"
        row = self.session.execute(text(sql_str), params).fetchone()

        if row is None:
            return {"error": f"User {user_id} not found"}, 404

        self.session.commit()
        return {"result": "User info updated successfully"}, 200

    def _is_team_member(self, team_id: int, user_id: int) -> bool:
        return (
            self.session.execute(
                text("SELECT * FROM team_members " "WHERE team_id = :team_id AND user_id = :user_id"),
                {"team_id": team_id, "user_id": user_id},
            ).fetchone()
            is not None
        )

    def _get_team_by_name(self, name: str) -> dict | None:
        row = self.session.execute(
            text("SELECT id, name FROM teams WHERE name = :name"),
            {"name": name},
        ).fetchone()
        return dict(row._mapping) if row else None

    def import_users_from_csv(self, file_bytes: bytes) -> dict:
        from logos.dbutils.dbrequest import (
            CSV_HEADER_EMAIL,
            CSV_HEADER_NAME,
            CSV_HEADER_PRENAME,
            CSV_HEADER_TEAM,
            REQUIRED_CSV_HEADERS,
        )

        text_content = file_bytes.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text_content))

        actual_headers = set(reader.fieldnames or [])
        missing = REQUIRED_CSV_HEADERS - actual_headers
        if missing:
            return {"error": f"Missing required CSV headers: {', '.join(sorted(missing))}"}

        rows_out = []
        summary = {"created": 0, "existing": 0, "failed": 0}

        email_re = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

        for row in reader:
            prename = (row.get(CSV_HEADER_PRENAME) or "").strip()
            name = (row.get(CSV_HEADER_NAME) or "").strip()
            email = (row.get(CSV_HEADER_EMAIL) or "").strip()
            team = (row.get(CSV_HEADER_TEAM) or "").strip()

            def fail(reason: str) -> dict:
                summary["failed"] += 1
                return {
                    "email": email or None,
                    "username": None,
                    "apiKey": None,
                    "team": team or None,
                    "status": "failed",
                    "error": reason,
                }

            if not prename:
                rows_out.append(fail("prename is required"))
                continue
            if not name:
                rows_out.append(fail("name is required"))
                continue
            if not email:
                rows_out.append(fail("email is required"))
                continue
            if not email_re.match(email):
                rows_out.append(fail("email format is invalid"))
                continue

            team_names = [t.strip() for t in team.split(",") if t.strip()]
            team_ids = []

            if team_names:
                missing_teams = []
                for t_name in team_names:
                    t_obj = self._get_team_by_name(t_name)
                    if t_obj:
                        team_ids.append(t_obj["id"])
                    else:
                        missing_teams.append(t_name)

                if missing_teams:
                    rows_out.append(fail(f"Team(s) not found: {', '.join(missing_teams)}"))
                    continue

            try:
                existing = self._get_user_by_email(email)
                if existing:
                    user_id = existing["id"]
                    username = existing["username"]

                    newly_generated_keys = []
                    for tid in team_ids:
                        if not self._is_team_member(tid, user_id):
                            self.add_team_member(tid, user_id)

                            key_row = self.session.execute(
                                text("SELECT key_value FROM api_keys WHERE user_id = :uid AND team_id = :tid"),
                                {"uid": user_id, "tid": tid},
                            ).fetchone()

                            if key_row:
                                newly_generated_keys.append(key_row.key_value)

                    summary["existing"] += 1
                    rows_out.append(
                        {
                            "email": email,
                            "username": username,
                            "apiKey": ("\n".join(newly_generated_keys) if newly_generated_keys else None),
                            "team": team,
                            "status": "existing",
                            "error": None,
                        }
                    )
                else:
                    user_dict, generated_keys, status = self.create_user(
                        prename, name, email, "app_developer", team_ids=team_ids
                    )
                    if status != 200:
                        rows_out.append(fail(user_dict.get("error", "User creation failed")))
                        continue

                    summary["created"] += 1
                    rows_out.append(
                        {
                            "email": email,
                            "username": user_dict["username"],
                            "apiKey": ("\n".join(generated_keys) if generated_keys else None),
                            "team": team,
                            "status": "created",
                            "error": None,
                        }
                    )
            except Exception as exc:
                rows_out.append(fail(str(exc)))

        return {"summary": summary, "rows": rows_out}

    def delete_user(self, user_id: int) -> tuple[dict, int]:
        self.session.execute(text("DELETE FROM api_keys WHERE user_id = :uid"), {"uid": user_id})
        result = self.session.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": user_id})
        self.session.commit()

        if result.rowcount > 0:
            return {"result": "User deleted successfully"}, 200
        return {"error": "User not found"}, 404

    def list_teams(self, user_id: int | None = None, is_logos_admin: bool = False) -> list[dict]:
        if is_logos_admin:
            sql = text(
                """
                       SELECT t.id,
                              t.name,
                              t.default_cloud_rpm_limit,
                              t.default_cloud_tpm_limit,
                              t.default_local_rpm_limit,
                              t.default_local_tpm_limit,
                              t.default_monthly_budget_micro_cents,
                              t.team_monthly_budget_micro_cents,
                              COALESCE(json_agg(json_build_object('id', u.id, 'username', u.username))
                                       FILTER(WHERE u.id IS NOT NULL), '[]' ::json) AS owners,
                              (SELECT COUNT(*) FROM team_members WHERE team_id = t.id) AS member_count,
                              (SELECT COUNT(*) FROM team_model_permissions WHERE team_id = t.id) AS model_count,
                              true AS is_caller_owner
                       FROM teams t
                                LEFT JOIN team_members tm ON t.id = tm.team_id AND tm.is_owner = true
                                LEFT JOIN users u ON tm.user_id = u.id
                       GROUP BY t.id
                       ORDER BY t.id
                       """
            )
            params = {}
        else:
            sql = text(
                """
                       SELECT t.id,
                              t.name,
                              t.default_cloud_rpm_limit,
                              t.default_cloud_tpm_limit,
                              t.default_local_rpm_limit,
                              t.default_local_tpm_limit,
                              t.default_monthly_budget_micro_cents,
                              t.team_monthly_budget_micro_cents,
                              COALESCE(json_agg(json_build_object('id', u.id, 'username', u.username))
                                       FILTER(WHERE u.id IS NOT NULL), '[]' ::json) AS owners,
                              (SELECT COUNT(*) FROM team_members WHERE team_id = t.id) AS member_count,
                              (SELECT COUNT(*) FROM team_model_permissions WHERE team_id = t.id) AS model_count,
                              (SELECT is_owner
                               FROM team_members
                               WHERE team_id = t.id AND user_id = :uid) AS is_caller_owner
                       FROM teams t
                                LEFT JOIN team_members tm ON t.id = tm.team_id AND tm.is_owner = true
                                LEFT JOIN users u ON tm.user_id = u.id
                       WHERE EXISTS (SELECT 1 FROM team_members WHERE team_id = t.id AND user_id = :uid)
                       GROUP BY t.id
                       ORDER BY t.id
                       """
            )
            params = {"uid": user_id}

        rows = self.session.execute(sql, params).fetchall()
        result = []
        for row in rows:
            data = dict(row._mapping)
            owners = data.get("owners", [])
            if isinstance(owners, str):
                import json

                owners = json.loads(owners)
            data["owners"] = owners
            result.append(data)
        return result

    def create_team(
        self,
        name: str,
        owner_ids: list[int],
        default_cloud_rpm_limit: int | None = None,
        default_cloud_tpm_limit: int | None = None,
        default_local_rpm_limit: int | None = None,
        default_local_tpm_limit: int | None = None,
        default_monthly_budget_micro_cents: int | None = None,
        team_monthly_budget_micro_cents: int | None = None,
    ) -> tuple[int | None, int]:
        existing = self.session.execute(
            text("SELECT id FROM teams WHERE name = :name"),
            {"name": name},
        ).fetchone()
        if existing is not None:
            return None, 409
        row = self.session.execute(
            text(
                """
                 INSERT INTO teams (name,
                                    default_cloud_rpm_limit,
                                    default_cloud_tpm_limit,
                                    default_local_rpm_limit,
                                    default_local_tpm_limit,
                                    default_monthly_budget_micro_cents,
                                    team_monthly_budget_micro_cents)
                 VALUES (:name,
                         COALESCE(:c_rpm, :default_c_rpm),
                         COALESCE(:c_tpm, :default_c_tpm),
                         COALESCE(:l_rpm, :default_l_rpm),
                         COALESCE(:l_tpm, :default_l_tpm),
                         COALESCE(:mbudget, :default_mbudget),
                         COALESCE(:tbudget, :default_tbudget)) RETURNING id
                 """
            ),
            {
                "name": name,
                "c_rpm": default_cloud_rpm_limit,
                "c_tpm": default_cloud_tpm_limit,
                "l_rpm": default_local_rpm_limit,
                "l_tpm": default_local_tpm_limit,
                "mbudget": default_monthly_budget_micro_cents,
                "tbudget": team_monthly_budget_micro_cents,
                "default_c_rpm": DEFAULT_CLOUD_RPM_LIMIT,
                "default_c_tpm": DEFAULT_CLOUD_TPM_LIMIT,
                "default_l_rpm": DEFAULT_LOCAL_RPM_LIMIT,
                "default_l_tpm": DEFAULT_LOCAL_TPM_LIMIT,
                "default_mbudget": DEFAULT_MONTHLY_BUDGET_MICRO_CENTS,
                "default_tbudget": TEAM_MONTHLY_BUDGET_MICRO_CENTS,
            },
        ).fetchone()
        team_id = row.id
        for user_id in owner_ids:
            existing_member = self.session.execute(
                text("SELECT user_id FROM team_members WHERE team_id = :tid AND user_id = :uid"),
                {"tid": team_id, "uid": user_id},
            ).fetchone()
            self.session.execute(
                text(
                    """
                     INSERT INTO team_members (team_id, user_id, is_owner)
                     VALUES (:team_id, :user_id, true) ON CONFLICT (team_id, user_id) DO NOTHING
                     """
                ),
                {"team_id": team_id, "user_id": user_id},
            )
            if not existing_member:
                user_row = self.session.execute(
                    text("SELECT username FROM users WHERE id = :uid"),
                    {"uid": user_id},
                ).fetchone()
                if user_row and user_row.username != "root":
                    self.create_api_key(
                        name=f"{user_row.username}-{name}-key",
                        key_type="developer",
                        team_id=team_id,
                        user_id=user_id,
                        environment="-",
                        log="BILLING",
                        settings={},
                        default_priority=1,
                    )
        self.session.commit()
        return team_id, 200

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

    def delete_team(self, team_id: int):
        self.session.execute(text("DELETE FROM api_keys WHERE team_id = :tid"), {"tid": team_id})

        self.session.execute(text("DELETE FROM teams WHERE id = :tid"), {"tid": team_id})
        self.session.commit()
        return {"result": "Team deleted"}, 200

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

    def update_team_name(self, team_id: int, name: str):
        name = (name or "").strip()

        if not name:
            return {"error": "Team name is required"}, 422

        existing = self.session.execute(
            text(
                """
                 SELECT id
                 FROM teams
                 WHERE name = :name
                   AND id != :team_id
                 """
            ),
            {"name": name, "team_id": team_id},
        ).fetchone()

        if existing is not None:
            return {"error": "A team with this name already exists."}, 409

        row = self.session.execute(
            text(
                """
                 UPDATE teams
                 SET name = :name
                 WHERE id = :team_id RETURNING id, name
                 """
            ),
            {"name": name, "team_id": team_id},
        ).fetchone()

        if row is None:
            return {"error": "Team not found"}, 404

        self.session.commit()
        return dict(row._mapping), 200

    def list_team_members(self, team_id: int) -> list[dict]:
        sql = text(
            """
                   SELECT u.id, u.username, u.prename, u.name, u.email, u.role, tm.is_owner
                   FROM team_members tm
                            JOIN users u ON tm.user_id = u.id
                   WHERE tm.team_id = :team_id
                   ORDER BY tm.is_owner DESC, u.username
                   """
        )
        rows = self.session.execute(sql, {"team_id": team_id}).fetchall()
        return [dict(row._mapping) for row in rows]

    def add_team_member(self, team_id: int, user_id: int, is_owner: bool = False) -> tuple[dict, int]:
        row = self.session.execute(
            text(
                """
                 SELECT u.username, t.name as team_name, tm.user_id IS NOT NULL as already_exists
                 FROM users u
                          CROSS JOIN teams t
                          LEFT JOIN team_members tm ON tm.user_id = u.id AND tm.team_id = t.id
                 WHERE u.id = :uid
                   AND t.id = :tid
                 """
            ),
            {"uid": user_id, "tid": team_id},
        ).fetchone()

        if not row:
            return {"error": "User or Team not found"}, 404

        self.session.execute(
            text(
                """
                 INSERT INTO team_members (team_id, user_id, is_owner)
                 VALUES (:team_id, :user_id, :is_owner) ON CONFLICT (team_id, user_id) DO
                 UPDATE
                     SET is_owner = EXCLUDED.is_owner
                 """
            ),
            {"team_id": team_id, "user_id": user_id, "is_owner": is_owner},
        )

        if not row.already_exists:
            if row.username != "root" and row.team_name:
                self.create_api_key(
                    name=f"{row.username}-{row.team_name}-key",
                    key_type="developer",
                    team_id=team_id,
                    user_id=user_id,
                    environment="-",
                    log="BILLING",
                    settings={},
                    default_priority=1,
                )
            message = "Member added successfully"
        else:
            message = "Member updated successfully"

        self.session.commit()
        return {"result": message}, 200

    def remove_team_member(self, team_id: int, user_id: int) -> tuple[dict, int]:
        result = self.session.execute(
            text(
                """
                 WITH deleted_member AS (
                 DELETE
                 FROM team_members
                 WHERE team_id = :tid
                   AND user_id = :uid RETURNING user_id
                 )
                 DELETE
                 FROM api_keys
                 WHERE team_id = :tid
                   AND user_id = :uid
                   AND EXISTS (SELECT 1 FROM deleted_member)
                 RETURNING (SELECT user_id FROM deleted_member) as original_user_id
                 """
            ),
            {"tid": team_id, "uid": user_id},
        ).fetchone()

        if not result:
            row = self.session.execute(
                text("DELETE FROM team_members WHERE team_id = :tid AND user_id = :uid RETURNING user_id"),
                {"tid": team_id, "uid": user_id},
            ).fetchone()

            if not row:
                return {"error": "Member not found in team"}, 404

            self.session.execute(
                text("DELETE FROM api_keys WHERE team_id = :tid AND user_id = :uid"),
                {"tid": team_id, "uid": user_id},
            )

        self.session.commit()
        return {"result": "Member and associated API keys removed"}, 200

    def list_admin_users(self) -> list[dict]:
        sql = text(
            """
                   SELECT id, username
                   FROM users
                   WHERE role IN ('app_admin', 'logos_admin')
                   ORDER BY username
                   """
        )
        rows = self.session.execute(sql).fetchall()
        return [dict(row._mapping) for row in rows]

    def set_team_owner(self, team_id: int, user_id: int, is_owner: bool) -> tuple[dict, int]:
        row = self.session.execute(
            text(
                """
                 UPDATE team_members
                 SET is_owner = :is_owner
                 WHERE team_id = :team_id
                   AND user_id = :user_id RETURNING user_id
                 """
            ),
            {"team_id": team_id, "user_id": user_id, "is_owner": is_owner},
        ).fetchone()
        if row is None:
            return {"error": "Member not found in team"}, 404
        self.session.commit()
        return {"result": "Owner status updated"}, 200

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

    def get_team_model_permissions(self, team_id: int) -> list[int]:
        rows = self.session.execute(
            text("SELECT model_id FROM team_model_permissions WHERE team_id = :tid"),
            {"tid": team_id},
        ).fetchall()
        return [r.model_id for r in rows]

    def add_team_model_permission(self, team_id: int, model_id: int) -> None:
        self.session.execute(
            text(
                """
                 INSERT INTO team_model_permissions (team_id, model_id)
                 VALUES (:tid, :mid) ON CONFLICT DO NOTHING
                 """
            ),
            {"tid": team_id, "mid": model_id},
        )
        self.session.commit()

    def clear_team_model_permissions(self, team_id: int) -> None:
        self.session.execute(
            text("DELETE FROM team_model_permissions WHERE team_id = :tid"),
            {"tid": team_id},
        )
        self.session.commit()

    def get_api_key_model_permissions(self, api_key_id: int) -> list[int]:
        rows = self.session.execute(
            text("SELECT model_id FROM api_key_model_permissions WHERE api_key_id = :aki"),
            {"aki": api_key_id},
        ).fetchall()
        return [r.model_id for r in rows]

    def add_api_key_model_permission(self, api_key_id: int, model_id: int) -> None:
        self.session.execute(
            text(
                """
                 INSERT INTO api_key_model_permissions (api_key_id, model_id)
                 VALUES (:aki, :mid) ON CONFLICT DO NOTHING
                 """
            ),
            {"aki": api_key_id, "mid": model_id},
        )
        self.session.commit()

    def clear_api_key_model_permissions(self, api_key_id: int) -> None:
        self.session.execute(
            text("DELETE FROM api_key_model_permissions WHERE api_key_id = :aki"),
            {"aki": api_key_id},
        )
        self.session.commit()

    def get_team_budget_usage(self, team_id: int, month_start: str) -> int:
        row = self.session.execute(
            text(
                """
                 SELECT COALESCE(SUM(bu.cost_micro_cents), 0) AS total
                 FROM budget_usage bu
                          JOIN api_keys ak ON ak.id = bu.api_key_id
                 WHERE ak.team_id = :tid
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
                  environment, log, settings, default_priority, is_active)
                 VALUES (:kv,
                         :name,
                         CAST(:kt AS api_key_type_enum),
                         :tid,
                         :uid,
                         :env,
                         CAST(:log AS logging_enum),
                         CAST(:settings AS jsonb),
                         :dprio,
                         true) RETURNING id, key_value
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
            },
        ).fetchone()
        self.session.commit()
        return {"id": row.id, "key_value": row.key_value}

    def get_api_keys_for_team(self, team_id: int) -> list:
        month_start = datetime.date.today().replace(day=1).isoformat()
        rows = self.session.execute(
            text(
                """
                 SELECT id,
                        key_value,
                        name,
                        key_type,
                        user_id,
                        environment,
                        log,
                        settings,
                        default_priority,
                        is_active,
                        COALESCE((
                            SELECT cost_micro_cents FROM budget_usage
                            WHERE api_key_id = api_keys.id AND month = :month_start
                        ), 0) as used_micro_cents
                 FROM api_keys
                 WHERE team_id = :tid
                   AND is_active = true
                 ORDER BY id
                 """
            ),
            {"tid": team_id, "month_start": month_start},
        ).fetchall()
        return [dict(r._mapping) for r in rows]

    def get_api_key_by_id(self, api_key_id: int) -> Optional[Dict[str, Any]]:
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
                        ak.default_priority,
                        ak.is_active,
                        ak.settings,
                        u.role
                 FROM api_keys ak
                          LEFT JOIN users u ON u.id = ak.user_id
                 WHERE ak.id = :aki
                 """
            ),
            {"aki": api_key_id},
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

    def deactivate_api_key(self, api_key_id: int) -> None:
        self.session.execute(
            text("UPDATE api_keys SET is_active = false WHERE id = :aki"),
            {"aki": api_key_id},
        )
        self.session.commit()

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

    def update_api_key(
        self,
        api_key_id: int,
        environment: Optional[str] = None,
        default_priority: Optional[int] = None,
        log: Optional[str] = None,
        budget_limit_micro_cents: Optional[int] = None,
        cloud_rpm_limit: Optional[int] = None,
        cloud_tpm_limit: Optional[int] = None,
        local_rpm_limit: Optional[int] = None,
        local_tpm_limit: Optional[int] = None,
    ):

        row = self.session.execute(text("SELECT settings FROM api_keys WHERE id = :id"), {"id": api_key_id}).fetchone()

        if not row:
            return {"error": "API Key not found"}, 404

        current_settings = row[0]
        if not current_settings:
            current_settings = {}
        elif isinstance(current_settings, str):
            current_settings = json.loads(current_settings)
        elif not isinstance(current_settings, dict):
            current_settings = dict(current_settings)

        limits_to_check = {
            "budget_limit_micro_cents": budget_limit_micro_cents,
            "cloud_rpm_limit": cloud_rpm_limit,
            "cloud_tpm_limit": cloud_tpm_limit,
            "local_rpm_limit": local_rpm_limit,
            "local_tpm_limit": local_tpm_limit,
        }

        settings_changed = False
        for key, value in limits_to_check.items():
            if value is not None:
                settings_changed = True
                if value == -1:
                    current_settings.pop(key, None)
                else:
                    current_settings[key] = value

        updates = []
        params = {"api_key_id": api_key_id}

        if environment is not None:
            updates.append("environment = :environment")
            params["environment"] = environment
        if default_priority is not None:
            updates.append("default_priority = :default_priority")
            params["default_priority"] = default_priority
        if log is not None:
            updates.append("log = CAST(:log AS logging_enum)")
            params["log"] = log

        if settings_changed:
            updates.append("settings = CAST(:settings_json AS jsonb)")
            params["settings_json"] = json.dumps(current_settings)

        if not updates:
            return {"result": "No changes"}, 200

        sql_str = f"UPDATE api_keys SET {', '.join(updates)} WHERE id = :api_key_id"

        self.session.execute(text(sql_str), params)
        self.session.commit()

        return {"result": "API Key updated successfully"}, 200

    def update_team_limits(
        self,
        team_id: int,
        default_cloud_rpm_limit: Optional[int],
        default_cloud_tpm_limit: Optional[int],
        default_local_rpm_limit: Optional[int],
        default_local_tpm_limit: Optional[int],
        default_monthly_budget_micro_cents: Optional[int],
        team_monthly_budget_micro_cents: Optional[int],
    ):
        sql = text(
            """
                   UPDATE teams
                   SET default_cloud_rpm_limit            = COALESCE(:c_rpm, default_cloud_rpm_limit),
                       default_cloud_tpm_limit            = COALESCE(:c_tpm, default_cloud_tpm_limit),
                       default_local_rpm_limit            = COALESCE(:l_rpm, default_local_rpm_limit),
                       default_local_tpm_limit            = COALESCE(:l_tpm, default_local_tpm_limit),
                       default_monthly_budget_micro_cents = COALESCE(:mbudget, default_monthly_budget_micro_cents),
                       team_monthly_budget_micro_cents    = COALESCE(:tbudget, team_monthly_budget_micro_cents)
                   WHERE id = :team_id
                   """
        )
        self.session.execute(
            sql,
            {
                "team_id": team_id,
                "c_rpm": default_cloud_rpm_limit,
                "c_tpm": default_cloud_tpm_limit,
                "l_rpm": default_local_rpm_limit,
                "l_tpm": default_local_tpm_limit,
                "mbudget": default_monthly_budget_micro_cents,
                "tbudget": team_monthly_budget_micro_cents,
            },
        )
        self.session.commit()
        return {"result": "Team limits updated"}, 200

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


if __name__ == "__main__":
    """
    Logos Installation Steps:
    1. Set up database. On first startup, the server automatically creates a "root" user
        with an initial API key. The key is printed to stdout (check container logs).
        This key is used to configure the database in the following steps.
    2. Add Provider. Add a new provider, the corresponding base url, the API key and authentication syntax.
        "auth_name" is the name used in the header for authorization (e.g. "api-key" for azure),
        "auth_format" is used in the header to format the authentication (e.g. "Bearer {}" for OpenAI)
    3. Add models. This action is optional if you just want to use Logos as a proxy. Logos will then just take
        the header info of your requests and forward it to your specified provider. Otherwise, define
        now what models you want to have access to over Logos. Therefore define the model endpoint
        (without the base url) and the name of the model.
    4. Add teams and API keys. Teams are an intermediate step between users and services communicating with Logos and
        its underlying database structure. Users and applications can therefore act more dynamically with providers and models.  # noqa: E501
        A team has a name and can have many API keys. Each team or API key can then be configured to have access
        to certain models, as explained later. If you don't know the ID of an API key, you can find it
        out via the get_api_key_id-Endpoint by supplying a corresponding key.
    5. Connect API keys with Providers. Now you define which API keys can interact with which providers. Therefore
        call the connect_api_key_provider-Endpoint with the api key ID and provider ID. This validates the connection
        but provider access is ultimately controlled by model permissions.
    If you just want to use Logos as a proxy, you're done here with the basics. Else proceed with the following steps:
    6. Connect API keys with Models. Now you define which API keys can interact with which Models. Therefore
        call the connect_api_key_model-Endpoint analogous as in step 5.
    7. Connect Models with Providers. Now you define which Models are connected to which Providers. Therefore
        call the connect_model_provider-Endpoint analogous as in step 6.
    8. Connect api-key and model. If a model requires its own api-key under a certain provider, you can now
        connect a stored api-key to that model. Otherwise this is not necessary. Therefore call the
        connect_model_api-Endpoint with model_id, provider_id and api_key.
    Congratulations! You have successfully set up Logos and can now call Logos to obtain results from your
    stored models. Keep in mind that you now provide the logos-key in the request header, not the data.
    """
