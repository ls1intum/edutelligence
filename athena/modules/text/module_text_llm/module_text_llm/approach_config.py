from typing import Optional
from pydantic import ConfigDict, BaseModel, Field

from llm_core.models import ModelConfigType


class ApproachConfig(BaseModel):
    max_input_tokens: int = Field(
        default=3000, description="Maximum number of tokens in the input prompt."
    )
    # The model will be populated by the plugin's `build_default_config` method.
    model: Optional[ModelConfigType] = Field(
        default=None,
        title="Model",
        description="The model to use for the approach.",
    )
    type: str = Field(..., description="The type of approach config")
    model_config = ConfigDict(use_enum_values=True)
