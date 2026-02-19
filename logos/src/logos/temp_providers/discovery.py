"""
Model auto-discovery for temporary providers.

Supports:
- OpenAI-compatible servers (LMStudio, vLLM, etc.) via GET /v1/models
- Ollama servers via GET /api/tags
"""

import logging
from dataclasses import dataclass
from typing import List, Optional

import httpx

logger = logging.getLogger(__name__)

# Timeout for discovery requests (connect, read)
_DISCOVERY_TIMEOUT = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)


@dataclass
class DiscoveredModel:
    """A model discovered from a remote provider."""

    id: str
    owned_by: str = "temp-provider"


async def discover_openai_models(
    base_url: str,
    auth_key: Optional[str] = None,
) -> List[DiscoveredModel]:
    """
    Discover models via the OpenAI-compatible ``GET /v1/models`` endpoint.

    Args:
        base_url: Provider base URL (e.g. ``http://192.168.1.10:1234``).
        auth_key: Optional Bearer token for the provider.

    Returns:
        List of discovered models (may be empty on error).
    """
    url = base_url.rstrip("/") + "/v1/models"
    headers: dict[str, str] = {"Accept": "application/json"}
    if auth_key:
        headers["Authorization"] = f"Bearer {auth_key}"

    try:
        async with httpx.AsyncClient(timeout=_DISCOVERY_TIMEOUT) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        models: List[DiscoveredModel] = []
        for item in data.get("data", []):
            model_id = item.get("id")
            if model_id:
                models.append(
                    DiscoveredModel(
                        id=model_id,
                        owned_by=item.get("owned_by", "temp-provider"),
                    )
                )
        logger.info("OpenAI discovery from %s found %d model(s)", base_url, len(models))
        return models

    except Exception as exc:
        logger.warning("OpenAI discovery failed for %s: %s", base_url, exc)
        return []


async def discover_ollama_models(
    base_url: str,
    auth_key: Optional[str] = None,
) -> List[DiscoveredModel]:
    """
    Discover models via the Ollama ``GET /api/tags`` endpoint.

    Args:
        base_url: Provider base URL (e.g. ``http://192.168.1.10:11434``).
        auth_key: Optional Bearer token (uncommon for Ollama, but supported).

    Returns:
        List of discovered models (may be empty on error).
    """
    url = base_url.rstrip("/") + "/api/tags"
    headers: dict[str, str] = {"Accept": "application/json"}
    if auth_key:
        headers["Authorization"] = f"Bearer {auth_key}"

    try:
        async with httpx.AsyncClient(timeout=_DISCOVERY_TIMEOUT) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        models: List[DiscoveredModel] = []
        for item in data.get("models", []):
            model_name = item.get("name") or item.get("model")
            if model_name:
                models.append(DiscoveredModel(id=model_name, owned_by="ollama"))
        logger.info("Ollama discovery from %s found %d model(s)", base_url, len(models))
        return models

    except Exception as exc:
        logger.warning("Ollama discovery failed for %s: %s", base_url, exc)
        return []


async def discover_models(
    base_url: str,
    auth_key: Optional[str] = None,
) -> List[DiscoveredModel]:
    """
    Try OpenAI-compatible discovery first, falling back to Ollama.

    Returns:
        List of discovered models (may be empty if both fail).
    """
    models = await discover_openai_models(base_url, auth_key)
    if models:
        return models
    return await discover_ollama_models(base_url, auth_key)
