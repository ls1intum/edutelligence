from typing import List, Type, Union, cast
from llm_core.loaders.model_loaders import azure_loader, ollama_loader, openai_loader

from .model_config import ModelConfig
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

    class _StubConfig(ModelConfig):
        def get_model(self):
            raise RuntimeError("Stub model used")

        def supports_system_messages(self):
            return True

        def supports_function_calling(self):
            return True

        def supports_structured_output(self):
            return True

    available_configs.append(_StubConfig)

if len(available_configs) == 1:
    ModelConfigType = available_configs[0]
else:
    ModelConfigType = cast(Type[ModelConfig], Union[tuple(available_configs)])

__all__ = [
    "available_configs",
    "ModelConfigType",
    "BaseChatModelConfig",
    "OpenAIModelConfig",
    "AzureModelConfig",
    "OllamaModelConfig",
]
