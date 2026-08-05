from __future__ import annotations

import json
import re
import subprocess  # nosec B404 - fixed local module invocation
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from iris.qa.bootstrap import create_worker_configuration
from iris.qa.cost import BudgetGuard, ModelRate, SpendLedger
from iris.qa.evaluate import ScenarioEvaluation, evaluation_from_worker
from iris.qa.planning import RateCard, trial_reserve
from iris.qa.report import write_json_report, write_markdown_report


def _rates(rate_card: RateCard) -> dict[str, ModelRate]:
    return {
        rate.model: rate
        for rate in (*rate_card.candidates, rate_card.judge, rate_card.auxiliary)
    }


def _git_value(iris_root: Path, *args: str) -> str:
    completed = subprocess.run(  # nosec B603 B607 - fixed git arguments
        ["git", *args],
        cwd=iris_root,
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip() if completed.returncode == 0 else "unknown"


def trial_stem(model: str, scenario_id: str, repetition: int) -> str:
    """Build a stable filename without interpreting model IDs as paths."""
    safe_model = re.sub(r"[^A-Za-z0-9._-]+", "-", model).strip(".-")
    if not safe_model:
        raise ValueError(f"Model ID has no filename-safe characters: {model!r}")
    return f"{safe_model}-{scenario_id}-r{repetition}"


def run_paid_suite(
    *,
    qa_root: Path,
    scenarios: list,
    models: tuple[str, ...],
    repetitions: int,
    rate_card: RateCard,
    ledger: SpendLedger,
    hard_limit: Decimal,
    max_run_cost: Decimal,
    planned_cost: Decimal,
    output_root: Path | None = None,
) -> tuple[int, Path, list[ScenarioEvaluation]]:
    """Run each scenario through production Iris and the independent judge."""
    run_id = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{uuid4().hex[:8]}"
    )
    result_root = output_root or qa_root / "qa-results" / run_id
    raw_root = result_root / "raw"
    raw_root.mkdir(parents=True, exist_ok=False)
    guard = BudgetGuard(ledger, hard_limit)
    model_rates = _rates(rate_card)
    run_start_total = ledger.total()
    evaluations: list[ScenarioEvaluation] = []

    for model in models:
        configuration = create_worker_configuration(rate_card, model)
        try:
            for scenario in scenarios:
                for repetition in range(1, repetitions + 1):
                    reserve = trial_reserve(scenario, rate_card, model)
                    guard.require_capacity(reserve)
                    if ledger.total() - run_start_total + reserve > max_run_cost:
                        raise RuntimeError(
                            "Next scenario would exceed --max-cost-usd; "
                            "stopping before the paid call"
                        )
                    stem = trial_stem(model, scenario.id, repetition)
                    input_path = raw_root / f"{stem}.input.json"
                    output_path = raw_root / f"{stem}.output.json"
                    input_path.write_text(
                        scenario.model_dump_json(by_alias=True, indent=2),
                        encoding="utf-8",
                    )
                    started = time.monotonic()
                    completed = subprocess.run(  # nosec B603 - fixed Python module
                        [
                            sys.executable,
                            "-m",
                            "iris.qa.worker",
                            "--input",
                            str(input_path),
                            "--output",
                            str(output_path),
                        ],
                        cwd=qa_root.parent,
                        env=configuration.environment,
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=900,
                    )
                    duration = time.monotonic() - started
                    if output_path.exists():
                        payload = json.loads(output_path.read_text(encoding="utf-8"))
                    else:
                        payload = {
                            "response": None,
                            "activities": [],
                            "usage": [],
                            "executionError": (
                                f"Worker exited {completed.returncode} without a result"
                            ),
                        }
                    if completed.returncode and not payload.get("executionError"):
                        payload["executionError"] = (
                            f"Worker exited {completed.returncode}"
                        )
                    if completed.stderr:
                        (raw_root / f"{stem}.stderr.txt").write_text(
                            completed.stderr, encoding="utf-8"
                        )

                    accounted = False
                    for usage in payload.get("usage", []):
                        usage_model = str(usage.get("model", ""))
                        rate = model_rates.get(usage_model)
                        if rate is None:
                            payload["executionError"] = (
                                f"Unknown billed model in usage: {usage_model}"
                            )
                            continue
                        guard.record_usage(
                            run_id=run_id,
                            scenario_id=scenario.id,
                            pipeline=str(usage.get("pipeline", "unknown")),
                            rate=rate,
                            input_tokens=usage.get("inputTokens"),
                            output_tokens=usage.get("outputTokens"),
                        )
                        accounted = True
                    if completed.returncode and not accounted:
                        guard.record_reservation(
                            run_id=run_id,
                            scenario_id=scenario.id,
                            pipeline="failed-worker-upper-bound",
                            model=model,
                            cost_usd=reserve,
                        )

                    try:
                        evaluation = evaluation_from_worker(
                            scenario,
                            model=model,
                            repetition=repetition,
                            payload=payload,
                            duration_seconds=duration,
                        )
                    except ValueError as error:
                        payload["executionError"] = f"Invalid judge result: {error}"
                        evaluation = evaluation_from_worker(
                            scenario,
                            model=model,
                            repetition=repetition,
                            payload=payload,
                            duration_seconds=duration,
                        )
                    evaluations.append(evaluation)
                    status = (
                        f"ERROR {evaluation.execution_error}"
                        if evaluation.execution_error
                        else f"IrisScore {evaluation.score:.1f}"
                    )
                    print(
                        f"[{len(evaluations):>3}] {model:<14} "
                        f"{scenario.id:<38} run {repetition}: {status}",
                        flush=True,
                    )
        finally:
            configuration.close()

    iris_root = qa_root.parent
    metadata = {
        "runId": run_id,
        "sourceCommit": _git_value(iris_root, "rev-parse", "HEAD"),
        "sourceBranch": _git_value(iris_root, "branch", "--show-current"),
        "models": list(models),
        "repetitions": repetitions,
        "scenarioCount": len(scenarios),
        "plannedUpperBoundUsd": str(planned_cost),
        "measuredLedgerSpendUsd": str(ledger.total() - run_start_total),
        "rateSource": rate_card.source,
    }
    write_json_report(result_root / "report.json", evaluations, metadata=metadata)
    write_markdown_report(result_root / "report.md", evaluations, metadata=metadata)
    has_execution_errors = any(item.execution_error for item in evaluations)
    return (1 if has_execution_errors else 0), result_root, evaluations
