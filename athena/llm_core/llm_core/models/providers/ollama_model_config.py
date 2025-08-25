from llm_core.models.providers.base_chat_model_config import BaseChatModelConfig
from llm_core.catalog import ModelCatalog
from llm_core.loaders.catalogs import get_ollama_catalog
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
        catalog = ollama_catalog or self._catalog or get_ollama_catalog()

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
                f"Ollama model '{key}' not found in catalog. Known keys: {known}."
            )
        return self._template_get_model(tmpl)

    class Config:
        title = "Ollama"
