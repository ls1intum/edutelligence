from __future__ import annotations

from typing import List, Optional, Literal

from enum import Enum
from pydantic import (
    Field,
    PositiveInt,
    PrivateAttr,
    validator,
    AnyHttpUrl,
)
from langchain.base_language import BaseLanguageModel
from llm_core.loaders.llm_capabilities_loader import get_model_capabilities
from llm_core.loaders.model_loaders.ollama_loader import (
    OllamaModel,
    ollama_available_models,
)
from ..model_config import ModelConfig
from ..usage_handler import UsageHandler


class OllamaModelConfig(ModelConfig):
    """Configuration for an Ollama chat-completion deployment."""

    model_name: OllamaModel = Field(
        description="Model key as listed by `ollama_loader` (prefix `ollama_…`)."
    )

    # Common generation parameters ------------------------------------------------
    max_tokens: PositiveInt = Field(
        1000,
        description="Upper bound for generated tokens (visible + reasoning).",
    )
    temperature: float = Field(
        0.0,
        ge=0,
        le=2,
        description="Randomness ↗ with higher values.",
    )
    top_p: Optional[float] = Field(
        None,
        ge=0,
        le=1,
        description="Nucleus sampling probability mass.",
    )
    top_k: Optional[int] = Field(
        None,
        description="Top-K sampling limit.",
    )
    presence_penalty: Optional[float] = Field(
        None,
        ge=-2,
        le=2,
        description="Discourage / encourage new tokens based on presence.",
    )
    frequency_penalty: Optional[float] = Field(
        None,
        ge=-2,
        le=2,
        description="Discourage repetition.",
    )
    stop: Optional[List[str]] = Field(
        None,
        description="Stop sequences.",
    )
    format: Optional[Literal["json"]] = Field(
        "json",
        description="Use `'json'` to force valid-JSON output (recommended for Pydantic parsing).",
    )

    # Connection settings ---------------------------------------------------------
    base_url: AnyHttpUrl = Field(
        default_factory=lambda: (
            ollama_available_models[list(ollama_available_models.keys())[0]].base_url
            if ollama_available_models
            else "http://localhost:11434"
        ),
        description="Ollama server URL.",
    )

    # -- Internal capability flags (default: False) -------------------------------
    _supports_system_messages: bool = PrivateAttr(default=False)
    _supports_function_calling: bool = PrivateAttr(default=False)
    _supports_structured_output: bool = PrivateAttr(default=False)

    # -----------------------------------------------------------------------------#
    # YAML capability merge -------------------------------------------------------#
    # -----------------------------------------------------------------------------#
    def __init__(self, **data):
        super().__init__(**data)

        raw_key = (
            self.model_name.value
            if isinstance(self.model_name, Enum)
            else str(self.model_name)
        )
        caps = get_model_capabilities(raw_key)

        user_fields = set(data.keys())

        # scalar overrides --------------------------------------------------------
        for _field in (
            "temperature",
            "top_p",
            "top_k",
            "presence_penalty",
            "frequency_penalty",
            "max_tokens",
            "format",
        ):
            if _field not in user_fields and _field in caps:
                setattr(self, _field, caps[_field])

        # capability-flag overrides ----------------------------------------------
        self._supports_system_messages = bool(
            caps.get("supports_system_messages", False)
        )
        self._supports_function_calling = bool(
            caps.get("supports_function_calling", False)
        )
        self._supports_structured_output = bool(
            caps.get("supports_structured_output", False)
        )

    # -----------------------------------------------------------------------------#
    # Capability queries ----------------------------------------------------------#
    # -----------------------------------------------------------------------------#
    def supports_system_messages(self) -> bool:
        return self._supports_system_messages

    def supports_function_calling(self) -> bool:
        return self._supports_function_calling

    def supports_structured_output(self) -> bool:
        return self._supports_structured_output

    # -----------------------------------------------------------------------------#
    # Pydantic validators ---------------------------------------------------------#
    # -----------------------------------------------------------------------------#
    @validator("max_tokens")
    def _max_tokens_positive(cls, v):
        if v <= 0:
            raise ValueError("max_tokens must be positive")
        return v

    # -----------------------------------------------------------------------------#
    # Materialise a LangChain ChatOllama instance ---------------------------------#
    # -----------------------------------------------------------------------------#
    def get_model(self) -> BaseLanguageModel:
        if self.model_name.value not in ollama_available_models:
            raise ValueError(
                f"Ollama model '{self.model_name.value}' not discovered / reachable."
            )

        template = ollama_available_models[self.model_name.value]
        kwargs = template.__dict__.copy()  # starting point

        # Secrets (ChatOllama currently exposes none, but keep parity)
        if hasattr(template, "lc_secrets"):
            secrets = {s: getattr(template, s) for s in template.lc_secrets.keys()}
            kwargs.update(secrets)

        # Separate direct kwargs vs model_kwargs
        model_kwargs = kwargs.get("model_kwargs", {})

        for attr, value in self.dict().items():
            if attr == "model_name":
                continue
            if hasattr(template, attr):
                kwargs[attr] = value
            else:
                model_kwargs[attr] = value

        kwargs["model_kwargs"] = model_kwargs
        kwargs["callbacks"] = [UsageHandler()]

        model = template.__class__(**kwargs)
        return model

    class Config:
        title = "Ollama"
