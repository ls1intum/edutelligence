from __future__ import annotations

import re
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# pylint: disable=missing-class-docstring


class UseCase(StrEnum):
    CHAT = "chat"
    TUTOR_SUGGESTION = "tutor_suggestion"
    AUTONOMOUS_TUTOR = "autonomous_tutor"
    GLOBAL_SEARCH = "global_search"


ChatMode = Literal[
    "COURSE_CHAT",
    "LECTURE_CHAT",
    "PROGRAMMING_EXERCISE_CHAT",
    "TEXT_EXERCISE_CHAT",
]
SupportLevel = Literal["low", "moderate", "high"]
Profile = Literal["smoke", "weekly", "full"]
Difficulty = Literal["foundation", "advanced"]


def _default_profiles() -> set[Profile]:
    return {"full"}


class TokenCeiling(BaseModel):
    """Conservative capacity used only by the pre-run cost guard."""

    model_config = ConfigDict(extra="forbid")

    max_agent_turns: int = Field(default=3, ge=1, le=8)
    max_input_tokens: int = Field(default=36_000, ge=1)
    max_output_tokens: int = Field(default=4_500, ge=1)
    max_output_tokens_per_call: int = Field(default=3_000, ge=100, le=8_000)


class Criterion(BaseModel):
    """One human-readable quality dimension rated by the independent judge."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    description: str = Field(min_length=16, max_length=300)


class Scenario(BaseModel):
    """A realistic Iris request and the plain-language behavior we care about."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9-]{2,63}$")
    title: str = Field(min_length=8)
    description: str = Field(min_length=16)
    use_case: UseCase
    mode: ChatMode | None = None
    support_level: SupportLevel | None = None
    difficulty: Difficulty = "foundation"
    profiles: set[Profile] = Field(default_factory=_default_profiles)
    tags: set[str] = Field(default_factory=set)
    fixtures: list[str] = Field(default_factory=list)
    event: Literal["build_failed", "progress_stalled"] | None = None
    payload: dict[str, Any]
    criteria: list[Criterion] = Field(min_length=3, max_length=5)
    critical_errors: list[str] = Field(default_factory=list, max_length=3)
    token_ceiling: TokenCeiling = Field(default_factory=TokenCeiling)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, tags: set[str]) -> set[str]:
        invalid = [tag for tag in tags if not re.fullmatch(r"[a-z][a-z0-9_-]*", tag)]
        if invalid:
            raise ValueError(f"invalid tags: {invalid}")
        return tags

    @field_validator("critical_errors")
    @classmethod
    def validate_critical_errors(cls, values: list[str]) -> list[str]:
        if any(len(value.strip()) < 16 for value in values):
            raise ValueError(
                "critical errors must be clear natural-language statements"
            )
        if len(values) != len(set(values)):
            raise ValueError("critical errors must be unique")
        return values

    @model_validator(mode="after")
    def validate_shape(self):
        criterion_ids = [criterion.id for criterion in self.criteria]
        if len(criterion_ids) != len(set(criterion_ids)):
            raise ValueError("criterion ids must be unique")
        if (
            self.use_case in {UseCase.CHAT, UseCase.TUTOR_SUGGESTION}
            and self.mode is None
        ):
            raise ValueError("conversational scenarios require mode")
        if (
            self.use_case not in {UseCase.CHAT, UseCase.TUTOR_SUGGESTION}
            and self.mode is not None
        ):
            raise ValueError("mode is only valid for conversational scenarios")
        if self.use_case == UseCase.GLOBAL_SEARCH:
            if self.support_level is not None:
                raise ValueError("global search does not accept support_level")
        elif self.support_level is None:
            raise ValueError("conversational scenarios require support_level")
        if self.event and self.mode != "PROGRAMMING_EXERCISE_CHAT":
            raise ValueError("proactive events are only valid for programming chat")
        return self


class ScenarioSuite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[2]
    scenarios: list[Scenario]

    @model_validator(mode="after")
    def validate_suite_coverage(self):
        if len(self.scenarios) != 50:
            raise ValueError("the Iris benchmark corpus requires exactly 50 scenarios")

        ids = [scenario.id for scenario in self.scenarios]
        duplicates = sorted(
            {scenario_id for scenario_id in ids if ids.count(scenario_id) > 1}
        )
        if duplicates:
            raise ValueError(f"duplicate scenario ids: {duplicates}")

        chat = [
            scenario for scenario in self.scenarios if scenario.use_case == UseCase.CHAT
        ]
        covered = {(scenario.mode, scenario.support_level) for scenario in chat}
        expected = {
            (mode, support)
            for mode in (
                "COURSE_CHAT",
                "LECTURE_CHAT",
                "PROGRAMMING_EXERCISE_CHAT",
                "TEXT_EXERCISE_CHAT",
            )
            for support in ("low", "moderate", "high")
        }
        missing = sorted(expected - covered)
        if missing:
            raise ValueError(f"missing chat mode/support combinations: {missing}")

        covered_use_cases = {scenario.use_case for scenario in self.scenarios}
        missing_use_cases = set(UseCase) - covered_use_cases
        if missing_use_cases:
            raise ValueError(
                "missing use cases: "
                f"{sorted(item.value for item in missing_use_cases)}"
            )
        return self
