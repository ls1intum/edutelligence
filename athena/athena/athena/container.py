from dependency_injector import containers, providers
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .settings import Settings


class AthenaContainer(containers.DeclarativeContainer):
    """Base container for core Athena services."""

    # Configuration provider using our Pydantic Settings class
    settings = providers.Singleton(Settings)

    # Database providers
    db_engine = providers.Singleton(
        create_engine,
        url=settings.provided.DATABASE_URL,
        connect_args=providers.Factory(
            lambda url: (
                {"check_same_thread": False} if url.startswith("sqlite") else {}
            ),
            url=settings.provided.DATABASE_URL,
        ),
    )

    db_session_factory = providers.Singleton(
        sessionmaker,
        autocommit=False,
        autoflush=False,
        bind=db_engine,
    )
