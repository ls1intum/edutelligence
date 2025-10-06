from typing import List, Type, TypeAlias, Union

from .model_config import ModelConfig
from .providers.openai_model_config import OpenAIModelConfig
from .providers.azure_model_config import AzureModelConfig
from .providers.ollama_model_config import OllamaModelConfig
from .providers.base_chat_model_config import BaseChatModelConfig

# Explicitly define as a type alias for better static analysis
ModelConfigType: TypeAlias = Union[
    AzureModelConfig,
    OllamaModelConfig,
    OpenAIModelConfig,
]

available_configs: List[Type[ModelConfig]] = [
    OpenAIModelConfig,
    AzureModelConfig,
    OllamaModelConfig,
]


if not available_configs:
    available_configs.append(_StubConfig)

__all__ = [
    "available_configs",
    "ModelConfigType",
    "BaseChatModelConfig",
    "OpenAIModelConfig",
    "AzureModelConfig",
    "OllamaModelConfig",
]
