# llm_core/loaders/model_loaders/ollama_loader.py

from __future__ import annotations

from enum import Enum
from types import MappingProxyType
from typing import Dict, List

import requests

from langchain.base_language import BaseLanguageModel

# Depending on your LangChain version, ChatOllama import moves.
# This path is widely compatible; if your repo uses a different path, keep that one.
try:
    from langchain_ollama import ChatOllama
except Exception:  # pragma: no cover
    from langchain_community.chat_models import ChatOllama  # type: ignore

from athena.logger import logger
from athena.settings import LLMSettings
from llm_core.catalog import ModelCatalog


OLLAMA_PREFIX = "ollama_"


def _list_ollama_models(host: str) -> List[str]:
    """
    GET {host}/api/tags  -> { "models": [ { "name": "llama3:latest", ... }, ... ] }
    Returns the 'name' field for each local model.
    """
    resp = requests.get(f"{host}/api/tags", timeout=10)
    resp.raise_for_status()
    payload = resp.json() or {}
    models = payload.get("models") or []
    names = []
    for m in models:
        # Prefer 'name' (e.g. "llama3:latest"). Fallback to 'model' if present.
        name = m.get("name") or m.get("model")
        if name:
            names.append(name)
    return names


def bootstrap(settings: LLMSettings) -> ModelCatalog:
    """
    Discover local Ollama models and return an immutable catalog of ChatOllama templates.
    If nothing is discovered, return an empty catalog and an empty enum (no fallbacks).
    """
    templates: Dict[str, BaseLanguageModel] = {}

    try:
        names = _list_ollama_models(settings.OLLAMA_HOST)
        for n in names:
            key = f"{OLLAMA_PREFIX}{n.replace(':', '_')}"
            templates[key] = ChatOllama(model=n, base_url=settings.OLLAMA_HOST)
    except Exception as exc:
        logger.warning("Ollama discovery failed: %s", exc, exc_info=False)

    if templates:
        logger.info("Available Ollama models: %s", ", ".join(sorted(templates)))
        OllamaModel = Enum("OllamaModel", {name: name for name in templates})
    else:
        logger.warning("No Ollama models discovered at %s.", settings.OLLAMA_HOST)
        OllamaModel = Enum("OllamaModel", {})

    return ModelCatalog(templates=MappingProxyType(templates), enum=OllamaModel)
