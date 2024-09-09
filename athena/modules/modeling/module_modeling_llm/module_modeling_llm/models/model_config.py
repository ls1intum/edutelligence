from pydantic import BaseModel
from abc import ABC, abstractmethod
from langchain.base_language import BaseLanguageModel


class ModelConfig(BaseModel, ABC):

    @abstractmethod
    def get_model(self) -> BaseLanguageModel:
        pass
