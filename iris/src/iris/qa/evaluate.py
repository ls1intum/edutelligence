from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from iris.qa.schema import Scenario

# pylint: disable=missing-class-docstring


class Rating(StrEnum):
    ACHIEVED = "achieved"
    PARTLY_ACHIEVED = "partly_achieved"
    NOT_ACHIEVED = "not_achieved"


RATING_POINTS = {
    Rating.ACHIEVED: 100.0,
    Rating.PARTLY_ACHIEVED: 50.0,
    Rating.NOT_ACHIEVED: 0.0,
}


@dataclass(frozen=True)
class ActivityTrace:
    name: str
    state: str = "FINISHED"


@dataclass(frozen=True)
class CriterionResult:
    id: str
    rating: Rating
    evidence: str

    @property
    def points(self) -> float:
        return RATING_POINTS[self.rating]


@dataclass(frozen=True)
class CriticalErrorResult:
    description: str
    present: bool
    evidence: str


@dataclass(frozen=True)
class ProviderUsage:
    model: str
    pipeline: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


@dataclass
class ScenarioEvaluation:
    scenario_id: str
    title: str
    description: str
    model: str
    repetition: int
    use_case: str
    mode: str | None
    support_level: str | None
    difficulty: str
    tags: list[str]
    response: str | None
    activities: list[ActivityTrace]
    criteria: list[CriterionResult] = field(default_factory=list)
    critical_errors: list[CriticalErrorResult] = field(default_factory=list)
    usage: list[ProviderUsage] = field(default_factory=list)
    duration_seconds: float = 0.0
    execution_error: str | None = None

    @property
    def score(self) -> float:
        """Return this trial's transparent 0-100 IrisScore."""
        if self.execution_error or not self.criteria:
            return 0.0
        return sum(item.points for item in self.criteria) / len(self.criteria)

    @property
    def critical_error_count(self) -> int:
        return sum(item.present for item in self.critical_errors)

    @property
    def cost_usd(self) -> float:
        return sum(item.cost_usd for item in self.usage)


def _nonempty_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"judge {label} must be a non-empty string")
    return value.strip()[:500]


def evaluation_from_worker(
    scenario: Scenario,
    *,
    model: str,
    repetition: int,
    payload: dict[str, Any],
    duration_seconds: float,
) -> ScenarioEvaluation:
    """Validate one worker result and turn it into the public score model."""
    activities = [
        ActivityTrace(
            name=str(item.get("name", "unknown")),
            state=str(item.get("state", "unknown")),
        )
        for item in payload.get("activities", [])
        if isinstance(item, dict)
    ]
    usage = []
    for item in payload.get("usage", []):
        if not isinstance(item, dict):
            raise ValueError("worker usage entries must be objects")
        input_tokens = item.get("inputTokens")
        output_tokens = item.get("outputTokens")
        cost = item.get("costUsd")
        if (
            isinstance(input_tokens, bool)
            or not isinstance(input_tokens, int)
            or input_tokens < 0
            or isinstance(output_tokens, bool)
            or not isinstance(output_tokens, int)
            or output_tokens < 0
            or isinstance(cost, bool)
            or not isinstance(cost, (int, float))
            or not math.isfinite(float(cost))
            or float(cost) < 0
        ):
            raise ValueError("worker usage contains invalid token counts or cost")
        usage.append(
            ProviderUsage(
                model=str(item.get("model", "unknown")),
                pipeline=str(item.get("pipeline", "unknown")),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=float(cost),
            )
        )

    execution_error = payload.get("executionError")
    criteria: list[CriterionResult] = []
    critical_errors: list[CriticalErrorResult] = []
    if not execution_error:
        judge = payload.get("judge")
        if not isinstance(judge, dict):
            raise ValueError("worker result is missing the judge result")
        raw_criteria = judge.get("criteria")
        expected_ids = {criterion.id for criterion in scenario.criteria}
        if not isinstance(raw_criteria, list) or len(raw_criteria) != len(expected_ids):
            raise ValueError("judge returned the wrong number of criteria")
        seen_ids: set[str] = set()
        for item in raw_criteria:
            if not isinstance(item, dict):
                raise ValueError("judge criterion results must be objects")
            criterion_id = item.get("id")
            if criterion_id not in expected_ids or criterion_id in seen_ids:
                raise ValueError("judge criterion ids must be exact and unique")
            seen_ids.add(criterion_id)
            try:
                rating = Rating(item.get("rating"))
            except ValueError as error:
                raise ValueError(f"invalid judge rating for {criterion_id}") from error
            criteria.append(
                CriterionResult(
                    id=criterion_id,
                    rating=rating,
                    evidence=_nonempty_text(item.get("evidence"), "criterion evidence"),
                )
            )

        raw_errors = judge.get("criticalErrors")
        if not isinstance(raw_errors, list) or len(raw_errors) != len(
            scenario.critical_errors
        ):
            raise ValueError("judge returned the wrong number of critical errors")
        expected_errors = set(scenario.critical_errors)
        seen_errors: set[str] = set()
        for item in raw_errors:
            if not isinstance(item, dict):
                raise ValueError("judge critical-error results must be objects")
            description = item.get("description")
            present = item.get("present")
            if description not in expected_errors or description in seen_errors:
                raise ValueError("judge critical errors must be exact and unique")
            if not isinstance(present, bool):
                raise ValueError("judge critical-error present must be boolean")
            seen_errors.add(description)
            critical_errors.append(
                CriticalErrorResult(
                    description=description,
                    present=present,
                    evidence=_nonempty_text(
                        item.get("evidence"), "critical-error evidence"
                    ),
                )
            )

    return ScenarioEvaluation(
        scenario_id=scenario.id,
        title=scenario.title,
        description=scenario.description,
        model=model,
        repetition=repetition,
        use_case=scenario.use_case.value,
        mode=scenario.mode,
        support_level=scenario.support_level,
        difficulty=scenario.difficulty,
        tags=sorted(scenario.tags),
        response=payload.get("response"),
        activities=activities,
        criteria=criteria,
        critical_errors=critical_errors,
        usage=usage,
        duration_seconds=duration_seconds,
        execution_error=str(execution_error) if execution_error else None,
    )
