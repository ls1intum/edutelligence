# src/logos/pipeline/effort_normalization.py
"""
Reasoning-effort normalization for upstreams with a restricted scale.

Clients such as Claude Code attach the session's reasoning effort to every
request (``output_config.effort`` on the Anthropic Messages surface,
``reasoning_effort`` on the OpenAI surface). vLLM forwards the value to the
model's chat template, and the Qwen3.8 template validates it: it only accepts
``xhigh`` (its default), ``medium`` and ``low``. The Anthropic value
``high`` — and vLLM's ``minimal``/``max`` — therefore raise a template
exception that vLLM surfaces as an HTTP 500 ``internal_error``, failing every
turn of a client session left on ``high`` (ls1intum/edutelligence#749).

This module maps the wider client scale onto the scale the target model's
template accepts, in every payload location vLLM forwards to the chat
template:

- ``output_config.effort`` (Anthropic Messages API)
- ``reasoning_effort`` (OpenAI API, top level)
- ``chat_template_kwargs.reasoning_effort`` (explicit template kwarg)

Values already on the target scale (``xhigh``, ``medium``, ``low``) and
``none`` (which vLLM translates into ``enable_thinking=false``) pass through
unchanged.
"""

from typing import Any, Dict, Optional

# vLLM's reasoning_effort field accepts none, minimal, low, medium, high,
# xhigh and max. The Qwen3.8 chat template only accepts xhigh (default),
# medium and low — map the out-of-scale values onto the closest accepted
# level instead of letting the template reject them.
QWEN38_EFFORT_MAP = {
    "high": "xhigh",  # top level on both scales
    "max": "xhigh",  # DeepSeek-specific top level
    "minimal": "low",  # below low; low is the weakest accepted level
}


def model_uses_qwen38_effort_scale(model_name: Optional[str]) -> bool:
    """Return whether the model's chat template enforces the Qwen3.8 effort scale."""
    return "qwen3.8" in (model_name or "").lower()


def normalize_reasoning_effort(payload: Dict[str, Any], model_name: Optional[str]) -> Dict[str, Any]:
    """Map out-of-scale reasoning-effort values onto the model's accepted scale.

    Returns a copy of ``payload`` with ``high``/``max``/``minimal`` rewritten
    in every location vLLM forwards to the chat template; the input is never
    mutated. Payloads for other models, or payloads whose effort values are
    already accepted, are returned as-is.
    """
    if not isinstance(payload, dict) or not model_uses_qwen38_effort_scale(model_name):
        return payload

    result = payload
    output_config = payload.get("output_config")
    if isinstance(output_config, dict) and isinstance(output_config.get("effort"), str):
        mapped = QWEN38_EFFORT_MAP.get(output_config["effort"])
        if mapped is not None:
            result = {**result, "output_config": {**output_config, "effort": mapped}}

    if isinstance(payload.get("reasoning_effort"), str):
        mapped = QWEN38_EFFORT_MAP.get(payload["reasoning_effort"])
        if mapped is not None:
            result = {**result, "reasoning_effort": mapped}

    template_kwargs = payload.get("chat_template_kwargs")
    if isinstance(template_kwargs, dict) and isinstance(template_kwargs.get("reasoning_effort"), str):
        mapped = QWEN38_EFFORT_MAP.get(template_kwargs["reasoning_effort"])
        if mapped is not None:
            result = {**result, "chat_template_kwargs": {**template_kwargs, "reasoning_effort": mapped}}

    return result
