from contextlib import contextmanager
from typing import Generator
from sqlalchemy.orm import Session
from .container import get_container, AthenaContainer
from .settings import Settings


@contextmanager
def get_db() -> Generator[Session, None, None]:
    """Context manager that provides a SQLAlchemy session."""
    yield from get_db_session()


def get_db_session() -> Generator[Session, None, None]:
    """FastAPI dependency that provides a SQLAlchemy session."""
    container = get_container()

    # Corrected: Use the db_session_factory provider and call it to get a new session
    session_factory = container.db_session_factory()
    db = session_factory()

    try:
        yield db
    finally:
        db.close()


def get_settings() -> Settings:
    """FastAPI dependency that provides the application settings."""
    container = get_container()
    return container.settings()
