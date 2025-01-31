from llm_core.loaders.llm_config_loader import get_llm_config
from pydantic import BaseModel, Field
from llm_core.models import ModelConfigType
from abc import ABC, abstractmethod
from athena.text import Exercise, Submission

llm_config = get_llm_config()
    
class ApproachConfig(BaseModel, ABC):
    max_input_tokens: int = Field(default=3000, description="Maximum number of tokens in the input prompt.")
    model: ModelConfigType = Field(default=llm_config.models.base_model_config)
    type: str = Field(..., description="The type of approach config")

    @abstractmethod
    async def generate_suggestions(self, exercise: Exercise, submission: Submission, config, *, debug: bool, is_graded: bool):
        pass
    
    class Config:
        use_enum_values = True
        