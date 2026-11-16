"""USD cost reporting uses provider totals before explicit configured rates."""

# pylint: disable=protected-access

from types import SimpleNamespace

import httpx
import pytest
from openai import OpenAI
from openai.types import CompletionUsage
from openai.types.chat import ChatCompletionChunk
from openai.types.completion_usage import PromptTokensDetails
from openai.types.responses import ResponseUsage
from openai.types.responses.response_usage import InputTokensDetails

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.common.token_usage_dto import TokenUsageDTO  # noqa: E402
from iris.llm import CompletionArguments  # noqa: E402
from iris.llm.external.ollama import OllamaModel  # noqa: E402
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
        usage_reported=True,
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
        usage_reported=True,
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
    tokens = TokenUsageDTO(
        numInputTokens=1000, numCachedInputTokens=900, usage_reported=True
    )

    apply_model_costs(
        tokens, _model(cost_per_million_cached_input_token_usd=cache_rate)
    )

    assert tokens.total_cost_usd is None
    assert tokens.cost_source is None


def test_legacy_rate_configuration_does_not_establish_usd_cost():
    tokens = TokenUsageDTO(numInputTokens=1000, numOutputTokens=10, usage_reported=True)
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


def test_default_token_record_does_not_establish_known_usage():
    tokens = TokenUsageDTO()

    apply_model_costs(tokens, _model())

    assert not tokens.usage_reported
    assert tokens.total_cost_usd is None
    assert tokens.cost_source is None


def _usage_with_cache_details(api, details):
    if api.startswith("responses"):
        usage = {
            "input_tokens": 1000,
            "output_tokens": 10,
            "input_tokens_details": details,
        }
        if api.endswith("sdk"):
            result = ResponseUsage.model_construct(**usage)
            result.input_tokens_details = InputTokensDetails.model_construct(**details)
            for name, value in details.items():
                setattr(result.input_tokens_details, name, value)
            return result
    else:
        usage = {
            "prompt_tokens": 1000,
            "completion_tokens": 10,
            "prompt_tokens_details": details,
        }
        if api.endswith("sdk"):
            result = CompletionUsage.model_construct(**usage)
            result.prompt_tokens_details = PromptTokensDetails.model_construct(
                **details
            )
            # The SDK constructor coerces some bad values. Exercise the parser
            # with their original types, including malformed SDK extensions.
            for name, value in details.items():
                setattr(result.prompt_tokens_details, name, value)
            return result
    return usage


@pytest.mark.parametrize(
    "api", ["chat-dict", "responses-dict", "chat-sdk", "responses-sdk"]
)
@pytest.mark.parametrize("field", ["cached_tokens", "cache_write_tokens"])
@pytest.mark.parametrize("bad_count", ["900", -1, True, 1.5])
def test_malformed_reported_cache_count_prevents_usd_estimate(api, field, bad_count):
    usage = _usage_with_cache_details(api, {field: bad_count})
    tokens = create_token_usage(usage, "cost-test")

    apply_model_costs(tokens, _model())

    assert tokens.num_input_tokens == 1000
    assert tokens.num_output_tokens == 10
    assert not tokens.usage_reported
    assert tokens.total_cost_usd is None
    assert tokens.cost_source is None


@pytest.mark.parametrize(
    "api", ["chat-dict", "responses-dict", "chat-sdk", "responses-sdk"]
)
@pytest.mark.parametrize(
    "details",
    [
        {},
        {"cached_tokens": 0},
        {"cache_write_tokens": 0},
        {"cached_tokens": None},
        {"cache_write_tokens": None},
    ],
)
def test_absent_cache_counts_keep_zero_default_for_usd_estimate(api, details):
    tokens = create_token_usage(_usage_with_cache_details(api, details), "cost-test")

    apply_model_costs(tokens, _model())

    assert tokens.usage_reported
    assert tokens.total_cost_usd == pytest.approx(0.00208)
    assert tokens.cost_source == "CONFIGURATION"


@pytest.mark.parametrize("cost", [0, 0.001])
def test_malformed_cache_count_does_not_replace_reported_provider_cost(cost):
    usage = _usage_with_cache_details("chat-dict", {"cached_tokens": "900"})
    usage.update(cost=cost, cost_currency="USD")
    tokens = create_token_usage(usage, "cost-test")

    apply_model_costs(tokens, _model())

    assert tokens.total_cost_usd == cost
    assert tokens.cost_source == "PROVIDER"


@pytest.mark.parametrize("field", ["cached_tokens", "cache_write_tokens"])
@pytest.mark.parametrize("bad_count", ["bad", -1, 1.5])
def test_actual_openai_response_with_invalid_cache_count_stays_unpriced(
    field, bad_count
):
    response = {
        "id": "cost-test",
        "object": "chat.completion",
        "created": 1,
        "model": "cost-test",
        "choices": [],
        "usage": {
            "prompt_tokens": 1000,
            "completion_tokens": 10,
            "total_tokens": 1010,
            "prompt_tokens_details": {field: bad_count},
        },
    }
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=response)
        )
    ) as client:
        sdk = OpenAI(
            api_key="test",  # pragma: allowlist secret
            base_url="http://cost.invalid/v1",
            http_client=client,
        )
        completion = sdk.chat.completions.create(model="cost-test", messages=[])
    tokens = create_token_usage(completion.usage, "cost-test")

    apply_model_costs(tokens, _model())

    assert not tokens.usage_reported
    assert tokens.total_cost_usd is None
    assert tokens.cost_source is None


@pytest.mark.parametrize("api", ["chat", "responses"])
@pytest.mark.parametrize(
    "details",
    [
        "bad",
        [],
        0,
        False,
        None,
        {},
        {"cached_tokens": None},
        {"cache_write_tokens": None},
        pytest.param(Ellipsis, id="absent"),
    ],
)
@pytest.mark.parametrize("cost", [None, 0, 0.001])
def test_actual_openai_cache_details_container_controls_estimation(api, details, cost):
    if api == "chat":
        response = {
            "id": "cost-test",
            "object": "chat.completion",
            "created": 1,
            "model": "cost-test",
            "choices": [],
            "usage": {
                "prompt_tokens": 1000,
                "completion_tokens": 10,
                "total_tokens": 1010,
                "prompt_tokens_details": details,
            },
        }
    else:
        response = {
            "id": "cost-test",
            "object": "response",
            "created_at": 1,
            "model": "cost-test",
            "status": "completed",
            "output": [],
            "usage": {
                "input_tokens": 1000,
                "output_tokens": 10,
                "total_tokens": 1010,
                "input_tokens_details": details,
            },
        }
    if details is Ellipsis:
        response["usage"].pop(
            "prompt_tokens_details" if api == "chat" else "input_tokens_details"
        )
    if cost is not None:
        response["usage"].update(cost=cost, cost_currency="USD")
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=response)
        )
    ) as client:
        sdk = OpenAI(
            api_key="test",  # pragma: allowlist secret
            base_url="http://cost.invalid/v1",
            http_client=client,
        )
        resource = sdk.chat.completions if api == "chat" else sdk.responses
        create = resource.create
        # Iris imports Langfuse's global wrapper, which rejects malformed chat
        # details before this parser runs. Test the SDK decoder itself here.
        unwrapped = getattr(create, "__wrapped__", None)
        if getattr(unwrapped, "__self__", None) is resource:
            create = unwrapped
        arguments = {"messages": []} if api == "chat" else {"input": "hello"}
        completion = create(model="cost-test", **arguments)
    tokens = create_token_usage(completion.usage, "cost-test")

    apply_model_costs(tokens, _model())

    valid_details = details is Ellipsis or details is None or isinstance(details, dict)
    assert tokens.usage_reported is valid_details
    if cost is not None:
        assert tokens.total_cost_usd == cost
        assert tokens.cost_source == "PROVIDER"
    elif valid_details:
        assert tokens.total_cost_usd == pytest.approx(0.00208)
        assert tokens.cost_source == "CONFIGURATION"
    else:
        assert tokens.total_cost_usd is None
        assert tokens.cost_source is None


@pytest.mark.parametrize(
    "counts, reported, expected_cost",
    [
        ({}, False, None),
        ({"prompt_eval_count": 0}, False, None),
        ({"eval_count": 0}, False, None),
        ({"prompt_eval_count": None, "eval_count": 0}, False, None),
        ({"prompt_eval_count": 0, "eval_count": 0}, True, 0),
        ({"prompt_eval_count": 5, "eval_count": 2}, True, 0.000026),
    ],
)
def test_actual_ollama_response_preserves_missing_and_zero_usage(
    monkeypatch, counts, reported, expected_cost
):
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "false")
    model = OllamaModel(
        id="cost-test", type="ollama", model="cost-test", host="http://cost.invalid"
    )
    model._client._client.close()
    response = {
        "model": "cost-test",
        "message": {"role": "assistant", "content": "answer"},
        **counts,
    }
    with httpx.Client(
        base_url="http://cost.invalid",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=response)
        ),
    ) as client:
        model._client._client = client
        message = model.chat([], CompletionArguments(), None)

    tokens = message.token_usage
    apply_model_costs(tokens, _model())

    assert tokens.usage_reported is reported
    if expected_cost is None:
        assert tokens.total_cost_usd is None
    else:
        assert tokens.total_cost_usd == pytest.approx(expected_cost)
    assert tokens.cost_source == ("CONFIGURATION" if reported else None)


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
