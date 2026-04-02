from typing import TypedDict, List, Optional


class Deployment(TypedDict):
    """Minimal info describing an available model deployment."""
    model_id: int
    provider_id: int
    type: str  # 'azure' | 'logosnode'


def normalize_provider_type(
    provider_type: Optional[str],
    *,
    provider_name: Optional[str] = None,
    base_url: Optional[str] = None,
) -> str:
    normalized = (provider_type or "").strip().lower()
    if normalized in {"node", "node_controller", "ollama", "logos_worker_node", "logos-workernode", "logosnode"}:
        return "logosnode"
    if normalized == "azure":
        return "azure"
    provider_name_norm = (provider_name or "").strip().lower()
    base_url_norm = (base_url or "").strip().lower()
    if normalized == "cloud" and (
        "azure" in provider_name_norm or "openai.azure.com" in base_url_norm
    ):
        return "azure"
    if "openai.azure.com" in base_url_norm:
        return "azure"
    return normalized


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
