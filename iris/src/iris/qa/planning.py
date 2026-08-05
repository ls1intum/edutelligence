from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

from iris.qa.cost import ModelRate, SpendLedger
from iris.qa.schema import Scenario
from iris.qa.yaml_utils import safe_load_unique

# pylint: disable=missing-class-docstring

JUDGE_INPUT_CEILING = 20_000
JUDGE_OUTPUT_CEILING = 1_200
CANDIDATE_MODELS = (
    "gpt-5.4-mini",
    "gpt-5.5",
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
    "openai/gpt-oss-120b",
)
ZERO_RATE_CANDIDATES = {"openai/gpt-oss-120b"}


@dataclass(frozen=True)
class RateCard:
    candidates: tuple[ModelRate, ...]
    judge: ModelRate
    auxiliary: ModelRate
    confirmed: bool
    source: str


@dataclass(frozen=True)
class CostPlan:
    pipeline_costs: dict[str, Decimal]
    judge_cost: Decimal
    subtotal: Decimal
    uplift: Decimal
    planned_total: Decimal
    already_spent: Decimal
    hard_limit: Decimal

    @property
    def remaining_after_plan(self) -> Decimal:
        return self.hard_limit - self.already_spent - self.planned_total


def candidate_rates(
    rate_card: RateCard, models: Sequence[str]
) -> tuple[ModelRate, ...]:
    selected = tuple(dict.fromkeys(models))
    if not selected:
        raise ValueError("At least one candidate model must be selected")
    unknown = set(selected) - set(CANDIDATE_MODELS)
    if unknown:
        raise ValueError(f"Unknown candidate model(s): {sorted(unknown)}")
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
        or rate.input_per_million < 0
        or rate.output_per_million < 0
        or (
            (rate.input_per_million == 0 or rate.output_per_million == 0)
            and rate.model not in ZERO_RATE_CANDIDATES
        )
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
            "Rate card is not confirmed for this Azure resource; copy the example, "
            "verify the billed rates, and set confirmed_azure_rates: true"
        )
    source = str(raw.get("source", "")).strip()
    if not source:
        raise ValueError("Rate card must name its source")
    candidates = tuple(_rate(item) for item in raw.get("candidates", []))
    if {rate.model for rate in candidates} != set(CANDIDATE_MODELS):
        raise ValueError(
            "Rate card must define every supported candidate model: "
            + ", ".join(CANDIDATE_MODELS)
        )
    try:
        judge = _rate(raw["judge"])
        auxiliary = _rate(raw["auxiliary"])
    except KeyError as error:
        raise ValueError(f"Rate card is missing {error.args[0]}") from error
    if judge.model != "gpt-5.4":
        raise ValueError("Rate card judge must be gpt-5.4")
    if auxiliary.model != "gpt-5.4-mini":
        raise ValueError("Rate card auxiliary must be gpt-5.4-mini")
    return RateCard(candidates, judge, auxiliary, confirmed, source)


def trial_reserve(
    scenario: Scenario, rate_card: RateCard, candidate_model: str
) -> Decimal:
    """Pessimistic price for one real-pipeline execution plus one judge call.

    The scenario token ceiling covers the candidate and Iris helper calls
    together. It is priced at whichever of the candidate or helper deployment
    is more expensive, then the judge ceiling is added separately.
    """
    candidate = candidate_rates(rate_card, (candidate_model,))[0]
    pipeline_rate = ModelRate(
        model=candidate_model,
        input_per_million=max(
            candidate.input_per_million, rate_card.auxiliary.input_per_million
        ),
        output_per_million=max(
            candidate.output_per_million, rate_card.auxiliary.output_per_million
        ),
    )
    return pipeline_rate.cost(
        scenario.token_ceiling.max_input_tokens,
        scenario.token_ceiling.max_output_tokens,
    ) + rate_card.judge.cost(JUDGE_INPUT_CEILING, JUDGE_OUTPUT_CEILING)


def build_cost_plan(
    scenarios: list[Scenario],
    rate_card: RateCard,
    *,
    repetitions: int,
    ledger: SpendLedger,
    hard_limit: Decimal,
    uplift_percent: Decimal = Decimal("10"),
    models: Sequence[str] = CANDIDATE_MODELS,
) -> CostPlan:
    if repetitions < 1:
        raise ValueError("repetitions must be at least one")
    if not hard_limit.is_finite() or hard_limit <= 0:
        raise ValueError("development budget must be greater than zero")
    if not uplift_percent.is_finite() or not Decimal(0) <= uplift_percent <= Decimal(
        100
    ):
        raise ValueError("uplift percent must be between 0 and 100")
    selected = candidate_rates(rate_card, models)
    pipeline_costs = {
        rate.model: sum(
            (
                trial_reserve(scenario, rate_card, rate.model)
                - rate_card.judge.cost(JUDGE_INPUT_CEILING, JUDGE_OUTPUT_CEILING)
                for scenario in scenarios
            ),
            Decimal(0),
        )
        * repetitions
        for rate in selected
    }
    trials = len(scenarios) * repetitions * len(selected)
    judge_cost = (
        rate_card.judge.cost(JUDGE_INPUT_CEILING, JUDGE_OUTPUT_CEILING) * trials
    )
    subtotal = sum(pipeline_costs.values(), Decimal(0)) + judge_cost
    uplift = subtotal * uplift_percent / Decimal(100)
    return CostPlan(
        pipeline_costs=pipeline_costs,
        judge_cost=judge_cost,
        subtotal=subtotal,
        uplift=uplift,
        planned_total=subtotal + uplift,
        already_spent=ledger.total(),
        hard_limit=hard_limit,
    )
