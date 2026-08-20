# src/logos/pipeline/effort_normalization.py
"""
Reasoning-effort normalization for upstreams with a restricted scale.

Clients such as Claude Code attach the session's reasoning effort to every
request (``output_config.effort`` on the Anthropic Messages surface,
``reasoning_effort`` on the OpenAI surface). vLLM forwards the value to the
model's chat template, and some templates validate it. The Qwen3.8
template, for example, only accepts ``xhigh`` (its default), ``medium`` and
``low``; the Anthropic value ``high`` — and vLLM's ``minimal``/``max`` —
therefore raise a template exception that vLLM surfaces as an HTTP 500
``internal_error``, failing every turn of a client session left on
``high`` (ls1intum/edutelligence#749).

This module keeps a registry mapping chat template families to the effort
scale their ``chat_template.jinja`` enforces, and rewrites out-of-scale
values onto the closest accepted level in every payload location vLLM
forwards to the chat template:

- ``output_config.effort`` (Anthropic Messages API)
- ``reasoning_effort`` (OpenAI API, top level)
- ``chat_template_kwargs.reasoning_effort`` (explicit template kwarg)

A new template family with a restricted scale is added by registering one
entry in ``CHAT_TEMPLATE_EFFORT_SCALES``.
"""

from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, Mapping, Optional

# Snapshot of vLLM 0.27.1's ChatCompletionRequest.reasoning_effort Literal,
# kept in sync with the workernode's VLLM_PIP_SPEC (the "Logos - Update
# vLLM" workflow bumps that pin). It only drives the coverage test: runtime
# normalization is drift-proof, since unknown values fall back to the
# family's default instead of reaching the template.
VLLM_REASONING_EFFORT_VALUES = ("none", "minimal", "low", "medium", "high", "xhigh", "max")


@dataclass(frozen=True)
class EffortScale:
    """The reasoning-effort scale a chat template family enforces.

    ``accepted`` are the values the template accepts verbatim (in addition
    to ``none``, which vLLM translates into ``enable_thinking=false`` so
    the template's effort block is skipped); ``map`` rewrites known
    out-of-scale values onto the closest accepted level, and ``default``
    is the fallback every other value — including ones a future vLLM may
    introduce — is coerced to, so the template can never reject an effort
    value.
    """

    accepted: FrozenSet[str]
    map: Mapping[str, str]
    default: str


# Maps a chat template family (matched case-insensitively as a model-name
# substring) to the scale its chat_template.jinja enforces. Add an entry
# for every template family that validates reasoning_effort.
CHAT_TEMPLATE_EFFORT_SCALES: Dict[str, EffortScale] = {
    # Qwen3.8 (https://huggingface.co/Qwen/Qwen3.8-27B): accepts only
    # xhigh (default), medium and low.
    "qwen3.8": EffortScale(
        accepted=frozenset({"xhigh", "medium", "low"}),
        map={"high": "xhigh", "max": "xhigh", "minimal": "low"},
        # The template's own default — what it would resolve to without
        # rejecting the value.
        default="xhigh",
    ),
}


def effort_scale_for_model(model_name: Optional[str]) -> Optional[EffortScale]:
    """Return the effort scale the model's chat template enforces, if any.

    When several registered patterns match (e.g. a broad ``qwen3`` and a
    specific ``qwen3.8``), the most specific one — the longest matching
    pattern — wins, so broad entries cannot shadow specific ones
    regardless of registration order.
    """
    low = (model_name or "").lower()
    best_pattern: Optional[str] = None
    for pattern in CHAT_TEMPLATE_EFFORT_SCALES:
        if pattern in low and (best_pattern is None or len(pattern) > len(best_pattern)):
            best_pattern = pattern
    return None if best_pattern is None else CHAT_TEMPLATE_EFFORT_SCALES[best_pattern]


def _map_effort(value: str, scale: EffortScale) -> str:
    """Map a client effort value onto the family's accepted scale."""
    if value == "none" or value in scale.accepted:
        return value
    return scale.map.get(value, scale.default)


def normalize_reasoning_effort(payload: Dict[str, Any], model_name: Optional[str]) -> Dict[str, Any]:
    """Map out-of-scale reasoning-effort values onto the model's accepted scale.

    Returns a copy of ``payload`` with every value the model's scale does
    not accept rewritten (known values via its ``map``, all others to its
    ``default``) in each location vLLM forwards to the chat template; the
    input is never mutated. Payloads for models without a restricted
    scale, or payloads whose effort values are already accepted, are
    returned as-is.
    """
    scale = effort_scale_for_model(model_name)
    if not isinstance(payload, dict) or scale is None:
        return payload

    result = payload
    output_config = payload.get("output_config")
    if isinstance(output_config, dict) and isinstance(output_config.get("effort"), str):
        mapped = _map_effort(output_config["effort"], scale)
        if mapped != output_config["effort"]:
            result = {**result, "output_config": {**output_config, "effort": mapped}}

    if isinstance(payload.get("reasoning_effort"), str):
        mapped = _map_effort(payload["reasoning_effort"], scale)
        if mapped != payload["reasoning_effort"]:
            result = {**result, "reasoning_effort": mapped}

    template_kwargs = payload.get("chat_template_kwargs")
    if isinstance(template_kwargs, dict) and isinstance(template_kwargs.get("reasoning_effort"), str):
        mapped = _map_effort(template_kwargs["reasoning_effort"], scale)
        if mapped != template_kwargs["reasoning_effort"]:
            result = {**result, "chat_template_kwargs": {**template_kwargs, "reasoning_effort": mapped}}

    return result
