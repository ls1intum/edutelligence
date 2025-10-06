from llm_core.models.providers.base_chat_model_config import BaseChatModelConfig
from llm_core.catalog import ModelCatalog
from llm_core.loaders.catalogs import get_openai_catalog
from typing import ClassVar, Literal, Optional
from pydantic import Field, PrivateAttr
from typing import ClassVar, Literal
from pydantic import ConfigDict, Field
from langchain.base_language import BaseLanguageModel


class OpenAIModelConfig(BaseChatModelConfig):
    """Configuration for OpenAI"""

    PROVIDER: ClassVar[str] = "openai"
    KW_REMAP: ClassVar[dict[str, str]] = {
        "max_tokens": "max_completion_tokens",
    }

    provider: Literal["openai"] = "openai"
    model_name: str = Field(
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
        catalog = openai_catalog or self._catalog or get_openai_catalog()

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
                f"OpenAI model '{key}' not found in catalog. Known keys: {known}."
            )
        return self._template_get_model(tmpl)
    model_config = ConfigDict(title="OpenAI")
