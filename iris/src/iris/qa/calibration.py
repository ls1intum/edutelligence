from __future__ import annotations

import json
import subprocess  # nosec B404 - fixed local Python module invocation
import sys
import tempfile
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import yaml

from iris.qa.planning import JUDGE_INPUT_CEILING, JUDGE_OUTPUT_CEILING
from iris.qa.schema import Scenario
from iris.qa.yaml_utils import safe_load_unique

# pylint: disable=import-outside-toplevel,inconsistent-quotes


@dataclass(frozen=True)
class CalibrationCase:
    id: str
    scenario: Scenario
    answer: str | None
    activities: list[str]
    diagnostics: dict
    expected: dict[str, tuple[float, float]]


def load_calibration(path: Path, scenarios: list[Scenario]) -> list[CalibrationCase]:
    try:
        raw = safe_load_unique(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ValueError(
            f"Cannot read judge calibration set {path}: {error}"
        ) from error
    if not isinstance(raw, dict):
        raise ValueError("Calibration set must be a YAML mapping")
    if raw.get("version") != 1 or not isinstance(raw.get("cases"), list):
        raise ValueError("Calibration set must contain version 1 and a cases list")
    by_id = {scenario.id: scenario for scenario in scenarios}
    cases = []
    for item in raw["cases"]:
        if not isinstance(item, dict):
            raise ValueError("Each calibration case must be a YAML mapping")
        scenario_id = item.get("scenario")
        if not isinstance(scenario_id, str):
            raise ValueError("Each calibration case must name a scenario")
        scenario = by_id.get(scenario_id)
        if scenario is None:
            raise ValueError(f"Unknown calibration scenario {scenario_id}")
        diagnostics = item.get("diagnostics", {})
        if not isinstance(diagnostics, dict):
            raise ValueError(f"Invalid diagnostics in {item.get('id')}")
        unknown_diagnostics = set(diagnostics) - {
            "confidence",
            "sources",
            "terminalState",
        }
        if unknown_diagnostics:
            raise ValueError(
                f"Unknown diagnostics in {item.get('id')}: "
                f"{sorted(unknown_diagnostics)}"
            )
        sources = diagnostics.get("sources")
        if sources is not None and (
            not isinstance(sources, list)
            or len(sources) > 10
            or any(not isinstance(source, dict) for source in sources)
        ):
            raise ValueError(f"Invalid diagnostic sources in {item.get('id')}")
        expected = {}
        for criterion, bounds in item.get("expected", {}).items():
            if criterion not in {entry.id for entry in scenario.expectations.rubric}:
                raise ValueError(f"Unknown criterion {criterion} in {item.get('id')}")
            if not isinstance(bounds, list) or len(bounds) != 2:
                raise ValueError(f"Invalid bounds for {criterion} in {item.get('id')}")
            low, high = map(float, bounds)
            if not 0 <= low <= high <= 1:
                raise ValueError(f"Bounds outside 0..1 for {criterion}")
            expected[criterion] = (low, high)
        if set(expected) != {entry.id for entry in scenario.expectations.rubric}:
            raise ValueError(
                f"Calibration case {item.get('id')} must label every criterion"
            )
        cases.append(
            CalibrationCase(
                id=item["id"],
                scenario=scenario,
                answer=item.get("answer"),
                activities=list(item.get("activities", [])),
                diagnostics=diagnostics,
                expected=expected,
            )
        )
    if len(cases) != 14 or len({case.id for case in cases}) != 14:
        raise ValueError("The judge calibration set must contain 14 unique cases")
    return cases


def assess_calibration(
    cases: list[CalibrationCase],
    scores: dict[str, dict[str, float]],
    evidence: dict[str, dict[str, str]] | None = None,
) -> dict:
    evidence = evidence or {}
    criteria_total = 0
    criteria_correct = 0
    case_correct = 0
    details = []
    for case in cases:
        actual = scores.get(case.id, {})
        checks = {
            criterion: low <= float(actual.get(criterion, -1)) <= high
            for criterion, (low, high) in case.expected.items()
        }
        criteria_total += len(checks)
        criteria_correct += sum(checks.values())
        case_correct += all(checks.values())
        details.append(
            {
                "id": case.id,
                "checks": checks,
                "expected": {
                    criterion: [low, high]
                    for criterion, (low, high) in case.expected.items()
                },
                "scores": actual,
                "evidence": evidence.get(case.id, {}),
            }
        )
    criterion_accuracy = criteria_correct / criteria_total
    case_accuracy = case_correct / len(cases)
    return {
        "criterionAccuracy": criterion_accuracy,
        "caseAccuracy": case_accuracy,
        "passed": criterion_accuracy >= 0.85 and case_accuracy >= 0.75,
        "details": details,
    }


def run_calibration(
    *,
    cases: list[CalibrationCase],
    rate_card,
    ledger_path: Path,
    hard_limit: Decimal,
    max_cost: Decimal,
    output: Path,
    deployment_verification: dict | None = None,
) -> dict:
    from iris.qa.bootstrap import create_worker_configuration
    from iris.qa.cost import BudgetGuard, SpendLedger
    from iris.qa.run import _reconcile_usage, _spend_rates

    if (
        not hard_limit.is_finite()
        or not max_cost.is_finite()
        or hard_limit <= 0
        or max_cost <= 0
    ):
        raise ValueError("Calibration budgets must be greater than zero")
    estimate = rate_card.judge.cost(JUDGE_INPUT_CEILING, JUDGE_OUTPUT_CEILING) * len(
        cases
    )
    if estimate > max_cost:
        raise ValueError(
            f"Calibration refused: pessimistic ${estimate:.4f} exceeds "
            f"--max-cost-usd ${max_cost:.4f}"
        )
    ledger = SpendLedger(ledger_path)
    starting_spend = ledger.total()
    invocation_hard_limit = min(hard_limit, starting_spend + max_cost)
    guard = BudgetGuard(ledger, invocation_hard_limit)
    guard.require_capacity(estimate)
    config = create_worker_configuration(rate_card, "gpt-5.4-mini")
    scores = {}
    evidence = {}
    judge_call_reserve = rate_card.judge.cost(JUDGE_INPUT_CEILING, JUDGE_OUTPUT_CEILING)

    def reserve_unreported_call(case_id: str, ledger_count_before: int) -> None:
        if len(guard.ledger.records()) != ledger_count_before:
            return
        guard.record_reservation(
            run_id="judge-calibration",
            scenario_id=case_id,
            pipeline="ambiguous-provider-call-reserve",
            model=rate_card.judge.model,
            cost_usd=judge_call_reserve,
        )

    def record_flushed_usage(
        path: Path, case_id: str, ledger_count_before: int
    ) -> list[dict]:
        if not path.exists():
            records = []
        else:
            records = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        for usage in records:
            if usage.get("model") != rate_card.judge.model:
                raise RuntimeError(
                    f"Calibration case {case_id} used {usage.get('model')!r}; "
                    f"expected independent judge {rate_card.judge.model!r}"
                )
        _reconcile_usage(
            usage=records,
            direct_records=guard.ledger.records()[ledger_count_before:],
            guard=guard,
            rate_card=rate_card,
            run_id="judge-calibration",
            scenario_id=case_id,
        )
        return records

    try:
        for index, case in enumerate(cases, 1):
            guard.require_capacity(
                rate_card.judge.cost(JUDGE_INPUT_CEILING, JUDGE_OUTPUT_CEILING)
            )
            print(f"[{index:>2}/{len(cases)}] judge calibration {case.id}", flush=True)
            ledger_count_before = len(guard.ledger.records())
            with tempfile.TemporaryDirectory(prefix="iris-qa-calibration-") as temp:
                root = Path(temp)
                input_path = root / "input.json"
                output_path = root / "output.json"
                usage_path = root / "usage.jsonl"
                input_path.write_text(
                    json.dumps(
                        {
                            "scenario": case.scenario.model_dump(mode="json"),
                            "answer": case.answer,
                            "activities": case.activities,
                            "diagnostics": case.diagnostics,
                        }
                    ),
                    encoding="utf-8",
                )
                environment = dict(config.environment)
                environment.update(
                    IRIS_QA_PROVIDER_USAGE_LOG=str(usage_path),
                    IRIS_QA_MAX_OUTPUT_TOKENS=str(JUDGE_OUTPUT_CEILING),
                    IRIS_QA_FAIL_ON_TRUNCATION="1",
                    IRIS_QA_SPEND_LEDGER=str(ledger_path.resolve()),
                    IRIS_QA_SPEND_RATES=_spend_rates(rate_card),
                    IRIS_QA_SPEND_HARD_LIMIT_USD=str(invocation_hard_limit),
                    IRIS_QA_SPEND_RUN_ID="judge-calibration",
                    IRIS_QA_SPEND_SCENARIO_ID=case.id,
                    IRIS_QA_SPEND_PIPELINE="judge-calibration",
                )
                try:
                    completed = subprocess.run(  # nosec B603
                        [
                            sys.executable,
                            "-m",
                            "iris.qa.calibration_worker",
                            "--input",
                            str(input_path),
                            "--output",
                            str(output_path),
                        ],
                        env=environment,
                        capture_output=True,
                        text=True,
                        timeout=300,
                        check=False,
                    )
                except subprocess.TimeoutExpired as error:
                    record_flushed_usage(usage_path, case.id, ledger_count_before)
                    reserve_unreported_call(case.id, ledger_count_before)
                    raise RuntimeError(
                        f"Calibration worker {case.id} timed out after "
                        f"{error.timeout}s"
                    ) from error
                usage_records = record_flushed_usage(
                    usage_path, case.id, ledger_count_before
                )
                if completed.returncode != 0 or not output_path.exists():
                    reserve_unreported_call(case.id, ledger_count_before)
                    raise RuntimeError(
                        f"Calibration worker {case.id} failed: "
                        f"{completed.stderr[-1000:]}"
                    )
                if len(usage_records) != 1:
                    reserve_unreported_call(case.id, ledger_count_before)
                    raise RuntimeError(
                        f"Calibration case {case.id} expected one paid judge call, "
                        f"got {len(usage_records)}"
                    )
                judge_result = json.loads(output_path.read_text())
                scores[case.id] = judge_result["scores"]
                evidence[case.id] = judge_result["evidence"]
    finally:
        config.close()
    result = assess_calibration(cases, scores, evidence)
    result.update(
        estimatedCostUsd=str(estimate),
        runSpendUsd=str(guard.ledger.total() - starting_spend),
        runMaxCostUsd=str(max_cost),
        developmentHardLimitUsd=str(hard_limit),
        cumulativeSpendUsd=str(guard.ledger.total()),
        judgeModel=rate_card.judge.model,
        azureJudgeDeployment=(deployment_verification or {})
        .get("deployments", {})
        .get("gpt-5.4"),
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return result
