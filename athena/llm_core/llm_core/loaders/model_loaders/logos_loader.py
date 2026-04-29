import os
import requests
from enum import Enum
from typing import Dict, List

from langchain_openai import ChatOpenAI

from athena.logger import logger

LOGOS_PREFIX = "logos_"

LOGOS_BASE_URL: str = os.getenv("LOGOS_ENDPOINT", "https://logos.aet.cit.tum.de/v1")
LOGOS_API_KEY = os.getenv("LOGOS_API_KEY")

_headers = {"Authorization": f"Bearer {LOGOS_API_KEY}"} if LOGOS_API_KEY else None


def _discover_logos_models() -> List[str]:
    try:
        if not _headers:
            return []

        resp = requests.get(f"{LOGOS_BASE_URL}/models", headers=_headers, timeout=15)
        resp.raise_for_status()

        data = resp.json()
        return [m["id"] for m in data.get("data", [])]

    except Exception as exc:
        logger.warning("Could not query Logos server (%s): %s", LOGOS_BASE_URL, exc)
        return []


logos_available_models: Dict[str, ChatOpenAI] = {}

for _name in _discover_logos_models():
    safe_name = _name.replace("/", "_")
    key = LOGOS_PREFIX + safe_name
    params = {
        "model": _name,
        "base_url": LOGOS_BASE_URL,
        "api_key": LOGOS_API_KEY,
        "temperature": 0.0,
    }

    logos_available_models[key] = ChatOpenAI(**params)

if logos_available_models:
    logger.info("Available Logos models: %s", ", ".join(logos_available_models))
elif LOGOS_API_KEY:
    logger.warning("No Logos models discovered at %s.", LOGOS_BASE_URL)
else:
    logger.warning("No Logos API key configured. Skipping Logos model discovery.")


if logos_available_models:
    LogosModel = Enum(
        "LogosModel",
        {name: name for name in logos_available_models},  # type: ignore
    )
else:

    class LogosModel(str, Enum):
        """Fallback enum used when no Logos endpoint is reachable."""

        pass
