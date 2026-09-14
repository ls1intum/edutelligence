"""Prepare the usage values needed for billing."""

from typing import Any

from logos.billing.quantities import derive_billable_quantities
from logos.responses import extract_service_tier, extract_token_usage


def _get_provider_usage(response: Any) -> dict[str, Any]:
    """Return the standard or Gemini usage object."""
    if not isinstance(response, dict):
        return {}
    for field_name in ("usage", "usageMetadata"):
        usage = response.get(field_name)
        if isinstance(usage, dict):
            return usage
    return {}


def _get_transcription_duration_usage(response: Any, path: str) -> dict[str, Any]:
    """Convert a transcription duration into provider-style usage."""
    if not isinstance(response, dict):
        return {}
    normalized_path = path or ""
    if "audio/speech" in normalized_path or "/videos" in normalized_path or normalized_path.startswith("videos"):
        return {}
    duration = response.get("duration")
    if isinstance(duration, bool):
        return {}
    try:
        return {"seconds": float(duration)} if isinstance(duration, (int, float, str)) else {}
    except ValueError:
        return {}


def finalize_billing_inputs(
    request_payload: Any,
    response_payload: Any,
    path: str,
) -> tuple[dict[str, Any], str | None]:
    """Return normalized usage and the response's service tier."""
    provider_usage = _get_provider_usage(response_payload)
    if not provider_usage:
        provider_usage = _get_transcription_duration_usage(response_payload, path)
    normalized_usage = extract_token_usage(provider_usage) if provider_usage else {}

    derived_quantities = derive_billable_quantities(request_payload, response_payload, path)
    for quantity_name, quantity_value in derived_quantities.items():
        normalized_usage.setdefault(quantity_name, quantity_value)

    return normalized_usage, extract_service_tier(response_payload)
