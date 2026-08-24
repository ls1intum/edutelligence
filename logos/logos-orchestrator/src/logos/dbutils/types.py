from typing import List, Optional, TypedDict
from urllib.parse import urlparse


class Deployment(TypedDict):
    """Minimal info describing an available model deployment."""

    model_id: int
    provider_id: int
    type: str  # 'cloud' | 'logosnode'
    privacy_level: str


def normalize_provider_type(provider_type: Optional[str]) -> str:
    """Return the provider_type enum value ('logosnode' | 'cloud')."""
    normalized = (provider_type or "").strip().lower()
    if normalized in {
        "node",
        "node_controller",
        "ollama",
        "logos_worker_node",
        "logos-workernode",
        "logosnode",
    }:
        return "logosnode"
    if normalized in {"azure", "cloud"}:
        return "cloud"
    return normalized


def infer_cloud_provider_type(
    provider_type: Optional[str],
    *,
    base_url: Optional[str] = None,
) -> Optional[str]:
    normalized = (provider_type or "").strip().lower()
    if normalized == "azure":
        return "azure"

    base_url_norm = (base_url or "").strip().lower()
    parsed_url = urlparse(base_url_norm if "://" in base_url_norm else f"//{base_url_norm}")
    hostname = parsed_url.hostname or ""
    if hostname == "openai.azure.com" or hostname.endswith(".openai.azure.com"):
        return "azure"
    return None


def get_unique_models_from_deployments(deployments: List[Deployment]) -> List[int]:
    """
    Return unique model IDs from the deployment list while preserving order.
    """
    seen: set[int] = set()
    unique_models: List[int] = []
    for deployment in deployments:
        mid = deployment["model_id"]
        if mid not in seen:
            seen.add(mid)
            unique_models.append(mid)
    return unique_models
