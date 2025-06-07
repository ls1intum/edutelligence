import os
import requests
from enum import Enum
from typing import Dict, List
from langchain_community.chat_models import ChatOllama
from athena.logger import logger

OLLAMA_PREFIX = "ollama_"

OLLAMA_BASE_URL: str = os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434")
GPU_USER = os.getenv("GPU_USER")
GPU_PASSWORD = os.getenv("GPU_PASSWORD")

_auth = (GPU_USER, GPU_PASSWORD) if GPU_USER and GPU_PASSWORD else None
_headers = (
    {"Authorization": requests.auth._basic_auth_str(GPU_USER, GPU_PASSWORD)}  # type: ignore
    if _auth
    else None
)


def _discover_ollama_models() -> List[str]:
    try:
        resp = requests.get(f"{OLLAMA_BASE_URL}/api/tags", auth=_auth, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return [m["name"] for m in data.get("models", [])]
    except Exception as exc:
        logger.warning("Could not query Ollama server (%s): %s", OLLAMA_BASE_URL, exc)
        return []


ollama_available_models: Dict[str, ChatOllama] = {}

for _name in _discover_ollama_models():
    key = OLLAMA_PREFIX + _name
    params = {
        "model": _name,
        "base_url": OLLAMA_BASE_URL,
        "format": "json",
    }
    if _headers:
        params["headers"] = _headers
    ollama_available_models[key] = ChatOllama(**params)

if ollama_available_models:
    logger.info("Available Ollama models: %s", ", ".join(ollama_available_models))
else:
    logger.warning("No Ollama models discovered at %s.", OLLAMA_BASE_URL)


# Enum for referencing the discovered models
if ollama_available_models:
    OllamaModel = Enum(
        "OllamaModel", {name: name for name in ollama_available_models}  # type: ignore
    )
else:

    class OllamaModel(str, Enum):
        """Empty placeholder enum when no Ollama server is reachable."""

        pass
