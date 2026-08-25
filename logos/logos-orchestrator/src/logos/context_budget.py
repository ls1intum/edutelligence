# src/logos/context_budget.py
"""How much context window one request needs.

The orchestrator advertises the *smallest* window any worker serves for a
model (``max_model_len`` on ``GET /v1/models``), because a request may land on
any of them. That floor is safe but pessimistic: a model calibrated for 262144
tokens on one node and squeezed into 33000 on another is advertised — and, for
clients that size their conversation from the advertised number, *used* — as a
33000-token model everywhere.

This module supplies the estimate that lets routing do better: given a request
payload, how wide a window does it actually need? Deployments whose window is
too narrow can then be skipped while the request still reaches the ones that
fit (see ``_filter_logosnode_deployments`` in ``main.py``).

The estimate is deliberately coarse. It never sees the model's tokenizer, so
it counts characters and divides — and it rounds against itself at every step,
because the cost of overestimating is picking a roomier worker while the cost
of underestimating is a 400 from vLLM.
"""

from __future__ import annotations

from typing import Any, Iterator, Optional

# Characters per token. Real tokenizers land near 3.5-4 for English prose and
# code; 3.0 keeps the estimate above the true count for the mixed text
# (identifiers, JSON, diffs) coding assistants actually send.
CHARS_PER_TOKEN = 3.0

# What a client is assumed to reserve for its own output when the payload does
# not say. 20000 is what Claude Code reserves — it caps its reservation there
# regardless of how large a max_tokens it was configured with — and it is the
# largest default among the clients Logos serves, so it is the conservative
# choice for the ones that stay silent.
DEFAULT_OUTPUT_RESERVE_TOKENS = 20_000

# Slack on top of prompt + output before a window counts as wide enough. Same
# 3000 tokens Claude Code keeps between its own hard block and the limit it
# was told, which is the margin that has to absorb the difference between an
# estimate like this one and what the worker's tokenizer really counts.
SAFETY_MARGIN_TOKENS = 3_000

# Payload keys whose values are attachments, not prose: counting a base64
# image as ~1 token per 3 characters would swamp the estimate. Images do
# consume context, but a few hundred to a few thousand tokens - orders of
# magnitude below their encoded size.
_OPAQUE_KEYS = frozenset(
    {
        "b64_json",
        "data",
        "file",
        "file_data",
        "image_url",
        "source",
        "url",
    }
)

# Request fields that carry the prompt, across the API dialects Logos serves:
# chat completions and the Anthropic Messages API (``messages``, ``system``,
# ``tools``), the Responses API (``input``, ``instructions``) and legacy
# completions (``prompt``).
_PROMPT_KEYS = ("messages", "system", "prompt", "input", "instructions", "tools")

# Fields a client uses to cap its own output, most specific first.
_OUTPUT_KEYS = ("max_tokens", "max_completion_tokens", "max_output_tokens")


def _iter_text(value: Any) -> Iterator[str]:
    """Yield the human-readable strings inside a nested payload fragment."""
    if isinstance(value, str):
        # A data: URI is an attachment that lost its wrapper key.
        if not value.startswith("data:"):
            yield value
    elif isinstance(value, list):
        for item in value:
            yield from _iter_text(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str) and key in _OPAQUE_KEYS:
                continue
            yield from _iter_text(item)


def estimate_prompt_tokens(payload: Any) -> int:
    """Rough token count of the prompt in ``payload``, 0 when there is none.

    Returns 0 for anything this cannot read — a multipart audio upload, a
    body that is not a dict, a request whose prompt fields are all empty.
    Callers treat 0 as "no opinion" and skip context-based filtering, so an
    unreadable payload keeps the routing it had before.
    """
    if not isinstance(payload, dict):
        return 0
    chars = 0
    for key in _PROMPT_KEYS:
        if key in payload:
            chars += sum(len(text) for text in _iter_text(payload[key]))
    if chars <= 0:
        return 0
    return int(chars / CHARS_PER_TOKEN) + 1


def reserved_output_tokens(payload: Any) -> int:
    """Tokens the request reserves for its own completion.

    vLLM charges input and output against one budget, so a request needs room
    for both. Falls back to :data:`DEFAULT_OUTPUT_RESERVE_TOKENS` when the
    payload names no cap, since an uncapped request can generate until it hits
    the window.
    """
    if isinstance(payload, dict):
        for key in _OUTPUT_KEYS:
            raw = payload.get(key)
            if raw is None:
                continue
            try:
                value = int(raw)
            except (TypeError, ValueError):
                continue
            if value > 0:
                return value
    return DEFAULT_OUTPUT_RESERVE_TOKENS


def required_context_tokens(payload: Any) -> Optional[int]:
    """Smallest context window that can serve ``payload``, or None.

    None means "could not estimate" — the caller should not filter on context.
    """
    prompt_tokens = estimate_prompt_tokens(payload)
    if prompt_tokens <= 0:
        return None
    return prompt_tokens + reserved_output_tokens(payload) + SAFETY_MARGIN_TOKENS
