from functools import lru_cache
from typing import Dict, List
from athena.settings import LLMSettings
from llm_core.catalog import ModelCatalog
from llm_core.loaders.model_loaders import azure_loader, openai_loader, ollama_loader


@lru_cache(maxsize=1)
def get_azure_catalog() -> ModelCatalog:
    return azure_loader.bootstrap(LLMSettings())


@lru_cache(maxsize=1)
def get_openai_catalog() -> ModelCatalog:
    return openai_loader.bootstrap(LLMSettings())


@lru_cache(maxsize=1)
def get_ollama_catalog() -> ModelCatalog:
    return ollama_loader.bootstrap(LLMSettings())


def discovered_model_keys() -> Dict[str, List[str]]:
    """Convenience for schema injection."""
    return {
        "azure": sorted(get_azure_catalog().templates.keys()),
        "openai": sorted(get_openai_catalog().templates.keys()),
        "ollama": sorted(get_ollama_catalog().templates.keys()),
    }
