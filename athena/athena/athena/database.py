import importlib
import os
from contextlib import contextmanager
from typing import Iterator, Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from athena import env
from athena.logger import logger

Base = declarative_base()
OPTIONAL_DATABASE_ENV_VAR = "ATHENA_DATABASE_ENABLED"


class DatabaseDisabledError(RuntimeError):
    """Raised when code tries to use the database although it is disabled."""


_engine: Optional[Engine] = None
SessionLocal: Optional[sessionmaker] = None
_database_enabled = True


def optional_database_enabled_from_env() -> bool:
    """Return whether optional database support should be enabled for this module."""
    return os.environ.get(OPTIONAL_DATABASE_ENV_VAR, "0") == "1"


def configure_database(required: bool = True, enabled: Optional[bool] = None) -> None:
    """
    Configure whether Athena should use database-backed storage.

    Required modules always enable the database. Optional modules only enable it when explicitly requested or when
    `enabled` is passed directly.
    """
    global _database_enabled, _engine, SessionLocal

    if required:
        _database_enabled = True
        return

    _database_enabled = optional_database_enabled_from_env() if enabled is None else enabled
    if not _database_enabled:
        _engine = None
        SessionLocal = None


def is_database_enabled() -> bool:
    """Return whether database-backed storage is enabled for this process."""
    return _database_enabled


def _initialize_database() -> None:
    global _engine, SessionLocal

    if not _database_enabled:
        raise DatabaseDisabledError("Database support is disabled for this Athena module.")

    if _engine is not None and SessionLocal is not None:
        return

    database_url = env.DATABASE_URL

    if database_url.startswith("sqlite:///"):
        connect_args = {"check_same_thread": False}
        data_dir = os.path.dirname(database_url[10:])
        if data_dir:
            os.makedirs(data_dir, exist_ok=True)
    else:
        connect_args = {}

    _engine = create_engine(database_url, connect_args=connect_args)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


def create_tables(exercise_type: str) -> None:
    """
    Create all tables for models in athena.models, whose name starts with "DB"+exercise_type.name.title().
    Also create all tables which have been registered previously using `create_additional_table_if_not_exists`.
    """
    if not is_database_enabled():
        logger.info("Database support is disabled, skipping table creation")
        return

    _initialize_database()

    model_module = importlib.import_module("athena.models")
    model_class_name_start = "DB" + exercise_type.title()
    for model_class_name in dir(model_module):
        if model_class_name.startswith(model_class_name_start):
            # Get the model class so that Base knows about it
            getattr(model_module, model_class_name)

    assert _engine is not None
    Base.metadata.create_all(_engine)


@contextmanager
def get_db() -> Iterator[Session]:
    if not is_database_enabled():
        raise DatabaseDisabledError("Database support is disabled for this Athena module.")

    _initialize_database()
    assert SessionLocal is not None

    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
