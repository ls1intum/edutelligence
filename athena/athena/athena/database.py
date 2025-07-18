import importlib
from contextlib import contextmanager
from typing import Generator
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from athena.base import Base
from .depency import get_db_session


@contextmanager
def get_db() -> Generator[Session, None, None]:
    """Context manager that provides a SQLAlchemy session."""
    yield from get_db_session()


def create_tables(engine: Engine, exercise_type: str):
    """
    Create all tables for models in athena.models, whose name starts with "DB"+exercise_type.name.title().
    Also create all tables which have been registered previously using `create_additional_table_if_not_exists`.
    """
    model_module = importlib.import_module("athena.models")
    model_class_name_start = "DB" + exercise_type.title()
    for model_class_name in dir(model_module):
        if model_class_name.startswith(model_class_name_start):
            # Get the model class so that Base knows about it
            getattr(model_module, model_class_name)
    Base.metadata.create_all(engine)
