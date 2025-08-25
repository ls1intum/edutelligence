from __future__ import annotations
from enum import Enum
from types import MappingProxyType
from typing import Dict
from openai import OpenAI
from langchain.base_language import BaseLanguageModel
from langchain_openai import ChatOpenAI

from athena.logger import logger
from athena.settings import LLMSettings
from llm_core.catalog import ModelCatalog

OPENAI_PREFIX = "openai_"


def bootstrap(settings: LLMSettings) -> ModelCatalog:
    """
    Discover OpenAI chat models from the API and expose them for selection.
    If nothing is discovered (or credentials are missing), the catalog and enum are empty.
    """
    templates: Dict[str, BaseLanguageModel] = {}

    if settings.OPENAI_API_KEY:
        try:
            client = OpenAI(
                api_key=settings.OPENAI_API_KEY,
                base_url=(settings.OPENAI_BASE_URL or None),
            )
            # Filter to common chat/reasoning models; adjust if you want broader set
            discovered = [
                m.id
                for m in client.models.list().data
                if any(tok in m.id for tok in ("gpt", "o1", "o3"))
            ]
            for mid in discovered:
                key = f"{OPENAI_PREFIX}{mid}"
                templates[key] = ChatOpenAI(
                    model=mid,
                    api_key=settings.OPENAI_API_KEY,
                    base_url=(settings.OPENAI_BASE_URL or None),
                )
        except Exception as exc:
            logger.warning("OpenAI discovery failed: %s", exc, exc_info=False)

    if templates:
        logger.info("Available OpenAI models: %s", ", ".join(sorted(templates)))
        OpenAIModel = Enum("OpenAIModel", {name: name for name in templates})
    else:
        # No fallbacks — empty enum so the UI dropdown shows nothing
        logger.warning("No OpenAI models discovered.")
        OpenAIModel = Enum("OpenAIModel", {})

    return ModelCatalog(templates=MappingProxyType(templates), enum=OpenAIModel)
