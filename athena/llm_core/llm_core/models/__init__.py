from typing import Union

from llm_core.models.providers.azure_model_config import AzureModelConfig
from llm_core.models.providers.openai_model_config import OpenAIModelConfig


ModelConfigType = Union[OpenAIModelConfig, AzureModelConfig]