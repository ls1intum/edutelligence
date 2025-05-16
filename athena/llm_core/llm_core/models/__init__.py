from typing import Union

from .model_config import ModelConfig
from .providers.openai_model_config import OpenAIModelConfig
from .providers.azure_model_config import AzureModelConfig
from .providers.ollama_model_config import OllamaModelConfig


ModelConfigType = Union[OpenAIModelConfig, AzureModelConfig, OllamaModelConfig]

__all__ = [
    "ModelConfig",
    "ModelConfigType",
    "BaseChatModelConfig",
    "OpenAIModelConfig",
    "AzureModelConfig",
    "OllamaModelConfig",
]
