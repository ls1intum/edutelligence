import importlib

from pydantic import BaseModel
from sqlalchemy import Column, String, UniqueConstraint


class Model:

    @classmethod
    def get_schema_class(cls) -> BaseModel:
        # The schema class has the same name as myself, but without the "DB" prefix.
        # We can import it from athena.schemas
        # and then use getattr to get the class from the module.
        schema_module = importlib.import_module("athena.schemas")
        schema_class_name = cls.__name__[2:]
        return getattr(schema_module, schema_class_name)

    def to_schema(self):
        return type(self).get_schema_class().model_validate(self)
