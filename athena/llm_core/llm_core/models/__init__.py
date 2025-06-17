from typing import Union, List, Type
from llm_core.loaders.model_loaders import azure_loader, ollama_loader, openai_loader

from .model_config import ModelConfig
from .providers.base_chat_model_config import BaseChatModelConfig
from .providers.openai_model_config import OpenAIModelConfig
from .providers.azure_model_config import AzureModelConfig
from .providers.ollama_model_config import OllamaModelConfig

available_configs: List[Type[ModelConfig]] = []

if openai_loader.openai_available_models:
    available_configs.append(OpenAIModelConfig)
if azure_loader.azure_available_models:
    available_configs.append(AzureModelConfig)
if ollama_loader.ollama_available_models:
    available_configs.append(OllamaModelConfig)

if not available_configs:
    raise ImportError(
        "No LLM providers have available models. Check API keys / connections."
    )

ModelConfigType = Union[*available_configs]

__all__ = [
    "ModelConfig",
    "ModelConfigType",
    "BaseChatModelConfig",
    "OpenAIModelConfig",
    "AzureModelConfig",
    "OllamaModelConfig",
]
