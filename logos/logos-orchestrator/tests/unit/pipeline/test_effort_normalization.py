"""Reasoning-effort normalization for Qwen3.8 models.

Regression test for #749: the Qwen3.8 chat template only accepts
xhigh/medium/low as reasoning effort, while clients such as Claude Code send
the Anthropic value "high" in every request (output_config.effort). vLLM
forwards the value to the template, which rejects it with an error surfaced
as HTTP 500 internal_error — failing every turn of a session left on "high".
Logos maps the wider client scale onto the accepted one before forwarding.
"""

from logos.pipeline import effort_normalization
from logos.pipeline.context_resolver import ContextResolver, ExecutionContext
from logos.pipeline.effort_normalization import (
    CHAT_TEMPLATE_EFFORT_SCALES,
    VLLM_REASONING_EFFORT_VALUES,
    EffortScale,
    effort_scale_for_model,
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


def test_effort_scale_lookup_by_model_name():
    # Matched case-insensitively as a model-name substring.
    assert effort_scale_for_model("Qwen/Qwen3.8-27B") == CHAT_TEMPLATE_EFFORT_SCALES["qwen3.8"]
    assert effort_scale_for_model("qwen/qwen3.8-coder-30b-a3b") == CHAT_TEMPLATE_EFFORT_SCALES["qwen3.8"]
    # Other families keep their own scales and must not be rewritten.
    assert effort_scale_for_model("Qwen/Qwen3.5-27B") is None
    assert effort_scale_for_model("Qwen/Qwen3-32B") is None
    assert effort_scale_for_model("gpt-4.1-mini") is None
    assert effort_scale_for_model("") is None
    assert effort_scale_for_model(None) is None


def test_longest_matching_pattern_wins_over_broader_pattern(monkeypatch):
    # Overlapping patterns must resolve to the most specific (longest)
    # match regardless of registration order, so a broad "qwen3" entry
    # cannot shadow the specific "qwen3.8" one.
    broad = EffortScale(accepted=frozenset({"low", "medium", "high"}), map={"max": "high"}, default="medium")
    specific = CHAT_TEMPLATE_EFFORT_SCALES["qwen3.8"]
    for registry in (
        {"qwen3": broad, "qwen3.8": specific},
        {"qwen3.8": specific, "qwen3": broad},
    ):
        monkeypatch.setattr(effort_normalization, "CHAT_TEMPLATE_EFFORT_SCALES", registry)
        assert effort_scale_for_model("Qwen/Qwen3.8-27B") is specific
        assert effort_scale_for_model("Qwen/Qwen3-32B") is broad


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


def test_every_registered_scale_covers_every_vllm_reasoning_effort_value():
    # Every value vLLM's reasoning_effort Literal allows must either pass
    # through or be mapped to an accepted value (or "none"), per family;
    # the family default must itself be accepted.
    for pattern, scale in CHAT_TEMPLATE_EFFORT_SCALES.items():
        assert scale.default in scale.accepted, pattern
        for value in VLLM_REASONING_EFFORT_VALUES:
            assert scale.map.get(value, scale.default) in scale.accepted | {"none"}, pattern


def test_unknown_effort_falls_back_to_family_default():
    # Drift-proofing: a value neither accepted nor mapped (e.g. one a
    # future vLLM introduces) is coerced to the family default instead of
    # reaching the template, which would reject it with an HTTP 500.
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


def test_new_template_family_needs_only_a_registry_entry(monkeypatch):
    # Onboarding a chat template with its own restricted scale is a single
    # registry entry — the normalization logic stays family-agnostic.
    monkeypatch.setitem(
        CHAT_TEMPLATE_EFFORT_SCALES,
        "acme-1.0",
        EffortScale(
            accepted=frozenset({"deep", "shallow"}), map={"high": "deep", "medium": "shallow"}, default="shallow"
        ),
    )
    payload = {"model": "Acme/Acme-1.0-7B", "output_config": {"effort": "high"}}
    assert normalize_reasoning_effort(payload, "Acme/Acme-1.0-7B")["output_config"]["effort"] == "deep"
    # Unrelated models are still untouched.
    assert normalize_reasoning_effort(payload, "gpt-4.1-mini") is payload


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
