from llm_core.models.providers.base_chat_model_config import BaseChatModelConfig
from llm_core.catalog import ModelCatalog
from typing import ClassVar, Literal, Optional
from pydantic import Field, PrivateAttr, validator
from langchain.base_language import BaseLanguageModel


class AzureModelConfig(BaseChatModelConfig):
    """Configuration for an Azure OpenAI chat completion deployment"""

    PROVIDER: ClassVar[str] = "azure"
    KW_REMAP: ClassVar[dict[str, str]] = {}

    provider: Literal["azure"] = Field("azure", const=True)
    # We accept plain strings to avoid import-time discovery/Enums.
    # Keys look like: "azure_openai_<deployment>"
    model_name: str = Field(
        ..., description="Key of Azure deployment prefixed with 'azure_openai_'."
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
        # Do NOT force existence here; discovery happens after DI bootstrap
        return v

    def get_model(self, azure_catalog: ModelCatalog = None) -> BaseLanguageModel:
        """Get the model using either the provided catalog or the instance catalog."""
        catalog = azure_catalog or self._catalog
        if not catalog:
            raise RuntimeError(
                "No Azure catalog available. Either pass azure_catalog parameter "
                "or initialize AzureModelConfig with a catalog."
            )

        print(f"Getting Azure model for {self.model_name}", catalog)
        try:
            # resolve provider to actual catalog instance
            tmpl = catalog.templates[self.model_name]
        except KeyError:
            known = ", ".join(sorted(catalog.templates)) or "(none discovered)"
            raise RuntimeError(
                f"Azure deployment '{self.model_name}' not discovered yet. "
                f"Known keys: {known}. Make sure azure_loader.bootstrap() ran and your credentials are set."
            )
        return self._template_get_model(tmpl)

    class Config:
        title = "Azure"
