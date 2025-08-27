from llm_core.loaders.model_loaders.ollama_loader import (
    OllamaModel,
    ollama_available_models,
)
from llm_core.models.providers.base_chat_model_config import BaseChatModelConfig
from typing import ClassVar, Literal
from pydantic import ConfigDict, Field
from langchain.base_language import BaseLanguageModel


class OllamaModelConfig(BaseChatModelConfig):
    """Configuration for a local Ollama"""

    PROVIDER: ClassVar[str] = "ollama"
    ENUM: ClassVar[type] = OllamaModel
    KW_REMAP: ClassVar[dict[str, str]] = {}

    provider: Literal["ollama"] = "ollama"
    model_name: OllamaModel = Field(
        ...,
        description="Ollama model tag (enum value).",
    )

    def get_model(self) -> BaseLanguageModel:
        tmpl = ollama_available_models[self.model_name.value]
        return self._template_get_model(tmpl)
    model_config = ConfigDict(title="Ollama")
