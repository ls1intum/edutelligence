from llm_core.loaders.model_loaders.ollama_loader import (
    OllamaModel,
    ollama_available_models,
)
from llm_core.models.providers.base_chat_model_config import BaseChatModelConfig
from typing import ClassVar, Literal
from pydantic import ConfigDict, Field, PrivateAttr
from langchain_core.language_models import BaseLanguageModel


class OllamaModelConfig(BaseChatModelConfig):
    """Configuration for a local Ollama"""

    PROVIDER: ClassVar[str] = "ollama"
    ENUM: ClassVar[type] = OllamaModel
    KW_REMAP: ClassVar[dict[str, str]] = {}

    # Ollama's tool-calling support is inconsistent across small local models,
    # so function-calling based structured output stays disabled. Native
    # JSON-schema constrained decoding (see structured_output_method) is used
    # instead, which forces schema-conformant output regardless of model size.
    _supports_structured_output: bool = PrivateAttr(True)
    _supports_function_calling: bool = PrivateAttr(False)

    provider: Literal["ollama"] = "ollama"
    model_name: OllamaModel = Field(
        ...,
        description="Ollama model tag (enum value).",
    )

    def get_model(self) -> BaseLanguageModel:
        tmpl = ollama_available_models[self.model_name.value]
        return self._template_get_model(tmpl)
    model_config = ConfigDict(title="Ollama")

    def supports_function_calling(self) -> bool:
        return False

    def structured_output_method(self) -> str:
        return "json_schema"
