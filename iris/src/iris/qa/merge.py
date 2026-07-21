from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4

from iris.qa.baseline import Regression, compare_baseline, load_baseline
from iris.qa.evaluate import ActivityTrace, CheckResult, ScenarioEvaluation
from iris.qa.planning import CANDIDATE_MODELS
from iris.qa.report import (
    _summary,
    write_json_report,
    write_junit_report,
    write_markdown_report,
)
from iris.qa.run import _aggregate_passes, _scenario_fingerprints, _source_fingerprint


@dataclass(frozen=True)
class MergeResult:
    output_dir: Path
    passed: bool


@dataclass(frozen=True)
class _SourceReport:
    path: Path
    generated_at: str
    metadata: dict
    evaluations: list[ScenarioEvaluation]
    observation_keys: list[tuple[str, str, int]]


_REQUIRED_COMPATIBILITY_KEYS = (
    "models",
    "repetitions",
    "criticalRepetitions",
    "rateSource",
    "rateCard",
    "irisSourceSha256",
    "azureDeployments",
    "developmentHardLimitUsd",
    "baseline",
)
_OPTIONAL_COMPATIBILITY_KEYS = (
    # These fields are not emitted today, but fail closed if a future report
    # starts recording an independently versioned evaluator or judge prompt.
    "evaluatorVersion",
    "judgePromptSha256",
    "judgeCalibrationSha256",
)


def _report_path(path: Path) -> Path:
    resolved = path.resolve()
    if resolved.is_dir():
        resolved = resolved / "report.json"
    if not resolved.is_file():
        raise ValueError(f"QA shard report does not exist: {resolved}")
    return resolved


def _finite_number(value, label: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be a finite number") from error
    if not math.isfinite(parsed):
        raise ValueError(f"{label} must be a finite number")
    return parsed


def _money(value, label: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"{label} must be a finite decimal") from error
    if not parsed.is_finite() or parsed < 0:
        raise ValueError(f"{label} must be a finite nonnegative decimal")
    return parsed


def _evaluation(payload: dict, *, path: Path, index: int) -> ScenarioEvaluation:
    label = f"{path}: evaluation {index}"
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be an object")
    scenario_id = payload.get("scenario_id")
    model = payload.get("model")
    if not isinstance(scenario_id, str) or not scenario_id:
        raise ValueError(f"{label} has no scenario_id")
    if not isinstance(model, str) or not model:
        raise ValueError(f"{label} has no model")
    activities_payload = payload.get("activities")
    checks_payload = payload.get("checks")
    if not isinstance(activities_payload, list) or not isinstance(checks_payload, list):
        raise ValueError(f"{label} has invalid activities or checks")
    activities: list[ActivityTrace] = []
    for activity in activities_payload:
        if not isinstance(activity, dict):
            raise ValueError(f"{label} has an invalid activity")
        name = activity.get("name")
        state = activity.get("state")
        if not isinstance(name, str) or not name or not isinstance(state, str):
            raise ValueError(f"{label} has an invalid activity")
        activities.append(ActivityTrace(name=name, state=state))
    checks: list[CheckResult] = []
    for check in checks_payload:
        if not isinstance(check, dict):
            raise ValueError(f"{label} has an invalid check")
        check_id = check.get("id")
        passed = check.get("passed")
        message = check.get("message")
        critical = check.get("critical")
        score = _finite_number(check.get("score"), f"{label} check score")
        if (
            not isinstance(check_id, str)
            or not check_id
            or not isinstance(passed, bool)
            or not isinstance(message, str)
            or not isinstance(critical, bool)
            or not 0 <= score <= 1
        ):
            raise ValueError(f"{label} has an invalid check")
        checks.append(
            CheckResult(
                id=check_id,
                passed=passed,
                message=message,
                critical=critical,
                score=score,
            )
        )
    semantic_scores = payload.get("semantic_scores")
    semantic_weights = payload.get("semantic_weights")
    semantic_evidence = payload.get("semantic_evidence")
    if (
        not isinstance(semantic_scores, dict)
        or not isinstance(semantic_weights, dict)
        or not isinstance(semantic_evidence, dict)
    ):
        raise ValueError(f"{label} has invalid semantic results")
    parsed_scores = {
        str(key): _finite_number(value, f"{label} semantic score")
        for key, value in semantic_scores.items()
    }
    parsed_weights = {
        str(key): _finite_number(value, f"{label} semantic weight")
        for key, value in semantic_weights.items()
    }
    if any(not 0 <= value <= 1 for value in parsed_scores.values()) or any(
        value <= 0 for value in parsed_weights.values()
    ):
        raise ValueError(f"{label} has semantic values outside valid ranges")
    if not all(isinstance(value, str) for value in semantic_evidence.values()):
        raise ValueError(f"{label} has invalid semantic evidence")
    execution_error = payload.get("execution_error")
    if execution_error is not None and not isinstance(execution_error, str):
        raise ValueError(f"{label} has an invalid execution error")
    return ScenarioEvaluation(
        scenario_id=scenario_id,
        model=model,
        # Publishable reports deliberately omit raw responses. Scores are fully
        # reproducible from the retained checks and semantic evidence.
        response=None,
        activities=activities,
        checks=checks,
        semantic_scores=parsed_scores,
        semantic_weights=parsed_weights,
        semantic_evidence=dict(semantic_evidence),
        execution_error=execution_error,
    )


def _same_number(left, right) -> bool:
    try:
        return math.isclose(
            _finite_number(left, "reported value"),
            _finite_number(right, "computed value"),
            rel_tol=1e-12,
            abs_tol=1e-12,
        )
    except ValueError:
        return False


def _validate_summary(report: dict, evaluations: list[ScenarioEvaluation], path: Path):
    reported = report.get("summary")
    computed = _summary(evaluations)
    if not isinstance(reported, dict):
        raise ValueError(f"{path}: missing report summary")
    for key in ("total", "passed", "failed", "criticalFailures"):
        if reported.get(key) != computed[key]:
            raise ValueError(f"{path}: report summary does not match evaluations")
    if not _same_number(reported.get("meanScore"), computed["meanScore"]):
        raise ValueError(f"{path}: report summary does not match evaluations")


def _load_report(path: Path) -> _SourceReport:
    report_path = _report_path(path)
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(
            f"Cannot read QA shard report {report_path}: {error}"
        ) from error
    if not isinstance(report, dict):
        raise ValueError(f"{report_path}: report must be an object")
    generated_at = report.get("generatedAt")
    metadata = report.get("metadata")
    payloads = report.get("evaluations")
    if (
        not isinstance(generated_at, str)
        or not isinstance(metadata, dict)
        or not isinstance(payloads, list)
        or not payloads
    ):
        raise ValueError(f"{report_path}: incomplete QA report")
    evaluations = [
        _evaluation(payload, path=report_path, index=index)
        for index, payload in enumerate(payloads, 1)
    ]
    _validate_summary(report, evaluations, report_path)
    attempts = metadata.get("executionAttempts")
    if not isinstance(attempts, list) or len(attempts) != len(evaluations):
        raise ValueError(f"{report_path}: execution attempts do not match evaluations")
    observation_keys: list[tuple[str, str, int]] = []
    for index, (attempt, evaluation) in enumerate(zip(attempts, evaluations), 1):
        if not isinstance(attempt, dict):
            raise ValueError(f"{report_path}: invalid execution attempt {index}")
        repetition = attempt.get("repetition")
        if (
            attempt.get("scenarioId") != evaluation.scenario_id
            or attempt.get("model") != evaluation.model
            or not isinstance(repetition, int)
            or isinstance(repetition, bool)
            or repetition < 1
        ):
            raise ValueError(
                f"{report_path}: execution attempt {index} does not match evaluation"
            )
        expected_outcome = "PASS" if evaluation.passed else "FAIL"
        if attempt.get("finalOutcome") != expected_outcome:
            raise ValueError(
                f"{report_path}: execution attempt {index} has an invalid outcome"
            )
        observation_keys.append((evaluation.scenario_id, evaluation.model, repetition))
    if len(set(observation_keys)) != len(observation_keys):
        raise ValueError(
            f"{report_path}: duplicate scenario/model/repetition observation"
        )
    return _SourceReport(
        path=report_path,
        generated_at=generated_at,
        metadata=metadata,
        evaluations=evaluations,
        observation_keys=observation_keys,
    )


def _corpus_hash(scenario_hashes: dict[str, str]) -> str:
    payload = json.dumps(
        dict(sorted(scenario_hashes.items())),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _normalized_regressions(regressions) -> list[str]:
    return sorted(json.dumps(item, sort_keys=True) for item in regressions)


def _validate_shard(
    source: _SourceReport,
    *,
    scenarios_by_id: dict,
    expected_hashes: dict[str, str],
    baseline: dict | None,
) -> None:
    metadata = source.metadata
    run_id = metadata.get("runId")
    models = metadata.get("models")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError(f"{source.path}: missing run ID")
    if (
        not isinstance(models, list)
        or len(models) != 1
        or not isinstance(models[0], str)
        or models[0] not in CANDIDATE_MODELS
    ):
        raise ValueError(f"{source.path}: a shard must qualify exactly one model")
    model = models[0]
    if any(evaluation.model != model for evaluation in source.evaluations):
        raise ValueError(f"{source.path}: evaluation model differs from shard model")
    scenario_ids = {evaluation.scenario_id for evaluation in source.evaluations}
    unknown = scenario_ids - set(scenarios_by_id)
    if unknown:
        raise ValueError(
            f"{source.path}: observations outside the requested suite: {sorted(unknown)}"
        )
    reported_hashes = metadata.get("scenarioSha256")
    if not isinstance(reported_hashes, dict) or set(reported_hashes) != scenario_ids:
        raise ValueError(f"{source.path}: scenario hashes do not match observations")
    for scenario_id in scenario_ids:
        if reported_hashes.get(scenario_id) != expected_hashes[scenario_id]:
            raise ValueError(
                f"{source.path}: scenario {scenario_id} differs from the current suite"
            )
    if metadata.get("corpusSha256") != _corpus_hash(reported_hashes):
        raise ValueError(f"{source.path}: selected corpus hash is invalid")
    critical_keys = {
        (scenario_id, model)
        for scenario_id in scenario_ids
        if scenarios_by_id[scenario_id].requires_critical_gate
    }
    _, computed_gates = _aggregate_passes(
        source.evaluations, critical_keys=critical_keys
    )
    gates = metadata.get("gates")
    if not isinstance(gates, dict):
        raise ValueError(f"{source.path}: missing quality gates")
    if gates.get("thresholds") != computed_gates["thresholds"]:
        raise ValueError(f"{source.path}: quality threshold policy is incompatible")
    for key in ("meanScore", "passRate", "criticalPassRate"):
        if not _same_number(gates.get(key), computed_gates[key]):
            raise ValueError(f"{source.path}: quality gates do not match evaluations")
    if baseline is None:
        if gates.get("regressions", []) or gates.get("provisionalBaselineKeys", []):
            raise ValueError(f"{source.path}: unexpected baseline results")
    else:
        regressions, provisional = compare_baseline(
            source.evaluations,
            baseline,
            current_scenario_hashes=reported_hashes,
            current_judge_deployment=metadata["azureDeployments"]["gpt-5.4"],
        )
        expected_regressions = [regression.__dict__ for regression in regressions]
        if _normalized_regressions(gates.get("regressions", [])) != (
            _normalized_regressions(expected_regressions)
        ) or sorted(gates.get("provisionalBaselineKeys", [])) != sorted(provisional):
            raise ValueError(f"{source.path}: baseline gates do not match evaluations")


def _common_metadata(sources: list[_SourceReport]) -> dict:
    first = sources[0].metadata
    for key in _REQUIRED_COMPATIBILITY_KEYS:
        if any(key not in source.metadata for source in sources):
            raise ValueError(f"QA shard report is missing metadata field {key}")
        if any(source.metadata[key] != first[key] for source in sources):
            raise ValueError(f"QA shard reports have incompatible {key}")
    for key in _OPTIONAL_COMPATIBILITY_KEYS:
        present = [key in source.metadata for source in sources]
        if any(present) and not all(present):
            raise ValueError(f"QA shard reports disagree on metadata field {key}")
        if all(present) and any(
            source.metadata[key] != first[key] for source in sources
        ):
            raise ValueError(f"QA shard reports have incompatible {key}")
    deployments = first["azureDeployments"]
    if not isinstance(deployments, dict) or not {
        "gpt-5.4-mini",
        "gpt-5.5",
        "gpt-5.4",
    } <= set(deployments):
        raise ValueError("QA shard reports have invalid Azure deployment identities")
    for model, deployment in deployments.items():
        if (
            not isinstance(deployment, dict)
            or deployment.get("model") != model
            or not isinstance(deployment.get("deployment"), str)
            or not deployment["deployment"]
            or not isinstance(deployment.get("version"), str)
            or not deployment["version"]
        ):
            raise ValueError(
                "QA shard reports have invalid Azure deployment identities"
            )
    rate_card = first["rateCard"]
    if not isinstance(rate_card, dict) or not set(deployments) <= set(rate_card):
        raise ValueError("QA shard reports have invalid confirmed rates")
    for model in deployments:
        rates = rate_card.get(model)
        if not isinstance(rates, dict):
            raise ValueError("QA shard reports have invalid confirmed rates")
        for dimension in ("input", "output"):
            if _money(rates.get(dimension), f"rate for {model} {dimension}") <= 0:
                raise ValueError("QA shard reports have invalid confirmed rates")
    _money(first["developmentHardLimitUsd"], "development hard limit")
    return first


def _sum_money(sources: list[_SourceReport], key: str) -> Decimal:
    return sum(
        (
            _money(source.metadata.get(key, "0"), f"{source.path}: {key}")
            for source in sources
        ),
        Decimal(0),
    )


def _extreme_money(sources: list[_SourceReport], key: str, *, maximum: bool) -> Decimal:
    values = [
        _money(source.metadata.get(key, "0"), f"{source.path}: {key}")
        for source in sources
    ]
    return max(values) if maximum else min(values)


def _provider_usage(sources: list[_SourceReport]) -> dict[str, dict]:
    totals: dict[str, dict] = {}
    for source in sources:
        usage = source.metadata.get("providerUsage")
        if not isinstance(usage, dict):
            raise ValueError(f"{source.path}: invalid provider usage")
        for model, item in usage.items():
            if not isinstance(item, dict):
                raise ValueError(f"{source.path}: invalid provider usage for {model}")
            total = totals.setdefault(
                model,
                {
                    "calls": 0,
                    "inputTokens": 0,
                    "outputTokens": 0,
                    "maxInputTokensPerCall": 0,
                    "maxOutputTokensPerCall": 0,
                    "costUsd": Decimal(0),
                },
            )
            for key in ("calls", "inputTokens", "outputTokens"):
                value = item.get(key)
                if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                    raise ValueError(f"{source.path}: invalid provider usage {key}")
                total[key] += value
            for key in ("maxInputTokensPerCall", "maxOutputTokensPerCall"):
                value = item.get(key)
                if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                    raise ValueError(f"{source.path}: invalid provider usage {key}")
                total[key] = max(total[key], value)
            total["costUsd"] += _money(
                item.get("costUsd"), f"{source.path}: provider cost"
            )
            reservations = item.get("ambiguousReservations", 0)
            if (
                not isinstance(reservations, int)
                or isinstance(reservations, bool)
                or reservations < 0
            ):
                raise ValueError(f"{source.path}: invalid ambiguous reservations")
            if reservations:
                total["ambiguousReservations"] = (
                    total.get("ambiguousReservations", 0) + reservations
                )
                total["reservedCostUsd"] = total.get(
                    "reservedCostUsd", Decimal(0)
                ) + _money(
                    item.get("reservedCostUsd"),
                    f"{source.path}: reserved provider cost",
                )
    for item in totals.values():
        item["costUsd"] = str(item["costUsd"])
        if "reservedCostUsd" in item:
            item["reservedCostUsd"] = str(item["reservedCostUsd"])
    return dict(sorted(totals.items()))


def merge_paid_run_reports(
    *,
    qa_root: Path,
    scenarios: list,
    report_paths: list[Path],
    output_root: Path,
    baseline_path: Path | None = None,
) -> MergeResult:
    """Merge disjoint paid-run shards without making any provider calls."""
    if len(report_paths) < 2:
        raise ValueError("Merge requires at least two paid-run shard reports")
    if not scenarios:
        raise ValueError("Merge target suite is empty")
    sources = [_load_report(path) for path in report_paths]
    if len({source.path for source in sources}) != len(sources):
        raise ValueError("The same QA shard report was supplied more than once")
    common = _common_metadata(sources)
    source_run_ids = []
    for source in sources:
        run_id = source.metadata.get("runId")
        if not isinstance(run_id, str) or not run_id:
            raise ValueError(f"{source.path}: missing run ID")
        source_run_ids.append(run_id)
    if len(set(source_run_ids)) != len(source_run_ids):
        raise ValueError("QA shard reports contain duplicate run IDs")
    current_source_hash = _source_fingerprint(qa_root)
    if common.get("irisSourceSha256") != current_source_hash:
        raise ValueError("QA shards do not match the current Iris source and prompts")
    expected_hashes = _scenario_fingerprints(scenarios)
    scenarios_by_id = {scenario.id: scenario for scenario in scenarios}
    recorded_baseline = common.get("baseline")
    if recorded_baseline is None:
        if baseline_path is not None:
            raise ValueError(
                "A baseline was supplied but the shard reports did not use one"
            )
        baseline = None
    else:
        if baseline_path is None:
            raise ValueError(
                "Shard reports used a baseline; pass its immutable path to merge"
            )
        if Path(recorded_baseline).resolve() != baseline_path.resolve():
            raise ValueError("Merge baseline path differs from the shard reports")
        baseline = load_baseline(baseline_path)
    for source in sources:
        _validate_shard(
            source,
            scenarios_by_id=scenarios_by_id,
            expected_hashes=expected_hashes,
            baseline=baseline,
        )
    all_keys = [key for source in sources for key in source.observation_keys]
    if len(set(all_keys)) != len(all_keys):
        raise ValueError(
            "QA shards contain duplicate scenario/model/repetition observations"
        )
    model = common["models"][0]
    repetitions = common["repetitions"]
    critical_repetitions = common["criticalRepetitions"]
    if (
        not isinstance(repetitions, int)
        or isinstance(repetitions, bool)
        or repetitions < 1
        or not isinstance(critical_repetitions, int)
        or isinstance(critical_repetitions, bool)
        or critical_repetitions < 1
    ):
        raise ValueError("QA shard repetition policy is invalid")
    expected_keys = {
        (scenario.id, model, repetition)
        for scenario in scenarios
        for repetition in range(
            1,
            (critical_repetitions if scenario.risk.value == "critical" else repetitions)
            + 1,
        )
    }
    observed_keys = set(all_keys)
    missing = expected_keys - observed_keys
    extra = observed_keys - expected_keys
    if missing or extra:
        detail = []
        if missing:
            detail.append(f"missing {len(missing)} observations")
        if extra:
            detail.append(f"unexpected {len(extra)} observations")
        raise ValueError(
            "QA shards do not cover the requested suite: " + ", ".join(detail)
        )
    keyed_evaluations = {
        key: evaluation
        for source in sources
        for key, evaluation in zip(source.observation_keys, source.evaluations)
    }
    evaluations = [keyed_evaluations[key] for key in sorted(expected_keys)]
    critical_keys = {
        (scenario.id, model)
        for scenario in scenarios
        if scenario.requires_critical_gate
    }
    passed, gates = _aggregate_passes(evaluations, critical_keys=critical_keys)
    regressions: list[Regression] = []
    provisional: list[str] = []
    if baseline is not None:
        regressions, provisional = compare_baseline(
            evaluations,
            baseline,
            current_scenario_hashes=expected_hashes,
            current_judge_deployment=common["azureDeployments"]["gpt-5.4"],
        )
        passed = passed and not regressions
    gates["regressions"] = [regression.__dict__ for regression in regressions]
    gates["provisionalBaselineKeys"] = provisional
    run_id = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-merge-"
        + uuid4().hex[:8]
    )
    output_dir = output_root.resolve() / run_id
    output_dir.mkdir(parents=True, exist_ok=False)
    execution_attempts = []
    for source in sources:
        for attempt in source.metadata["executionAttempts"]:
            execution_attempts.append(
                {
                    **attempt,
                    "sourceRunId": source.metadata["runId"],
                    "sourceReport": str(source.path),
                }
            )
    metadata = {
        "runId": run_id,
        "models": [model],
        "repetitions": repetitions,
        "criticalRepetitions": critical_repetitions,
        "transientRetriesConfigured": sum(
            int(source.metadata.get("transientRetriesConfigured", 0))
            for source in sources
        ),
        "transientRetriesUsed": sum(
            int(source.metadata.get("transientRetriesUsed", 0)) for source in sources
        ),
        "transientRetryAllowanceUsd": str(
            _sum_money(sources, "transientRetryAllowanceUsd")
        ),
        "workerAttemptCount": sum(
            int(source.metadata.get("workerAttemptCount", 0)) for source in sources
        ),
        "executionAttempts": execution_attempts,
        "gates": gates,
        "accountedSpendUsd": str(
            _extreme_money(sources, "accountedSpendUsd", maximum=True)
        ),
        "measuredUsageSpendUsd": str(
            _extreme_money(sources, "measuredUsageSpendUsd", maximum=True)
        ),
        "runSpendUsd": str(_sum_money(sources, "runSpendUsd")),
        "measuredRunSpendUsd": str(_sum_money(sources, "measuredRunSpendUsd")),
        "ambiguousReserveUsd": str(_sum_money(sources, "ambiguousReserveUsd")),
        "startingSpendUsd": str(
            _extreme_money(sources, "startingSpendUsd", maximum=False)
        ),
        "plannedCostUsd": str(_sum_money(sources, "plannedCostUsd")),
        "rateSource": common["rateSource"],
        "providerUsage": _provider_usage(sources),
        "corpusSha256": _corpus_hash(expected_hashes),
        "scenarioSha256": expected_hashes,
        "irisSourceSha256": current_source_hash,
        "hardLimitUsd": common.get("developmentHardLimitUsd"),
        "developmentHardLimitUsd": common.get("developmentHardLimitUsd"),
        "runMaxCostUsd": str(_sum_money(sources, "runMaxCostUsd")),
        "preliminary": common.get("preliminary", repetitions == 1),
        "baseline": recorded_baseline,
        "azureDeployments": common["azureDeployments"],
        "compositeRunIds": source_run_ids,
        "compositeReports": [str(source.path) for source in sources],
        "compositeGeneratedAt": [source.generated_at for source in sources],
    }
    for key in (
        "rateCard",
        "evaluatorVersion",
        "judgePromptSha256",
        "judgeCalibrationSha256",
    ):
        if key in common:
            metadata[key] = common[key]
    write_json_report(output_dir / "report.json", evaluations, metadata=metadata)
    write_markdown_report(output_dir / "report.md", evaluations, metadata=metadata)
    write_junit_report(output_dir / "junit.xml", evaluations)
    return MergeResult(output_dir=output_dir, passed=passed)
