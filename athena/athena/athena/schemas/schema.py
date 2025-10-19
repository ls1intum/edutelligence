import abc
import importlib

from pydantic import ConfigDict, BaseModel
from pydantic.alias_generators import to_camel

from athena.base import Base
from athena.database import Base


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
        model_class = type(self).get_model_class()
        if not issubclass(model_class, Base):
            raise TypeError(f"Expected {model_class} to be a subclass of Base. Did you use the correct subclass (e.g. "
                            f"TextExercise instead of Exercise)? My class name: {self.__class__.__name__}")
        model_class = type(self).get_model_class()
        return model_class(**self.model_dump(mode="json", by_alias=False))
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
