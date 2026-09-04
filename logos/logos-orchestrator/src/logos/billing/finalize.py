"""Assemble the billing inputs for one response in one place.

Every path that records a response (proxy sync, proxy stream, pipeline) funnels
through :func:`finalize_billing_inputs` so the stored ``usage_tokens`` rows, the
persisted ``log_entry.service_tier`` and the live ``usage.cost`` all agree.
"""

from __future__ import annotations

from typing import Any

from logos.billing.quantities import derive_billable_quantities
from logos.responses import extract_service_tier, extract_token_usage


def finalize_billing_inputs(
    request_payload: Any,
    response_payload: Any,
    path: str,
) -> "tuple[dict, str | None]":
    """Return ``(usage_dict, service_tier)``.

    ``usage_dict`` is the canonical token usage (:func:`extract_token_usage`)
    merged with the derived non-token quantities
    (:func:`derive_billable_quantities`); token counts win on any key clash.
    """
    usage_obj = response_payload.get("usage") if isinstance(response_payload, dict) else None
    if not isinstance(usage_obj, dict) and isinstance(response_payload, dict):
        # Native Gemini calls use usageMetadata rather than the OpenAI-shaped
        # usage object exposed by Gemini's compatibility endpoint.
        usage_obj = response_payload.get("usageMetadata")
    usage: dict = extract_token_usage(usage_obj) if isinstance(usage_obj, dict) else {}
    # Verbose audio transcription responses commonly put duration at the response
    # root and omit usage entirely. Feed the same milliseconds to live pricing and
    # persistence so response usage.cost cannot diverge from stored budget cost.
    is_output_media = "audio/speech" in (path or "") or "/videos" in (path or "") or (path or "").startswith("videos")
    if not usage and isinstance(response_payload, dict) and not is_output_media:
        duration = response_payload.get("duration")
        if isinstance(duration, (int, float)) and not isinstance(duration, bool):
            usage = extract_token_usage({"seconds": duration})
        elif isinstance(duration, str):
            try:
                usage = extract_token_usage({"seconds": float(duration)})
            except ValueError:
                pass
    for key, value in derive_billable_quantities(request_payload, response_payload, path).items():
        usage.setdefault(key, value)
    return usage, extract_service_tier(response_payload)
