from typing import Optional

from llm_core.models.model_config import ModelConfig
from llm_core.models.providers.lmstudio_model_config import LMStudioModelConfig
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
    if n.startswith("lmstudio_"):
        return "lmstudio"
    return None


def create_config_for_model(model_name: str) -> ModelConfig:
    provider = _detect_provider(model_name)

    if provider == "openai":
        return OpenAIModelConfig(model_name=model_name)
    if provider == "azure_openai":
        return AzureModelConfig(model_name=model_name)
    if provider == "ollama":
        return OllamaModelConfig(model_name=model_name)
    if provider == "lmstudio":
        return LMStudioModelConfig(model_name=model_name)

    raise ValueError(f"Unknown or unsupported provider for model '{model_name}'.")
