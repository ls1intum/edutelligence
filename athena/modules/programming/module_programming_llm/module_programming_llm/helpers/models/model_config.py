from abc import ABC, abstractmethod
from langchain_core.pydantic_v1 import BaseModel
from langchain.base_language import BaseLanguageModel


class ModelConfig(BaseModel, ABC):

    @abstractmethod
    def get_model(self) -> BaseLanguageModel:
        pass
