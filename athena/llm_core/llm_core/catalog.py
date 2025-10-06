from dataclasses import dataclass
from typing import Mapping, Type
from enum import Enum
from langchain.base_language import BaseLanguageModel


@dataclass(frozen=True)
class ModelCatalog:
    """Immutable catalog of LLM templates and their ergonomic enum."""

    templates: Mapping[str, BaseLanguageModel]
    enum: Type[Enum]
