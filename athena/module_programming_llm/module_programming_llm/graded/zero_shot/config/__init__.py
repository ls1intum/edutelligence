from abc import ABC
from pydantic import BaseModel, Field

from module_programming_llm.helpers.models import ModelConfigType, DefaultModelConfig

from .generate import GradedZeroShotPrompt


class GradedZeroShotConfig(BaseModel, ABC):
    """This approach uses an LLM to just generate graded suggestions for all changed files at once."""

    model: ModelConfigType = Field(default=DefaultModelConfig()) # type: ignore
    max_input_tokens: int = Field(default=3000, description="Maximum number of tokens in the input prompt.")

    prompt: GradedZeroShotPrompt = Field(default=GradedZeroShotPrompt())
