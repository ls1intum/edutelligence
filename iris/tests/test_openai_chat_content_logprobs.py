"""Logprobs must cover only the visible answer, not reasoning or template tokens.

The token sequences mirror what Logos (vLLM) returned for Qwen3.8-27B with
thinking enabled and for gpt-oss-120b (harmony format).
"""

from types import SimpleNamespace

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.llm.external.openai_chat import convert_to_iris_message  # noqa: E402


def _tok(text, logprob=-0.1, raw=None):
    data = raw if raw is not None else list(text.encode("utf-8"))
    return SimpleNamespace(
        token=text,
        bytes=data,
        logprob=logprob,
        top_logprobs=[SimpleNamespace(token=text, logprob=logprob)],
    )


def _convert(content, tokens):
    message = SimpleNamespace(role="assistant", content=content, tool_calls=None)
    return convert_to_iris_message(
        message, None, "test-model", SimpleNamespace(content=tokens)
    )


def test_qwen_reasoning_and_end_tokens_are_excluded():
    tokens = [
        _tok("The", -2.0),
        _tok(" user", -2.0),
        _tok(" wants", -2.0),
        _tok(" naï", -2.0),
        _tok(".\n", -2.0),
        _tok("</think>", -2.0),
        _tok("\n\n", 0.0),
        _tok("Rec", -0.01),
        _tok("ursion", -0.02),
        _tok(" —", -0.03),
        _tok(" naï", -0.04),
        _tok("ve", -0.05),
        _tok(".", -0.06),
        _tok("<|im_end|>", -2.0),
    ]
    message = _convert("\n\nRecursion — naïve.", tokens)

    assert message.token_logprobs == [0.0, -0.01, -0.02, -0.03, -0.04, -0.05, -0.06]
    assert [e.token for e in message.token_logprob_entries] == [
        "\n\n",
        "Rec",
        "ursion",
        " —",
        " naï",
        "ve",
        ".",
    ]


def test_gpt_oss_analysis_channel_is_excluded_even_when_it_repeats_the_answer():
    answer = [_tok("39", -0.3), _tok("1", -0.4)]
    tokens = [
        _tok("<|channel|>", -2.0),
        _tok("analysis", -2.0),
        _tok("<|message|>", -2.0),
        _tok("17*23 = ", -2.0),
        _tok("391", -2.0),
        _tok("<|end|>", -2.0),
        _tok("<|start|>", -2.0),
        _tok("assistant", -2.0),
        _tok("<|channel|>", -2.0),
        _tok("final", -2.0),
        _tok("<|message|>", -2.0),
        *answer,
        _tok("<|return|>", -2.0),
    ]
    assert _convert("391", tokens).token_logprobs == [-0.3, -0.4]


def test_multibyte_character_split_across_tokens_is_kept_whole():
    # gpt-oss split "naïve" into "na", "ï", "ve"; vLLM reports partial UTF-8
    # sequences as raw bytes.
    tokens = [
        _tok("<|message|>", -2.0),
        _tok("na", -0.1),
        _tok("�", -0.2, raw=[195]),
        _tok("�", -0.3, raw=[175]),
        _tok("ve", -0.4),
        _tok("<|return|>", -2.0),
    ]
    assert _convert("naïve", tokens).token_logprobs == [-0.1, -0.2, -0.3, -0.4]


def test_models_without_reasoning_keep_every_token():
    tokens = [_tok("Hello", -0.1), _tok(" world", -0.2)]
    assert _convert("Hello world", tokens).token_logprobs == [-0.1, -0.2]


def test_unalignable_content_falls_back_to_all_tokens():
    tokens = [_tok("abc", -0.1), _tok("def", -0.2)]
    assert _convert("something else", tokens).token_logprobs == [-0.1, -0.2]


def test_tokens_without_bytes_align_by_text():
    tokens = [
        SimpleNamespace(token="<think>x</think>", bytes=None, logprob=-2.0),
        SimpleNamespace(token="ok", bytes=None, logprob=-0.5),
    ]
    assert _convert("ok", tokens).token_logprobs == [-0.5]
