"""Check Athena accounting against real LangChain OpenAI response conversion."""

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from langchain_openai import ChatOpenAI


@pytest.fixture
def accounting(monkeypatch):
    # The callback's metadata sink does not need Athena's application, database
    # or Git integration. Only that sink is replaced; LangChain and the SDK run.
    metadata = {}
    athena = ModuleType("athena")
    athena.get_meta = lambda: metadata
    athena.emit_meta = metadata.__setitem__
    monkeypatch.setitem(sys.modules, "athena", athena)
    for name in os.environ:
        if name.startswith("LLM_DEFAULT_MODEL_COST_PER_MILLION_"):
            monkeypatch.delenv(name)
    path = Path(__file__).resolve().parents[1] / "llm_core/models/usage_handler.py"
    spec = importlib.util.spec_from_file_location("athena_usage_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.UsageHandler(), metadata


def _response(cost=0.001, currency="USD"):
    return {
        "id": "test",
        "object": "chat.completion",
        "created": 1,
        "model": "cost-test",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "answer"},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 2,
            "total_tokens": 12,
            "cost": cost,
            "cost_currency": currency,
        },
    }


@pytest.mark.parametrize("cost", [0, 0.001])
def test_actual_nonstreaming_langchain_callback_retains_provider_cost(accounting, cost):
    handler, metadata = accounting
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=_response(cost))
        )
    ) as client:
        model = ChatOpenAI(
            model="cost-test",
            api_key="test",
            base_url="http://cost.invalid/v1",
            http_client=client,
            callbacks=[handler],
        )
        result = model.invoke("hello")

    assert result.content == "answer"
    assert metadata["llmRequests"][0]["totalCostUsd"] == cost


@pytest.mark.parametrize(
    "cost, currency",
    [
        (-1, "USD"),
        (True, "USD"),
        ("bad", "USD"),
        ({"amount": 1}, "USD"),
        (1, "EUR"),
        (1, None),
    ],
)
def test_invalid_provider_cost_keeps_tokens_without_usd_amount(
    accounting, cost, currency
):
    handler, metadata = accounting
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=_response(cost, currency))
        )
    ) as client:
        model = ChatOpenAI(
            model="cost-test",
            api_key="test",
            base_url="http://cost.invalid/v1",
            http_client=client,
            callbacks=[handler],
        )
        model.invoke("hello")

    assert metadata["llmRequests"][0]["numInputTokens"] == 10
    assert metadata["llmRequests"][0]["totalCostUsd"] is None


def test_streaming_adapter_cost_loss_uses_explicit_usd_estimate(
    accounting, monkeypatch
):
    handler, metadata = accounting
    monkeypatch.setenv("LLM_DEFAULT_MODEL_COST_PER_MILLION_INPUT_TOKEN_USD", "2")
    monkeypatch.setenv("LLM_DEFAULT_MODEL_COST_PER_MILLION_OUTPUT_TOKEN_USD", "8")
    chunks = [
        {
            "id": "test",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "cost-test",
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": "answer"},
                    "finish_reason": "stop",
                }
            ],
        },
        {
            "id": "test",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "cost-test",
            "choices": [],
            "usage": _response()["usage"],
        },
    ]
    stream = (
        "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks)
        + "data: [DONE]\n\n"
    )
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, text=stream, headers={"content-type": "text/event-stream"}
            )
        )
    ) as client:
        model = ChatOpenAI(
            model="cost-test",
            api_key="test",
            base_url="http://cost.invalid/v1",
            http_client=client,
            callbacks=[handler],
            stream_usage=True,
        )
        list(model.stream("hello"))

    assert metadata["llmRequests"][0]["totalCostUsd"] == pytest.approx(0.000036)


def test_configured_usd_cache_estimate_needs_each_used_rate(accounting, monkeypatch):
    handler, metadata = accounting
    monkeypatch.setenv("LLM_DEFAULT_MODEL_COST_PER_MILLION_INPUT_TOKEN_USD", "2")
    monkeypatch.setenv("LLM_DEFAULT_MODEL_COST_PER_MILLION_OUTPUT_TOKEN_USD", "8")
    message = AIMessage(
        content="answer",
        usage_metadata={
            "input_tokens": 10,
            "output_tokens": 2,
            "total_tokens": 12,
            "input_token_details": {"cache_read": 4},
        },
    )
    response = LLMResult(generations=[[ChatGeneration(message=message)]])

    handler.on_llm_end(response)
    assert metadata["llmRequests"][0]["totalCostUsd"] is None

    monkeypatch.setenv(
        "LLM_DEFAULT_MODEL_COST_PER_MILLION_CACHED_INPUT_TOKEN_USD", "0.2"
    )
    handler.on_llm_end(response)
    assert metadata["llmRequests"][1]["totalCostUsd"] == pytest.approx(0.0000288)


@pytest.mark.parametrize("tier", ["default", "priority", "flex"])
@pytest.mark.parametrize("missing_rate", ["CACHED_INPUT", "CACHE_WRITE_INPUT", None])
@pytest.mark.parametrize(
    "cached, written, expected_cost", [(4, 1, 0.0000298), (None, None, 0.000036)]
)
def test_actual_langchain_tiered_cache_counts_use_each_configured_price(
    accounting, monkeypatch, tier, missing_rate, cached, written, expected_cost
):
    handler, metadata = accounting
    for name, rate in (
        ("INPUT", "2"),
        ("OUTPUT", "8"),
        ("CACHED_INPUT", "0.2"),
        ("CACHE_WRITE_INPUT", "3"),
    ):
        if name != missing_rate:
            monkeypatch.setenv(
                f"LLM_DEFAULT_MODEL_COST_PER_MILLION_{name}_TOKEN_USD", rate
            )
    response = _response(cost=None)
    response["service_tier"] = tier
    response["usage"]["prompt_tokens_details"] = {
        "cached_tokens": cached,
        "cache_write_tokens": written,
    }
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=response)
        )
    ) as client:
        model = ChatOpenAI(
            model="cost-test",
            api_key="test",
            base_url="http://cost.invalid/v1",
            http_client=client,
            callbacks=[handler],
        )
        result = model.invoke("hello")

    prefix = "" if tier == "default" else f"{tier}_"
    details = result.usage_metadata["input_token_details"]
    assert details.get(f"{prefix}cache_read") == cached
    assert details.get(f"{prefix}cache_creation") == written
    call = metadata["llmRequests"][0]
    if missing_rate and cached is not None:
        assert call["totalCostUsd"] is None
    else:
        assert call["totalCostUsd"] == pytest.approx(expected_cost)


def test_cache_estimate_sums_counts_across_service_tiers(accounting, monkeypatch):
    handler, metadata = accounting
    for name, rate in (
        ("INPUT", "2"),
        ("OUTPUT", "8"),
        ("CACHED_INPUT", "0.2"),
        ("CACHE_WRITE_INPUT", "3"),
    ):
        monkeypatch.setenv(f"LLM_DEFAULT_MODEL_COST_PER_MILLION_{name}_TOKEN_USD", rate)
    message = AIMessage(
        content="answer",
        usage_metadata={
            "input_tokens": 10,
            "output_tokens": 2,
            "total_tokens": 12,
            "input_token_details": {
                "cache_read": 1,
                "priority_cache_read": 2,
                "flex_cache_read": 1,
                "cache_creation": 0,
                "priority_cache_creation": 1,
                "flex_cache_creation": 1,
            },
        },
    )

    handler.on_llm_end(LLMResult(generations=[[ChatGeneration(message=message)]]))

    assert metadata["llmRequests"][0]["totalCostUsd"] == pytest.approx(0.0000308)


@pytest.mark.parametrize("cost", [0, 0.001, None])
def test_actual_multiple_choices_record_request_usage_once(
    accounting, monkeypatch, cost
):
    handler, metadata = accounting
    for suffix in ("", "_USD"):
        monkeypatch.setenv(
            f"LLM_DEFAULT_MODEL_COST_PER_MILLION_INPUT_TOKEN{suffix}", "2"
        )
        monkeypatch.setenv(
            f"LLM_DEFAULT_MODEL_COST_PER_MILLION_OUTPUT_TOKEN{suffix}", "8"
        )
    response = _response(cost)
    response["choices"].append(
        {
            "index": 1,
            "message": {"role": "assistant", "content": "alternative"},
            "finish_reason": "stop",
        }
    )
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=response)
        )
    ) as client:
        model = ChatOpenAI(
            model="cost-test",
            api_key="test",
            base_url="http://cost.invalid/v1",
            http_client=client,
            callbacks=[handler],
            n=2,
        )
        result = model.generate([[HumanMessage(content="hello")]])

    assert len(result.generations[0]) == 2
    assert len(metadata["llmRequests"]) == 1
    assert metadata["totalUsage"] == {
        "numInputTokens": 10,
        "numOutputTokens": 2,
        "numTotalTokens": 12,
        "cost": pytest.approx(0.000036),
    }
    call = metadata["llmRequests"][0]
    assert call["totalCostUsd"] == pytest.approx(0.000036 if cost is None else cost)


def test_request_group_uses_first_choice_with_usage(accounting):
    handler, metadata = accounting
    empty = ChatGeneration(message=AIMessage(content="no usage"))
    known = ChatGeneration(
        message=AIMessage(
            content="answer",
            usage_metadata={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
            response_metadata={"token_usage": _response()["usage"]},
        )
    )

    handler.on_llm_end(LLMResult(generations=[[empty, known, known], [known, known]]))

    assert len(metadata["llmRequests"]) == 2
    assert metadata["totalUsage"]["numInputTokens"] == 20
    assert metadata["totalUsage"]["numOutputTokens"] == 4
    assert all(call["totalCostUsd"] == 0.001 for call in metadata["llmRequests"])


def test_aggregate_native_usage_is_not_assigned_to_each_generation(accounting):
    handler, metadata = accounting
    message = AIMessage(
        content="answer",
        usage_metadata={
            "input_tokens": 10,
            "output_tokens": 2,
            "total_tokens": 12,
        },
    )
    handler.on_llm_end(
        LLMResult(
            generations=[
                [ChatGeneration(message=message)],
                [ChatGeneration(message=message)],
            ],
            llm_output={"token_usage": _response()["usage"]},
        )
    )

    assert len(metadata["llmRequests"]) == 2
    assert all(call["totalCostUsd"] is None for call in metadata["llmRequests"])
    assert metadata["totalUsage"]["numInputTokens"] == 20
    assert metadata["totalUsage"]["numOutputTokens"] == 4
    assert metadata["totalUsage"]["numTotalTokens"] == 24


def test_mismatched_native_counts_do_not_establish_a_provider_total(accounting):
    handler, metadata = accounting
    message = AIMessage(
        content="answer",
        usage_metadata={"input_tokens": 20, "output_tokens": 4, "total_tokens": 24},
    )

    handler.on_llm_end(
        LLMResult(
            generations=[[ChatGeneration(message=message)]],
            llm_output={"token_usage": _response()["usage"]},
        )
    )

    assert metadata["llmRequests"][0]["totalCostUsd"] is None


def test_legacy_estimate_bills_input_at_input_rate(accounting, monkeypatch):
    handler, metadata = accounting
    monkeypatch.setenv("LLM_DEFAULT_MODEL_COST_PER_MILLION_INPUT_TOKEN", "2")
    monkeypatch.setenv("LLM_DEFAULT_MODEL_COST_PER_MILLION_OUTPUT_TOKEN", "8")
    message = AIMessage(
        content="answer",
        usage_metadata={
            "input_tokens": 10,
            "output_tokens": 2,
            "total_tokens": 12,
        },
    )

    handler.on_llm_end(LLMResult(generations=[[ChatGeneration(message=message)]]))

    assert metadata["totalUsage"]["cost"] == pytest.approx(0.000036)
    assert metadata["llmRequests"][0]["totalCostUsd"] is None
