from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

from iris.qa.cost import BudgetExceeded, SpendLedger
from iris.qa.loader import filter_scenarios, load_suite
from iris.qa.planning import CANDIDATE_MODELS, build_cost_plan, load_rate_card

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


def _decimal(value: str, label: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"{label} must be a decimal number") from error
    if not parsed.is_finite():
        raise ValueError(f"{label} must be finite")
    return parsed


def _money(value: Decimal) -> str:
    return f"${value.quantize(Decimal('0.01'))}"


def _root(value: str | None) -> Path:
    return Path(value).resolve() if value else DEFAULT_QA_ROOT.resolve()


def _suite(args):
    root = _root(args.qa_root)
    return root, load_suite(root / "scenarios", root / "fixtures", root / "artifacts")


def _selection(args, suite):
    selected = filter_scenarios(
        suite,
        profile=args.profile,
        scenario_ids=set(args.scenario or []) or None,
        tags=set(args.tag or []) or None,
    )
    if not selected:
        raise ValueError("Scenario selection is empty")
    return selected


def _models(args) -> tuple[str, ...]:
    return tuple(dict.fromkeys(args.model or CANDIDATE_MODELS))


def _header(subtitle: str) -> None:
    print(STYLE.title("IRIS BENCHMARK"))
    print(STYLE.dim(subtitle))
    print()


def _validate_contracts(root: Path, scenarios) -> None:
    os.environ.setdefault(
        "APPLICATION_YML_PATH", str(root.parent / "application.example.yml")
    )
    from iris.qa.contracts import validate_suite_contracts

    validate_suite_contracts(scenarios, qa_root=root)


def command_validate(args) -> int:
    root, suite = _suite(args)
    _validate_contracts(root, suite.scenarios)
    counts = Counter(scenario.use_case.value for scenario in suite.scenarios)
    _header("Schema, fixtures, artifacts, coverage, and production DTO contracts")
    print(STYLE.good(f"VALID  {len(suite.scenarios)} realistic scenarios"))
    print(
        "       " + "  ".join(f"{key}={value}" for key, value in sorted(counts.items()))
    )
    print("       scoring=achieved:100  partly_achieved:50  not_achieved:0")
    print("       quality-threshold=none")
    return 0


def command_list(args) -> int:
    _, suite = _suite(args)
    selected = _selection(args, suite)
    _header(f"{len(selected)} selected scenarios")
    print(f"{'ID':<38} {'USE CASE':<18} {'MODE':<29} SUPPORT")
    print("-" * 100)
    for scenario in selected:
        print(
            f"{scenario.id:<38} {scenario.use_case.value:<18} "
            f"{(scenario.mode or '-'):<29} {scenario.support_level or '-'}"
        )
    return 0


def _plan(args):
    root, suite = _suite(args)
    scenarios = _selection(args, suite)
    rate_card = load_rate_card(Path(args.rates), require_confirmed=False)
    ledger_path = Path(args.ledger or root / ".spend-ledger.jsonl")
    plan = build_cost_plan(
        scenarios,
        rate_card,
        repetitions=args.repetitions,
        ledger=SpendLedger(ledger_path),
        hard_limit=_decimal(args.budget_usd, "--budget-usd"),
        uplift_percent=_decimal(args.uplift_percent, "--uplift-percent"),
        models=_models(args),
    )
    return root, scenarios, rate_card, ledger_path, plan


def command_plan(args) -> int:
    _, scenarios, rate_card, ledger_path, plan = _plan(args)
    _header(
        f"Cost guard for {len(scenarios)} scenarios × {len(_models(args))} model(s) "
        f"× {args.repetitions} run(s)"
    )
    print(f"Rate source          {rate_card.source}")
    for model, cost in plan.pipeline_costs.items():
        print(f"Pipeline {model:<13} {_money(cost):>10}")
    print(f"Independent judge    {_money(plan.judge_cost):>10}")
    print(f"Safety allowance     {_money(plan.uplift):>10}")
    print("-" * 34)
    print(f"Planned upper bound  {_money(plan.planned_total):>10}")
    print(f"Already accounted    {_money(plan.already_spent):>10}")
    print(f"Budget ceiling       {_money(plan.hard_limit):>10}")
    print(f"Remaining after plan {_money(plan.remaining_after_plan):>10}")
    print(f"Ledger               {ledger_path}")
    if plan.remaining_after_plan < 0:
        print()
        print(STYLE.bad("REFUSED  the planned upper bound exceeds the budget"))
        return 2
    print()
    print(STYLE.good("READY  the planned upper bound fits the budget"))
    return 0


def command_doctor(args) -> int:
    from iris.qa.bootstrap import apply_local_llm_config, create_worker_configuration

    apply_local_llm_config(Path(args.llm_config))
    rate_card = load_rate_card(Path(args.rates), require_confirmed=False)
    for model in _models(args):
        configuration = create_worker_configuration(rate_card, model)
        configuration.close()
    _header("Local configuration preflight; no model request was sent")
    print(STYLE.good("READY  credentials, deployments, and model configuration loaded"))
    return 0


def command_run(args) -> int:
    from iris.qa.bootstrap import apply_local_llm_config
    from iris.qa.report import summarize
    from iris.qa.run import run_paid_suite

    root = _root(args.qa_root)
    ledger_path = Path(args.ledger or root / ".spend-ledger.jsonl")
    with SpendLedger(ledger_path).exclusive_paid_run():
        root, scenarios, rate_card, ledger_path, plan = _plan(args)
        _validate_contracts(root, scenarios)
        apply_local_llm_config(Path(args.llm_config))
        max_run_cost = _decimal(args.max_cost_usd, "--max-cost-usd")
        if max_run_cost <= 0:
            raise ValueError("--max-cost-usd must be greater than zero")
        if plan.planned_total > max_run_cost:
            raise BudgetExceeded(
                f"Planned upper bound {_money(plan.planned_total)} exceeds "
                f"--max-cost-usd {_money(max_run_cost)}"
            )
        if plan.remaining_after_plan < 0:
            raise BudgetExceeded("Planned upper bound exceeds --budget-usd")
        _header(
            f"Running {len(scenarios)} scenarios against {', '.join(_models(args))}"
        )
        code, report_root, evaluations = run_paid_suite(
            qa_root=root,
            scenarios=scenarios,
            models=_models(args),
            repetitions=args.repetitions,
            rate_card=rate_card,
            ledger=SpendLedger(ledger_path),
            hard_limit=plan.hard_limit,
            max_run_cost=max_run_cost,
            planned_cost=plan.planned_total,
            output_root=Path(args.output).resolve() if args.output else None,
        )
    summary = summarize(evaluations)
    print()
    for model, item in summary["models"].items():
        print(
            STYLE.good(
                f"{model}: IrisScore {item['score']:.2f} "
                f"({item['ci95Low']:.2f}–{item['ci95High']:.2f})"
            )
        )
    print(
        f"Critical and execution incidents remain separate in {report_root / 'report.md'}"
    )
    print(f"Measured model cost: ${summary['totalCostUsd']:.4f}")
    return code


def command_rejudge(args) -> int:
    from iris.qa.bootstrap import apply_local_llm_config
    from iris.qa.rejudge import rejudge_saved_runs
    from iris.qa.report import summarize

    root, suite = _suite(args)
    rate_card = load_rate_card(Path(args.rates), require_confirmed=False)
    ledger_path = Path(args.ledger or root / ".spend-ledger.jsonl")
    models = _models(args)
    hard_limit = _decimal(args.budget_usd, "--budget-usd")
    max_run_cost = _decimal(args.max_cost_usd, "--max-cost-usd")
    if hard_limit <= 0 or max_run_cost <= 0:
        raise ValueError("rejudge cost limits must be greater than zero")
    apply_local_llm_config(Path(args.llm_config))
    output_root = Path(args.output).resolve()

    with SpendLedger(ledger_path).exclusive_paid_run():
        _header("Rejudging saved answers; candidate models will not be invoked")
        code, evaluations = rejudge_saved_runs(
            input_roots=[Path(path).resolve() for path in args.input_run],
            output_root=output_root,
            scenarios={scenario.id: scenario for scenario in suite.scenarios},
            models=models,
            scenario_ids=set(args.scenario or []) or None,
            rate_card=rate_card,
            ledger=SpendLedger(ledger_path),
            hard_limit=hard_limit,
            max_run_cost=max_run_cost,
            resume=args.resume,
        )
    summary = summarize(evaluations)
    print()
    for model, item in summary["models"].items():
        print(
            STYLE.good(
                f"{model}: IrisScore {item['score']:.2f}; "
                f"critical errors {item['criticalErrorRate']:.1%}"
            )
        )
    print(f"Rejudged report: {output_root / 'report.md'}")
    return code


def _add_selection(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--profile", choices=("smoke", "weekly", "full"))
    parser.add_argument("--scenario", action="append")
    parser.add_argument("--tag", action="append")


def _add_run_shape(parser: argparse.ArgumentParser) -> None:
    _add_selection(parser)
    parser.add_argument("--model", action="append", choices=CANDIDATE_MODELS)
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--rates", required=True)
    parser.add_argument("--ledger")
    parser.add_argument("--budget-usd", default="30")
    parser.add_argument("--uplift-percent", default="10")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="iris-benchmark",
        description="Run realistic Iris scenarios and compute a transparent 0–100 IrisScore.",
    )
    parser.add_argument("--qa-root")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="validate the scenario corpus")
    validate.set_defaults(handler=command_validate)

    listing = subparsers.add_parser("list", help="show scenarios")
    _add_selection(listing)
    listing.set_defaults(handler=command_list)

    plan = subparsers.add_parser("plan", help="show the paid-run upper bound")
    _add_run_shape(plan)
    plan.set_defaults(handler=command_plan)

    doctor = subparsers.add_parser("doctor", help="check local model configuration")
    doctor.add_argument("--llm-config", required=True)
    doctor.add_argument("--rates", required=True)
    doctor.add_argument("--model", action="append", choices=CANDIDATE_MODELS)
    doctor.set_defaults(handler=command_doctor)

    run = subparsers.add_parser("run", help="run the benchmark")
    _add_run_shape(run)
    run.add_argument("--llm-config", required=True)
    run.add_argument("--max-cost-usd", default="30")
    run.add_argument("--output")
    run.set_defaults(handler=command_run)

    rejudge = subparsers.add_parser(
        "rejudge", help="re-evaluate saved answers without invoking candidates"
    )
    rejudge.add_argument("--input-run", action="append", required=True)
    rejudge.add_argument("--output", required=True)
    rejudge.add_argument("--llm-config", required=True)
    rejudge.add_argument("--rates", required=True)
    rejudge.add_argument("--ledger")
    rejudge.add_argument("--budget-usd", default="30")
    rejudge.add_argument("--max-cost-usd", default="30")
    rejudge.add_argument("--model", action="append", choices=CANDIDATE_MODELS)
    rejudge.add_argument("--scenario", action="append")
    rejudge.add_argument("--resume", action="store_true")
    rejudge.set_defaults(handler=command_rejudge)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except (BudgetExceeded, OSError, ValueError, RuntimeError) as error:
        print(STYLE.bad(f"ERROR  {error}"), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
