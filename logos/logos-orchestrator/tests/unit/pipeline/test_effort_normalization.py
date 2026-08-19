"""Reasoning-effort normalization for Qwen3.8 models.

Regression test for #749: the Qwen3.8 chat template only accepts
xhigh/medium/low as reasoning effort, while clients such as Claude Code send
the Anthropic value "high" in every request (output_config.effort). vLLM
forwards the value to the template, which rejects it with an error surfaced
as HTTP 500 internal_error — failing every turn of a session left on "high".
Logos maps the wider client scale onto the accepted one before forwarding.
"""

from logos.pipeline.context_resolver import ContextResolver, ExecutionContext
from logos.pipeline.effort_normalization import (
    QWEN38_EFFORT_MAP,
    model_uses_qwen38_effort_scale,
    normalize_reasoning_effort,
)

MODEL = "Qwen/Qwen3.8-27B"


def _context(model_name: str = MODEL, provider_type: str = "logosnode") -> ExecutionContext:
    return ExecutionContext(
        model_id=1,
        provider_id=1,
        provider_name="node-1",
        provider_type=provider_type,
        forward_url="logosnode://provider/1/lane/1" if provider_type == "logosnode" else "https://upstream/v1",
        auth_header="Authorization",
        auth_value="Bearer key",
        model_name=model_name,
    )


def test_qwen38_model_detected_case_insensitively():
    assert model_uses_qwen38_effort_scale("Qwen/Qwen3.8-27B")
    assert model_uses_qwen38_effort_scale("qwen/qwen3.8-coder-30b-a3b")
    # Other families keep their own scales and must not be rewritten.
    assert not model_uses_qwen38_effort_scale("Qwen/Qwen3.5-27B")
    assert not model_uses_qwen38_effort_scale("Qwen/Qwen3-32B")
    assert not model_uses_qwen38_effort_scale("gpt-4.1-mini")
    assert not model_uses_qwen38_effort_scale("")
    assert not model_uses_qwen38_effort_scale(None)


def test_anthropic_output_config_high_mapped_to_xhigh():
    # The exact request shape from #749 (Claude Code /v1/messages).
    payload = {
        "model": "Qwen/Qwen3.8-27B",
        "max_tokens": 64,
        "output_config": {"effort": "high"},
        "messages": [{"role": "user", "content": "hello"}],
    }
    assert normalize_reasoning_effort(payload, MODEL)["output_config"]["effort"] == "xhigh"


def test_openai_reasoning_effort_high_mapped_to_xhigh():
    assert (
        normalize_reasoning_effort({"model": MODEL, "reasoning_effort": "high"}, MODEL)["reasoning_effort"] == "xhigh"
    )


def test_chat_template_kwargs_effort_mapped():
    payload = {"model": MODEL, "chat_template_kwargs": {"reasoning_effort": "high"}}
    assert normalize_reasoning_effort(payload, MODEL)["chat_template_kwargs"]["reasoning_effort"] == "xhigh"


def test_all_three_locations_mapped_independently():
    payload = {
        "model": MODEL,
        "output_config": {"effort": "high"},
        "reasoning_effort": "max",
        "chat_template_kwargs": {"reasoning_effort": "minimal", "enable_thinking": True},
    }
    result = normalize_reasoning_effort(payload, MODEL)
    assert result["output_config"]["effort"] == "xhigh"
    assert result["reasoning_effort"] == "xhigh"
    assert result["chat_template_kwargs"]["reasoning_effort"] == "low"
    # Sibling keys survive the copy.
    assert result["chat_template_kwargs"]["enable_thinking"] is True


def test_accepted_values_pass_through_unchanged():
    for value in ("xhigh", "medium", "low", "none"):
        payload = {"model": MODEL, "output_config": {"effort": value}, "reasoning_effort": value}
        assert normalize_reasoning_effort(payload, MODEL) is payload


def test_map_covers_every_vllm_reasoning_effort_value():
    # vLLM's ChatCompletionRequest.reasoning_effort Literal: none, minimal,
    # low, medium, high, xhigh, max. Everything must either pass through or
    # be mapped to an accepted Qwen3.8 value.
    accepted = {"xhigh", "medium", "low"}
    for value in ("none", "minimal", "low", "medium", "high", "xhigh", "max"):
        assert QWEN38_EFFORT_MAP.get(value, value) in accepted | {"none"}


def test_other_models_keep_high_untouched():
    payload = {"model": "gpt-4.1-mini", "output_config": {"effort": "high"}, "reasoning_effort": "high"}
    assert normalize_reasoning_effort(payload, "gpt-4.1-mini") is payload
    assert normalize_reasoning_effort(payload, "Qwen/Qwen3.5-27B") is payload


def test_non_string_effort_ignored():
    payload = {"model": MODEL, "output_config": {"effort": 7}, "reasoning_effort": None}
    assert normalize_reasoning_effort(payload, MODEL) is payload


def test_payload_without_effort_fields_unchanged():
    payload = {"model": MODEL, "messages": [{"role": "user", "content": "hello"}]}
    assert normalize_reasoning_effort(payload, MODEL) is payload


def test_input_payload_not_mutated():
    payload = {"model": MODEL, "output_config": {"effort": "high"}, "reasoning_effort": "high"}
    normalize_reasoning_effort(payload, MODEL)
    assert payload["output_config"]["effort"] == "high"
    assert payload["reasoning_effort"] == "high"


def test_prepare_headers_and_payload_normalizes_for_qwen38():
    # End-to-end through the forward-time hook (sync + streaming + jobs all
    # go through prepare_headers_and_payload).
    _, payload = ContextResolver.prepare_headers_and_payload(
        _context(), {"model": "Qwen/Qwen3.8-27B", "output_config": {"effort": "high"}}
    )
    assert payload["output_config"]["effort"] == "xhigh"


def test_prepare_headers_and_payload_keeps_effort_for_other_models():
    _, payload = ContextResolver.prepare_headers_and_payload(
        _context(model_name="gpt-4.1-mini", provider_type="cloud"),
        {"model": "gpt-4.1-mini", "output_config": {"effort": "high"}},
    )
    assert payload["output_config"]["effort"] == "high"


def test_prepare_headers_and_payload_multipart_payload():
    # Audio uploads carry no effort fields; the normalizer must not choke on
    # the multipart representation.
    payload = {
        "model": MODEL,
        "input_audio": "file.wav",
        "_logos_multipart": {"fields": [["model", MODEL]], "files": []},
    }
    _, prepared = ContextResolver.prepare_headers_and_payload(_context(), payload)
    assert prepared["model"] == MODEL
