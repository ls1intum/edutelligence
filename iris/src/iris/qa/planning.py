from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

from iris.qa.cost import ModelRate, SpendLedger, estimate_candidate_cost
from iris.qa.schema import RiskLevel, Scenario, UseCase
from iris.qa.yaml_utils import safe_load_unique

# pylint: disable=missing-class-docstring

JUDGE_INPUT_CEILING = 2_500
JUDGE_OUTPUT_CEILING = 1_600
CANDIDATE_MODELS = ("gpt-5.4-mini", "gpt-5.5")
MAX_TRANSIENT_RETRIES = 2


@dataclass(frozen=True)
class RateCard:
    candidates: tuple[ModelRate, ...]
    judge: ModelRate
    auxiliary: ModelRate
    confirmed: bool
    source: str


@dataclass(frozen=True)
class CostPlan:
    candidate_costs: dict[str, Decimal]
    judge_cost: Decimal
    auxiliary_cost: Decimal
    subtotal: Decimal
    uplift: Decimal
    runtime_capacity_floor: Decimal
    transient_retry_allowance: Decimal
    planned_total: Decimal
    already_spent: Decimal
    hard_limit: Decimal

    @property
    def remaining_after_plan(self) -> Decimal:
        return self.hard_limit - self.already_spent - self.planned_total


def citation_call_allowance(scenario: Scenario) -> tuple[int, int]:
    """Return total and maximum concurrent citation calls for one candidate."""
    if scenario.use_case != UseCase.CHAT or not scenario.expectations.require_citation:
        return 0, 0
    retrieval = scenario.payload.get("qa", {}).get("retrieval", {})
    current = retrieval.get("currentView", {})
    faq_items = len(retrieval.get("faqs", []))
    lecture_items = (
        len(current.get("pages", []))
        + len(current.get("transcript", []))
        + len(retrieval.get("search", []))
    )
    if not faq_items and not lecture_items:
        raise ValueError(
            f"{scenario.id}: citation expectation has no controlled source items"
        )
    groups = int(faq_items > 0) + int(lecture_items > 0)
    # Each group has one formatting call. Every cited item can then require one
    # keyword call and one summary call. Summaries run beside one keyword worker.
    total_calls = groups + 2 * (faq_items + lecture_items)
    concurrent_calls = max(
        faq_items + 1 if faq_items else 0,
        lecture_items + 1 if lecture_items else 0,
    )
    return total_calls, concurrent_calls


def mcq_call_allowance(scenario: Scenario) -> tuple[int, int]:
    """Return total and maximum concurrent MCQ-generation calls.

    Every question uses one generation call and one required correctness-review
    call. Multi-question output first extracts subtopics, then each parallel
    worker performs its generation and review calls sequentially.
    """
    if not scenario.expectations.require_mcq:
        return 0, 0
    count = scenario.expectations.mcq_count or 1
    if count == 1:
        return 2, 1
    return 1 + 2 * count, count


def guide_call_allowance(scenario: Scenario) -> int:
    """Return paid-QA guide calls for one candidate execution.

    Exercise chat always runs the integrity guide. Other chat modes run it for
    low-support substantive responses, except MCQ requests whose structured
    output bypasses response refinement. Paid QA disables the one production
    validation retry, so that retry must never be silently added here.
    """
    if scenario.use_case != UseCase.CHAT:
        return 0
    if scenario.mode == "PROGRAMMING_EXERCISE_CHAT":
        return 1
    return int(
        getattr(scenario, "support_level", None) == "low"
        and not scenario.expectations.require_mcq
    )


def worker_token_ceiling(scenario: Scenario) -> tuple[int, int]:
    """Total provider-token ceiling for one scenario/model worker process."""
    input_tokens = scenario.token_ceiling.max_input_tokens + JUDGE_INPUT_CEILING
    output_tokens = scenario.token_ceiling.max_output_tokens + JUDGE_OUTPUT_CEILING
    guide_calls = guide_call_allowance(scenario)
    input_tokens += guide_calls * 8000
    output_tokens += guide_calls * 2000
    citation_calls, _ = citation_call_allowance(scenario)
    input_tokens += citation_calls * 5000
    output_tokens += citation_calls * 1000
    if scenario.use_case == UseCase.CHAT:
        input_tokens += 2000
        output_tokens += 200
    if scenario.mode in {"COURSE_CHAT", "PROGRAMMING_EXERCISE_CHAT"}:
        input_tokens += 3000
        output_tokens += 300
    mcq_calls, _ = mcq_call_allowance(scenario)
    input_tokens += mcq_calls * 10000
    output_tokens += mcq_calls * 2000
    return input_tokens, output_tokens


def worker_cost_reserve(
    scenario: Scenario,
    rate_card: RateCard,
    *,
    candidate_models: Sequence[str] = CANDIDATE_MODELS,
) -> Decimal:
    """Return the worst one-worker capacity required by the runtime guard.

    The plan is usually larger than this floor. Small targeted selections must
    still surface it so copying the printed plan into ``--max-cost-usd`` cannot
    be rejected before the first paid call.
    """
    total_input, total_output = worker_token_ceiling(scenario)
    concurrent_calls = 1
    concurrent_input = scenario.token_ceiling.max_input_tokens
    _, mcq_concurrency = mcq_call_allowance(scenario)
    if mcq_concurrency:
        concurrent_calls = max(concurrent_calls, mcq_concurrency)
        concurrent_input = max(concurrent_input, 10_000 * mcq_concurrency)
    _, citation_concurrency = citation_call_allowance(scenario)
    if citation_concurrency:
        concurrent_calls = max(concurrent_calls, citation_concurrency)
        concurrent_input = max(concurrent_input, citation_concurrency * 5_000)
    total_input += concurrent_input
    total_output += concurrent_calls * scenario.token_ceiling.max_output_tokens_per_call
    selected_rates = _candidate_rates(rate_card, candidate_models)
    rates = (*selected_rates, rate_card.judge, rate_card.auxiliary)
    input_rate = max(rate.input_per_million for rate in rates)
    output_rate = max(rate.output_per_million for rate in rates)
    return (
        Decimal(total_input) * input_rate + Decimal(total_output) * output_rate
    ) / Decimal(1_000_000)


def _scenario_auxiliary_cost(scenario: Scenario, rate: ModelRate) -> Decimal:
    """Return the fixed helper allowance for one scenario/model execution."""
    citation_calls = citation_call_allowance(scenario)[0]
    mcq_calls = mcq_call_allowance(scenario)[0]
    return (
        rate.cost(8000, 2000) * guide_call_allowance(scenario)
        + rate.cost(5000, 1000) * citation_calls
        + rate.cost(2000, 200) * (scenario.use_case == UseCase.CHAT)
        + rate.cost(3000, 300)
        * (scenario.mode in {"COURSE_CHAT", "PROGRAMMING_EXERCISE_CHAT"})
        + rate.cost(10000, 2000) * mcq_calls
    )


def _candidate_rates(
    rate_card: RateCard, models: Sequence[str]
) -> tuple[ModelRate, ...]:
    """Resolve a non-empty, ordered candidate selection without weakening rates."""
    selected = tuple(dict.fromkeys(models))
    if not selected:
        raise ValueError("At least one candidate model must be selected")
    unknown = set(selected) - set(CANDIDATE_MODELS)
    if unknown:
        unknown_names = ", ".join(sorted(unknown))
        raise ValueError(f"Unknown candidate model(s): {unknown_names}")
    by_model = {rate.model: rate for rate in rate_card.candidates}
    return tuple(by_model[model] for model in selected)


def _rate(raw: dict[str, Any]) -> ModelRate:
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid model rate: {raw}")
    try:
        rate = ModelRate(
            model=str(raw["model"]),
            input_per_million=Decimal(str(raw["input_per_million"])),
            output_per_million=Decimal(str(raw["output_per_million"])),
        )
    except (KeyError, ValueError, InvalidOperation) as error:
        raise ValueError(f"Invalid model rate: {raw}") from error
    if (
        not rate.model
        or not rate.input_per_million.is_finite()
        or not rate.output_per_million.is_finite()
        or rate.input_per_million <= 0
        or rate.output_per_million <= 0
    ):
        raise ValueError(f"Invalid model rate: {raw}")
    return rate


def load_rate_card(path: Path, *, require_confirmed: bool = True) -> RateCard:
    try:
        raw = safe_load_unique(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ValueError(f"Cannot read rate card {path}: {error}") from error
    if not isinstance(raw, dict):
        raise ValueError("Rate card must be a YAML mapping")
    confirmed = raw.get("confirmed_azure_rates") is True
    if require_confirmed and not confirmed:
        raise ValueError(
            "Rate card is not confirmed for the target Azure deployments; copy the "
            "example, verify billed rates, and set confirmed_azure_rates: true"
        )
    source = str(raw.get("source", "")).strip()
    if not source:
        raise ValueError("Rate card must name the source of its confirmed Azure rates")
    candidate_entries = raw.get("candidates", [])
    if not isinstance(candidate_entries, list):
        raise ValueError("Rate card candidates must be a list")
    candidates = tuple(_rate(item) for item in candidate_entries)
    if len(candidates) != 2 or {rate.model for rate in candidates} != {
        "gpt-5.4-mini",
        "gpt-5.5",
    }:
        raise ValueError("Rate card must define exactly gpt-5.4-mini and gpt-5.5")
    try:
        judge = _rate(raw["judge"])
        auxiliary = _rate(raw["auxiliary"])
    except KeyError as error:
        raise ValueError(f"Rate card is missing {error.args[0]}") from error
    if judge.model != "gpt-5.4":
        raise ValueError("Rate card judge must be gpt-5.4")
    if auxiliary.model != "gpt-5.4-mini":
        raise ValueError("Rate card auxiliary must be gpt-5.4-mini")
    mini_candidate = next(rate for rate in candidates if rate.model == "gpt-5.4-mini")
    if (
        auxiliary.input_per_million != mini_candidate.input_per_million
        or auxiliary.output_per_million != mini_candidate.output_per_million
    ):
        raise ValueError(
            "Rate card auxiliary prices must equal the gpt-5.4-mini candidate "
            "prices because both roles use the same Azure deployment"
        )
    return RateCard(
        candidates=candidates,
        judge=judge,
        auxiliary=auxiliary,
        confirmed=confirmed,
        source=source,
    )


def build_cost_plan(
    scenarios: list[Scenario],
    rate_card: RateCard,
    *,
    repetitions: int,
    critical_repetitions: int = 1,
    transient_retries: int = 0,
    ledger: SpendLedger,
    hard_limit: Decimal,
    uplift_percent: Decimal = Decimal("0"),
    models: Sequence[str] = CANDIDATE_MODELS,
) -> CostPlan:
    if critical_repetitions < repetitions:
        raise ValueError("critical_repetitions must be at least repetitions")
    if (
        not isinstance(transient_retries, int)
        or isinstance(transient_retries, bool)
        or not 0 <= transient_retries <= MAX_TRANSIENT_RETRIES
    ):
        raise ValueError(
            f"transient_retries must be between 0 and {MAX_TRANSIENT_RETRIES}"
        )
    if not hard_limit.is_finite() or hard_limit <= 0:
        raise ValueError("development budget must be greater than zero")
    if not uplift_percent.is_finite() or not Decimal(0) <= uplift_percent <= Decimal(
        100
    ):
        raise ValueError("uplift percent must be between 0 and 100")
    critical = [
        scenario for scenario in scenarios if scenario.risk == RiskLevel.CRITICAL
    ]
    selected_rates = _candidate_rates(rate_card, models)
    candidate_costs = estimate_candidate_cost(
        scenarios, selected_rates, repetitions=repetitions
    )
    extra_repetitions = critical_repetitions - repetitions
    if extra_repetitions:
        extra = estimate_candidate_cost(
            critical, selected_rates, repetitions=extra_repetitions
        )
        candidate_costs = {
            model: cost + extra[model] for model, cost in candidate_costs.items()
        }
    scenario_runs = len(scenarios) * repetitions + len(critical) * extra_repetitions
    calls = scenario_runs * len(selected_rates)
    judge_cost = rate_card.judge.cost(JUDGE_INPUT_CEILING, JUDGE_OUTPUT_CEILING) * calls

    # Candidate-independent subpipeline allowances. The input/output caps mirror
    # ARCHITECTURE.md and are charged only where the production path can call them.
    weighted = [
        scenario
        for scenario in scenarios
        for _ in range(
            critical_repetitions if scenario.risk == RiskLevel.CRITICAL else repetitions
        )
    ]
    guide_calls = sum(guide_call_allowance(s) for s in weighted)
    citation_calls = sum(citation_call_allowance(s)[0] for s in weighted)
    mcq_calls = sum(mcq_call_allowance(s)[0] for s in weighted)
    chats = sum(s.use_case == UseCase.CHAT for s in weighted)
    suggestion = sum(
        s.mode in {"COURSE_CHAT", "PROGRAMMING_EXERCISE_CHAT"} for s in weighted
    )
    auxiliary_cost = (
        rate_card.auxiliary.cost(8000, 2000) * guide_calls * len(selected_rates)
        + rate_card.auxiliary.cost(5000, 1000) * citation_calls * len(selected_rates)
        + rate_card.auxiliary.cost(2000, 200) * chats * len(selected_rates)
        + rate_card.auxiliary.cost(3000, 300) * suggestion * len(selected_rates)
        + rate_card.auxiliary.cost(10000, 2000) * mcq_calls * len(selected_rates)
    )
    subtotal = sum(candidate_costs.values(), Decimal(0)) + judge_cost + auxiliary_cost
    uplift = subtotal * uplift_percent / Decimal(100)
    uplift_multiplier = Decimal(1) + uplift_percent / Decimal(100)
    prior_execution_ceiling = Decimal(0)
    runtime_capacity_floor = Decimal(0)
    for rate in selected_rates:
        for scenario in weighted:
            runtime_capacity_floor = max(
                runtime_capacity_floor,
                prior_execution_ceiling
                + worker_cost_reserve(
                    scenario, rate_card, candidate_models=(rate.model,)
                ),
            )
            execution_ceiling = (
                rate.cost(
                    scenario.token_ceiling.max_input_tokens,
                    scenario.token_ceiling.max_output_tokens,
                )
                + rate_card.judge.cost(JUDGE_INPUT_CEILING, JUDGE_OUTPUT_CEILING)
                + _scenario_auxiliary_cost(scenario, rate_card.auxiliary)
            )
            prior_execution_ceiling += execution_ceiling * uplift_multiplier
    largest_worker_reserve = max(
        worker_cost_reserve(
            scenario,
            rate_card,
            candidate_models=(rate.model,),
        )
        for rate in selected_rates
        for scenario in scenarios
    )
    # Retries are a global run-level contingency, not an extra repetition of
    # every scenario. Price each permitted extra attempt at the largest worker
    # reserve among the selected scenario/model combinations.
    transient_retry_allowance = largest_worker_reserve * transient_retries
    planned_total = (
        max(subtotal + uplift, runtime_capacity_floor) + transient_retry_allowance
    )
    return CostPlan(
        candidate_costs=candidate_costs,
        judge_cost=judge_cost,
        auxiliary_cost=auxiliary_cost,
        subtotal=subtotal,
        uplift=uplift,
        runtime_capacity_floor=runtime_capacity_floor,
        transient_retry_allowance=transient_retry_allowance,
        planned_total=planned_total,
        already_spent=ledger.total(),
        hard_limit=hard_limit,
    )
