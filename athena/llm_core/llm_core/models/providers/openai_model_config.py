from llm_core.loaders.model_loaders.openai_loader import (
    OpenAIModel,
    openai_available_models,
)
from llm_core.models.providers.base_chat_model_config import BaseChatModelConfig
from typing import ClassVar, Literal
from pydantic import ConfigDict, Field
from langchain.base_language import BaseLanguageModel


class OpenAIModelConfig(BaseChatModelConfig):
    """Configuration for OpenAI"""

    PROVIDER: ClassVar[str] = "openai"
    ENUM: ClassVar[type] = OpenAIModel
    KW_REMAP: ClassVar[dict[str, str]] = {
        "max_tokens": "max_completion_tokens",
    }

    provider: Literal["openai"] = "openai"
    model_name: OpenAIModel = Field(
        ...,
        description="OpenAI model id (enum value).",
    )

    def get_model(self) -> BaseLanguageModel:
        tmpl = openai_available_models[self.model_name.value]
        return self._template_get_model(tmpl)
    model_config = ConfigDict(title="OpenAI")
