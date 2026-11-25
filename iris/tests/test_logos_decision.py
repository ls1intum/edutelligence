"""Exercise the real native decision client against an in-memory HTTP transport."""

# pylint: disable=protected-access  # Close the configured test client without sending requests.

import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import yaml
from pydantic import ValidationError

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.llm.external.logos_decision import LogosDecisionModel, SystemOneResponse
from iris.llm.llm_manager import LlmList
from iris.llm.request_handler import llm_request_handler

MODEL = "autotrust/JEV-27B-VL"


def test_example_profile_registers_the_exact_jev_model():
    config = yaml.safe_load(
        (Path(__file__).parent.parent / "llm_config.example.yml").read_text()
    )
    entry = next(item for item in config if item["id"] == "logos-jev-27b-vl")
    model = LlmList(llms=[entry]).llms[0]
    try:
        assert isinstance(model, LogosDecisionModel)
        assert model.model == MODEL
    finally:
        model._client.close()


@pytest.fixture
def model_factory(monkeypatch):
    client_type = httpx.Client
    clients = []

    def create(handler):
        def client(**kwargs):
            instance = client_type(transport=httpx.MockTransport(handler), **kwargs)
            clients.append(instance)
            return instance

        monkeypatch.setattr("iris.llm.external.logos_decision.httpx.Client", client)
        return LogosDecisionModel(
            id="logos-jev-27b-vl",
            type="logos_decision",
            model=MODEL,
            base_url="https://logos.example/v1",
            api_key="synthetic-test-key",  # pragma: allowlist secret
        )

    yield create
    for client in clients:
        client.close()


def answer(probability=0.9):
    return {
        "model": MODEL,
        "answers": {"decision": {"type": "noul", "noul": probability}},
        "usage": {"input_tokens": 123, "output_tokens": 1},
    }


def test_sends_one_native_noul_request_and_keeps_usage(model_factory):
    requests = []

    def route(request):
        requests.append(request)
        assert str(request.url) == "https://logos.example/v1/systemone"
        assert request.headers["Authorization"] == "Bearer synthetic-test-key"
        payload = json.loads(request.content)
        assert payload == {
            "model": MODEL,
            "state": "entire synthetic chat",
            "questions": {
                "decision": {
                    "type": "noul",
                    "instructions": "Is the latest message a solution request?",
                }
            },
        }
        return httpx.Response(200, json=answer())

    model = model_factory(route)
    result = model.decide(
        "entire synthetic chat", "Is the latest message a solution request?"
    )
    assert len(requests) == 1
    assert result.probability == 0.9
    assert result.token_usage.model_info == MODEL
    assert result.token_usage.num_input_tokens == 123
    assert result.token_usage.num_output_tokens == 1
    assert result.token_usage.usage_reported
    assert "synthetic-test-key" not in repr(model)
    assert "api_key" not in model.model_dump()


@pytest.mark.parametrize("probability", [-0.1, 1.1, True, "0.9", float("inf")])
def test_rejects_invalid_yes_probabilities(probability):
    # Infinity is malformed JSON, so exercise the Pydantic response model directly for that case.
    with pytest.raises(ValidationError):
        SystemOneResponse.model_validate(answer(probability))


@pytest.mark.parametrize("failure", ["missing-answer", "wrong-model", "wrong-type"])
def test_rejects_mismatched_protocol_responses(model_factory, failure):
    body = answer()
    if failure == "missing-answer":
        body["answers"] = {}
    elif failure == "wrong-model":
        body["model"] = "another-model"
    else:
        body["answers"]["decision"]["type"] = "choice"
    model = model_factory(lambda _request: httpx.Response(200, json=body))
    with pytest.raises(ValueError):
        model.decide("chat", "question")


def test_absent_usage_is_not_claimed_as_reported_zero_usage(model_factory):
    body = answer()
    del body["usage"]
    model = model_factory(lambda _request: httpx.Response(200, json=body))
    assert not model.decide("chat", "question").token_usage.usage_reported


def test_timeout_is_not_retried(model_factory):
    calls = []

    def route(request):
        calls.append(request)
        raise httpx.ReadTimeout("Synthetic timeout", request=request)

    model = model_factory(route)
    with pytest.raises(httpx.ReadTimeout):
        model.decide("chat", "question")
    assert len(calls) == 1


def test_request_handler_dispatches_to_the_native_model(model_factory, monkeypatch):
    model = model_factory(lambda _request: httpx.Response(200, json=answer()))
    monkeypatch.setattr(
        llm_request_handler, "LlmManager", lambda: SimpleNamespace(entries=[model])
    )
    handler = llm_request_handler.LlmRequestHandler(model_id=model.id)
    assert handler.supports_decisions()
    assert handler.decide("chat", "question").probability == 0.9
