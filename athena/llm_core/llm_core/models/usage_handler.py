import logging
import math
import os

from athena import emit_meta, get_meta
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

logger = logging.getLogger(__name__)


def _configured_rate(name: str) -> float | None:
    """Read an optional price without letting bad telemetry stop a callback."""
    value = os.environ.get(name)
    if value is None:
        return None
    try:
        rate = float(value)
        if math.isfinite(rate) and rate >= 0:
            return rate
    except (ValueError, OverflowError):
        pass
    logger.warning("Ignoring invalid configured token price: %s", name)
    return None


def _reported_usd_cost(usage: dict, normalized_usage: dict) -> float | None:
    cost = usage.get("cost")
    if cost is None:
        return None
    try:
        valid = (
            usage.get("cost_currency") == "USD"
            and isinstance(cost, (int, float))
            and not isinstance(cost, bool)
            and math.isfinite(cost)
            and cost >= 0
            and usage.get("prompt_tokens", usage.get("input_tokens"))
            == normalized_usage["input_tokens"]
            and usage.get("completion_tokens", usage.get("output_tokens"))
            == normalized_usage["output_tokens"]
        )
    except OverflowError:
        valid = False
    if valid:
        return float(cost)
    logger.warning("Ignoring invalid provider cost or missing USD currency")
    return None


def _estimated_usd_cost(usage: dict) -> float | None:
    details = usage.get("input_token_details") or {}
    cached = sum(
        details.get(f"{prefix}cache_read") or 0 for prefix in ("", "priority_", "flex_")
    )
    written = sum(
        details.get(f"{prefix}cache_creation") or 0
        for prefix in ("", "priority_", "flex_")
    )
    counts = (
        usage["input_tokens"] - cached - written,
        cached,
        written,
        usage["output_tokens"],
    )
    names = ("INPUT", "CACHED_INPUT", "CACHE_WRITE_INPUT", "OUTPUT")
    rates = tuple(
        _configured_rate(f"LLM_DEFAULT_MODEL_COST_PER_MILLION_{name}_TOKEN_USD")
        for name in names
    )
    if not any(rate is not None for rate in rates) or any(
        count < 0 for count in counts
    ):
        return None
    total = 0.0
    for count, rate in zip(counts, rates):
        if count == 0:
            continue
        if rate is None:
            return None
        total += count * rate / 1_000_000
    return total if math.isfinite(total) else None


class UsageHandler(BaseCallbackHandler):
    """Attach per-call usage and optional USD costs to Athena responses."""

    def on_llm_end(self, response: LLMResult, **kwargs) -> None:
        cost_per_million_input_tokens = (
            _configured_rate("LLM_DEFAULT_MODEL_COST_PER_MILLION_INPUT_TOKEN") or 0.0
        )
        cost_per_million_output_tokens = (
            _configured_rate("LLM_DEFAULT_MODEL_COST_PER_MILLION_OUTPUT_TOKEN") or 0.0
        )

        meta = get_meta()

        total_usage = meta.get(
            "totalUsage",
            {"numInputTokens": 0, "numOutputTokens": 0, "numTotalTokens": 0, "cost": 0},
        )
        llm_calls = meta.get("llmRequests", [])
        single_request = len(response.generations) == 1

        for generations in response.generations:
            for generation in generations:
                message = getattr(generation, "message", None)
                generation_usage = getattr(message, "usage_metadata", None)
                if not generation_usage:
                    continue
                response_metadata = message.response_metadata
                output_metadata = response.llm_output or {}
                model_name = response_metadata.get(
                    "model_name", output_metadata.get("model_name")
                )
                # ChatOpenAI keeps the full nonstreaming usage in llm_output;
                # its normalized UsageMetadata contains token counts only.
                provider_usage = response_metadata.get("token_usage")
                if provider_usage is None and single_request:
                    provider_usage = output_metadata.get("token_usage")
                reported_cost = _reported_usd_cost(
                    provider_usage if isinstance(provider_usage, dict) else {},
                    generation_usage,
                )
                cost_usd = reported_cost
                source = "PROVIDER" if reported_cost is not None else None
                if cost_usd is None:
                    cost_usd = _estimated_usd_cost(generation_usage)
                    source = "CONFIGURATION" if cost_usd is not None else None

                total_usage["numInputTokens"] += generation_usage["input_tokens"]
                total_usage["numOutputTokens"] += generation_usage["output_tokens"]
                total_usage["numTotalTokens"] += generation_usage["total_tokens"]

                total_usage["cost"] += (
                    int(generation_usage["input_tokens"])
                    * cost_per_million_input_tokens
                    / 1_000_000
                )
                total_usage["cost"] += (
                    int(generation_usage["output_tokens"])
                    * cost_per_million_output_tokens
                    / 1_000_000
                )

                llm_calls.append(
                    {
                        "model": model_name,
                        "costPerMillionInputToken": cost_per_million_input_tokens,
                        "costPerMillionOutputToken": cost_per_million_output_tokens,
                        "numInputTokens": generation_usage["input_tokens"],
                        "numOutputTokens": generation_usage["output_tokens"],
                        "numTotalTokens": generation_usage["total_tokens"],
                        "totalCostUsd": cost_usd,
                        "costSource": source,
                    }
                )
                # Choices in one request repeat its aggregate usage.
                break

        emit_meta("totalUsage", total_usage)
        emit_meta("llmRequests", llm_calls)
