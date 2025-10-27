from llm_core.loaders.model_loaders.azure_loader import (
    AzureModel,
    azure_available_models,
)
from llm_core.models.providers.base_chat_model_config import BaseChatModelConfig
from typing import ClassVar, Literal
from pydantic import ConfigDict, Field
from langchain.base_language import BaseLanguageModel


class AzureModelConfig(BaseChatModelConfig):
    """Configuration for an Azure OpenAI chat completion deployment"""

    PROVIDER: ClassVar[str] = "azure"
    ENUM: ClassVar[type] = AzureModel
    KW_REMAP: ClassVar[dict[str, str]] = {}

    provider: Literal["azure"] = "azure"
    model_name: AzureModel = Field(
        ...,
        description="Azure model name",
    )

    def get_model(self) -> BaseLanguageModel:
        tmpl = azure_available_models[self.model_name.value]
        return self._template_get_model(tmpl)
    model_config = ConfigDict(title="Azure")
