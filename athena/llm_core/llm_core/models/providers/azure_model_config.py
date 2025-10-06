from llm_core.models.providers.base_chat_model_config import BaseChatModelConfig
from llm_core.catalog import ModelCatalog
from llm_core.loaders.catalogs import get_azure_catalog
from typing import ClassVar, Literal, Optional
from pydantic import Field, PrivateAttr, validator
from typing import ClassVar, Literal
from pydantic import ConfigDict, Field
from langchain.base_language import BaseLanguageModel


class AzureModelConfig(BaseChatModelConfig):
    """Configuration for an Azure OpenAI chat completion deployment"""

    PROVIDER: ClassVar[str] = "azure"
    KW_REMAP: ClassVar[dict[str, str]] = {}

    provider: Literal["azure"] = "azure"
    model_name: str = Field(
        ...,
        description="Azure model name",
    )
    _catalog: Optional[ModelCatalog] = PrivateAttr(None)

    def __init__(self, catalog: ModelCatalog = None, **data):
        """Initialize with optional catalog reference."""
        super().__init__(**data)
        self._catalog = catalog

    @validator("model_name")
    def _prefix_ok(cls, v: str) -> str:
        if not v.startswith("azure_openai_"):
            raise ValueError("Azure model_name must start with 'azure_openai_'.")
        return v

    def get_model(self, azure_catalog: ModelCatalog = None) -> BaseLanguageModel:
        """Get the model using either the provided catalog or the instance catalog."""
        catalog = azure_catalog or self._catalog or get_azure_catalog()
        key = self.model_name
        try:
            tmpl = catalog.templates[key]
        except KeyError:
            known = ", ".join(sorted(catalog.templates)) or "(none discovered)"
            raise RuntimeError(
                f"Azure deployment '{key}' not discovered. Known keys: {known}."
            )
        return self._template_get_model(tmpl)
    model_config = ConfigDict(title="Azure")
