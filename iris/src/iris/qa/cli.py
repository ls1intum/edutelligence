from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

from iris.qa.cost import BudgetExceeded, SpendLedger
from iris.qa.loader import filter_scenarios, load_suite
from iris.qa.planning import (
    CANDIDATE_MODELS,
    MAX_TRANSIENT_RETRIES,
    build_cost_plan,
    load_rate_card,
)

# pylint: disable=import-outside-toplevel,missing-class-docstring,inconsistent-quotes


DEFAULT_QA_ROOT = Path(__file__).parents[3] / "qa"


class Style:
    def __init__(self):
        self.enabled = sys.stdout.isatty() and "NO_COLOR" not in os.environ

    def text(self, value: str, code: str) -> str:
        return f"\033[{code}m{value}\033[0m" if self.enabled else value

    def title(self, value: str) -> str:
        return self.text(value, "1;36")

    def good(self, value: str) -> str:
        return self.text(value, "1;32")

    def bad(self, value: str) -> str:
        return self.text(value, "1;31")

    def dim(self, value: str) -> str:
        return self.text(value, "2")


STYLE = Style()


def _money(value: Decimal) -> str:
    return f"${value.quantize(Decimal('0.01'))}"


def _decimal(value: str, label: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"{label} must be a decimal number") from error
    if not parsed.is_finite():
        raise ValueError(f"{label} must be a finite decimal number")
    return parsed


def _score_at_least(value, minimum: float) -> bool:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(score) and score >= minimum


def _root(value: str | None) -> Path:
    return Path(value).resolve() if value else DEFAULT_QA_ROOT.resolve()


def _suite(args):
    root = _root(args.qa_root)
    return root, load_suite(root / "scenarios", root / "fixtures", root / "artifacts")


def _validate_contracts(root: Path, scenarios):
    # Importing the production DTOs traverses iris.pipeline, whose package
    # initialization expects application settings even though validation makes
    # no network calls. Use the checked-in example only when the caller has not
    # selected an application configuration.
    os.environ.setdefault(
        "APPLICATION_YML_PATH", str(root.parent / "application.example.yml")
    )
    from iris.qa.contracts import validate_suite_contracts

    return validate_suite_contracts(scenarios, qa_root=root)


def _selection(args, suite):
    ids = set(args.scenario or []) or None
    tags = set(args.tag or []) or None
    selected = filter_scenarios(
        suite, profile=args.profile, scenario_ids=ids, tags=tags
    )
    if not selected:
        raise ValueError("Scenario selection is empty")
    return selected


def _models(args) -> tuple[str, ...]:
    return tuple(dict.fromkeys(args.model or CANDIDATE_MODELS))


def _print_header(subtitle: str) -> None:
    print(STYLE.title("IRIS QUALITY ASSURANCE"))
    print(STYLE.dim(subtitle))
    print()


def command_validate(args) -> int:
    root, suite = _suite(args)
    contracts = _validate_contracts(root, suite.scenarios)
    from iris.qa.calibration import load_calibration

    calibration = load_calibration(
        root / "calibration" / "judge-sample.yml", suite.scenarios
    )
    counts = Counter(scenario.use_case.value for scenario in suite.scenarios)
    _print_header("Scenario schema, artifacts, coverage, and Artemis wire contracts")
    print(STYLE.good(f"PASS  {len(contracts)} scenarios are valid"))
    print(
        "      " + "  ".join(f"{key}={value}" for key, value in sorted(counts.items()))
    )
    print(f"      fixtures={root / 'fixtures'}")
    print(f"      artifacts={root / 'artifacts'}")
    print(f"      judge-calibration-cases={len(calibration)}")
    return 0


def command_list(args) -> int:
    _, suite = _suite(args)
    selected = _selection(args, suite)
    _print_header(f"{len(selected)} selected scenarios")
    print(f"{'ID':<38} {'USE CASE':<18} {'MODE':<29} SUPPORT")
    print("-" * 100)
    for scenario in selected:
        print(
            f"{scenario.id:<38} {scenario.use_case.value:<18} "
            f"{(scenario.mode or '-'):<29} {scenario.support_level or '-'}"
        )
    return 0


def command_doctor(args) -> int:
    from iris.qa.bootstrap import create_worker_configuration

    rate_card = load_rate_card(Path(args.rates), require_confirmed=True)
    for model in ("gpt-5.4-mini", "gpt-5.5"):
        configuration = create_worker_configuration(rate_card, model)
        configuration.close()
    _print_header("Azure configuration preflight; no credential or model request")
    print(STYLE.good("PASS  endpoint, auth mode, rates, and deployments are valid"))
    return 0


def _plan(args):
    root, suite = _suite(args)
    scenarios = _selection(args, suite)
    rate_card = load_rate_card(Path(args.rates), require_confirmed=True)
    ledger_path = Path(args.ledger or root / ".spend-ledger.jsonl")
    plan = build_cost_plan(
        scenarios,
        rate_card,
        repetitions=args.repetitions,
        critical_repetitions=args.critical_repetitions,
        transient_retries=args.transient_retries,
        ledger=SpendLedger(ledger_path),
        hard_limit=_decimal(args.development_budget_usd, "development budget"),
        uplift_percent=_decimal(args.uplift_percent, "uplift percent"),
        models=_models(args),
    )
    return root, scenarios, rate_card, ledger_path, plan


def command_plan(args) -> int:
    _, scenarios, rate_card, ledger_path, plan = _plan(args)
    _print_header(
        f"Fail-closed preflight for {len(scenarios)} scenarios; "
        f"base repetitions={args.repetitions}, "
        f"risk-critical repetitions={args.critical_repetitions}, "
        f"global transient retries={args.transient_retries}"
    )
    print(f"Rate source          {rate_card.source}")
    for model, cost in plan.candidate_costs.items():
        print(f"Candidate {model:<12} {_money(cost):>10}")
    print(f"Independent judge    {_money(plan.judge_cost):>10}")
    print(f"Fixed auxiliaries    {_money(plan.auxiliary_cost):>10}")
    print(f"Safety uplift        {_money(plan.uplift):>10}")
    print(f"Runtime reserve floor{_money(plan.runtime_capacity_floor):>10}")
    print(f"Retry allowance      {_money(plan.transient_retry_allowance):>10}")
    print("-" * 34)
    print(f"Pessimistic plan     {_money(plan.planned_total):>10}")
    print(f"Already spent        {_money(plan.already_spent):>10}")
    print(f"Hard session limit   {_money(plan.hard_limit):>10}")
    print(f"Remaining after plan {_money(plan.remaining_after_plan):>10}")
    print(f"Ledger               {ledger_path}")
    if plan.remaining_after_plan < 0:
        print()
        print(STYLE.bad("REFUSED  planned spend exceeds the cumulative hard limit"))
        return 2
    print()
    print(STYLE.good("READY  cost plan fits the cumulative hard limit"))
    return 0


def command_run(args) -> int:
    from iris.qa.deployment_verification import validate_deployment_verification
    from iris.qa.run import run_paid_suite

    root = _root(args.qa_root)
    ledger_path = Path(args.ledger or root / ".spend-ledger.jsonl")
    with SpendLedger(ledger_path).exclusive_paid_run():
        root, scenarios, rate_card, ledger_path, plan = _plan(args)
        _validate_contracts(root, scenarios)
        deployment_verification = validate_deployment_verification(
            Path(args.deployment_verification),
            candidate_models=_models(args),
        )
        per_run_limit = _decimal(args.max_cost_usd, "--max-cost-usd")
        if not per_run_limit.is_finite() or per_run_limit <= 0:
            raise ValueError("--max-cost-usd must be greater than zero")
        if plan.planned_total > per_run_limit:
            raise BudgetExceeded(
                f"Paid run refused: pessimistic plan {_money(plan.planned_total)} "
                f"exceeds --max-cost-usd {_money(per_run_limit)}"
            )
        if plan.remaining_after_plan < 0:
            raise BudgetExceeded(
                "Paid run refused: cumulative development budget exceeded"
            )
        invocation_hard_limit = min(
            plan.hard_limit,
            plan.already_spent + per_run_limit,
        )
        return run_paid_suite(
            qa_root=root,
            scenarios=scenarios,
            rate_card=rate_card,
            ledger_path=ledger_path,
            hard_limit=invocation_hard_limit,
            development_hard_limit=plan.hard_limit,
            max_run_cost=per_run_limit,
            output_dir=Path(args.output),
            repetitions=args.repetitions,
            critical_repetitions=args.critical_repetitions,
            transient_retries=args.transient_retries,
            transient_retry_allowance=plan.transient_retry_allowance,
            baseline_path=Path(args.baseline) if args.baseline else None,
            deployment_verification=deployment_verification,
            planned_cost=plan.planned_total,
            starting_spend=plan.already_spent,
            models=_models(args),
        )


def command_merge(args) -> int:
    from iris.qa.merge import merge_paid_run_reports

    root, suite = _suite(args)
    scenarios = _selection(args, suite)
    result = merge_paid_run_reports(
        qa_root=root,
        scenarios=scenarios,
        report_paths=[Path(path) for path in args.report],
        output_root=Path(args.output),
        baseline_path=Path(args.baseline) if args.baseline else None,
    )
    _print_header(
        f"Offline qualification from {len(args.report)} disjoint paid-run shards"
    )
    status = STYLE.good("PASS") if result.passed else STYLE.bad("FAIL")
    print(f"{status}  merged report: {result.output_dir / 'report.md'}")
    return 0 if result.passed else 1


def command_baseline(args) -> int:
    from iris.qa.baseline import approve_report

    if args.approve != "APPROVE":
        raise ValueError("Baseline mutation requires --approve APPROVE")
    calibration = json.loads(Path(args.calibration_report).read_text(encoding="utf-8"))
    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    report_deployments = report.get("metadata", {}).get("azureDeployments")
    report_judge = (
        report_deployments.get("gpt-5.4")
        if isinstance(report_deployments, dict)
        else None
    )
    calibration_judge = calibration.get("azureJudgeDeployment")
    if (
        calibration.get("passed") is not True
        or calibration.get("judgeModel") != "gpt-5.4"
        or not _score_at_least(calibration.get("criterionAccuracy"), 0.85)
        or not _score_at_least(calibration.get("caseAccuracy"), 0.75)
        or len(calibration.get("details", [])) != 14
        or not isinstance(calibration_judge, dict)
        or not isinstance(report_judge, dict)
        or calibration_judge != report_judge
    ):
        raise ValueError(
            "Baseline mutation requires a complete, passing gpt-5.4 judge "
            "calibration report for the report's exact Azure judge deployment"
        )
    added = approve_report(Path(args.report), Path(args.output))
    print(STYLE.good(f"APPROVED  added {added} observations to {args.output}"))
    return 0


def command_calibrate(args) -> int:
    from iris.qa.calibration import load_calibration, run_calibration
    from iris.qa.deployment_verification import validate_deployment_verification

    root, suite = _suite(args)
    cases = load_calibration(root / "calibration" / "judge-sample.yml", suite.scenarios)
    rate_card = load_rate_card(Path(args.rates), require_confirmed=True)
    ledger = Path(args.ledger or root / ".spend-ledger.jsonl")
    with SpendLedger(ledger).exclusive_paid_run():
        deployment_verification = validate_deployment_verification(
            Path(args.deployment_verification)
        )
        result = run_calibration(
            cases=cases,
            rate_card=rate_card,
            ledger_path=ledger,
            hard_limit=_decimal(args.development_budget_usd, "development budget"),
            max_cost=_decimal(args.max_cost_usd, "--max-cost-usd"),
            output=Path(args.output),
            deployment_verification=deployment_verification,
        )
    status = STYLE.good("PASS") if result["passed"] else STYLE.bad("FAIL")
    print(
        f"{status}  judge calibration: "
        f"criterion={result['criterionAccuracy']:.1%} "
        f"cases={result['caseAccuracy']:.1%}"
    )
    print(
        f"      estimated={_money(Decimal(result['estimatedCostUsd']))} "
        f"cumulative={_money(Decimal(result['cumulativeSpendUsd']))}"
    )
    return 0 if result["passed"] else 1


def command_attest(args) -> int:
    from iris.qa.attestation import run_responses_attestation

    rate_card = load_rate_card(Path(args.rates), require_confirmed=True)
    ledger = Path(args.ledger or _root(args.qa_root) / ".spend-ledger.jsonl")
    with SpendLedger(ledger).exclusive_paid_run():
        result = run_responses_attestation(
            rate_card=rate_card,
            ledger_path=ledger,
            hard_limit=_decimal(args.development_budget_usd, "development budget"),
            max_cost=_decimal(args.max_cost_usd, "--max-cost-usd"),
            output=Path(args.output),
        )
    _print_header("Azure Responses API deployment attestation")
    for model, metadata in result["deployments"].items():
        print(STYLE.good(f"PASS  {model} -> {metadata['deployment']}"))
    print(f"      proof={args.output}")
    print(f"      cumulative={_money(SpendLedger(ledger).total())}")
    return 0


def _selection_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--profile", choices=("smoke", "weekly", "full"))
    parser.add_argument(
        "--scenario", action="append", help="Exact scenario ID; repeatable"
    )
    parser.add_argument("--tag", action="append", help="Require tag; repeatable")


def _cost_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--model",
        action="append",
        choices=CANDIDATE_MODELS,
        help="Candidate model to qualify; repeat for both (default: both)",
    )
    parser.add_argument("--rates", required=True, help="Confirmed Azure YAML rate card")
    parser.add_argument("--ledger", help="Append-only cumulative spend ledger")
    parser.add_argument("--repetitions", type=int, default=1, choices=range(1, 4))
    parser.add_argument(
        "--critical-repetitions",
        type=int,
        default=1,
        choices=range(1, 4),
        help="Repeat risk=critical scenarios; weekly CI uses 3",
    )
    parser.add_argument(
        "--transient-retries",
        type=int,
        default=0,
        choices=range(MAX_TRANSIENT_RETRIES + 1),
        help=(
            "Global extra attempts for ambiguous transient worker failures "
            f"(0..{MAX_TRANSIENT_RETRIES}, default: 0)"
        ),
    )
    parser.add_argument(
        "--development-budget-usd",
        default="30.00",
        help="Cumulative hard ceiling across the shared ledger (default: 30)",
    )
    parser.add_argument(
        "--uplift-percent",
        default="0",
        help="Extra pessimistic cost margin from 0 to 100 (default: 0)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="iris-qa",
        description="Cost-bounded, source-grounded quality assurance for Iris",
    )
    parser.add_argument("--qa-root", help="Override the checked-in qa directory")
    parser.add_argument(
        "--llm-config",
        help="Reuse credentials from a local Iris llm_config YAML file",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    validate = commands.add_parser(
        "validate", help="Validate all fixtures and wire DTOs"
    )
    validate.set_defaults(handler=command_validate)

    listing = commands.add_parser("list", help="List scenarios and coverage")
    _selection_arguments(listing)
    listing.set_defaults(handler=command_list)

    doctor = commands.add_parser(
        "doctor", help="Validate paid-run configuration without an Azure request"
    )
    doctor.add_argument("--rates", required=True, help="Confirmed Azure YAML rate card")
    doctor.set_defaults(handler=command_doctor)

    plan = commands.add_parser("plan", help="Compute a pessimistic paid-run ceiling")
    _selection_arguments(plan)
    _cost_arguments(plan)
    plan.set_defaults(handler=command_plan)

    run = commands.add_parser("run", help="Execute production pipelines against Azure")
    _selection_arguments(run)
    _cost_arguments(run)
    run.add_argument(
        "--max-cost-usd", required=True, help="Hard ceiling for this invocation"
    )
    run.add_argument(
        "--deployment-verification",
        required=True,
        help="ARM deployment proof generated within the last hour",
    )
    run.add_argument("--output", default="qa-results")
    run.add_argument("--baseline", help="Approved rolling baseline JSON")
    run.set_defaults(handler=command_run)

    merge = commands.add_parser(
        "merge",
        help="Combine disjoint paid-run shards into one offline qualification",
    )
    merge.add_argument(
        "--profile",
        required=True,
        choices=("smoke", "weekly", "full"),
        help="Required target suite; missing shard observations fail closed",
    )
    merge.add_argument(
        "--scenario", action="append", help="Exact scenario ID; repeatable"
    )
    merge.add_argument("--tag", action="append", help="Require tag; repeatable")
    merge.add_argument(
        "--report",
        action="append",
        required=True,
        help="Shard report.json or its run directory; repeat at least twice",
    )
    merge.add_argument("--output", default="qa-results/merged")
    merge.add_argument(
        "--baseline",
        help="Immutable baseline used by every shard; required only if shards used one",
    )
    merge.set_defaults(handler=command_merge)

    baseline = commands.add_parser(
        "baseline", help="Explicitly approve a passing report into a rolling baseline"
    )
    baseline.add_argument("--report", required=True)
    baseline.add_argument("--output", required=True)
    baseline.add_argument("--calibration-report", required=True)
    baseline.add_argument("--approve", required=True)
    baseline.set_defaults(handler=command_baseline)

    calibrate = commands.add_parser(
        "calibrate", help="Run the independent judge on 14 curated reference samples"
    )
    calibrate.add_argument("--rates", required=True)
    calibrate.add_argument(
        "--deployment-verification",
        required=True,
        help="ARM deployment proof generated within the last hour",
    )
    calibrate.add_argument("--ledger")
    calibrate.add_argument("--development-budget-usd", default="30.00")
    calibrate.add_argument("--max-cost-usd", required=True)
    calibrate.add_argument("--output", default="qa-results/judge-calibration.json")
    calibrate.set_defaults(handler=command_calibrate)

    attest = commands.add_parser(
        "attest",
        help="Verify local Azure deployment identities through tiny paid calls",
    )
    attest.add_argument("--rates", required=True)
    attest.add_argument("--ledger")
    attest.add_argument("--development-budget-usd", default="30.00")
    attest.add_argument("--max-cost-usd", required=True)
    attest.add_argument("--output", default="qa-results/deployments.json")
    attest.set_defaults(handler=command_attest)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        if args.llm_config:
            from iris.qa.bootstrap import apply_local_llm_config

            apply_local_llm_config(Path(args.llm_config))
        return int(args.handler(args))
    except (ValueError, BudgetExceeded, RuntimeError) as error:
        print(STYLE.bad(f"ERROR  {error}"), file=sys.stderr)
        return 2
