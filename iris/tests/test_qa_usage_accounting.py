# pylint: disable=unused-import

import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

import iris.pipeline.pipeline  # noqa: F401 - establishes repo import order
from iris.common.pyris_message import IrisMessageRole, PyrisMessage
from iris.common.token_usage_dto import TokenUsageDTO
from iris.llm import CompletionArguments
from iris.llm.external.model import ChatModel
from iris.llm.request_handler.llm_request_handler import LlmRequestHandler
from iris.qa.cost import SpendLedger
from iris.qa.run import _reconcile_usage


def test_request_handler_fsyncs_qa_usage_after_each_provider_call(
    tmp_path, monkeypatch
):
    log = tmp_path / "usage.jsonl"
    ledger = tmp_path / "spend.jsonl"
    monkeypatch.setenv("IRIS_QA_PROVIDER_USAGE_LOG", str(log))
    monkeypatch.setenv("IRIS_QA_SPEND_LEDGER", str(ledger))
    monkeypatch.setenv(
        "IRIS_QA_SPEND_RATES",
        json.dumps({"gpt-5.4-mini": {"input": "1.00", "output": "2.00"}}),
    )
    monkeypatch.setenv("IRIS_QA_SPEND_HARD_LIMIT_USD", "30")
    monkeypatch.setenv("IRIS_QA_SPEND_RUN_ID", "run-1")
    monkeypatch.setenv("IRIS_QA_SPEND_SCENARIO_ID", "scenario-1")
    monkeypatch.setenv("IRIS_QA_SPEND_PIPELINE", "provider-call")
    model = Mock(spec=ChatModel)
    model.id = "qa-mini"
    model.model = "gpt-5.4-mini"
    model.cost_per_million_input_token = 1
    model.cost_per_million_output_token = 2
    model.chat.return_value = PyrisMessage(
        sender=IrisMessageRole.ASSISTANT,
        contents=[],
        token_usage=TokenUsageDTO(numInputTokens=123, numOutputTokens=45),
    )
    manager = Mock(entries=[model])
    with patch(
        "iris.llm.request_handler.llm_request_handler.LlmManager",
        return_value=manager,
    ):
        handler = LlmRequestHandler("qa-mini")

    handler.chat([], CompletionArguments(), None)

    record = json.loads(log.read_text(encoding="utf-8"))
    assert record == {
        "input_tokens": 123,
        "model": "gpt-5.4-mini",
        "output_tokens": 45,
        "recorded_at": record["recorded_at"],
    }
    spend = SpendLedger(ledger).records()
    assert len(spend) == 1
    assert spend[0].run_id == "run-1"
    assert spend[0].scenario_id == "scenario-1"
    assert spend[0].input_tokens == 123
    assert spend[0].output_tokens == 45


def test_usage_is_recorded_before_total_ceiling_failure(tmp_path, monkeypatch):
    log = tmp_path / "usage.jsonl"
    monkeypatch.setenv("IRIS_QA_PROVIDER_USAGE_LOG", str(log))
    monkeypatch.setenv("IRIS_QA_MAX_TOTAL_INPUT_TOKENS", "100")
    model = Mock(spec=ChatModel)
    model.id = "qa-mini"
    model.model = "gpt-5.4-mini"
    model.cost_per_million_input_token = 1
    model.cost_per_million_output_token = 2
    model.chat.return_value = PyrisMessage(
        sender=IrisMessageRole.ASSISTANT,
        contents=[],
        token_usage=TokenUsageDTO(numInputTokens=123, numOutputTokens=45),
    )
    manager = Mock(entries=[model])
    with patch(
        "iris.llm.request_handler.llm_request_handler.LlmManager",
        return_value=manager,
    ):
        handler = LlmRequestHandler("qa-mini")

    with pytest.raises(RuntimeError, match="total input token ceiling"):
        handler.chat([], CompletionArguments(), None)
    assert json.loads(log.read_text(encoding="utf-8"))["input_tokens"] == 123


def test_rejected_billable_response_is_recorded_before_error_propagates(
    tmp_path, monkeypatch
):
    log = tmp_path / "usage.jsonl"
    monkeypatch.setenv("IRIS_QA_PROVIDER_USAGE_LOG", str(log))
    model = Mock(spec=ChatModel)
    model.id = "qa-mini"
    model.model = "gpt-5.4-mini"
    rejected = RuntimeError("completion was truncated")
    rejected.qa_token_usage = TokenUsageDTO(  # type: ignore[attr-defined]
        numInputTokens=200,
        numOutputTokens=100,
    )
    model.chat.side_effect = rejected
    manager = Mock(entries=[model])
    with patch(
        "iris.llm.request_handler.llm_request_handler.LlmManager",
        return_value=manager,
    ):
        handler = LlmRequestHandler("qa-mini")

    with pytest.raises(RuntimeError, match="truncated"):
        handler.chat([], CompletionArguments(), None)

    record = json.loads(log.read_text(encoding="utf-8"))
    assert record["model"] == "gpt-5.4-mini"
    assert record["input_tokens"] == 200
    assert record["output_tokens"] == 100


def test_parent_reconciliation_accepts_parallel_usage_in_either_order():
    direct = [
        SimpleNamespace(
            run_id="run-1",
            scenario_id="scenario-1",
            model="gpt-5.4-mini",
            input_tokens=100,
            output_tokens=20,
        ),
        SimpleNamespace(
            run_id="run-1",
            scenario_id="scenario-1",
            model="gpt-5.4",
            input_tokens=200,
            output_tokens=40,
        ),
    ]
    usage = [
        {"model": "gpt-5.4", "input_tokens": 200, "output_tokens": 40},
        {"model": "gpt-5.4-mini", "input_tokens": 100, "output_tokens": 20},
    ]
    guard = Mock()

    _reconcile_usage(
        usage=usage,
        direct_records=direct,
        guard=guard,
        rate_card=None,
        run_id="run-1",
        scenario_id="scenario-1",
    )

    guard.record_usage.assert_not_called()
