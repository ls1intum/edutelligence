import json

import pytest

from iris.qa.baseline import approve_report, compare_baseline
from iris.qa.evaluate import CheckResult, ScenarioEvaluation


def _add_provenance(report: dict) -> dict:
    scenario_ids = {item["scenario_id"] for item in report["evaluations"]}
    report["metadata"].update(
        azureDeployments={
            model: {
                "deployment": f"{model}-deployment",
                "model": model,
                "version": "2026-07-13",
            }
            for model in ("gpt-5.4-mini", "gpt-5.5", "gpt-5.4")
        },
        scenarioSha256={scenario_id: "a" * 64 for scenario_id in scenario_ids},
        irisSourceSha256="b" * 64,
        rateSource="test Azure rate card",
    )
    return report


def _evaluation(score: float) -> ScenarioEvaluation:
    result = ScenarioEvaluation("scenario", "model", "answer", [])
    result.checks = [CheckResult("response", True, "ok")]
    result.semantic_scores = {"grounding": score}
    return result


def test_baseline_is_provisional_before_three_observations():
    regressions, provisional = compare_baseline(
        [_evaluation(0.5)],
        {"version": 1, "observations": {"scenario::model": [{"score": 0.9}] * 2}},
    )
    assert not regressions
    assert provisional == ["scenario::model"]


def test_baseline_requires_fixed_and_statistical_drop():
    baseline = {
        "version": 1,
        "observations": {
            "scenario::model": [
                {"score": 0.90, "criteria": {"grounding": 0.90}},
                {"score": 0.91, "criteria": {"grounding": 0.91}},
                {"score": 0.89, "criteria": {"grounding": 0.89}},
            ]
        },
    }
    regressions, provisional = compare_baseline([_evaluation(0.70)], baseline)
    assert not provisional
    assert {item.dimension for item in regressions} == {"overall", "grounding"}


def test_small_drop_does_not_trigger_regression():
    baseline = {
        "version": 1,
        "observations": {
            "scenario::model": [{"score": 0.90}, {"score": 0.91}, {"score": 0.89}]
        },
    }
    regressions, _ = compare_baseline([_evaluation(0.88)], baseline)
    assert not regressions


def test_changed_scenario_or_judge_starts_a_fresh_provisional_window():
    judge = {
        "deployment": "judge",
        "model": "gpt-5.4",
        "version": "v1",
    }
    baseline = {
        "version": 1,
        "observations": {
            "scenario::model": [
                {
                    "score": 0.9,
                    "scenarioSha256": "old",
                    "judgeDeployment": judge,
                }
            ]
            * 3
        },
    }

    regressions, provisional = compare_baseline(
        [_evaluation(0.5)],
        baseline,
        current_scenario_hashes={"scenario": "new"},
        current_judge_deployment=judge,
    )

    assert not regressions
    assert provisional == ["scenario::model"]

    regressions, provisional = compare_baseline(
        [_evaluation(0.5)],
        baseline,
        current_scenario_hashes={"scenario": "old"},
        current_judge_deployment={**judge, "version": "v2"},
    )

    assert not regressions
    assert provisional == ["scenario::model"]


def test_zero_variance_regression_has_json_safe_infinite_sigma():
    baseline = {
        "version": 1,
        "observations": {
            "scenario::model": [{"score": 0.9, "criteria": {"grounding": 0.9}}] * 3
        },
    }

    regressions, _ = compare_baseline([_evaluation(0.7)], baseline)

    assert regressions
    assert all(item.sigma_drop is None for item in regressions)


def test_baseline_approval_requires_real_models_and_absolute_gates(tmp_path):
    report = {
        "metadata": {
            "runId": "run-1",
            "models": ["gpt-5.4-mini", "gpt-5.5"],
            "gates": {
                "meanScore": 0.9,
                "passRate": 1.0,
                "criticalPassRate": 1.0,
                "thresholds": {"meanScore": 0.0, "passRate": 0.0},
            },
        },
        "evaluations": [
            {
                "scenario_id": "scenario",
                "model": model,
                "execution_error": None,
                "checks": [{"id": "response", "passed": True, "score": 1.0}],
                "semantic_scores": {"grounding": 0.9},
                "semantic_weights": {"grounding": 2.0},
            }
            for model in ("gpt-5.4-mini", "gpt-5.5")
        ],
    }
    _add_provenance(report)
    report_path = tmp_path / "report.json"
    baseline_path = tmp_path / "baseline.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    assert approve_report(report_path, baseline_path) == 2
    baseline = json.loads(baseline_path.read_text())
    observation = baseline["observations"]["scenario::gpt-5.4-mini"][0]
    assert observation["score"] == pytest.approx(0.94)
    assert observation["scenarioSha256"] == "a" * 64
    assert observation["irisSourceSha256"] == "b" * 64
    assert observation["candidateDeployment"]["model"] == "gpt-5.4-mini"
    assert observation["judgeDeployment"]["model"] == "gpt-5.4"

    incomplete = json.loads(json.dumps(report))
    incomplete["metadata"]["runId"] = "run-2"
    incomplete["evaluations"] = incomplete["evaluations"][:1]
    report_path.write_text(json.dumps(incomplete), encoding="utf-8")
    with pytest.raises(ValueError, match="incomplete candidate coverage"):
        approve_report(report_path, baseline_path)

    non_finite_gate = json.loads(json.dumps(report))
    non_finite_gate["metadata"]["runId"] = "run-3"
    non_finite_gate["metadata"]["gates"]["meanScore"] = float("nan")
    report_path.write_text(json.dumps(non_finite_gate), encoding="utf-8")
    with pytest.raises(ValueError, match="failed quality or regression gates"):
        approve_report(report_path, baseline_path)

    non_finite_score = json.loads(json.dumps(report))
    non_finite_score["metadata"]["runId"] = "run-4"
    non_finite_score["evaluations"][0]["semantic_scores"]["grounding"] = float("nan")
    report_path.write_text(json.dumps(non_finite_score), encoding="utf-8")
    with pytest.raises(ValueError, match="non-finite evaluation scores"):
        approve_report(report_path, baseline_path)

    report["metadata"]["models"] = ["unexpected-model"]
    report_path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match="failed quality or regression gates"):
        approve_report(report_path, baseline_path)

    report["metadata"]["models"] = ["gpt-5.4-mini", "gpt-5.5"]
    report["metadata"]["gates"]["regressions"] = [{"key": "scenario::model"}]
    report_path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match="failed quality or regression gates"):
        approve_report(report_path, baseline_path)


def test_baseline_persists_zero_for_a_hard_failed_evaluation(tmp_path):
    report = {
        "metadata": {
            "runId": "run-hard-failure",
            "models": ["gpt-5.4-mini", "gpt-5.5"],
            "gates": {
                "meanScore": 0.9,
                "passRate": 0.9,
                "criticalPassRate": 1.0,
            },
        },
        "evaluations": [
            {
                "scenario_id": "scenario",
                "model": model,
                "execution_error": None,
                "checks": [
                    {
                        "id": "forbidden_tool",
                        "passed": False,
                        "critical": True,
                        "score": 1.0,
                    },
                    {
                        "id": "response",
                        "passed": True,
                        "critical": False,
                        "score": 1.0,
                    },
                ],
                "semantic_scores": {"grounding": 1.0},
                "semantic_weights": {"grounding": 1.0},
            }
            for model in ("gpt-5.4-mini", "gpt-5.5")
        ],
    }
    _add_provenance(report)
    report_path = tmp_path / "report.json"
    baseline_path = tmp_path / "baseline.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    assert approve_report(report_path, baseline_path) == 2
    baseline = json.loads(baseline_path.read_text())
    assert baseline["observations"]["scenario::gpt-5.4-mini"][0]["score"] == 0.0


def test_baseline_aggregates_repetitions_into_one_independent_observation(tmp_path):
    report = {
        "metadata": {
            "runId": "run-with-repetitions",
            "models": ["gpt-5.4-mini", "gpt-5.5"],
            "gates": {
                "meanScore": 0.9,
                "passRate": 1.0,
                "criticalPassRate": 1.0,
            },
        },
        "evaluations": [
            {
                "scenario_id": "critical-scenario",
                "model": model,
                "execution_error": None,
                "checks": [{"id": "response", "passed": True, "score": 1.0}],
                "semantic_scores": {"grounding": score},
                "semantic_weights": {"grounding": 1.0},
            }
            for model in ("gpt-5.4-mini", "gpt-5.5")
            for score in (0.8, 0.9, 1.0)
        ],
    }
    _add_provenance(report)
    report_path = tmp_path / "report.json"
    baseline_path = tmp_path / "baseline.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    assert approve_report(report_path, baseline_path) == 2
    observations = json.loads(baseline_path.read_text())["observations"][
        "critical-scenario::gpt-5.5"
    ]
    assert len(observations) == 1
    assert observations[0]["sampleCount"] == 3
    assert observations[0]["score"] == pytest.approx(0.94)
    assert observations[0]["criteria"]["grounding"] == pytest.approx(0.9)


def test_baseline_counts_execution_error_sample_as_zero(tmp_path):
    report = {
        "metadata": {
            "runId": "run-with-standard-error",
            "models": ["gpt-5.4-mini", "gpt-5.5"],
            "gates": {
                "meanScore": 0.8,
                "passRate": 0.9,
                "criticalPassRate": 1.0,
            },
        },
        "evaluations": [
            {
                "scenario_id": "standard-scenario",
                "model": model,
                "execution_error": "provider timeout",
                "checks": [],
                "semantic_scores": {},
                "semantic_weights": {},
            }
            for model in ("gpt-5.4-mini", "gpt-5.5")
        ],
    }
    _add_provenance(report)
    report_path = tmp_path / "report.json"
    baseline_path = tmp_path / "baseline.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    assert approve_report(report_path, baseline_path) == 2
    observation = json.loads(baseline_path.read_text())["observations"][
        "standard-scenario::gpt-5.4-mini"
    ][0]
    assert observation["score"] == 0.0
    assert observation["sampleCount"] == 1

    with pytest.raises(ValueError, match="already in the baseline"):
        approve_report(report_path, baseline_path)
