from llm_core.models.providers.base_chat_model_config import BaseChatModelConfig
from llm_core.catalog import ModelCatalog
from typing import ClassVar, Literal, Union, Optional
from pydantic import Field, PrivateAttr
from langchain.base_language import BaseLanguageModel


class OpenAIModelConfig(BaseChatModelConfig):
    """Configuration for OpenAI"""

    PROVIDER: ClassVar[str] = "openai"
    KW_REMAP: ClassVar[dict[str, str]] = {
        "max_tokens": "max_completion_tokens",
    }

    provider: Literal["openai"] = Field("openai", const=True)
    model_name: Union[str, object] = Field(
        ...,
        description="OpenAI model key (string) or enum value.",
    )
    _catalog: Optional[ModelCatalog] = PrivateAttr(None)

    def __init__(self, catalog: ModelCatalog = None, **data):
        """Initialize with optional catalog reference."""
        super().__init__(**data)
        self._catalog = catalog

    def get_model(self, openai_catalog: ModelCatalog = None) -> BaseLanguageModel:
        """Get the model using either the provided catalog or the instance catalog."""
        catalog = openai_catalog or self._catalog
        if not catalog:
            raise RuntimeError(
                "No OpenAI catalog available. Either pass openai_catalog parameter "
                "or initialize OpenAIModelConfig with a catalog."
            )

        # Handle both string keys and enum values
        key = (
            self.model_name.value
            if hasattr(self.model_name, "value")
            else str(self.model_name)
        )
        try:
            tmpl = catalog.templates[key]
        except KeyError:
            known = ", ".join(sorted(catalog.templates)) or "(none discovered)"
            raise RuntimeError(
                f"OpenAI model '{key}' not found in catalog. "
                f"Known keys: {known}. Make sure your OPENAI_API_KEY is set."
            )
        return self._template_get_model(tmpl)

    class Config:
        title = "OpenAI"
