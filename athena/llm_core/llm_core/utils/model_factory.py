from __future__ import annotations  # Enables string-based type hints without imports

from typing import Optional, Protocol

from llm_core.models.model_config import ModelConfig
from llm_core.models.providers.openai_model_config import OpenAIModelConfig
from llm_core.models.providers.azure_model_config import AzureModelConfig
from llm_core.models.providers.ollama_model_config import OllamaModelConfig


def _detect_provider(model_name: str) -> Optional[str]:
    n = model_name.lower()
    if n.startswith("openai_"):
        return "openai"
    if n.startswith("azure_openai_"):
        return "azure_openai"
    if n.startswith("ollama_"):
        return "ollama"
    return None


class ModelFactories(Protocol):
    def openai_model_config(self, **kwargs) -> ModelConfig: ...
    def azure_model_config(self, **kwargs) -> ModelConfig: ...
    def ollama_model_config(self, **kwargs) -> ModelConfig: ...


def create_config_for_model(model_name: str, factories: ModelFactories) -> ModelConfig:
    provider = _detect_provider(model_name)
    if provider == "openai":
        return factories.openai_model_config(model_name=model_name)
    if provider == "azure_openai":
        return factories.azure_model_config(model_name=model_name)
    if provider == "ollama":
        return factories.ollama_model_config(model_name=model_name)
    raise ValueError(f"Unknown or unsupported provider for model '{model_name}'.")
