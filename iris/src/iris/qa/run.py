from __future__ import annotations

import hashlib
import json
import subprocess  # nosec B404 - fixed local Python module invocation
import sys
import tempfile
from collections import Counter
from collections.abc import Sequence
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from pydantic_core import to_jsonable_python

from iris.qa.baseline import Regression, compare_baseline, load_baseline
from iris.qa.bootstrap import create_worker_configuration
from iris.qa.cost import BudgetGuard, ModelRate, SpendLedger
from iris.qa.evaluate import (
    ActivityTrace,
    CheckResult,
    ScenarioEvaluation,
    evaluate_deterministic,
)
from iris.qa.planning import (
    CANDIDATE_MODELS,
    JUDGE_INPUT_CEILING,
    JUDGE_OUTPUT_CEILING,
    MAX_TRANSIENT_RETRIES,
    worker_cost_reserve,
    worker_token_ceiling,
)
from iris.qa.report import write_json_report, write_junit_report, write_markdown_report
from iris.qa.schema import RiskLevel

# pylint: disable=inconsistent-quotes


def _canonical_json_value(value):
    """Return a JSON-compatible value with deterministic unordered collections."""
    if isinstance(value, dict):
        return {
            key: _canonical_json_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (set, frozenset)):
        normalized = [_canonical_json_value(item) for item in value]
        return sorted(
            normalized,
            key=lambda item: json.dumps(
                item,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ),
        )
    if isinstance(value, (list, tuple)):
        return [_canonical_json_value(item) for item in value]
    return value


def _scenario_fingerprints(scenarios: list) -> dict[str, str]:
    fingerprints = {}
    for scenario in scenarios:
        canonical = _canonical_json_value(
            scenario.model_dump(mode="python", by_alias=True)
        )
        payload = json.dumps(
            to_jsonable_python(canonical),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        fingerprints[scenario.id] = hashlib.sha256(payload).hexdigest()
    return dict(sorted(fingerprints.items()))


def _source_fingerprint(qa_root: Path) -> str:
    """Hash checked-in Iris behavior code and prompts, excluding bytecode."""
    source_root = qa_root.parent / "src" / "iris"
    digest = hashlib.sha256()
    included = 0
    for path in sorted(source_root.rglob("*")):
        if not path.is_file() or path.suffix not in {".py", ".j2", ".txt", ".typed"}:
            continue
        relative = path.relative_to(source_root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        content = path.read_bytes()
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
        included += 1
    if not included:
        raise RuntimeError(f"No Iris source files found below {source_root}")
    return digest.hexdigest()


def _usage_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as error:
            raise RuntimeError(
                f"Invalid worker usage record at line {line_number}"
            ) from error
    return records


def _usage_summary(records) -> dict[str, dict]:
    summary: dict[str, dict] = {}
    for record in records:
        item = summary.setdefault(
            record.model,
            {
                "calls": 0,
                "inputTokens": 0,
                "outputTokens": 0,
                "maxInputTokensPerCall": 0,
                "maxOutputTokensPerCall": 0,
                "costUsd": Decimal(0),
            },
        )
        if record.reservation:
            item["ambiguousReservations"] = item.get("ambiguousReservations", 0) + 1
            item["reservedCostUsd"] = item.get("reservedCostUsd", Decimal(0)) + Decimal(
                record.cost_usd
            )
            item["costUsd"] += Decimal(record.cost_usd)
            continue
        item["calls"] += 1
        item["inputTokens"] += record.input_tokens
        item["outputTokens"] += record.output_tokens
        item["maxInputTokensPerCall"] = max(
            item["maxInputTokensPerCall"], record.input_tokens
        )
        item["maxOutputTokensPerCall"] = max(
            item["maxOutputTokensPerCall"], record.output_tokens
        )
        item["costUsd"] += Decimal(record.cost_usd)
    for item in summary.values():
        item["costUsd"] = str(item["costUsd"])
        if "reservedCostUsd" in item:
            item["reservedCostUsd"] = str(item["reservedCostUsd"])
    return dict(sorted(summary.items()))


def _rate_for(model: str, rate_card) -> ModelRate:
    rates = {
        rate.model: rate
        for rate in (*getattr(rate_card, "candidates", ()), rate_card.judge)
    }
    if model not in rates:
        raise RuntimeError(f"Provider reported unpriced model {model!r}")
    return rates[model]


def _spend_rates(rate_card) -> str:
    rates = {
        rate.model: rate
        for rate in (*getattr(rate_card, "candidates", ()), rate_card.judge)
    }
    return json.dumps(
        {
            model: {
                "input": str(rate.input_per_million),
                "output": str(rate.output_per_million),
            }
            for model, rate in rates.items()
        },
        sort_keys=True,
    )


def _reconcile_usage(
    *,
    usage: list[dict],
    direct_records: list,
    guard: BudgetGuard,
    rate_card,
    run_id: str,
    scenario_id: str,
) -> None:
    if direct_records:
        if any(
            record.run_id != run_id or record.scenario_id != scenario_id
            for record in direct_records
        ):
            raise RuntimeError(
                f"{scenario_id}: direct spend ledger contains another execution"
            )
        if usage and len(direct_records) != len(usage):
            raise RuntimeError(
                f"{scenario_id}: direct ledger has {len(direct_records)} new "
                f"records but worker usage log has {len(usage)}"
            )
        direct_usage = Counter(
            (record.model, record.input_tokens, record.output_tokens)
            for record in direct_records
        )
        logged_usage = Counter(
            (item.get("model"), item.get("input_tokens"), item.get("output_tokens"))
            for item in usage
        )
        if usage and direct_usage != logged_usage:
            raise RuntimeError(
                f"{scenario_id}: direct spend ledger differs from worker usage"
            )
        return
    for index, item in enumerate(usage):
        guard.record_usage(
            run_id=run_id,
            scenario_id=scenario_id,
            pipeline=f"provider-call-{index + 1}",
            rate=_rate_for(item["model"], rate_card),
            input_tokens=item.get("input_tokens"),
            output_tokens=item.get("output_tokens"),
        )


def _ambiguous_worker_failure(completed, failed_result: dict) -> bool:
    detail = str(failed_result.get("executionError", ""))
    transient_types = (
        "APITimeoutError:",
        "APIConnectionError:",
        "APIStatusError:",
        "ConflictError:",
        "InternalServerError:",
        "RateLimitError:",
    )
    missing_usage_markers = (
        "QA provider response omitted token usage",
        "QA provider response reported no token usage",
        "Provider omitted paid token usage",
    )
    return (
        completed.returncode == 124
        or detail.startswith(transient_types)
        or any(f"({error_type}" in detail for error_type in transient_types)
        or any(marker in detail for marker in missing_usage_markers)
    )


def _ambiguous_failure_reserve(
    *, scenario, rate_card, candidate_model: str, failed_result: dict
) -> tuple[str, Decimal]:
    if failed_result.get("executionStage") == "judge":
        return (
            rate_card.judge.model,
            rate_card.judge.cost(JUDGE_INPUT_CEILING, JUDGE_OUTPUT_CEILING),
        )
    # The pipeline may be in a candidate, guide, citation, MCQ, title, or
    # suggestion call. Its preflight reserve prices the complete worker at the
    # highest configured rate and covers known parallel fan-out.
    return candidate_model, worker_cost_reserve(
        scenario, rate_card, candidate_models=(candidate_model,)
    )


def _evaluate(scenario, model: str, payload: dict, qa_root: Path) -> ScenarioEvaluation:
    activities = [
        ActivityTrace(
            name=item.get("name", "unknown"),
            state=item.get("state", "FINISHED"),
            detail=item.get("detail"),
            result=item.get("result"),
        )
        for item in payload.get("activities", [])
    ]
    evaluation = evaluate_deterministic(
        scenario,
        model=model,
        response=payload.get("response"),
        activities=activities,
        fixture_root=qa_root / "artifacts",
        product_diagnostics=payload.get("diagnostics"),
    )
    evaluation.execution_error = payload.get("executionError")
    judge = payload.get("judge") or {}
    evaluation.semantic_scores = {
        key: float(value) for key, value in judge.get("scores", {}).items()
    }
    evaluation.semantic_weights = {
        criterion.id: criterion.weight for criterion in scenario.expectations.rubric
    }
    evaluation.semantic_evidence = judge.get("evidence", {})
    critical_failures = set(judge.get("criticalFailures", []))
    for criterion in scenario.expectations.rubric:
        if criterion.critical:
            failed = criterion.id in critical_failures
            evaluation.checks.append(
                CheckResult(
                    id=f"semantic:{criterion.id}",
                    passed=not failed,
                    message=(
                        f"Critical semantic criterion {criterion.id} passed."
                        if not failed
                        else f"Critical semantic criterion {criterion.id} failed: "
                        f"{evaluation.semantic_evidence.get(criterion.id, '')}"
                    ),
                    critical=True,
                )
            )
    return evaluation


def _aggregate_passes(
    evaluations: list[ScenarioEvaluation],
    *,
    critical_keys: set[tuple[str, str]],
) -> tuple[bool, dict]:
    total = len(evaluations)
    grouped: dict[tuple[str, str], list[ScenarioEvaluation]] = {}
    for item in evaluations:
        grouped.setdefault((item.scenario_id, item.model), []).append(item)
    group_passes = {}
    for key, samples in grouped.items():
        required = len(samples) // 2 + 1
        group_passes[key] = sum(sample.passed for sample in samples) >= required
    pass_rate = sum(group_passes.values()) / len(group_passes) if grouped else 0
    mean_score = sum(item.score for item in evaluations) / total if total else 0
    critical_pass = all(
        key in group_passes and group_passes[key] for key in critical_keys
    )
    gates = {
        "meanScore": mean_score,
        "passRate": pass_rate,
        "criticalPassRate": 1.0 if critical_pass else 0.0,
        "thresholds": {"meanScore": 0.80, "passRate": 0.85, "criticalPassRate": 1.0},
    }
    return mean_score >= 0.80 and pass_rate >= 0.85 and critical_pass, gates


def run_paid_suite(
    *,
    qa_root: Path,
    scenarios: list,
    rate_card,
    ledger_path: Path,
    hard_limit: Decimal,
    development_hard_limit: Decimal,
    max_run_cost: Decimal,
    output_dir: Path,
    repetitions: int,
    critical_repetitions: int,
    transient_retries: int = 0,
    transient_retry_allowance: Decimal = Decimal(0),
    baseline_path: Path | None = None,
    deployment_verification: dict | None = None,
    planned_cost: Decimal | None = None,
    starting_spend: Decimal = Decimal(0),
    models: Sequence[str] = CANDIDATE_MODELS,
) -> int:
    if (
        not isinstance(transient_retries, int)
        or isinstance(transient_retries, bool)
        or not 0 <= transient_retries <= MAX_TRANSIENT_RETRIES
    ):
        raise ValueError(
            f"transient_retries must be between 0 and {MAX_TRANSIENT_RETRIES}"
        )
    if not transient_retry_allowance.is_finite() or transient_retry_allowance < 0:
        raise ValueError("transient_retry_allowance must be finite and nonnegative")
    selected_models = tuple(dict.fromkeys(models))
    unknown_models = set(selected_models) - set(CANDIDATE_MODELS)
    if not selected_models or unknown_models:
        raise ValueError("A valid candidate model selection is required")
    # Validate auth mode, endpoint, candidate, auxiliary, and judge deployment
    # bindings before creating a result directory or printing a run as started.
    environment_probe = create_worker_configuration(rate_card, selected_models[0])
    environment_probe.close()
    run_id = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    )
    scenario_fingerprints = _scenario_fingerprints(scenarios)
    corpus_fingerprint = hashlib.sha256(
        json.dumps(scenario_fingerprints, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    source_fingerprint = _source_fingerprint(qa_root)
    output_dir = output_dir.resolve() / run_id
    output_dir.mkdir(parents=True, exist_ok=False)
    guard = BudgetGuard(SpendLedger(ledger_path), hard_limit)
    evaluations: list[ScenarioEvaluation] = []
    raw_dir = output_dir / "raw"
    raw_dir.mkdir()
    per_model_runs = sum(
        critical_repetitions if scenario.risk == RiskLevel.CRITICAL else repetitions
        for scenario in scenarios
    )
    total_runs = len(selected_models) * per_model_runs
    completed_runs = 0
    worker_attempt_count = 0
    transient_retries_used = 0
    execution_attempts: list[dict] = []
    print(f"Iris QA run {run_id}: {total_runs} isolated scenario/model executions")
    if transient_retries:
        print(
            f"Global ambiguous-failure retry allowance: {transient_retries} "
            f"extra attempt(s), budgeted at ${transient_retry_allowance:.4f}"
        )

    for model in selected_models:
        configuration = create_worker_configuration(rate_card, model)
        try:
            for scenario in scenarios:
                scenario_repetitions = (
                    critical_repetitions
                    if scenario.risk == RiskLevel.CRITICAL
                    else repetitions
                )
                for repetition in range(1, scenario_repetitions + 1):
                    completed_runs += 1
                    attempt = 0
                    ambiguous_failures = 0
                    raw_files: list[str] = []
                    worker_reserve = worker_cost_reserve(
                        scenario, rate_card, candidate_models=(model,)
                    )
                    while True:
                        attempt += 1
                        worker_attempt_count += 1
                        guard.require_capacity(worker_reserve)
                        ledger_count_before = len(guard.ledger.records())
                        attempt_label = "" if attempt == 1 else f" retry {attempt - 1}"
                        print(
                            f"[{completed_runs:>3}/{total_runs}] {model:<12} "
                            f"{scenario.id} r{repetition} a{attempt}{attempt_label}",
                            flush=True,
                        )
                        with tempfile.TemporaryDirectory(
                            prefix="iris-qa-worker-"
                        ) as temp:
                            temp_root = Path(temp)
                            scenario_path = temp_root / "scenario.json"
                            result_path = temp_root / "result.json"
                            usage_path = temp_root / "usage.jsonl"
                            scenario_path.write_text(
                                scenario.model_dump_json(by_alias=True),
                                encoding="utf-8",
                            )
                            environment = dict(configuration.environment)
                            total_input, total_output = worker_token_ceiling(scenario)
                            environment.update(
                                IRIS_QA_PROVIDER_USAGE_LOG=str(usage_path),
                                IRIS_QA_MAX_OUTPUT_TOKENS=str(
                                    scenario.token_ceiling.max_output_tokens_per_call
                                ),
                                IRIS_QA_MAX_AGENT_TURNS=str(
                                    scenario.token_ceiling.max_agent_turns
                                ),
                                IRIS_QA_MAX_TOTAL_INPUT_TOKENS=str(total_input),
                                IRIS_QA_MAX_TOTAL_OUTPUT_TOKENS=str(total_output),
                                IRIS_QA_SPEND_LEDGER=str(ledger_path.resolve()),
                                IRIS_QA_SPEND_RATES=_spend_rates(rate_card),
                                IRIS_QA_SPEND_HARD_LIMIT_USD=str(hard_limit),
                                IRIS_QA_SPEND_RUN_ID=run_id,
                                IRIS_QA_SPEND_SCENARIO_ID=scenario.id,
                                IRIS_QA_SPEND_PIPELINE=f"provider-call-a{attempt}",
                            )
                            completed: (
                                subprocess.CompletedProcess[str] | SimpleNamespace
                            )
                            try:
                                completed = subprocess.run(  # nosec B603
                                    [
                                        sys.executable,
                                        "-m",
                                        "iris.qa.worker",
                                        "--input",
                                        str(scenario_path),
                                        "--output",
                                        str(result_path),
                                    ],
                                    env=environment,
                                    capture_output=True,
                                    text=True,
                                    timeout=900,
                                    check=False,
                                )
                            except subprocess.TimeoutExpired as error:
                                completed = SimpleNamespace(
                                    returncode=124,
                                    stderr=f"worker timed out after {error.timeout}s",
                                )
                            usage = _usage_records(usage_path)
                            direct_records = guard.ledger.records()[
                                ledger_count_before:
                            ]
                            failed_result = {}
                            if result_path.exists():
                                try:
                                    failed_result = json.loads(
                                        result_path.read_text(encoding="utf-8")
                                    )
                                except (OSError, json.JSONDecodeError):
                                    failed_result = {}
                            ambiguous_failure = (
                                completed.returncode != 0
                                and _ambiguous_worker_failure(completed, failed_result)
                            )
                            if (
                                not usage
                                and not direct_records
                                and completed.returncode == 0
                            ):
                                raise RuntimeError(
                                    f"{scenario.id}/{model}: worker succeeded "
                                    "without provider usage; refusing non-model "
                                    "QA evidence"
                                )
                            if (
                                not usage
                                and not direct_records
                                and not ambiguous_failure
                                and not failed_result
                            ):
                                raise RuntimeError(
                                    f"{scenario.id}/{model}: worker emitted no "
                                    "provider usage; stopping because an unreported "
                                    "charge cannot be ruled out"
                                )
                            _reconcile_usage(
                                usage=usage,
                                direct_records=direct_records,
                                guard=guard,
                                rate_card=rate_card,
                                run_id=run_id,
                                scenario_id=scenario.id,
                            )
                            if completed.returncode != 0:
                                detail = completed.stderr[-2000:]
                                detail = failed_result.get("executionError", detail)
                                if ambiguous_failure:
                                    ambiguous_failures += 1
                                    reserved_model, reserve = (
                                        _ambiguous_failure_reserve(
                                            scenario=scenario,
                                            rate_card=rate_card,
                                            candidate_model=model,
                                            failed_result=failed_result,
                                        )
                                    )
                                    guard.record_reservation(
                                        run_id=run_id,
                                        scenario_id=scenario.id,
                                        pipeline=(
                                            "ambiguous-provider-call-reserve-"
                                            f"a{attempt}"
                                        ),
                                        model=reserved_model,
                                        cost_usd=reserve,
                                    )
                                elif not failed_result:
                                    raise RuntimeError(
                                        f"{scenario.id}/{model}: worker exited "
                                        f"{completed.returncode} after known usage "
                                        "was reconciled; stopping because another "
                                        "billable call cannot be ruled out: "
                                        f"{detail}"
                                    )
                                failed_result.update(
                                    scenarioId=scenario.id,
                                    model=model,
                                    executionError=detail,
                                )
                                failed_result.setdefault("response", None)
                                failed_result.setdefault("activities", [])
                                failed_result.setdefault("judge", {})
                                result = failed_result
                            elif result_path.exists():
                                result = json.loads(
                                    result_path.read_text(encoding="utf-8")
                                )
                            else:
                                result = {
                                    "response": None,
                                    "activities": [],
                                    "judge": {},
                                    "executionError": (
                                        f"worker exited {completed.returncode}: "
                                        f"{completed.stderr[-2000:]}"
                                    ),
                                }

                            provider_records = usage or [
                                {"model": record.model} for record in direct_records
                            ]
                            diagnostics = result.setdefault("diagnostics", {})
                            diagnostics["candidateProviderCalls"] = sum(
                                item.get("model") == model for item in provider_records
                            )
                            result["qaAttempt"] = {
                                "repetition": repetition,
                                "attempt": attempt,
                                "retry": attempt > 1,
                                "ambiguousFailure": ambiguous_failure,
                            }
                            raw_name = (
                                f"{scenario.id}--{model}--r{repetition}--"
                                f"a{attempt}.json"
                            )
                            (raw_dir / raw_name).write_text(
                                json.dumps(result, indent=2, ensure_ascii=False),
                                encoding="utf-8",
                            )
                            raw_files.append(raw_name)

                        if ambiguous_failure and (
                            transient_retries_used < transient_retries
                        ):
                            # The failed attempt's full conservative reservation
                            # is already durable. Require another complete worker
                            # before consuming one global retry slot.
                            guard.require_capacity(worker_reserve)
                            transient_retries_used += 1
                            print(
                                "            RETRY ambiguous transient failure "
                                f"({transient_retries_used}/{transient_retries}) "
                                f"spent=${guard.ledger.total():.4f}",
                                flush=True,
                            )
                            continue

                        evaluation = _evaluate(scenario, model, result, qa_root)
                        evaluations.append(evaluation)
                        status = "PASS" if evaluation.passed else "FAIL"
                        execution_attempts.append(
                            {
                                "scenarioId": scenario.id,
                                "model": model,
                                "repetition": repetition,
                                "attempts": attempt,
                                "retriesUsed": attempt - 1,
                                "ambiguousFailures": ambiguous_failures,
                                "finalOutcome": status,
                                "rawFiles": raw_files,
                            }
                        )
                        print(
                            f"            {status} score={evaluation.score:.3f} "
                            f"attempts={attempt} "
                            f"spent=${guard.ledger.total():.4f}",
                            flush=True,
                        )
                        break
        finally:
            configuration.close()

    critical_keys = {
        (scenario.id, model)
        for scenario in scenarios
        if scenario.requires_critical_gate
        for model in selected_models
    }
    passed, gates = _aggregate_passes(evaluations, critical_keys=critical_keys)
    regressions: list[Regression] = []
    provisional: list[str] = []
    if baseline_path is not None:
        regressions, provisional = compare_baseline(
            evaluations,
            load_baseline(baseline_path),
            current_scenario_hashes=scenario_fingerprints,
            current_judge_deployment=(deployment_verification or {})
            .get("deployments", {})
            .get("gpt-5.4"),
        )
        passed = passed and not regressions
    gates["regressions"] = [regression.__dict__ for regression in regressions]
    gates["provisionalBaselineKeys"] = provisional
    cumulative_spend = guard.ledger.total()
    cumulative_reserve = sum(
        (
            Decimal(record.cost_usd)
            for record in guard.ledger.records()
            if record.reservation
        ),
        Decimal(0),
    )
    run_records = [
        record for record in guard.ledger.records() if record.run_id == run_id
    ]
    run_spend = sum((Decimal(record.cost_usd) for record in run_records), Decimal(0))
    ambiguous_reserve = sum(
        (Decimal(record.cost_usd) for record in run_records if record.reservation),
        Decimal(0),
    )
    metadata = {
        "runId": run_id,
        "models": list(selected_models),
        "repetitions": repetitions,
        "criticalRepetitions": critical_repetitions,
        "transientRetriesConfigured": transient_retries,
        "transientRetriesUsed": transient_retries_used,
        "transientRetryAllowanceUsd": str(transient_retry_allowance),
        "workerAttemptCount": worker_attempt_count,
        "executionAttempts": execution_attempts,
        "gates": gates,
        "accountedSpendUsd": str(cumulative_spend),
        "measuredUsageSpendUsd": str(cumulative_spend - cumulative_reserve),
        "runSpendUsd": str(run_spend),
        "measuredRunSpendUsd": str(run_spend - ambiguous_reserve),
        "ambiguousReserveUsd": str(ambiguous_reserve),
        "startingSpendUsd": str(starting_spend),
        "plannedCostUsd": str(planned_cost) if planned_cost is not None else None,
        "rateSource": rate_card.source,
        "rateCard": json.loads(_spend_rates(rate_card)),
        "providerUsage": _usage_summary(run_records),
        "corpusSha256": corpus_fingerprint,
        "scenarioSha256": scenario_fingerprints,
        "irisSourceSha256": source_fingerprint,
        "hardLimitUsd": str(hard_limit),
        "developmentHardLimitUsd": str(development_hard_limit),
        "runMaxCostUsd": str(max_run_cost),
        "preliminary": repetitions == 1,
        "baseline": str(baseline_path) if baseline_path else None,
        "azureDeployments": (deployment_verification or {}).get("deployments"),
    }
    write_json_report(output_dir / "report.json", evaluations, metadata=metadata)
    write_markdown_report(output_dir / "report.md", evaluations, metadata=metadata)
    write_junit_report(output_dir / "junit.xml", evaluations)
    print(f"Iris QA report: {output_dir / 'report.md'}")
    label = (
        "Accounted run spend upper bound" if ambiguous_reserve else "Actual run spend"
    )
    print(f"{label}: ${run_spend:.4f}")
    if ambiguous_reserve:
        print(f"Ambiguous-call reserve: ${ambiguous_reserve:.4f}")
    print(f"Accounted cumulative spend: ${cumulative_spend:.4f} / ${hard_limit:.2f}")
    return 0 if passed else 1
