import abc
import importlib

from pydantic import BaseModel


class Schema(BaseModel, abc.ABC):
    @classmethod
    def get_model_class(cls) -> type:
        # The model class has the same name as myself, but with a "DB" prefix.
        # We can import it from athena.models
        # and then use getattr to get the class from the module.
        model_module = importlib.import_module("athena.models")
        model_class_name = "DB" + cls.__name__
        return getattr(model_module, model_class_name)

    def to_model(self):
        return type(self).get_model_class()(**self.dict())
