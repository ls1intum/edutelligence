import os
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from alembic.config import Config as AlembicConfig
from alembic import command

from athena import env

# SQLite specific configuration
is_sqlite = env.DATABASE_URL.startswith("sqlite:///")
if is_sqlite:
    connect_args = {"check_same_thread": False}
    # create the data directory if it does not exist
    data_dir = os.path.dirname(env.DATABASE_URL[10:])
    os.makedirs(data_dir, exist_ok=True)
else:
    connect_args = {}

engine = create_engine(env.DATABASE_URL, connect_args=connect_args)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


@contextmanager
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


_ALEMBIC_CFG = AlembicConfig(str(Path(__file__).parent.parent / "alembic.ini"))


def run_migrations() -> None:
    """Upgrade the SQL schema to the latest revision."""
    command.upgrade(_ALEMBIC_CFG, "head")
