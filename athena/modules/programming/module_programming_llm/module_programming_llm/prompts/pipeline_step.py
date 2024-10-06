from typing import Generic, TypeVar, Optional
from abc import abstractmethod
from pydantic import BaseModel, Field

from module_programming_llm.helpers.models import ModelConfigType

# Generic types for input and output
TInput = TypeVar('TInput')
TOutput = TypeVar('TOutput')


class PipelineStep(BaseModel, Generic[TInput, TOutput]):
    max_input_tokens: int = Field(default=3000, description="Maximum number of tokens in the input prompt.")

    @abstractmethod
    async def process(self, input_data: TInput, debug: bool, model: ModelConfigType) -> Optional[TOutput]:
        raise NotImplementedError('This is an abstract method')
