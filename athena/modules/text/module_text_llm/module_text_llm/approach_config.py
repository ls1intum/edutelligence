from pydantic import BaseModel, Field
from llm_core.models import ModelConfigType, DefaultModelConfig
from abc import ABC, abstractmethod
from athena.text import Exercise, Submission
    
class ApproachConfig(BaseModel, ABC):
    max_input_tokens: int = Field(default=3000, description="Maximum number of tokens in the input prompt.")
    model: ModelConfigType = Field(default=DefaultModelConfig())
    type: str = Field(..., description="The type of approach config")

    @abstractmethod
    async def generate_suggestions(self, exercise: Exercise, submission: Submission, config, debug: bool,is_graded: bool):
        pass
    
    class Config:
        use_enum_values = True
        