import os
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


# The API version every Anthropic endpoint requires on every request; without
# it the call is rejected before it reaches a model. Pinned rather than
# tracked: a newer version can change response shapes, so moving it is a
# deliberate change.
ANTHROPIC_VERSION = os.getenv("LOGOS_ANTHROPIC_VERSION", "2023-06-01")

# Per-provider header conventions, for the ones that do not follow the
# "Authorization: Bearer" default. Anthropic authenticates with x-api-key.
_AUTH_DEFAULTS = {"anthropic": ("x-api-key", "{}")}


def cloud_auth_header(
    auth_name: Optional[str],
    auth_format: Optional[str],
    api_key: Optional[str],
    cloud_provider_type: Optional[str] = None,
) -> Optional[tuple[str, str]]:
    """The HTTP auth header a cloud provider's stored credentials produce.

    The provider form advertises "Authorization" and "Bearer {}" as
    placeholders, so operators routinely save an OpenAI-shaped provider with
    both fields empty; without a default the header is dropped and the upstream
    rejects the request as unauthenticated. An explicit header name (e.g.
    Azure's "api-key") keeps its own name and defaults to the bare key rather
    than a Bearer prefix.

    The default follows the provider type where that type does not use Bearer
    — Anthropic reads ``x-api-key`` and ignores an Authorization header — so a
    provider saved with the form's placeholders still authenticates.

    Returns ``None`` when there is no key to send, which is legitimate for an
    upstream that serves unauthenticated.
    """
    name = (auth_name or "").strip()
    fmt = auth_format or ""
    if not api_key:
        return None
    if not name:
        name, default_format = _AUTH_DEFAULTS.get((cloud_provider_type or "").lower(), ("Authorization", "Bearer {}"))
        fmt = fmt or default_format
    elif not fmt:
        fmt = "{}"
    return name, fmt.format(api_key)


def cloud_protocol_headers(cloud_provider_type: Optional[str]) -> dict[str, str]:
    """Headers a provider's protocol requires on every request.

    Anthropic rejects a request that carries no ``anthropic-version``, both for
    inference and for the model list, so an Anthropic upstream is unusable
    without it. Every other provider type needs nothing.
    """
    if (cloud_provider_type or "").lower() == "anthropic":
        return {"anthropic-version": ANTHROPIC_VERSION}
    return {}


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
