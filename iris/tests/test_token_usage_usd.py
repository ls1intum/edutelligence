"""USD cost reporting uses provider totals before explicit configured rates."""

# pylint: disable=protected-access

from types import SimpleNamespace

import pytest
from openai.types import CompletionUsage
from openai.types.chat import ChatCompletionChunk
from openai.types.responses import ResponseUsage

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.common.token_usage_dto import TokenUsageDTO  # noqa: E402
from iris.llm.external.openai_chat import (  # noqa: E402
    DirectOpenAIChatModel,
    create_token_usage,
)
from iris.llm.request_handler.llm_request_handler import (  # noqa: E402
    apply_model_costs,
)


def _model(**overrides):
    config = {
        "id": "cost-test",
        "type": "openai_chat",
        "model": "cost-test",
        "api_key": "sk-test",  # pragma: allowlist secret
        "cost_per_million_input_token": 99.0,
        "cost_per_million_output_token": 99.0,
        "cost_per_million_input_token_usd": 2.0,
        "cost_per_million_cached_input_token_usd": 0.2,
        "cost_per_million_cache_write_input_token_usd": 2.5,
        "cost_per_million_output_token_usd": 8.0,
    }
    config.update(overrides)
    return DirectOpenAIChatModel(**config)


@pytest.mark.parametrize("cost", [0, 0.000123])
@pytest.mark.parametrize("api", ["chat", "responses", "dict"])
def test_sdk_usage_keeps_explicit_provider_usd_total(api, cost):
    raw = {
        "cost": cost,
        "cost_currency": "USD",
        "total_tokens": 1020,
    }
    if api == "chat":
        usage = CompletionUsage(prompt_tokens=1000, completion_tokens=20, **raw)
    elif api == "responses":
        usage = ResponseUsage(
            input_tokens=1000,
            output_tokens=20,
            input_tokens_details={"cached_tokens": 900, "cache_write_tokens": 0},
            output_tokens_details={"reasoning_tokens": 0},
            **raw,
        )
    else:
        usage = {"prompt_tokens": 1000, "completion_tokens": 20, **raw}

    tokens = create_token_usage(usage, "cost-test")
    apply_model_costs(tokens, _model())

    assert tokens.total_cost_usd == cost
    assert tokens.cost_source == "PROVIDER"
    assert tokens.model_dump(by_alias=True)["totalCostUsd"] == cost
    assert "usage_reported" not in tokens.model_dump(by_alias=True)


@pytest.mark.parametrize(
    "cost, source",
    [
        (-1, "PROVIDER"),
        (float("nan"), "PROVIDER"),
        (float("inf"), "PROVIDER"),
        (10**1000, "PROVIDER"),
        (True, "PROVIDER"),
        ("0.5", "PROVIDER"),
        ({"amount": 1}, "PROVIDER"),
        ([1], "PROVIDER"),
        (0.5, "provider"),
        (0.5, "FUTURE_SOURCE"),
        (0.5, {}),
        (0.5, None),
        (None, "PROVIDER"),
    ],
)
def test_bad_optional_cost_pair_does_not_reject_token_record(cost, source):
    tokens = TokenUsageDTO(numInputTokens=10, totalCostUsd=cost, costSource=source)

    assert tokens.num_input_tokens == 10
    assert tokens.total_cost_usd is None
    assert tokens.cost_source is None


def test_unknown_currency_does_not_become_a_usd_provider_cost():
    tokens = create_token_usage(
        {
            "prompt_tokens": 5,
            "completion_tokens": 2,
            "cost": 100,
            "cost_currency": "EUR",
        },
        "cost-test",
    )

    apply_model_costs(tokens, _model())

    assert tokens.total_cost_usd == pytest.approx(0.000026)
    assert tokens.cost_source == "CONFIGURATION"


def test_configured_usd_estimate_prices_cache_classes_separately():
    tokens = TokenUsageDTO(
        numInputTokens=1000,
        numCachedInputTokens=900,
        numCacheWriteInputTokens=50,
        numOutputTokens=10,
    )

    apply_model_costs(tokens, _model())

    assert tokens.total_cost_usd == pytest.approx(0.000485)
    assert tokens.cost_source == "CONFIGURATION"
    assert tokens.cost_per_million_input_token == 99


def test_configured_usd_estimate_applies_long_context_tier():
    tokens = TokenUsageDTO(
        numInputTokens=1000,
        numCachedInputTokens=900,
        numCacheWriteInputTokens=50,
        numOutputTokens=10,
    )

    apply_model_costs(
        tokens,
        _model(
            long_context_threshold_tokens=999,
            long_context_input_cost_multiplier=2,
            long_context_output_cost_multiplier=1.5,
        ),
    )

    assert tokens.total_cost_usd == pytest.approx(0.00093)


@pytest.mark.parametrize("cache_rate", [None, -1, float("inf")])
def test_missing_or_bad_used_usd_rate_stays_unpriced(cache_rate):
    tokens = TokenUsageDTO(numInputTokens=1000, numCachedInputTokens=900)

    apply_model_costs(
        tokens, _model(cost_per_million_cached_input_token_usd=cache_rate)
    )

    assert tokens.total_cost_usd is None
    assert tokens.cost_source is None


def test_legacy_rate_configuration_does_not_establish_usd_cost():
    tokens = TokenUsageDTO(numInputTokens=1000, numOutputTokens=10)
    model = DirectOpenAIChatModel(
        id="legacy",
        type="openai_chat",
        model="legacy",
        api_key="sk-test",  # pragma: allowlist secret
        cost_per_million_input_token=1,
        cost_per_million_output_token=2,
    )

    apply_model_costs(tokens, model)

    assert tokens.total_cost_usd is None
    assert tokens.cost_source is None


def test_absent_usage_is_not_known_free():
    tokens = create_token_usage(None, "cost-test")

    apply_model_costs(tokens, _model())

    assert tokens.total_cost_usd is None
    assert tokens.cost_source is None


@pytest.mark.parametrize("cost", [0, 0.001])
def test_final_chat_stream_usage_keeps_usd_cost(cost):
    chunks = [
        ChatCompletionChunk(
            id="test",
            object="chat.completion.chunk",
            created=1,
            model="cost-test",
            choices=[
                {"index": 0, "delta": {"content": "answer"}, "finish_reason": "stop"}
            ],
        ),
        ChatCompletionChunk(
            id="test",
            object="chat.completion.chunk",
            created=1,
            model="cost-test",
            choices=[],
            usage={
                "prompt_tokens": 10,
                "completion_tokens": 2,
                "total_tokens": 12,
                "cost": cost,
                "cost_currency": "USD",
            },
        ),
    ]

    result = _model()._read_streamed_chat_completion(iter(chunks), lambda _: None)

    assert result.token_usage.total_cost_usd == cost
    assert result.token_usage.cost_source == "PROVIDER"


def test_final_responses_stream_usage_keeps_usd_cost():
    usage = ResponseUsage(
        input_tokens=10,
        output_tokens=2,
        total_tokens=12,
        input_tokens_details={"cached_tokens": 0, "cache_write_tokens": 0},
        output_tokens_details={"reasoning_tokens": 0},
        cost=0.001,
        cost_currency="USD",
    )
    events = iter(
        [
            SimpleNamespace(
                type="response.completed",
                response=SimpleNamespace(
                    output=[],
                    output_text="answer",
                    status="completed",
                    usage=usage,
                ),
            )
        ]
    )

    result = _model()._read_streamed_responses_completion(events, lambda _: None)

    assert result.token_usage.total_cost_usd == 0.001
    assert result.token_usage.cost_source == "PROVIDER"
