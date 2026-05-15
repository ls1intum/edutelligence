from typing import Union
from pydantic import BaseModel, Field

from athena import config_schema_provider

from module_text_llm.default_approach import DefaultApproachConfig
from module_text_llm.divide_and_conquer import DivideAndConquerConfig
from module_text_llm.self_consistency import SelfConsistencyConfig
import module_text_llm.approach_config as approach_config

llm_config = approach_config.llm_config

ApproachConfigUnion = Union[DefaultApproachConfig, DivideAndConquerConfig, SelfConsistencyConfig]

@config_schema_provider
class Configuration(BaseModel):
    debug: bool = Field(default=False, description="Enable debug mode.")
    approach: ApproachConfigUnion = Field(default_factory=DefaultApproachConfig)  # Default to DefaultApproach
