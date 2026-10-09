"""Reasoning-effort normalization onto a model's learned scale.

The Qwen3.8 chat template only accepts xhigh/medium/low as reasoning effort,
while clients such as Claude Code send the Anthropic value "high" in every
request (output_config.effort). vLLM forwards the value to the template,
which rejects it with an error surfaced as HTTP 500 internal_error — failing
every turn of a session left on "high". Once the model has rejected a value
(see test_effort_learning.py), Logos maps the wider client scale onto the
accepted one before forwarding. No model family is known in advance.
"""

import pytest

from logos.pipeline.context_resolver import ContextResolver, ExecutionContext
from logos.pipeline.effort_normalization import (
    EFFORT_LEVELS,
    VLLM_REASONING_EFFORT_VALUES,
    adapt_payload_after_effort_rejection,
    effort_scale_for_model,
    forget_learned_effort_scales,
    normalize_reasoning_effort,
)

MODEL = "Qwen/Qwen3.8-27B"
QWEN_REJECTION = "Unexpected reasoning effort high. Supported types are xhigh (default), medium, and low"


@pytest.fixture(autouse=True)
def _clean_learned_scales():
    forget_learned_effort_scales()
    yield
    forget_learned_effort_scales()


def _learn(model_name: str = MODEL, rejection: str = QWEN_REJECTION) -> None:
    adapt_payload_after_effort_rejection({"reasoning_effort": "max"}, model_name, rejection)


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


def test_no_model_has_a_scale_before_it_rejected_a_value():
    for name in (MODEL, "openai/gpt-oss-120b", "gpt-4.1-mini", "", None):
        assert effort_scale_for_model(name) is None
    payload = {"model": MODEL, "output_config": {"effort": "high"}, "reasoning_effort": "high"}
    assert normalize_reasoning_effort(payload, MODEL) is payload


def test_the_learned_scale_belongs_to_exactly_that_model():
    _learn()
    assert effort_scale_for_model("qwen/qwen3.8-27b") is not None
    # A sibling of the same family has not rejected anything yet.
    assert effort_scale_for_model("Qwen/Qwen3.8-35B-A3B") is None


def test_anthropic_output_config_high_mapped_to_xhigh():
    _learn()
    payload = {
        "model": MODEL,
        "output_config": {"effort": "high"},
        "messages": [{"role": "user", "content": "hello"}],
    }
    result = normalize_reasoning_effort(payload, MODEL)
    assert result["output_config"]["effort"] == "xhigh"
    assert result["messages"] == payload["messages"]


def test_openai_reasoning_effort_high_mapped_to_xhigh():
    _learn()
    result = normalize_reasoning_effort({"model": MODEL, "reasoning_effort": "high"}, MODEL)
    assert result["reasoning_effort"] == "xhigh"


def test_chat_template_kwargs_effort_mapped():
    _learn()
    payload = {"model": MODEL, "chat_template_kwargs": {"reasoning_effort": "high", "enable_thinking": True}}
    result = normalize_reasoning_effort(payload, MODEL)
    assert result["chat_template_kwargs"] == {"reasoning_effort": "xhigh", "enable_thinking": True}


def test_all_three_locations_mapped_independently():
    _learn()
    payload = {
        "model": MODEL,
        "output_config": {"effort": "max"},
        "reasoning_effort": "minimal",
        "chat_template_kwargs": {"reasoning_effort": "high"},
    }
    result = normalize_reasoning_effort(payload, MODEL)
    assert result["output_config"]["effort"] == "xhigh"
    assert result["reasoning_effort"] == "low"
    assert result["chat_template_kwargs"]["reasoning_effort"] == "xhigh"


def test_accepted_values_pass_through_unchanged():
    _learn()
    for value in ("xhigh", "medium", "low", "none"):
        payload = {"model": MODEL, "output_config": {"effort": value}, "reasoning_effort": value}
        assert normalize_reasoning_effort(payload, MODEL) is payload


def test_every_vllm_reasoning_effort_value_has_a_place_in_the_level_order():
    # A value vLLM adds must be placed in EFFORT_LEVELS, or a learned scale
    # cannot map it onto a neighbouring level ("none" is passed through).
    assert set(VLLM_REASONING_EFFORT_VALUES) - {"none"} <= set(EFFORT_LEVELS)


def test_unknown_effort_falls_back_to_the_scale_default():
    # Drift-proofing: a value neither accepted nor in the level order (e.g.
    # one a future vLLM introduces) is coerced to the scale's default instead
    # of reaching the template, which would reject it.
    _learn()
    payload = {
        "model": MODEL,
        "output_config": {"effort": "banana"},
        "reasoning_effort": "banana",
        "chat_template_kwargs": {"reasoning_effort": "banana"},
    }
    result = normalize_reasoning_effort(payload, MODEL)
    assert result["output_config"]["effort"] == "xhigh"
    assert result["reasoning_effort"] == "xhigh"
    assert result["chat_template_kwargs"]["reasoning_effort"] == "xhigh"


def test_non_string_effort_ignored():
    _learn()
    payload = {"model": MODEL, "output_config": {"effort": 7}, "reasoning_effort": None}
    assert normalize_reasoning_effort(payload, MODEL) is payload


def test_payload_without_effort_fields_unchanged():
    _learn()
    payload = {"model": MODEL, "messages": [{"role": "user", "content": "hello"}]}
    assert normalize_reasoning_effort(payload, MODEL) is payload


def test_input_payload_not_mutated():
    _learn()
    payload = {"model": MODEL, "output_config": {"effort": "high"}, "reasoning_effort": "high"}
    normalize_reasoning_effort(payload, MODEL)
    assert payload["output_config"]["effort"] == "high"
    assert payload["reasoning_effort"] == "high"


def test_prepare_headers_and_payload_normalizes_onto_the_learned_scale():
    # End-to-end through the forward-time hook (sync + streaming + jobs all
    # go through prepare_headers_and_payload).
    _learn()
    _, payload = ContextResolver.prepare_headers_and_payload(
        _context(), {"model": MODEL, "output_config": {"effort": "high"}}
    )
    assert payload["output_config"]["effort"] == "xhigh"


def test_prepare_headers_and_payload_keeps_effort_for_other_models():
    _learn()
    _, payload = ContextResolver.prepare_headers_and_payload(
        _context(model_name="gpt-4.1-mini", provider_type="cloud"),
        {"model": "gpt-4.1-mini", "output_config": {"effort": "high"}},
    )
    assert payload["output_config"]["effort"] == "high"


def test_prepare_headers_and_payload_multipart_payload():
    # Audio uploads carry no effort fields; the normalizer must not choke on
    # the multipart representation.
    _learn()
    payload = {
        "model": MODEL,
        "input_audio": "file.wav",
        "_logos_multipart": {"fields": [["model", MODEL]], "files": []},
    }
    _, prepared = ContextResolver.prepare_headers_and_payload(_context(), payload)
    assert prepared["model"] == MODEL
