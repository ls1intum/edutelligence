from __future__ import annotations

import json
import shutil
import subprocess  # nosec B404 - fixed local module invocation
import sys
from decimal import Decimal
from pathlib import Path

from iris.qa.bootstrap import create_worker_configuration
from iris.qa.cost import BudgetGuard, SpendLedger
from iris.qa.evaluate import ScenarioEvaluation, evaluation_from_worker
from iris.qa.planning import JUDGE_INPUT_CEILING, JUDGE_OUTPUT_CEILING, RateCard
from iris.qa.report import write_json_report, write_markdown_report


def rejudge_saved_runs(
    *,
    input_roots: list[Path],
    output_root: Path,
    scenarios: dict,
    models: tuple[str, ...],
    scenario_ids: set[str] | None,
    rate_card: RateCard,
    ledger: SpendLedger,
    hard_limit: Decimal,
    max_run_cost: Decimal,
    resume: bool = False,
) -> tuple[int, list[ScenarioEvaluation]]:
    """Re-evaluate saved candidate answers without invoking candidates again."""
    raw_root = output_root / "raw"
    raw_root.mkdir(parents=True, exist_ok=resume)
    guard = BudgetGuard(ledger, hard_limit)
    run_start_total = ledger.total()
    evaluations: list[ScenarioEvaluation] = []
    seen: set[tuple[str, str, int]] = set()

    for input_root in input_roots:
        report = json.loads((input_root / "report.json").read_text(encoding="utf-8"))
        for saved in report.get("evaluations", []):
            model = saved["model"]
            if model not in models or (
                scenario_ids and saved["scenario_id"] not in scenario_ids
            ):
                continue
            identity = (model, saved["scenario_id"], int(saved["repetition"]))
            if identity in seen:
                raise ValueError(f"Duplicate saved trial: {identity}")
            seen.add(identity)
            scenario = scenarios.get(saved["scenario_id"])
            if scenario is None:
                raise ValueError(
                    f"Saved run references unknown scenario: {identity[1]}"
                )

            stem = f"{model}-{identity[1]}-r{identity[2]}"
            source_input = input_root / "raw" / f"{stem}.input.json"
            source_output = input_root / "raw" / f"{stem}.output.json"
            target_input = raw_root / f"{stem}.input.json"
            target_output = raw_root / f"{stem}.output.json"

            if resume and target_output.exists():
                payload = json.loads(target_output.read_text(encoding="utf-8"))
                evaluations.append(
                    evaluation_from_worker(
                        scenario,
                        model=model,
                        repetition=identity[2],
                        payload=payload,
                        duration_seconds=float(saved.get("duration_seconds", 0)),
                    )
                )
                print(f"[{len(evaluations):>3}] {model:<15} {identity[1]:<38} reused")
                continue

            interrupted_call = resume and target_input.exists()
            shutil.copy2(source_input, target_input)
            payload = json.loads(source_output.read_text(encoding="utf-8"))

            if not payload.get("executionError"):
                reserve = rate_card.judge.cost(
                    JUDGE_INPUT_CEILING, JUDGE_OUTPUT_CEILING
                )
                if interrupted_call:
                    guard.record_reservation(
                        run_id=f"rejudge-{output_root.name}",
                        scenario_id=identity[1],
                        pipeline="interrupted-rejudge-upper-bound",
                        model=rate_card.judge.model,
                        cost_usd=reserve,
                    )
                guard.require_capacity(reserve)
                if ledger.total() - run_start_total + reserve > max_run_cost:
                    raise RuntimeError(
                        "Next judge call would exceed --max-cost-usd; stopping before "
                        "the paid call"
                    )
                configuration = create_worker_configuration(rate_card, model)
                try:
                    completed = subprocess.run(  # nosec B603 - fixed Python module
                        [
                            sys.executable,
                            "-m",
                            "iris.qa.worker",
                            "--input",
                            str(target_input),
                            "--output",
                            str(target_output),
                            "--rejudge-from",
                            str(source_output),
                        ],
                        cwd=output_root.parents[1],
                        env=configuration.environment,
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=900,
                    )
                finally:
                    configuration.close()
                if not target_output.exists():
                    raise RuntimeError(
                        f"Judge worker exited {completed.returncode} without a result"
                    )
                payload = json.loads(target_output.read_text(encoding="utf-8"))
                usage = payload.get("rejudgeUsage")
                if not isinstance(usage, dict):
                    worker_error = payload.get("executionError")
                    raise RuntimeError(
                        f"Judge worker failed for {identity}: {worker_error}"
                    )
                guard.record_usage(
                    run_id=f"rejudge-{output_root.name}",
                    scenario_id=identity[1],
                    pipeline="qa-rejudge",
                    rate=rate_card.judge,
                    input_tokens=usage.get("inputTokens"),
                    output_tokens=usage.get("outputTokens"),
                )
            else:
                shutil.copy2(source_output, target_output)

            evaluations.append(
                evaluation_from_worker(
                    scenario,
                    model=model,
                    repetition=identity[2],
                    payload=payload,
                    duration_seconds=float(saved.get("duration_seconds", 0)),
                )
            )
            print(
                f"[{len(evaluations):>3}] {model:<15} {identity[1]:<38} "
                f"IrisScore {evaluations[-1].score:.1f}",
                flush=True,
            )

    metadata = {
        "models": list(models),
        "scenarioCount": len({item.scenario_id for item in evaluations}),
        "repetitions": max((item.repetition for item in evaluations), default=0),
        "rejudgedFrom": [str(path.resolve()) for path in input_roots],
        "candidateModelsInvoked": False,
        "judgeContext": "production instructions and derived metrics",
        "measuredRejudgeSpendUsd": str(ledger.total() - run_start_total),
        "rateSource": rate_card.source,
    }
    write_json_report(output_root / "report.json", evaluations, metadata=metadata)
    write_markdown_report(output_root / "report.md", evaluations, metadata=metadata)
    return (1 if any(item.execution_error for item in evaluations) else 0), evaluations
