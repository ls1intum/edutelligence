from pydantic import BaseModel, Field

from athena import config_schema_provider

from module_programming_llm.graded.basic_by_file.config import GradedBasicByFileConfig

from module_programming_llm.guided.basic_by_file.config import GuidedBasicByFileConfig
from module_programming_llm.guided.zero_shot.config import GuidedZeroShotConfig


@config_schema_provider
class Configuration(BaseModel):
    """Configuration settings for the entire module, including debug mode and approach-specific configurations."""

    debug: bool = Field(default=False, description="Enable debug mode.")
    
    graded_basic_by_file: GradedBasicByFileConfig = Field(default=GradedBasicByFileConfig())
    
    # GuidedBasicByFileConfig | GuidedZeroShotConfig
    guided_zero_shot:  GuidedZeroShotConfig = Field(default=GuidedZeroShotConfig())