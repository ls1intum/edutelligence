from typing import TypedDict, List


class Deployment(TypedDict):
    """Minimal info describing an available model deployment."""
    model_id: int
    provider_id: int
    type: str  # 'azure' | 'ollama'


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
