from dataclasses import dataclass
from typing import Callable, Any
from llm_core.catalog import ModelCatalog
from module_modeling_llm.config import Configuration


@dataclass
class AppContext:
    azure_catalog: ModelCatalog
    openai_catalog: ModelCatalog
    ollama_catalog: ModelCatalog
    default_config: Configuration
    llm_factory: Callable[[str], Any]
