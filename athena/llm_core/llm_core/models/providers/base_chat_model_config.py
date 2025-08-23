from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from pydantic import (
    model_validator, field_validator, BaseModel,
    Field,
    PositiveInt,
    PrivateAttr)
from langchain.base_language import BaseLanguageModel

from llm_core.models.model_config import ModelConfig
from llm_core.loaders.llm_capabilities_loader import get_model_capabilities
from llm_core.models.usage_handler import UsageHandler


class BaseChatModelConfig(ModelConfig, BaseModel, ABC):
    """Common configuration for any chat-completion model provider"""

    # Provider‑specific parameters
    PROVIDER: ClassVar[str]
    ENUM: ClassVar[type]
    KW_REMAP: ClassVar[dict[str, str]] = {}

    # Generation parameters
    max_tokens: PositiveInt = Field(
        4000,
        description=(
            "An upper bound for the number of tokens that can be generated for a "
            "completion, including visible output tokens and reasoning tokens."
        ),
    )
    temperature: float = Field(
        0.0,
        ge=0,
        le=2,
        description="""\
What sampling temperature to use, between 0 and 2. Higher values like 0.8 will make the output more random, 
while lower values like 0.2 will make it more focused and deterministic.

We generally recommend altering this or `top_p` but not both.\
""",
    )
    top_p: float = Field(
        1.0,
        ge=0,
        le=1,
        description="""\
An alternative to sampling with temperature, called nucleus sampling, where the model considers the results 
of the tokens with top_p probability mass. So 0.1 means only the tokens comprising the top 10% probability 
mass are considered.

We generally recommend altering this or `temperature` but not both.\
""",
    )
    presence_penalty: float = Field(
        0.0,
        ge=-2,
        le=2,
        description="""\
Number between -2.0 and 2.0. Positive values penalize new tokens based on whether they appear in the text so far, 
increasing the model's likelihood to talk about new topics.

[See more information about frequency and presence penalties.](https://platform.openai.com/docs/api-reference/parameter-details)\
""",
    )
    frequency_penalty: float = Field(
        0.0,
        ge=-2,
        le=2,
        description="""\
Number between -2.0 and 2.0. Positive values penalize new tokens based on their existing frequency in the text so far, 
decreasing the model's likelihood to repeat the same line verbatim.

[See more information about frequency and presence penalties.](https://platform.openai.com/docs/api-reference/parameter-details)\
""",
    )

    # Capability flags
    _supports_system_messages: bool = PrivateAttr(True)
    _supports_function_calling: bool = PrivateAttr(True)
    _supports_structured_output: bool = PrivateAttr(True)

    _CAP_FIELDS: ClassVar[tuple[str, ...]] = (
        "max_tokens",
        "temperature",
        "top_p",
        "presence_penalty",
        "frequency_penalty",
    )
    _FLAG_FIELDS: ClassVar[tuple[str, ...]] = (
        "supports_system_messages",
        "supports_function_calling",
        "supports_structured_output",
    )

    # YAML capability merge
    @model_validator(mode="before")
    @classmethod
    def _merge_yaml_caps(cls, values):
        model_key = values.get("model_name")
        if not model_key:
            return values
        caps = get_model_capabilities(model_key)
        for fld in cls._CAP_FIELDS:
            if fld not in values and fld in caps:
                values[fld] = caps[fld]
        for flag in cls._FLAG_FIELDS:
            if flag in caps:
                values[f"_{flag}"] = bool(caps[flag])
        return values

    # Validators and helpers
    @field_validator("max_tokens")
    @classmethod
    def _max_tokens_positive(cls, v):
        if v <= 0:
            raise ValueError("max_tokens must be positive")
        return v

    def supports_system_messages(self) -> bool:
        return self._supports_system_messages

    def supports_function_calling(self) -> bool:
        return self._supports_function_calling

    def supports_structured_output(self) -> bool:
        return self._supports_structured_output

    # Common LangChain‑instantiation helper
    def _template_get_model(self, tmpl: BaseLanguageModel) -> BaseLanguageModel:
        """Return a fresh LC model instance with our params merged in"""
        kwargs = tmpl.__dict__.copy()
        secrets = {s: getattr(tmpl, s) for s in getattr(tmpl, "lc_secrets", {})}
        kwargs.update(secrets)
        model_kwargs = kwargs.setdefault("model_kwargs", {})

        for attr, value in self.dict().items():
            if attr in ("provider", "model_name"):
                continue
            mapped = self.KW_REMAP.get(attr, attr)
            target = kwargs if hasattr(tmpl, mapped) else model_kwargs
            target[mapped] = value

        kwargs["callbacks"] = [UsageHandler()]
        return tmpl.__class__(**kwargs)

    @abstractmethod
    def get_model(self) -> BaseLanguageModel:
        """Return a configured LangChain model instance"""
