import importlib

from pydantic import BaseModel, AnyUrl
from sqlalchemy import Column, String, UniqueConstraint, event
from sqlalchemy.orm import mapper


class Model:

    artemis_url = Column(String, index=True, nullable=False)

    __table_args__ = (
        UniqueConstraint('id', 'artemis_url'),
    )

    @classmethod
    def get_schema_class(cls) -> BaseModel:
        # The schema class has the same name as myself, but without the "DB" prefix.
        # We can import it from athena.schemas
        # and then use getattr to get the class from the module.
        schema_module = importlib.import_module("athena.schemas")
        schema_class_name = cls.__name__[2:]
        return getattr(schema_module, schema_class_name)

    def to_schema(self):
        return type(self).get_schema_class().from_orm(self)

    @event.listens_for(mapper, 'before_insert')
    @event.listens_for(mapper, 'before_update')
    def receive_before_insert(mapper, connection, target):
        for key, value in target.__dict__.items():
            if isinstance(value, AnyUrl):
                setattr(target, key, str(value))