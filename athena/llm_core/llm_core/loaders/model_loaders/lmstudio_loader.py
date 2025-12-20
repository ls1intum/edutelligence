import os
import requests
from enum import Enum
from typing import Dict, List
from langchain_openai import ChatOpenAI
from athena.logger import logger

LMSTUDIO_PREFIX = "lmstudio_"

# LM Studio default base URL
LMSTUDIO_BASE_URL: str = os.getenv("LMSTUDIO_ENDPOINT", "http://localhost:1234/v1")
LMSTUDIO_API_KEY = os.getenv("LMSTUDIO_API_KEY", "lm-studio")
# LM Studio accepts any non-empty API key, but some clients require one.

_headers = {"Authorization": f"Bearer {LMSTUDIO_API_KEY}"}


def _discover_lmstudio_models() -> List[str]:
    """
    Queries the LM Studio local server for available models.
    LM Studio exposes the OpenAI-compatible endpoint: GET /v1/models
    """
    try:
        resp = requests.get(f"{LMSTUDIO_BASE_URL}/models", headers=_headers, timeout=15)
        resp.raise_for_status()

        data = resp.json()
        return [m["id"] for m in data.get("data", [])]

    except Exception as exc:
        logger.warning("Could not query LM Studio server (%s): %s", LMSTUDIO_BASE_URL, exc)
        return []


lmstudio_available_models: Dict[str, ChatOpenAI] = {}

for _name in _discover_lmstudio_models():
    safe_name = _name.replace("/", "_")  # <-- replace slashes
    key = LMSTUDIO_PREFIX + safe_name
    params = {
        "model": _name,
        "base_url": LMSTUDIO_BASE_URL,
        "api_key": LMSTUDIO_API_KEY,
        "temperature": 0.0,
    }

    lmstudio_available_models[key] = ChatOpenAI(**params)

if lmstudio_available_models:
    logger.info("Available LM Studio models: %s", ", ".join(lmstudio_available_models))
    logger.info(list(lmstudio_available_models.keys()))
else:
    logger.warning("No LM Studio models discovered at %s.", LMSTUDIO_BASE_URL)


# Enum for referencing the auto-discovered models
if lmstudio_available_models:
    LMStudioModel = Enum(
        "LMStudioModel",
        {name: name for name in lmstudio_available_models},  # type: ignore
    )
else:

    class LMStudioModel(str, Enum):
        """Fallback enum used when no LM Studio server is reachable."""
        pass
