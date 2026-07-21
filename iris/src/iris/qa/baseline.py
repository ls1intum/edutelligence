from __future__ import annotations

import json
import math
import os
import re
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from iris.qa.evaluate import ScenarioEvaluation

# pylint: disable=inconsistent-quotes

_CANDIDATE_MODELS = {"gpt-5.4-mini", "gpt-5.5"}
_DEPLOYMENT_MODELS = _CANDIDATE_MODELS | {"gpt-5.4"}
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class Regression:
    key: str
    dimension: str
    baseline_mean: float
    current_mean: float
    fixed_drop: float
    sigma_drop: float | None


def load_baseline(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "observations": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != 1 or not isinstance(data.get("observations"), dict):
        raise ValueError(f"Invalid Iris QA baseline: {path}")
    return data


def compare_baseline(
    evaluations: list[ScenarioEvaluation],
    baseline: dict,
    *,
    fixed_margin: float = 0.05,
    sigma_multiplier: float = 2.0,
    current_scenario_hashes: dict[str, str] | None = None,
    current_judge_deployment: dict | None = None,
) -> tuple[list[Regression], list[str]]:
    grouped: dict[str, list[ScenarioEvaluation]] = {}
    for item in evaluations:
        grouped.setdefault(f"{item.scenario_id}::{item.model}", []).append(item)
    regressions: list[Regression] = []
    provisional: list[str] = []
    for key, current in grouped.items():
        history = baseline["observations"].get(key, [])
        scenario_id = key.rsplit("::", 1)[0]
        if current_scenario_hashes is not None:
            expected_hash = current_scenario_hashes.get(scenario_id)
            history = [
                item for item in history if item.get("scenarioSha256") == expected_hash
            ]
        if current_judge_deployment is not None:
            history = [
                item
                for item in history
                if item.get("judgeDeployment") == current_judge_deployment
            ]
        if len(history) < 3:
            provisional.append(key)
            continue
        dimensions = {"overall"}
        dimensions.update(
            criterion
            for observation in history
            for criterion in observation.get("criteria", {})
        )
        for dimension in dimensions:
            historical = [
                float(
                    item["score"]
                    if dimension == "overall"
                    else item.get("criteria", {}).get(dimension)
                )
                for item in history
                if dimension == "overall" or dimension in item.get("criteria", {})
            ]
            current_values = [
                (
                    item.score
                    if dimension == "overall"
                    else item.semantic_scores[dimension]
                )
                for item in current
                if dimension == "overall" or dimension in item.semantic_scores
            ]
            if len(historical) < 3 or not current_values:
                continue
            old_mean = statistics.mean(historical)
            new_mean = statistics.mean(current_values)
            fixed_drop = old_mean - new_mean
            deviation = statistics.pstdev(historical)
            sigma_drop = fixed_drop / deviation if deviation else None
            if fixed_drop > fixed_margin and (
                deviation == 0 or fixed_drop > sigma_multiplier * deviation
            ):
                regressions.append(
                    Regression(
                        key=key,
                        dimension=dimension,
                        baseline_mean=old_mean,
                        current_mean=new_mean,
                        fixed_drop=fixed_drop,
                        sigma_drop=sigma_drop,
                    )
                )
    return regressions, provisional


def approve_report(report_path: Path, baseline_path: Path) -> int:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    metadata = report.get("metadata", {})
    gates = metadata.get("gates", {})
    if (
        metadata.get("models") != ["gpt-5.4-mini", "gpt-5.5"]
        or not _finite_at_least(gates.get("meanScore"), 0.8)
        or not _finite_at_least(gates.get("passRate"), 0.85)
        or not _finite_at_least(gates.get("criticalPassRate"), 1.0)
        or bool(gates.get("regressions"))
    ):
        raise ValueError(
            "Cannot approve a report that failed quality or regression gates"
        )
    deployments, scenario_hashes = _validate_report_provenance(report)
    baseline = load_baseline(baseline_path)
    report_run_id = metadata.get("runId")
    if not isinstance(report_run_id, str) or not report_run_id.strip():
        raise ValueError("Cannot approve a report without a stable runId")
    prior_run_ids = {
        observation.get("reportRunId")
        for observations in baseline["observations"].values()
        for observation in observations
        if isinstance(observation, dict)
    }
    if report_run_id in prior_run_ids:
        raise ValueError(f"Report run {report_run_id} is already in the baseline")
    added = 0
    timestamp = datetime.now(timezone.utc).isoformat()
    grouped: dict[str, list[dict]] = {}
    for item in report.get("evaluations", []):
        key = f"{item['scenario_id']}::{item['model']}"
        grouped.setdefault(key, []).append(item)
    for key, samples in grouped.items():
        scenario_id, model = key.rsplit("::", 1)
        criteria = {
            criterion
            for item in samples
            for criterion in item.get("semantic_scores", {})
        }
        sample_scores = [_score_from_report(item) for item in samples]
        criterion_scores = {
            criterion: [
                float(item.get("semantic_scores", {}).get(criterion, 0.0))
                for item in samples
            ]
            for criterion in criteria
        }
        if not all(math.isfinite(score) for score in sample_scores) or any(
            not all(math.isfinite(score) for score in scores)
            for scores in criterion_scores.values()
        ):
            raise ValueError("Cannot approve non-finite evaluation scores")
        baseline["observations"].setdefault(key, []).append(
            {
                "score": statistics.mean(sample_scores),
                "criteria": {
                    criterion: statistics.mean(criterion_scores[criterion])
                    for criterion in criteria
                },
                "approvedAt": timestamp,
                "reportRunId": report_run_id,
                "sampleCount": len(samples),
                "scenarioSha256": scenario_hashes[scenario_id],
                "irisSourceSha256": metadata["irisSourceSha256"],
                "candidateDeployment": deployments[model],
                "judgeDeployment": deployments["gpt-5.4"],
                "rateSource": metadata["rateSource"],
            }
        )
        # Retain a bounded rolling window while preserving enough variance data.
        baseline["observations"][key] = baseline["observations"][key][-12:]
        added += 1
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = baseline_path.with_name(f".{baseline_path.name}.tmp")
    temporary.write_text(
        json.dumps(baseline, indent=2, sort_keys=True), encoding="utf-8"
    )
    os.replace(temporary, baseline_path)
    return added


def _finite_at_least(value, minimum: float) -> bool:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(score) and score >= minimum


def _validate_report_provenance(report: dict) -> tuple[dict, dict[str, str]]:
    metadata = report.get("metadata", {})
    deployments = metadata.get("azureDeployments")
    if not isinstance(deployments, dict) or set(deployments) != _DEPLOYMENT_MODELS:
        raise ValueError("Cannot approve a report without all Azure model bindings")
    names = []
    for model in _DEPLOYMENT_MODELS:
        item = deployments.get(model)
        if (
            not isinstance(item, dict)
            or item.get("model") != model
            or not isinstance(item.get("deployment"), str)
            or not item["deployment"].strip()
            or not isinstance(item.get("version"), str)
            or not item["version"].strip()
        ):
            raise ValueError(f"Cannot approve invalid Azure binding for {model}")
        names.append(item["deployment"])
    if len(set(names)) != len(names):
        raise ValueError("Cannot approve non-distinct Azure model deployments")

    evaluations = report.get("evaluations")
    if not isinstance(evaluations, list) or not evaluations:
        raise ValueError("Cannot approve an empty report")
    model_counts: dict[str, dict[str, int]] = {}
    for item in evaluations:
        scenario_id = item.get("scenario_id") if isinstance(item, dict) else None
        evaluated_model = item.get("model") if isinstance(item, dict) else None
        if not isinstance(scenario_id, str) or not scenario_id.strip():
            raise ValueError("Cannot approve an evaluation without a scenario ID")
        if (
            not isinstance(evaluated_model, str)
            or evaluated_model not in _CANDIDATE_MODELS
        ):
            raise ValueError(
                f"Cannot approve unexpected evaluation model {evaluated_model!r}"
            )
        counts = model_counts.setdefault(scenario_id, {})
        counts[evaluated_model] = counts.get(evaluated_model, 0) + 1
    for scenario_id, counts in model_counts.items():
        if set(counts) != _CANDIDATE_MODELS or len(set(counts.values())) != 1:
            raise ValueError(
                f"Cannot approve incomplete candidate coverage for {scenario_id}"
            )

    scenario_hashes = metadata.get("scenarioSha256")
    if (
        not isinstance(scenario_hashes, dict)
        or set(scenario_hashes) != set(model_counts)
        or any(
            not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None
            for value in scenario_hashes.values()
        )
    ):
        raise ValueError("Cannot approve invalid scenario fingerprints")
    source_hash = metadata.get("irisSourceSha256")
    if not isinstance(source_hash, str) or _SHA256_RE.fullmatch(source_hash) is None:
        raise ValueError("Cannot approve an invalid Iris source fingerprint")
    if (
        not isinstance(metadata.get("rateSource"), str)
        or not metadata["rateSource"].strip()
    ):
        raise ValueError("Cannot approve a report without Azure rate provenance")
    return deployments, scenario_hashes


def _deterministic_from_report(item: dict) -> float:
    checks = [
        check
        for check in item.get("checks", [])
        if not check.get("id", "").startswith("semantic:")
    ]
    if not checks:
        return 0.0
    return sum(
        float(check.get("score", 1.0)) for check in checks if check.get("passed")
    ) / len(checks)


def _score_from_report(item: dict) -> float:
    if item.get("execution_error") or any(
        check.get("critical") and not check.get("passed")
        for check in item.get("checks", [])
    ):
        return 0.0
    deterministic = _deterministic_from_report(item)
    scores = item.get("semantic_scores", {})
    if not scores:
        return deterministic
    weights = item.get("semantic_weights", {})
    total_weight = sum(float(weights.get(key, 1.0)) for key in scores)
    semantic = (
        sum(
            float(score) * float(weights.get(key, 1.0)) for key, score in scores.items()
        )
        / total_weight
    )
    return 0.4 * deterministic + 0.6 * semantic
