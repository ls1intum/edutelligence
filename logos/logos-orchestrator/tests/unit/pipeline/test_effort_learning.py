"""Learning a reasoning-effort scale from an upstream rejection.

An upstream whose chat template accepts only part of the effort scale
rejects every request carrying another value before the first token. When
the rejection names the supported values, Logos records that scale for the
model and rewrites the payload onto it, so the request can be resent once
and every later request is normalized before it is sent — with no registry
entry for the model family.
"""

import pytest

from logos.pipeline import effort_normalization
from logos.pipeline.effort_normalization import (
    EFFORT_LEVELS,
    adapt_payload_after_effort_rejection,
    effort_scale_for_model,
    effort_scale_from_accepted,
    forget_learned_effort_scales,
    normalize_reasoning_effort,
    parse_effort_rejection,
)

HARMONY_400 = (
    "reasoning_effort='xhigh' is not supported by Harmony. Supported values are: high, medium, low. "
    "(parameter=reasoning_effort)"
)
QWEN_TEMPLATE_500 = "Unexpected reasoning effort high. Supported types are xhigh (default), medium, and low"
GPT_OSS = "openai/gpt-oss-120b"


@pytest.fixture(autouse=True)
def _clean_learned_scales():
    forget_learned_effort_scales()
    yield
    forget_learned_effort_scales()


def test_parses_the_harmony_rejection():
    assert parse_effort_rejection(HARMONY_400) == frozenset({"high", "medium", "low"})


def test_parses_the_qwen_template_rejection():
    assert parse_effort_rejection(QWEN_TEMPLATE_500) == frozenset({"xhigh", "medium", "low"})


def test_parses_a_rejection_inside_a_json_error_body():
    body = '{"error": {"message": "' + HARMONY_400 + '", "type": "BadRequestError", "code": 400}}'
    assert parse_effort_rejection(body) == frozenset({"high", "medium", "low"})


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "This model's maximum context length is 32768 tokens.",
        "Supported values are: json_object, text",  # not about the effort
        "reasoning effort missing",  # about the effort, but names no levels
    ],
)
def test_other_errors_are_not_effort_rejections(text):
    assert parse_effort_rejection(text) is None


def test_a_rejected_level_moves_up_to_the_next_accepted_one():
    scale = effort_scale_from_accepted(frozenset({"xhigh", "medium", "low"}))
    assert scale.map["high"] == "xhigh"
    assert scale.map["minimal"] == "low"
    # Nothing above max is accepted, so it comes down to the highest level.
    assert scale.map["max"] == "xhigh"
    assert scale.default == "xhigh"


def test_a_level_above_every_accepted_one_moves_down():
    scale = effort_scale_from_accepted(frozenset({"high", "medium", "low"}))
    assert scale.map["xhigh"] == "high"
    assert scale.map["max"] == "high"
    assert scale.default == "high"


def test_every_learned_scale_covers_every_level():
    for accepted in ({"low"}, {"max"}, {"medium", "high"}, {"minimal", "xhigh"}):
        scale = effort_scale_from_accepted(frozenset(accepted))
        for level in EFFORT_LEVELS:
            assert scale.map.get(level, level) in scale.accepted


def test_adapting_learns_the_scale_and_rewrites_every_location():
    payload = {
        "model": GPT_OSS,
        "output_config": {"effort": "xhigh"},
        "reasoning_effort": "xhigh",
        "chat_template_kwargs": {"reasoning_effort": "max"},
    }
    adapted = adapt_payload_after_effort_rejection(payload, GPT_OSS, HARMONY_400)
    assert adapted["output_config"]["effort"] == "high"
    assert adapted["reasoning_effort"] == "high"
    assert adapted["chat_template_kwargs"]["reasoning_effort"] == "high"
    # The input stays untouched: the caller still holds what it first sent.
    assert payload["reasoning_effort"] == "xhigh"


def test_adapting_a_responses_payload():
    # The Responses API (and a Messages request translated by to_responses)
    # carries the effort as reasoning.effort.
    payload = {"model": GPT_OSS, "input": "hi", "reasoning": {"effort": "xhigh", "summary": "auto"}}
    adapted = adapt_payload_after_effort_rejection(payload, GPT_OSS, HARMONY_400)
    assert adapted["reasoning"] == {"effort": "high", "summary": "auto"}
    later = normalize_reasoning_effort({"input": "hi", "reasoning": {"effort": "max"}}, GPT_OSS)
    assert later["reasoning"]["effort"] == "high"


def test_a_learned_scale_normalizes_later_requests_up_front():
    adapt_payload_after_effort_rejection({"reasoning_effort": "xhigh"}, GPT_OSS, HARMONY_400)
    later = normalize_reasoning_effort({"output_config": {"effort": "max"}}, GPT_OSS)
    assert later["output_config"]["effort"] == "high"
    # Learned per model, case-insensitively, and only for that model.
    assert effort_scale_for_model("OpenAI/GPT-OSS-120B") is not None
    assert effort_scale_for_model("openai/gpt-oss-20b") is None


def test_relearning_replaces_a_changed_scale():
    # A redeployed model with a different template is learned anew.
    adapt_payload_after_effort_rejection({"reasoning_effort": "high"}, GPT_OSS, QWEN_TEMPLATE_500)
    assert normalize_reasoning_effort({"reasoning_effort": "high"}, GPT_OSS)["reasoning_effort"] == "xhigh"
    adapt_payload_after_effort_rejection({"reasoning_effort": "xhigh"}, GPT_OSS, HARMONY_400)
    assert normalize_reasoning_effort({"reasoning_effort": "xhigh"}, GPT_OSS)["reasoning_effort"] == "high"


def test_no_retry_when_the_error_is_something_else():
    payload = {"reasoning_effort": "xhigh"}
    assert adapt_payload_after_effort_rejection(payload, GPT_OSS, "upstream timed out") is None
    assert effort_scale_for_model(GPT_OSS) is None


def test_no_retry_when_rewriting_changes_nothing():
    # The value already fits the named scale, so resending would fail the same way.
    assert adapt_payload_after_effort_rejection({"reasoning_effort": "high"}, GPT_OSS, HARMONY_400) is None


def test_no_retry_without_a_model_name():
    assert adapt_payload_after_effort_rejection({"reasoning_effort": "xhigh"}, None, HARMONY_400) is None


def test_relearning_the_same_scale_logs_once(caplog):
    caplog.set_level("INFO", logger=effort_normalization.__name__)
    for _ in range(3):
        adapt_payload_after_effort_rejection({"reasoning_effort": "xhigh"}, GPT_OSS, HARMONY_400)
    assert sum("Learned the reasoning-effort scale" in record.message for record in caplog.records) == 1
