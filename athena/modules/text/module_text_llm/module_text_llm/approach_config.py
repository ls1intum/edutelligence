from pathlib import Path
from llm_core.loaders.llm_config_loader import get_llm_config
from pydantic import ConfigDict, BaseModel, Field

from llm_core.models import ModelConfigType

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "llm_config.yml"
llm_config = get_llm_config(str(_CONFIG_PATH))


class ApproachConfig(BaseModel):
    max_input_tokens: int = Field(
        default=3000, description="Maximum number of tokens in the input prompt."
    )
    model: ModelConfigType = Field(
        title="Model",
        description="The model to use for the approach.",
        default=llm_config.models.base_model_config,
    )
    type: str = Field(..., description="The type of approach config")
    model_config = ConfigDict(use_enum_values=True)
