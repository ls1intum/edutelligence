from llm_core.models.providers.base_chat_model_config import BaseChatModelConfig
from llm_core.catalog import ModelCatalog
from typing import ClassVar, Literal, Union, Optional
from pydantic import Field, PrivateAttr
from langchain.base_language import BaseLanguageModel


class OllamaModelConfig(BaseChatModelConfig):
    """Configuration for a local Ollama"""

    PROVIDER: ClassVar[str] = "ollama"
    KW_REMAP: ClassVar[dict[str, str]] = {}

    provider: Literal["ollama"] = Field("ollama", const=True)
    model_name: Union[str, object] = Field(
        ...,
        description="Ollama model key (string) or enum value.",
    )
    _catalog: Optional[ModelCatalog] = PrivateAttr(None)

    def __init__(self, catalog: ModelCatalog = None, **data):
        """Initialize with optional catalog reference."""
        super().__init__(**data)
        self._catalog = catalog

    def get_model(self, ollama_catalog: ModelCatalog = None) -> BaseLanguageModel:
        """Get the model using either the provided catalog or the instance catalog."""
        catalog = ollama_catalog or self._catalog
        if not catalog:
            raise RuntimeError(
                "No Ollama catalog available. Either pass ollama_catalog parameter "
                "or initialize OllamaModelConfig with a catalog."
            )

        # Handle both string keys and enum values
        key = (
            self.model_name.value
            if hasattr(self.model_name, "value")
            else str(self.model_name)
        )
        try:
            # resolve provider to actual catalog instance
            tmpl = catalog.templates[key]
        except KeyError:
            known = ", ".join(sorted(catalog.templates)) or "(none discovered)"
            raise RuntimeError(
                f"Ollama model '{key}' not found in catalog. "
                f"Known keys: {known}. Make sure Ollama is running at the configured host."
            )
        return self._template_get_model(tmpl)

    class Config:
        title = "Ollama"
