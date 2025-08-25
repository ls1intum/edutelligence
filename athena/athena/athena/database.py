import importlib
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.engine import Engine

from athena.base import Base
from athena.settings import Settings


_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def init_engine(url: str):
    """Initialize the database engine with the given URL."""
    global _engine, _SessionLocal
    _engine = create_engine(url, future=True, pool_pre_ping=True)
    _SessionLocal = sessionmaker(
        bind=_engine, autoflush=False, autocommit=False, future=True
    )


def _ensure_engine():
    global _engine, _SessionLocal
    if _engine is None:
        url = Settings().DATABASE_URL  # single source of truth
        _engine = create_engine(url, future=True, pool_pre_ping=True)
        _SessionLocal = sessionmaker(
            bind=_engine, autoflush=False, autocommit=False, future=True
        )


@contextmanager
def get_db() -> Generator[Session, None, None]:
    """Context manager that provides a SQLAlchemy session."""
    _ensure_engine()
    assert _SessionLocal is not None
    db = _SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def create_tables(engine: Engine, exercise_type: str):
    """
    Create all tables for models in athena.models whose name starts with "DB"+exercise_type.title()
    """
    model_module = importlib.import_module("athena.models")
    model_class_name_start = "DB" + exercise_type.title()
    for model_class_name in dir(model_module):
        if model_class_name.startswith(model_class_name_start):
            getattr(model_module, model_class_name)
    Base.metadata.create_all(engine)
