from abc import ABC, abstractmethod

from langchain.base_language import BaseLanguageModel
from pydantic import BaseModel


class ModelConfig(BaseModel, ABC):

    @abstractmethod
    def get_model(self) -> BaseLanguageModel:
        pass
