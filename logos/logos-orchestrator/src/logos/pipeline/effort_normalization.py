# src/logos/pipeline/effort_normalization.py
"""
Reasoning-effort normalization for upstreams with a restricted scale.

Clients such as Claude Code attach the session's reasoning effort to every
request (``output_config.effort`` on the Anthropic Messages surface,
``reasoning_effort`` on the OpenAI surface). vLLM forwards the value to the
model's chat template, and some templates validate it: the Qwen3.8 template
accepts only ``xhigh``, ``medium`` and ``low`` and answers ``high`` with an
HTTP 500; gpt-oss (Harmony) accepts only ``low``, ``medium`` and ``high`` and
answers ``xhigh`` with an HTTP 400. Either fails every turn of a client
session left on the rejected value.

Nothing here knows any model family in advance. Every such rejection names
the values the upstream supports (Harmony: ``Supported values are: high,
medium, low``; Qwen3.8: ``Supported types are xhigh (default), medium, and
low``). ``adapt_payload_after_effort_rejection`` reads that list, records the
scale for the model and returns the payload rewritten onto it, so the
forwarding path resends the request once — the client gets the answer, not
the error. Every later request to that model is normalized before it is sent,
in every payload location vLLM forwards to the chat template:

- ``output_config.effort`` (Anthropic Messages API)
- ``reasoning_effort`` (OpenAI API, top level)
- ``chat_template_kwargs.reasoning_effort`` (explicit template kwarg)
"""

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, Mapping, Optional

logger = logging.getLogger(__name__)

# Snapshot of vLLM 0.31.0's ChatCompletionRequest.reasoning_effort Literal,
# kept in sync with the workernode's VLLM_PIP_SPEC (the "Logos - Update
# vLLM" workflow bumps that pin). It only drives a coverage test: every value
# but "none" must have its place in EFFORT_LEVELS below. Runtime
# normalization is drift-proof either way, since an unknown value falls back
# to the scale's default instead of reaching the template.
VLLM_REASONING_EFFORT_VALUES = ("none", "minimal", "low", "medium", "high", "xhigh", "max")


@dataclass(frozen=True)
class EffortScale:
    """The reasoning-effort scale an upstream enforces.

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


# The effort levels in ascending order. A learned scale maps a level the
# upstream rejects onto the next higher level it accepts, and onto the next
# lower one only when nothing higher is accepted: asking for more reasoning
# than requested is closer to the client's intent than asking for less.
EFFORT_LEVELS = ("minimal", "low", "medium", "high", "xhigh", "max")

# Scales learned from upstream rejections, keyed by the lower-cased model
# name. Process-local: after a restart the first request to each model is
# rejected once more and resent, which relearns its scale.
_LEARNED_EFFORT_SCALES: Dict[str, EffortScale] = {}

# "Supported values are: high, medium, low" (vLLM / Harmony) and
# "Supported types are xhigh (default), medium, and low" (Qwen3.8 template).
# The list runs to the end of the line or of the JSON string it sits in.
_SUPPORTED_LIST_RE = re.compile(r"supported\s+(?:values|types|levels)\s*(?:are)?\s*:?\s*([^\n\"]*)", re.IGNORECASE)


def effort_scale_from_accepted(accepted: FrozenSet[str]) -> EffortScale:
    """The scale for an upstream that accepts exactly ``accepted``.

    Every known level outside it maps to the next higher accepted level, or
    the next lower one when none is higher; anything else falls back to
    what ``high`` (the Anthropic default) maps to.
    """
    ranked = [level for level in EFFORT_LEVELS if level in accepted]

    def nearest(level: str) -> str:
        position = EFFORT_LEVELS.index(level)
        higher = [candidate for candidate in ranked if EFFORT_LEVELS.index(candidate) > position]
        return higher[0] if higher else ranked[-1]

    mapping = {level: nearest(level) for level in EFFORT_LEVELS if level not in accepted}
    return EffortScale(accepted=frozenset(ranked), map=mapping, default=mapping.get("high", "high"))


def parse_effort_rejection(error_text: Any) -> Optional[FrozenSet[str]]:
    """The effort levels an upstream error says it supports, or None.

    Only an error about the reasoning effort that lists at least one known
    level counts; anything else — a context-length error, a timeout, an
    unrelated "supported values" message — returns None.
    """
    text = str(error_text or "")
    if "effort" not in text.lower():
        return None
    match = _SUPPORTED_LIST_RE.search(text)
    if match is None:
        return None
    accepted = frozenset(word for word in re.findall(r"[a-z]+", match.group(1).lower()) if word in EFFORT_LEVELS)
    return accepted or None


def adapt_payload_after_effort_rejection(
    payload: Dict[str, Any], model_name: Optional[str], error_text: Any
) -> Optional[Dict[str, Any]]:
    """The payload to resend after an upstream rejected its effort, or None.

    When ``error_text`` is an effort rejection that names the supported
    levels, the scale is recorded for ``model_name`` (so every later request
    is normalized up front) and the payload is returned rewritten onto it.
    Returns None when the error is not an effort rejection, when there is no
    model to learn for, or when rewriting changes nothing — resending the
    same payload would only fail the same way.
    """
    accepted = parse_effort_rejection(error_text)
    if accepted is None or not model_name or not isinstance(payload, dict):
        return None
    scale = effort_scale_from_accepted(accepted)
    key = model_name.lower()
    if _LEARNED_EFFORT_SCALES.get(key) != scale:
        _LEARNED_EFFORT_SCALES[key] = scale
        logger.info(
            "Learned the reasoning-effort scale of %s from an upstream rejection: %s",
            model_name,
            ", ".join(level for level in EFFORT_LEVELS if level in scale.accepted),
        )
    adapted = normalize_reasoning_effort(payload, model_name)
    return None if adapted is payload else adapted


def forget_learned_effort_scales() -> None:
    """Drop every learned scale (used by the tests)."""
    _LEARNED_EFFORT_SCALES.clear()


def effort_scale_for_model(model_name: Optional[str]) -> Optional[EffortScale]:
    """The effort scale learned for this model, or None while none was rejected."""
    return _LEARNED_EFFORT_SCALES.get((model_name or "").lower())


def _map_effort(value: str, scale: EffortScale) -> str:
    """Map a client effort value onto the model's accepted scale."""
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
