from abc import ABC
from pydantic import BaseModel, Field
from llm_core.models import ModelConfigType, DefaultModelConfig
from enum import Enum

class ApproachType(str, Enum):
    basic = "BasicApproach"
    chain_of_thought = "ChainOfThought"
    
class ApproachConfig(BaseModel, ABC):
    max_input_tokens: int = Field(default=3000, description="Maximum number of tokens in the input prompt.")
    model: ModelConfigType = Field(default=DefaultModelConfig())
    type: str = Field(..., description="The type of approach config")

    class Config:
        use_enum_values = True