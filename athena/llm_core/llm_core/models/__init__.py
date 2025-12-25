from typing import Annotated, List, Literal, Type, Union
from pydantic import Field
from llm_core.loaders.model_loaders import azure_loader, ollama_loader, openai_loader, lmstudio_loader

from .model_config import ModelConfig
from .providers.base_chat_model_config import BaseChatModelConfig
from .providers.lmstudio_model_config import LMStudioModelConfig
from .providers.openai_model_config import OpenAIModelConfig
from .providers.azure_model_config import AzureModelConfig
from .providers.ollama_model_config import OllamaModelConfig


class _StubConfig(ModelConfig):
    provider: Literal["stub"] = "stub"

    def get_model(self):
        raise RuntimeError("Stub model used")

    def supports_system_messages(self):
        return True

    def supports_function_calling(self):
        return True

    def supports_structured_output(self):
        return True


available_configs: List[Type[ModelConfig]] = []

if openai_loader.openai_available_models:
    available_configs.append(OpenAIModelConfig)
if azure_loader.azure_available_models:
    available_configs.append(AzureModelConfig)
if ollama_loader.ollama_available_models:
    available_configs.append(OllamaModelConfig)
if lmstudio_loader.lmstudio_available_models:
    available_configs.append(LMStudioModelConfig)


if not available_configs:
    available_configs.append(_StubConfig)

ModelConfigType = Annotated[
    Union[OpenAIModelConfig, AzureModelConfig, OllamaModelConfig, LMStudioModelConfig, _StubConfig],
    Field(discriminator="provider"),
]

__all__ = [
    "available_configs",
    "ModelConfigType",
    "BaseChatModelConfig",
    "OpenAIModelConfig",
    "AzureModelConfig",
    "OllamaModelConfig",
    "LMStudioModelConfig",
]
