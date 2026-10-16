from __future__ import annotations

import importlib
import json
import subprocess
import threading
from collections import Counter
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from iris.qa.cost import BudgetExceeded, BudgetGuard, ModelRate, SpendLedger
from iris.qa.evaluate import Rating, evaluation_from_worker
from iris.qa.loader import load_suite
from iris.qa.planning import build_cost_plan, trial_reserve
from iris.qa.report import report_payload
from iris.qa.run import run_paid_suite, trial_stem
from iris.qa.schema import Scenario, TokenCeiling
from iris.qa.worker import (
    _extract_callback,
    _judge_answer,
    _ScenarioRequestBudget,
)

QA_ROOT = Path(__file__).parents[1] / "qa"


def _scenario() -> Scenario:
    return Scenario.model_validate(
        {
            "id": "simple-example",
            "title": "A simple benchmark example",
            "description": "The answer should help the student take the next step.",
            "use_case": "chat",
            "mode": "COURSE_CHAT",
            "support_level": "moderate",
            "payload": {},
            "criteria": [
                {"id": "grounding", "description": "Uses only supplied evidence."},
                {"id": "pedagogy", "description": "Matches the support level."},
                {"id": "next_step", "description": "Leaves a useful next action."},
            ],
            "critical_errors": ["The answer invents facts not in the evidence."],
        }
    )


def _rate_card():
    return SimpleNamespace(
        candidates=(ModelRate("gpt-5.4-mini", Decimal("0.75"), Decimal("4.5")),),
        judge=ModelRate("gpt-5.4", Decimal("2.5"), Decimal("15")),
        auxiliary=ModelRate("gpt-5.4-mini", Decimal("0.75"), Decimal("4.5")),
        source="test rates",
    )


def test_request_budget_caps_each_call_and_agent_iterations(monkeypatch):
    importlib.import_module("iris.pipeline.pipeline")
    # pylint: disable=import-outside-toplevel
    from iris.llm import CompletionArguments
    from iris.llm.request_handler.llm_request_handler import (
        LlmRequestHandler,
    )

    # pylint: enable=import-outside-toplevel

    usage = iter(((100, 80), (100, 70)))

    def fake_chat(handler, messages, arguments, tools):
        del handler, messages, arguments, tools
        input_tokens, output_tokens = next(usage)
        return SimpleNamespace(
            token_usage=SimpleNamespace(
                num_input_tokens=input_tokens,
                num_output_tokens=output_tokens,
            )
        )

    executor_arguments = {}

    def fake_executor(*_args, **kwargs):
        executor_arguments.update(kwargs)
        return object()

    monkeypatch.setattr(LlmRequestHandler, "chat", fake_chat)
    from iris.pipeline import (  # pylint: disable=import-outside-toplevel
        abstract_agent_pipeline,
    )

    monkeypatch.setattr(abstract_agent_pipeline, "AgentExecutor", fake_executor)
    ceiling = TokenCeiling(
        max_agent_turns=2,
        max_input_tokens=10_000,
        max_output_tokens=150,
        max_output_tokens_per_call=100,
    )
    with _ScenarioRequestBudget(ceiling):
        first = CompletionArguments()
        LlmRequestHandler.chat(object(), [{"text": "first"}], first, None)
        assert first.max_tokens == 100

        second = CompletionArguments()
        LlmRequestHandler.chat(object(), [{"text": "second"}], second, None)
        assert second.max_tokens == 70

        with pytest.raises(RuntimeError, match="output-token limit"):
            LlmRequestHandler.chat(
                object(), [{"text": "third"}], CompletionArguments(), None
            )
        abstract_agent_pipeline.AgentExecutor(agent=object(), tools=[])

    assert executor_arguments["max_iterations"] == 2


def test_request_budget_reserves_concurrent_output_capacity(monkeypatch):
    importlib.import_module("iris.pipeline.pipeline")
    # pylint: disable=import-outside-toplevel
    from iris.llm import CompletionArguments
    from iris.llm.request_handler.llm_request_handler import (
        LlmRequestHandler,
    )

    # pylint: enable=import-outside-toplevel

    barrier = threading.Barrier(2)
    limits = []
    errors = []

    def fake_chat(handler, messages, arguments, tools):
        del handler, messages, tools
        limits.append(arguments.max_tokens)
        barrier.wait(timeout=2)
        return SimpleNamespace(
            token_usage=SimpleNamespace(
                num_input_tokens=100,
                num_output_tokens=arguments.max_tokens,
            )
        )

    def invoke():
        try:
            LlmRequestHandler.chat(
                object(), [{"text": "parallel"}], CompletionArguments(), None
            )
        except Exception as error:  # pragma: no cover - assertion reports detail
            errors.append(error)

    monkeypatch.setattr(LlmRequestHandler, "chat", fake_chat)
    ceiling = TokenCeiling(
        max_agent_turns=2,
        max_input_tokens=10_000,
        max_output_tokens=150,
        max_output_tokens_per_call=100,
    )
    with _ScenarioRequestBudget(ceiling):
        threads = [threading.Thread(target=invoke) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=3)

    assert not errors
    assert sorted(limits) == [50, 100]


def test_request_budget_keeps_ambiguous_failed_call_reserved(monkeypatch):
    importlib.import_module("iris.pipeline.pipeline")
    # pylint: disable=import-outside-toplevel
    from iris.llm import CompletionArguments
    from iris.llm.request_handler.llm_request_handler import (
        LlmRequestHandler,
    )

    # pylint: enable=import-outside-toplevel

    def failed_chat(handler, messages, arguments, tools):
        del handler, messages, arguments, tools
        raise RuntimeError("provider connection closed")

    monkeypatch.setattr(LlmRequestHandler, "chat", failed_chat)
    ceiling = TokenCeiling(
        max_agent_turns=2,
        max_input_tokens=10_000,
        max_output_tokens=150,
        max_output_tokens_per_call=100,
    )
    budget = _ScenarioRequestBudget(ceiling)
    with budget:
        with pytest.raises(RuntimeError, match="provider connection closed"):
            LlmRequestHandler.chat(
                object(), [{"text": "first"}], CompletionArguments(), None
            )
        with pytest.raises(RuntimeError, match="usage is ambiguous"):
            LlmRequestHandler.chat(
                object(), [{"text": "second"}], CompletionArguments(), None
            )

    with pytest.raises(RuntimeError, match="usage is ambiguous"):
        budget.raise_if_failed()


def test_paid_run_records_reservation_before_worker_timeout(tmp_path, monkeypatch):
    scenario = _scenario()
    rate_card = _rate_card()
    ledger = SpendLedger(tmp_path / "spend.jsonl")

    monkeypatch.setattr(
        "iris.qa.run.create_worker_configuration",
        lambda *_args: SimpleNamespace(environment={}, close=lambda: None),
    )

    def timeout(*_args, **_kwargs):
        records = ledger.records()
        assert len(records) == 1
        assert records[0].reservation is True
        raise subprocess.TimeoutExpired("worker", 900)

    monkeypatch.setattr("iris.qa.run.subprocess.run", timeout)
    with pytest.raises(subprocess.TimeoutExpired):
        run_paid_suite(
            qa_root=tmp_path / "qa",
            scenarios=[scenario],
            models=("gpt-5.4-mini",),
            repetitions=1,
            rate_card=rate_card,
            ledger=ledger,
            hard_limit=Decimal("30"),
            max_run_cost=Decimal("30"),
            planned_cost=Decimal("1"),
            output_root=tmp_path / "timeout-run",
        )

    assert ledger.records()[0].reservation is True


def test_verified_usage_atomically_replaces_reservation(tmp_path):
    ledger = SpendLedger(tmp_path / "spend.jsonl")
    guard = BudgetGuard(ledger, Decimal("30"))
    rate = ModelRate("gpt-5.4-mini", Decimal("1"), Decimal("2"))
    reservation = guard.record_reservation(
        run_id="run",
        scenario_id="scenario",
        pipeline="trial-upper-bound",
        model=rate.model,
        cost_usd=Decimal("1"),
    )
    assert ledger.has_reservation(
        run_id="run", scenario_id="scenario", pipeline="trial-upper-bound"
    )

    guard.reconcile_reservation(
        reservation=reservation,
        usage=[("chat", rate, 100, 50)],
    )

    records = ledger.records()
    assert len(records) == 1
    assert records[0].reservation is False
    assert records[0].input_tokens == 100
    assert ledger.total() == Decimal("0.00020000")
    assert not ledger.has_reservation(
        run_id="run", scenario_id="scenario", pipeline="trial-upper-bound"
    )


def test_verified_overspend_replaces_lower_reservation_before_stopping(tmp_path):
    ledger = SpendLedger(tmp_path / "spend.jsonl")
    guard = BudgetGuard(ledger, Decimal("30"))
    rate = ModelRate("gpt-5.4-mini", Decimal("1"), Decimal("2"))
    reservation = guard.record_reservation(
        run_id="run",
        scenario_id="scenario",
        pipeline="trial-upper-bound",
        model=rate.model,
        cost_usd=Decimal("0.0001"),
    )

    with pytest.raises(BudgetExceeded, match="exceeds reserved upper bound"):
        guard.reconcile_reservation(
            reservation=reservation,
            usage=[("chat", rate, 100, 50)],
        )

    records = ledger.records()
    assert len(records) == 1
    assert records[0].reservation is False
    assert ledger.total() == Decimal("0.00020000")


def test_failed_judge_keeps_full_trial_reservation(tmp_path, monkeypatch):
    scenario = _scenario()
    rate_card = _rate_card()
    ledger = SpendLedger(tmp_path / "spend.jsonl")

    monkeypatch.setattr(
        "iris.qa.run.create_worker_configuration",
        lambda *_args: SimpleNamespace(environment={}, close=lambda: None),
    )
    monkeypatch.setattr("iris.qa.run._git_value", lambda *_args: "test")

    def failed_judge(args, **_kwargs):
        output = Path(args[args.index("--output") + 1])
        output.write_text(
            json.dumps(
                {
                    "response": "Candidate answer",
                    "activities": [],
                    "usage": [
                        {
                            "model": "gpt-5.4-mini",
                            "pipeline": "chat",
                            "inputTokens": 100,
                            "outputTokens": 50,
                            "costUsd": 0.0003,
                        }
                    ],
                    "judge": {},
                    "executionError": "Judge failed",
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(args, 1, "", "")

    monkeypatch.setattr("iris.qa.run.subprocess.run", failed_judge)
    code, _, _ = run_paid_suite(
        qa_root=tmp_path / "qa",
        scenarios=[scenario],
        models=("gpt-5.4-mini",),
        repetitions=1,
        rate_card=rate_card,
        ledger=ledger,
        hard_limit=Decimal("30"),
        max_run_cost=Decimal("30"),
        planned_cost=trial_reserve(scenario, rate_card, "gpt-5.4-mini"),
        output_root=tmp_path / "failed-judge-run",
    )

    assert code == 1
    records = ledger.records()
    assert len(records) == 1
    assert records[0].reservation is True


def test_corpus_has_fifty_scenarios_and_explicit_mode_support_matrix():
    suite = load_suite(
        QA_ROOT / "scenarios", QA_ROOT / "fixtures", QA_ROOT / "artifacts"
    )
    assert len(suite.scenarios) == 50
    assert all(3 <= len(scenario.criteria) <= 5 for scenario in suite.scenarios)
    assert all(not hasattr(scenario, "expectations") for scenario in suite.scenarios)
    chat = [
        scenario for scenario in suite.scenarios if scenario.use_case.value == "chat"
    ]
    assert Counter(scenario.mode for scenario in chat) == {
        "PROGRAMMING_EXERCISE_CHAT": 12,
        "COURSE_CHAT": 10,
        "LECTURE_CHAT": 10,
        "TEXT_EXERCISE_CHAT": 10,
    }
    assert Counter(scenario.support_level for scenario in chat) == {
        "low": 14,
        "moderate": 14,
        "high": 14,
    }
    assert len({(scenario.mode, scenario.support_level) for scenario in chat}) == 12


def test_advanced_cases_are_distinct_and_use_five_plain_language_criteria():
    suite = load_suite(
        QA_ROOT / "scenarios", QA_ROOT / "fixtures", QA_ROOT / "artifacts"
    )
    advanced = [
        scenario for scenario in suite.scenarios if scenario.difficulty == "advanced"
    ]
    assert len(advanced) == 22
    assert all(len(scenario.criteria) == 5 for scenario in advanced)
    assert len({tuple(scenario.fixtures) for scenario in advanced}) == len(advanced)
    assert {
        scenario.mode for scenario in advanced if scenario.use_case.value == "chat"
    } == {
        "COURSE_CHAT",
        "LECTURE_CHAT",
        "PROGRAMMING_EXERCISE_CHAT",
        "TEXT_EXERCISE_CHAT",
    }


def test_callback_evidence_keeps_autonomous_confidence():
    callback = SimpleNamespace(
        payloads=[
            {
                "runState": "FINISHED",
                "result": "Grounded answer",
                "confidence": 0.87,
                "tokens": [],
            }
        ],
        activities=[],
        failure_exception=None,
    )

    response, activities, terminal, artifacts = _extract_callback(
        callback, "autonomous_tutor"
    )

    assert response == "Grounded answer"
    assert activities == []
    assert terminal["runState"] == "FINISHED"
    assert artifacts["confidence"] == 0.87


def test_callback_evaluates_tutor_artifact_instead_of_acknowledgement_reply():
    callback = SimpleNamespace(
        payloads=[
            {
                "runState": "FINISHED",
                "result": "Ask if you would like more help.",
                "artifact": "<ul><li>Trace the failed state transition.</li></ul>",
                "tokens": [],
            }
        ],
        activities=[],
        failure_exception=None,
    )

    response, _, _, artifacts = _extract_callback(callback, "tutor_suggestion")

    assert response == "<ul><li>Trace the failed state transition.</li></ul>"
    assert artifacts["reply"] == "Ask if you would like more help."
    assert artifacts["artifact"] == response


def test_judge_receives_long_candidate_answer_without_middle_clipping():
    response = "first criterion\n" + ("detail " * 1_000) + "\nlast criterion"

    judged, truncated = _judge_answer(response)

    assert judged == response
    assert truncated is False


def test_trial_filename_sanitizes_openai_compatible_model_id():
    stem = trial_stem("openai/gpt-oss-120b", "tutor-workbook-investigation", 2)

    assert stem == "openai-gpt-oss-120b-tutor-workbook-investigation-r2"
    assert "/" not in stem


def test_report_includes_difficulty_breakdown():
    scenario = _scenario()
    evaluation = evaluation_from_worker(
        scenario,
        model="gpt-5.4-mini",
        repetition=1,
        duration_seconds=1,
        payload={
            "response": "answer",
            "activities": [],
            "usage": [],
            "judge": {
                "criteria": [
                    {"id": item, "rating": "achieved", "evidence": "evidence"}
                    for item in ("grounding", "pedagogy", "next_step")
                ],
                "criticalErrors": [
                    {
                        "description": scenario.critical_errors[0],
                        "present": False,
                        "evidence": "none",
                    }
                ],
            },
        },
    )
    assert report_payload([evaluation])["breakdowns"]["difficulty"] == [
        {
            "model": "gpt-5.4-mini",
            "group": "foundation",
            "scenarios": 1,
            "score": 100,
            "ci95Low": 100,
            "ci95High": 100,
        }
    ]


def test_score_maps_categorical_judgements_and_keeps_critical_errors_separate():
    scenario = _scenario()
    evaluation = evaluation_from_worker(
        scenario,
        model="gpt-5.4-mini",
        repetition=1,
        duration_seconds=1.2,
        payload={
            "response": "Try tracing the first branch.",
            "activities": [{"name": "get_exercise_list", "state": "FINISHED"}],
            "usage": [],
            "judge": {
                "criteria": [
                    {
                        "id": "grounding",
                        "rating": "achieved",
                        "evidence": "Evidence used.",
                    },
                    {
                        "id": "pedagogy",
                        "rating": "partly_achieved",
                        "evidence": "Some guidance.",
                    },
                    {
                        "id": "next_step",
                        "rating": "not_achieved",
                        "evidence": "No concrete step.",
                    },
                ],
                "criticalErrors": [
                    {
                        "description": scenario.critical_errors[0],
                        "present": False,
                        "evidence": "No invented fact found.",
                    }
                ],
            },
        },
    )
    assert evaluation.score == 50
    assert evaluation.criteria[0].rating == Rating.ACHIEVED
    assert evaluation.critical_error_count == 0


def test_report_averages_repetitions_before_model_score():
    scenario = _scenario()
    evaluations = []
    for repetition, rating in ((1, "achieved"), (2, "not_achieved")):
        evaluations.append(
            evaluation_from_worker(
                scenario,
                model="gpt-5.4-mini",
                repetition=repetition,
                duration_seconds=1,
                payload={
                    "response": "answer",
                    "activities": [],
                    "usage": [],
                    "judge": {
                        "criteria": [
                            {"id": item, "rating": rating, "evidence": "evidence"}
                            for item in ("grounding", "pedagogy", "next_step")
                        ],
                        "criticalErrors": [
                            {
                                "description": scenario.critical_errors[0],
                                "present": False,
                                "evidence": "none",
                            }
                        ],
                    },
                },
            )
        )
    model = report_payload(evaluations)["summary"]["models"]["gpt-5.4-mini"]
    assert model["score"] == 50
    assert model["repeatedScenarios"] == 1
    assert model["meanRepeatSpan"] == 100
    assert model["maxRepeatSpan"] == 100


def test_cost_plan_is_visible_and_budget_aware(tmp_path):
    scenario = _scenario()
    card = type(
        "RateCard",
        (),
        {
            "candidates": (
                ModelRate("gpt-5.4-mini", Decimal("0.75"), Decimal("4.5")),
                ModelRate("gpt-5.5", Decimal("5"), Decimal("30")),
            ),
            "judge": ModelRate("gpt-5.4", Decimal("2.5"), Decimal("15")),
            "auxiliary": ModelRate("gpt-5.4-mini", Decimal("0.75"), Decimal("4.5")),
            "source": "test rates",
        },
    )()
    plan = build_cost_plan(
        [scenario],
        card,
        repetitions=1,
        ledger=SpendLedger(tmp_path / "ledger.jsonl"),
        hard_limit=Decimal("30"),
        models=("gpt-5.4-mini",),
    )
    assert plan.planned_total > plan.judge_cost
    assert plan.remaining_after_plan > 0
