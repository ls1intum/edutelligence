import json
import subprocess
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from iris.qa.calibration import assess_calibration, load_calibration, run_calibration
from iris.qa.cost import ModelRate, SpendLedger
from iris.qa.loader import load_suite
from iris.qa.worker import _judge_policy_facts

QA_ROOT = Path(__file__).parents[1] / "qa"


def test_human_labeled_judge_calibration_has_fourteen_valid_cases():
    suite = load_suite(
        QA_ROOT / "scenarios", QA_ROOT / "fixtures", QA_ROOT / "artifacts"
    )
    cases = load_calibration(
        QA_ROOT / "calibration" / "judge-sample.yml", suite.scenarios
    )
    assert len(cases) == 14
    no_metrics = next(case for case in cases if case.id == "course-greeting-pass")
    assert no_metrics.activities == []
    global_pass = next(case for case in cases if case.id == "global-search-pass")
    assert len(global_pass.diagnostics["sources"]) == 1


def test_calibration_policy_context_keeps_course_planning_rule_scoped():
    suite = load_suite(
        QA_ROOT / "scenarios", QA_ROOT / "fixtures", QA_ROOT / "artifacts"
    )
    cases = load_calibration(
        QA_ROOT / "calibration" / "judge-sample.yml", suite.scenarios
    )
    course_planning = next(
        case
        for case in cases
        if case.scenario.mode == "COURSE_CHAT"
        and "get_competency_list" in case.scenario.expectations.required_tools
    )
    lecture = next(
        case
        for case in cases
        if case.scenario.mode == "LECTURE_CHAT"
        and case.scenario.support_level == "moderate"
    )
    tutor = next(
        case for case in cases if case.scenario.use_case.value == "tutor_suggestion"
    )
    course_faq = next(
        scenario
        for scenario in suite.scenarios
        if scenario.mode == "COURSE_CHAT"
        and scenario.support_level == "low"
        and "grace period" in str(scenario.payload.get("chatHistory"))
    )
    calibrated_low_pedagogical = [
        case.scenario
        for case in cases
        if case.scenario.use_case.value == "chat"
        and case.scenario.support_level == "low"
    ]

    assert "nearSoftDueDateAttentionRule" in _judge_policy_facts(
        course_planning.scenario
    )
    assert "nearSoftDueDateAttentionRule" not in _judge_policy_facts(lecture.scenario)
    assert not _judge_policy_facts(tutor.scenario)
    assert set(_judge_policy_facts(course_faq)) == {
        "lowSupportOfficialLogisticsException"
    }
    assert calibrated_low_pedagogical
    assert all(
        "lowSupportTaskSpecificRule" in _judge_policy_facts(scenario)
        and "lowSupportOfficialLogisticsException" not in _judge_policy_facts(scenario)
        for scenario in calibrated_low_pedagogical
    )


def test_calibration_assessment_gates_criterion_and_case_accuracy():
    suite = load_suite(
        QA_ROOT / "scenarios", QA_ROOT / "fixtures", QA_ROOT / "artifacts"
    )
    cases = load_calibration(
        QA_ROOT / "calibration" / "judge-sample.yml", suite.scenarios
    )
    scores = {
        case.id: {
            criterion: (low + high) / 2
            for criterion, (low, high) in case.expected.items()
        }
        for case in cases
    }
    result = assess_calibration(cases, scores)
    assert result["passed"]
    assert result["criterionAccuracy"] == 1
    assert result["caseAccuracy"] == 1
    assert result["details"][0]["expected"]


def test_failed_calibration_worker_records_flushed_billable_usage(tmp_path):
    ledger_path = tmp_path / "ledger.jsonl"
    judge_rate = ModelRate(
        "gpt-5.4",
        input_per_million=Decimal(1),
        output_per_million=Decimal(1),
    )
    rate_card = SimpleNamespace(judge=judge_rate)
    config = SimpleNamespace(environment={}, close=Mock())
    scenario = Mock()
    scenario.model_dump.return_value = {}
    case = SimpleNamespace(
        id="calibration-case",
        scenario=scenario,
        answer="answer",
        activities=[],
        diagnostics={},
    )

    def failed_worker(*_args, **kwargs):
        usage_path = Path(kwargs["env"]["IRIS_QA_PROVIDER_USAGE_LOG"])
        usage_path.write_text(
            json.dumps(
                {
                    "model": "gpt-5.4",
                    "input_tokens": 100,
                    "output_tokens": 20,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=1, stderr="judge output parse failed")

    with (
        patch(
            "iris.qa.bootstrap.create_worker_configuration",
            return_value=config,
        ),
        patch("iris.qa.calibration.subprocess.run", side_effect=failed_worker),
        pytest.raises(RuntimeError, match="judge output parse failed"),
    ):
        run_calibration(
            cases=[case],
            rate_card=rate_card,
            ledger_path=ledger_path,
            hard_limit=Decimal(30),
            max_cost=Decimal(1),
            output=tmp_path / "calibration.json",
        )

    assert SpendLedger(ledger_path).total() == judge_rate.cost(100, 20)
    config.close.assert_called_once()


def test_timed_out_calibration_reserves_unreported_judge_call(tmp_path):
    ledger_path = tmp_path / "ledger.jsonl"
    judge_rate = ModelRate(
        "gpt-5.4",
        input_per_million=Decimal(1),
        output_per_million=Decimal(1),
    )
    rate_card = SimpleNamespace(judge=judge_rate)
    config = SimpleNamespace(environment={}, close=Mock())
    scenario = Mock()
    scenario.model_dump.return_value = {}
    case = SimpleNamespace(
        id="calibration-timeout",
        scenario=scenario,
        answer="answer",
        activities=[],
        diagnostics={},
    )

    with (
        patch(
            "iris.qa.bootstrap.create_worker_configuration",
            return_value=config,
        ),
        patch(
            "iris.qa.calibration.subprocess.run",
            side_effect=subprocess.TimeoutExpired("judge", 300),
        ),
        pytest.raises(RuntimeError, match="timed out"),
    ):
        run_calibration(
            cases=[case],
            rate_card=rate_card,
            ledger_path=ledger_path,
            hard_limit=Decimal(30),
            max_cost=Decimal(1),
            output=tmp_path / "calibration.json",
        )

    records = SpendLedger(ledger_path).records()
    assert len(records) == 1
    assert records[0].reservation is True
    assert Decimal(records[0].cost_usd) == judge_rate.cost(2500, 1600)
    config.close.assert_called_once()
