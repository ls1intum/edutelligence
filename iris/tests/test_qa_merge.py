from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest

from iris.qa.cli import main
from iris.qa.evaluate import CheckResult, ScenarioEvaluation
from iris.qa.loader import filter_scenarios, load_suite
from iris.qa.merge import merge_paid_run_reports
from iris.qa.report import write_json_report
from iris.qa.run import (
    _aggregate_passes,
    _canonical_json_value,
    _scenario_fingerprints,
    _source_fingerprint,
)

QA_ROOT = Path(__file__).parents[1] / "qa"


def test_fingerprint_canonicalization_sorts_unordered_collections_recursively():
    assert _canonical_json_value(
        {
            "profiles": {"weekly", "full", "smoke"},
            "nested": [{"tags": frozenset({"privacy", "grounding"})}],
        }
    ) == {
        "nested": [{"tags": ["grounding", "privacy"]}],
        "profiles": ["full", "smoke", "weekly"],
    }


def _corpus_hash(hashes: dict[str, str]) -> str:
    return hashlib.sha256(
        json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _evaluation(scenario_id: str, *, passed: bool = True) -> ScenarioEvaluation:
    return ScenarioEvaluation(
        scenario_id=scenario_id,
        model="gpt-5.5",
        response="publishable reports omit this",
        activities=[],
        checks=[
            CheckResult(
                id="synthetic-check",
                passed=passed,
                message="Synthetic report fixture.",
                critical=not passed,
            )
        ],
    )


def _suite(profile: str = "smoke"):
    suite = load_suite(
        QA_ROOT / "scenarios", QA_ROOT / "fixtures", QA_ROOT / "artifacts"
    )
    return filter_scenarios(suite, profile=profile)


def _write_shard(
    root: Path,
    *,
    run_id: str,
    scenarios: list,
    starting_spend: Decimal,
    failed_ids: set[str] | None = None,
) -> Path:
    failed_ids = failed_ids or set()
    evaluations = [
        _evaluation(scenario.id, passed=scenario.id not in failed_ids)
        for scenario in scenarios
    ]
    critical_keys = {
        (scenario.id, "gpt-5.5")
        for scenario in scenarios
        if scenario.requires_critical_gate
    }
    _, gates = _aggregate_passes(evaluations, critical_keys=critical_keys)
    gates["regressions"] = []
    gates["provisionalBaselineKeys"] = []
    scenario_hashes = _scenario_fingerprints(scenarios)
    run_spend = Decimal("1.25")
    metadata = {
        "runId": run_id,
        "models": ["gpt-5.5"],
        "repetitions": 1,
        "criticalRepetitions": 1,
        "transientRetriesConfigured": 0,
        "transientRetriesUsed": 0,
        "transientRetryAllowanceUsd": "0",
        "workerAttemptCount": len(scenarios),
        "executionAttempts": [
            {
                "scenarioId": scenario.id,
                "model": "gpt-5.5",
                "repetition": 1,
                "attempts": 1,
                "retriesUsed": 0,
                "ambiguousFailures": 0,
                "finalOutcome": ("FAIL" if scenario.id in failed_ids else "PASS"),
                "rawFiles": [f"{scenario.id}.json"],
            }
            for scenario in scenarios
        ],
        "gates": gates,
        "accountedSpendUsd": str(starting_spend + run_spend),
        "measuredUsageSpendUsd": str(starting_spend + run_spend),
        "runSpendUsd": str(run_spend),
        "measuredRunSpendUsd": str(run_spend),
        "ambiguousReserveUsd": "0",
        "startingSpendUsd": str(starting_spend),
        "plannedCostUsd": "8.50",
        "rateSource": "unit-test confirmed rates",
        "rateCard": {
            "gpt-5.4": {"input": "2.5", "output": "15"},
            "gpt-5.4-mini": {"input": "0.5", "output": "3"},
            "gpt-5.5": {"input": "1.75", "output": "14"},
        },
        "providerUsage": {
            "gpt-5.5": {
                "calls": len(scenarios),
                "inputTokens": len(scenarios) * 100,
                "outputTokens": len(scenarios) * 10,
                "maxInputTokensPerCall": 100,
                "maxOutputTokensPerCall": 10,
                "costUsd": str(run_spend),
            }
        },
        "corpusSha256": _corpus_hash(scenario_hashes),
        "scenarioSha256": scenario_hashes,
        "irisSourceSha256": _source_fingerprint(QA_ROOT),
        "hardLimitUsd": "45",
        "developmentHardLimitUsd": "45",
        "runMaxCostUsd": "10",
        "preliminary": True,
        "baseline": None,
        "azureDeployments": {
            model: {
                "model": model,
                "deployment": f"qa-{model}",
                "version": "provider-reported",
            }
            for model in ("gpt-5.4-mini", "gpt-5.5", "gpt-5.4")
        },
    }
    directory = root / run_id
    directory.mkdir()
    write_json_report(directory / "report.json", evaluations, metadata=metadata)
    return directory


def _shards(tmp_path: Path):
    scenarios = _suite()
    midpoint = len(scenarios) // 2
    first = _write_shard(
        tmp_path,
        run_id="shard-a",
        scenarios=scenarios[:midpoint],
        starting_spend=Decimal(0),
    )
    second = _write_shard(
        tmp_path,
        run_id="shard-b",
        scenarios=scenarios[midpoint:],
        starting_spend=Decimal("1.25"),
    )
    return scenarios, first, second


def test_merge_cli_recomputes_complete_qualification_and_provenance(
    tmp_path: Path, capsys
):
    scenarios, first, second = _shards(tmp_path)
    output_root = tmp_path / "merged"

    result = main(
        [
            "--qa-root",
            str(QA_ROOT),
            "merge",
            "--profile",
            "smoke",
            "--report",
            str(first),
            "--report",
            str(second / "report.json"),
            "--output",
            str(output_root),
        ]
    )

    assert result == 0
    assert "PASS  merged report:" in capsys.readouterr().out
    merged_dirs = list(output_root.iterdir())
    assert len(merged_dirs) == 1
    report = json.loads((merged_dirs[0] / "report.json").read_text(encoding="utf-8"))
    assert report["summary"] == {
        "total": len(scenarios),
        "passed": len(scenarios),
        "failed": 0,
        "criticalFailures": 0,
        "meanScore": 1.0,
    }
    assert report["metadata"]["gates"]["passRate"] == 1.0
    assert report["metadata"]["gates"]["criticalPassRate"] == 1.0
    assert report["metadata"]["compositeRunIds"] == ["shard-a", "shard-b"]
    assert report["metadata"]["runSpendUsd"] == "2.50"
    assert report["metadata"]["providerUsage"]["gpt-5.5"]["calls"] == len(scenarios)
    assert all(
        "sourceRunId" in attempt for attempt in report["metadata"]["executionAttempts"]
    )
    assert (merged_dirs[0] / "report.md").is_file()
    assert (merged_dirs[0] / "junit.xml").is_file()
    assert "Composite qualification provenance" in (
        merged_dirs[0] / "report.md"
    ).read_text(encoding="utf-8")


def test_merge_fails_closed_when_target_profile_is_incomplete(tmp_path: Path):
    scenarios = _suite()
    midpoint = len(scenarios) // 2
    first = _write_shard(
        tmp_path,
        run_id="shard-a",
        scenarios=scenarios[:midpoint],
        starting_spend=Decimal(0),
    )
    second = _write_shard(
        tmp_path,
        run_id="shard-b",
        scenarios=scenarios[midpoint:-1],
        starting_spend=Decimal("1.25"),
    )

    with pytest.raises(ValueError, match="missing 1 observations"):
        merge_paid_run_reports(
            qa_root=QA_ROOT,
            scenarios=scenarios,
            report_paths=[first, second],
            output_root=tmp_path / "merged",
        )
    assert not (tmp_path / "merged").exists()


def test_merge_rejects_duplicate_observations_across_runs(tmp_path: Path):
    scenarios, first, _ = _shards(tmp_path)
    duplicate = _write_shard(
        tmp_path,
        run_id="shard-duplicate",
        scenarios=scenarios,
        starting_spend=Decimal("1.25"),
    )

    with pytest.raises(ValueError, match="duplicate scenario/model/repetition"):
        merge_paid_run_reports(
            qa_root=QA_ROOT,
            scenarios=scenarios,
            report_paths=[first, duplicate],
            output_root=tmp_path / "merged",
        )


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    [
        ("rateSource", "different rates", "incompatible rateSource"),
        ("rateCard", {"changed": True}, "incompatible rateCard"),
        ("irisSourceSha256", "0" * 64, "incompatible irisSourceSha256"),
        (
            "azureDeployments",
            {"changed": True},
            "incompatible azureDeployments",
        ),
        ("evaluatorVersion", "v2", "disagree on metadata field evaluatorVersion"),
    ],
)
def test_merge_rejects_incompatible_shard_metadata(
    tmp_path: Path, field: str, replacement, message: str
):
    scenarios, first, second = _shards(tmp_path)
    report_path = second / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["metadata"][field] = replacement
    report_path.write_text(json.dumps(report), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        merge_paid_run_reports(
            qa_root=QA_ROOT,
            scenarios=scenarios,
            report_paths=[first, second],
            output_root=tmp_path / "merged",
        )


def test_merge_rejects_changed_threshold_policy(tmp_path: Path):
    scenarios, first, second = _shards(tmp_path)
    for directory in (first, second):
        report_path = directory / "report.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["metadata"]["gates"]["thresholds"]["passRate"] = 0.5
        report_path.write_text(json.dumps(report), encoding="utf-8")

    with pytest.raises(ValueError, match="threshold policy is incompatible"):
        merge_paid_run_reports(
            qa_root=QA_ROOT,
            scenarios=scenarios,
            report_paths=[first, second],
            output_root=tmp_path / "merged",
        )


def test_merge_rejects_tampered_report_summary(tmp_path: Path):
    scenarios, first, second = _shards(tmp_path)
    report_path = second / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["summary"]["meanScore"] = 0.99
    report_path.write_text(json.dumps(report), encoding="utf-8")

    with pytest.raises(ValueError, match="summary does not match evaluations"):
        merge_paid_run_reports(
            qa_root=QA_ROOT,
            scenarios=scenarios,
            report_paths=[first, second],
            output_root=tmp_path / "merged",
        )


def test_merge_writes_failed_qualification_without_hiding_failure(tmp_path: Path):
    scenarios = _suite()
    midpoint = len(scenarios) // 2
    first = _write_shard(
        tmp_path,
        run_id="shard-a",
        scenarios=scenarios[:midpoint],
        starting_spend=Decimal(0),
        failed_ids={scenario.id for scenario in scenarios[:midpoint]},
    )
    second = _write_shard(
        tmp_path,
        run_id="shard-b",
        scenarios=scenarios[midpoint:],
        starting_spend=Decimal("1.25"),
    )

    result = merge_paid_run_reports(
        qa_root=QA_ROOT,
        scenarios=scenarios,
        report_paths=[first, second],
        output_root=tmp_path / "merged",
    )

    assert not result.passed
    report = json.loads((result.output_dir / "report.json").read_text(encoding="utf-8"))
    assert report["metadata"]["gates"]["passRate"] < 0.85
    assert report["summary"]["failed"] == midpoint
