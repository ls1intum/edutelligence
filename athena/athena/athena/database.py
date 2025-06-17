import os
from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

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
