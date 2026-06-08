from typing import ClassVar, Literal

from langchain_core.language_models import BaseLanguageModel
from pydantic import ConfigDict, Field

from llm_core.loaders.model_loaders.logos_loader import (
    LogosModel,
    logos_available_models,
)
from llm_core.models.providers.base_chat_model_config import BaseChatModelConfig


class LogosModelConfig(BaseChatModelConfig):
    """Configuration for a Logos OpenAI-compatible model."""

    PROVIDER: ClassVar[str] = "logos"
    ENUM: ClassVar[type] = LogosModel
    KW_REMAP: ClassVar[dict[str, str]] = {}

    provider: Literal["logos"] = "logos"
    model_name: LogosModel = Field(
        ...,
        description="Logos model ID (enum value).",
    )

    def get_model(self) -> BaseLanguageModel:
        tmpl = logos_available_models[self.model_name.value]
        return self._template_get_model(tmpl)

    model_config = ConfigDict(title="Logos")
