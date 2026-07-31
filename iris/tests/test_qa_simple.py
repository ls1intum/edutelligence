from __future__ import annotations

from collections import Counter
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from iris.qa.cost import ModelRate, SpendLedger
from iris.qa.evaluate import Rating, evaluation_from_worker
from iris.qa.loader import load_suite
from iris.qa.planning import build_cost_plan
from iris.qa.report import report_payload
from iris.qa.schema import Scenario
from iris.qa.worker import _extract_callback, _judge_answer

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
    assert len(advanced) == 20
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
            "activities": [
                {"name": "get_student_exercise_metrics", "state": "FINISHED"}
            ],
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
