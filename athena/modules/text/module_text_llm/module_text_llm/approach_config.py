from abc import ABC
from llm_core.loaders.llm_config_loader import get_llm_config
from pydantic import BaseModel, Field
from llm_core.models.model_config import ModelConfig
from enum import Enum

llm_config = get_llm_config()

class ApproachType(str, Enum):
    basic = "BasicApproach"
    chain_of_thought = "ChainOfThought"
    
class ApproachConfig(BaseModel, ABC):
    max_input_tokens: int = Field(default=3000, description="Maximum number of tokens in the input prompt.")
    model: ModelConfig = Field(default=llm_config.models.base_model_config)
    type: str = Field(..., description="The type of approach config")

    class Config:
        use_enum_values = True