from typing import Union
from pydantic import BaseModel, Field

from athena import config_schema_provider

from module_text_llm.basic_approach import BasicApproachConfig
from module_text_llm.divide_and_conquer import DivideAndConquerConfig
from module_text_llm.self_consistency import SelfConsistencyConfig
from module_text_llm.competency_approach import CompetencyApproachConfig

ApproachConfigUnion = Union[BasicApproachConfig, DivideAndConquerConfig, SelfConsistencyConfig, CompetencyApproachConfig]

@config_schema_provider
class Configuration(BaseModel):
    debug: bool = Field(default=False, description="Enable debug mode.")
    approach: ApproachConfigUnion = Field(default_factory=CompetencyApproachConfig)  # Default to BasicApproach

    class Config:
        smart_union = True 
