from contextlib import contextmanager
from typing import Generator
from sqlalchemy.orm import Session
from .container import get_container, DependencyContainer
from .settings import Settings


def get_db_session() -> Generator[Session, None, None]:
    """FastAPI dependency that provides a SQLAlchemy session."""
    container = get_container()
    db = container.SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_settings() -> Settings:
    """FastAPI dependency that provides the application settings."""
    return get_container().settings
