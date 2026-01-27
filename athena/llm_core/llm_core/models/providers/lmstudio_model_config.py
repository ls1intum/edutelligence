from llm_core.loaders.model_loaders.lmstudio_loader import (
    LMStudioModel,
    lmstudio_available_models,
)
from llm_core.models.providers.base_chat_model_config import BaseChatModelConfig
from typing import ClassVar, Literal
from pydantic import ConfigDict, Field, PrivateAttr
from langchain.base_language import BaseLanguageModel


class LMStudioModelConfig(BaseChatModelConfig):
    """Configuration for a local LM Studio model"""

    PROVIDER: ClassVar[str] = "lmstudio"
    ENUM: ClassVar[type] = LMStudioModel
    KW_REMAP: ClassVar[dict[str, str]] = {}

    # LM Studio's OpenAI-compatible server often does not support OpenAI's
    # structured_outputs (response_format/json_mode) or function-calling tools.
    # Setting these capability flags to False prevents higher layers from
    # sending incompatible parameters like `response_format` in requests.
    _supports_structured_output: bool = PrivateAttr(False)
    _supports_function_calling: bool = PrivateAttr(False)

    provider: Literal["lmstudio"] = "lmstudio"
    model_name: LMStudioModel = Field(
        ...,
        description="LM Studio model ID (enum value).",
    )

    def get_model(self) -> BaseLanguageModel:
        tmpl = lmstudio_available_models[self.model_name.value]
        return self._template_get_model(tmpl)

    model_config = ConfigDict(title="LM Studio")

    # Hard-disable capabilities that trigger OpenAI-only params/routes.
    def supports_structured_output(self) -> bool:
        return False

    def supports_function_calling(self) -> bool:
        return False
