from typing import Union, Annotated
from pydantic import Field

from .model_config import ModelConfig
from .providers.openai_model_config import OpenAIModelConfig  # noqa: F401
from .providers.azure_model_config import AzureModelConfig  # noqa: F401
from .providers.ollama_model_config import OllamaModelConfig  # noqa: F401

# --------------------------------------------------------------------------- #
# Type alias                                                                   #
# --------------------------------------------------------------------------- #
ModelConfigType = Union[OpenAIModelConfig, AzureModelConfig, OllamaModelConfig]

__all__ = [
    "ModelConfig",
    "ModelConfigType",
    "OpenAIModelConfig",
    "AzureModelConfig",
    "OllamaModelConfig",
]
