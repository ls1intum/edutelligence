from module_text_llm.in_context_learning import InContextLearningConfig
from module_text_llm.self_consistency import SelfConsistencyConfig
from pydantic import BaseModel, Field
from typing import Union
from athena import config_schema_provider

from module_text_llm.chain_of_thought_approach import ChainOfThoughtConfig
from module_text_llm.basic_approach import BasicApproachConfig
from module_text_llm.divide_and_conquer import DivideAndConquerConfig

ApproachConfigUnion = Union[BasicApproachConfig, ChainOfThoughtConfig, DivideAndConquerConfig, SelfConsistencyConfig, InContextLearningConfig]

@config_schema_provider
class Configuration(BaseModel):
    debug: bool = Field(default=False, description="Enable debug mode.")
    approach: ApproachConfigUnion = Field(default_factory=BasicApproachConfig)  # Default to BasicApproach

    class Config:
        smart_union = True 
