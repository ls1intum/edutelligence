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


class RiskLevel(StrEnum):
    STANDARD = "standard"
    CRITICAL = "critical"


ChatMode = Literal[
    "COURSE_CHAT",
    "LECTURE_CHAT",
    "PROGRAMMING_EXERCISE_CHAT",
    "TEXT_EXERCISE_CHAT",
]
SupportLevel = Literal["low", "moderate", "high"]
Profile = Literal["smoke", "weekly", "full"]


def _default_profiles() -> set[Profile]:
    return {"full"}


class TokenCeiling(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_agent_turns: int = Field(default=3, ge=1, le=8)
    max_input_tokens: int = Field(default=36_000, ge=1)
    max_output_tokens: int = Field(default=4_500, ge=1)
    max_output_tokens_per_call: int = Field(default=3_000, ge=100, le=8_000)


class RubricCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    description: str = Field(min_length=8)
    weight: float = Field(default=1.0, gt=0)
    critical: bool = False


class Expectations(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: Literal["en", "de"] = "en"
    min_words: int | None = Field(default=None, ge=0)
    max_words: int | None = Field(default=None, ge=1)
    questions_only: bool = False
    require_citation: bool = False
    require_mcq: Literal["single", "set"] | None = None
    mcq_count: int | None = Field(default=None, ge=1, le=10)
    no_answer_expected: bool = False
    require_session_title: bool = False
    suggestion_count: int | None = Field(default=None, ge=1, le=5)
    confidence_min: float | None = Field(default=None, ge=0, le=1)
    confidence_max: float | None = Field(default=None, ge=0, le=1)
    source_count_min: int | None = Field(default=None, ge=0)
    source_count_max: int | None = Field(default=None, ge=0)
    required_tools: list[str] = Field(default_factory=list)
    optional_tools: list[str] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    tool_order: list[str] = Field(default_factory=list)
    must_include_any: list[str] = Field(default_factory=list)
    must_include_all: list[str] = Field(default_factory=list)
    must_not_include: list[str] = Field(default_factory=list)
    forbidden_code_identifiers: list[str] = Field(default_factory=list)
    solution_files: list[str] = Field(default_factory=list)
    max_solution_similarity: float = Field(default=0.80, ge=0, le=1)
    rubric: list[RubricCriterion] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_ranges_and_tools(self):
        rubric_ids = [criterion.id for criterion in self.rubric]
        if len(rubric_ids) != len(set(rubric_ids)):
            raise ValueError("rubric criterion ids must be unique")
        for field_name in (
            "required_tools",
            "optional_tools",
            "forbidden_tools",
            "tool_order",
        ):
            values = getattr(self, field_name)
            if len(values) != len(set(values)):
                raise ValueError(f"{field_name} entries must be unique")
        if (
            self.min_words is not None
            and self.max_words is not None
            and self.min_words > self.max_words
        ):
            raise ValueError("min_words must not exceed max_words")
        categories = {
            "required": set(self.required_tools),
            "optional": set(self.optional_tools),
            "forbidden": set(self.forbidden_tools),
        }
        overlaps = {
            f"{left}/{right}": categories[left] & categories[right]
            for left, right in (
                ("required", "optional"),
                ("required", "forbidden"),
                ("optional", "forbidden"),
            )
            if categories[left] & categories[right]
        }
        if overlaps:
            raise ValueError(f"tool expectation categories overlap: {overlaps}")
        missing_from_required = set(self.tool_order) - (
            set(self.required_tools) | set(self.optional_tools)
        )
        if missing_from_required:
            raise ValueError(
                "tool_order entries must be required or optional: "
                f"{missing_from_required}"
            )
        if self.require_mcq is None and self.mcq_count is not None:
            raise ValueError("mcq_count requires require_mcq")
        if self.require_mcq == "single" and self.mcq_count not in {None, 1}:
            raise ValueError("single MCQ output must have mcq_count 1")
        if self.require_mcq == "set" and (self.mcq_count or 0) < 2:
            raise ValueError("MCQ set output requires mcq_count of at least 2")
        if (self.confidence_min is None) != (self.confidence_max is None):
            raise ValueError("confidence_min and confidence_max must be set together")
        if (
            self.confidence_min is not None
            and self.confidence_max is not None
            and self.confidence_min > self.confidence_max
        ):
            raise ValueError("confidence_min must not exceed confidence_max")
        if (self.source_count_min is None) != (self.source_count_max is None):
            raise ValueError(
                "source_count_min and source_count_max must be set together"
            )
        if (
            self.source_count_min is not None
            and self.source_count_max is not None
            and self.source_count_min > self.source_count_max
        ):
            raise ValueError("source_count_min must not exceed source_count_max")
        return self


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9-]{2,63}$")
    title: str = Field(min_length=8)
    description: str = Field(min_length=16)
    use_case: UseCase
    mode: ChatMode | None = None
    support_level: SupportLevel | None = None
    risk: RiskLevel = RiskLevel.STANDARD
    profiles: set[Profile] = Field(default_factory=_default_profiles)
    tags: set[str] = Field(default_factory=set)
    fixtures: list[str] = Field(default_factory=list)
    event: Literal["build_failed", "progress_stalled"] | None = None
    payload: dict[str, Any]
    expectations: Expectations
    token_ceiling: TokenCeiling = Field(default_factory=TokenCeiling)

    @property
    def requires_critical_gate(self) -> bool:
        """Return whether one failed group must fail the suite-level safety gate."""
        return bool(
            self.risk == RiskLevel.CRITICAL
            or self.expectations.must_not_include
            or self.expectations.forbidden_code_identifiers
            or self.expectations.solution_files
        )

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, tags: set[str]) -> set[str]:
        invalid = [tag for tag in tags if not re.fullmatch(r"[a-z][a-z0-9_-]*", tag)]
        if invalid:
            raise ValueError(f"invalid tags: {invalid}")
        return tags

    @model_validator(mode="after")
    def validate_use_case_shape(self):
        if self.use_case == UseCase.CHAT and self.mode is None:
            raise ValueError("chat scenarios require mode")
        if self.use_case != UseCase.CHAT and self.mode is not None:
            raise ValueError("mode is only valid for unified chat scenarios")
        if self.use_case == UseCase.GLOBAL_SEARCH:
            if self.support_level is not None:
                raise ValueError("global search does not accept support_level")
        elif self.support_level is None:
            raise ValueError("conversational scenarios require support_level")
        has_source_bounds = self.expectations.source_count_min is not None
        if has_source_bounds != (self.use_case == UseCase.GLOBAL_SEARCH):
            raise ValueError(
                "source count bounds are required only for global-search scenarios"
            )
        if self.event and self.mode != "PROGRAMMING_EXERCISE_CHAT":
            raise ValueError("proactive events are only valid for programming chat")
        return self


class ScenarioSuite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(default=1, ge=1)
    scenarios: list[Scenario] = Field(min_length=30, max_length=50)

    @model_validator(mode="after")
    def validate_suite_coverage(self):
        ids = [scenario.id for scenario in self.scenarios]
        duplicates = sorted(
            {scenario_id for scenario_id in ids if ids.count(scenario_id) > 1}
        )
        if duplicates:
            raise ValueError(f"duplicate scenario ids: {duplicates}")

        chat = [s for s in self.scenarios if s.use_case == UseCase.CHAT]
        covered = {(s.mode, s.support_level) for s in chat}
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

        multi_turn_covered = {
            (scenario.mode, scenario.support_level)
            for scenario in chat
            if len(scenario.payload.get("chatHistory", [])) >= 3
        }
        missing_multi_turn = sorted(expected - multi_turn_covered)
        if missing_multi_turn:
            raise ValueError(
                "missing multi-turn chat mode/support combinations: "
                f"{missing_multi_turn}"
            )

        missing_titles = [
            scenario.id
            for scenario in chat
            if not scenario.expectations.require_session_title
        ]
        if missing_titles:
            raise ValueError(
                f"chat scenarios must check session-title output: {missing_titles}"
            )
        invalid_suggestions = [
            scenario.id
            for scenario in chat
            if (
                scenario.mode in {"COURSE_CHAT", "PROGRAMMING_EXERCISE_CHAT"}
                and scenario.expectations.suggestion_count != 2
            )
            or (
                scenario.mode in {"LECTURE_CHAT", "TEXT_EXERCISE_CHAT"}
                and scenario.expectations.suggestion_count is not None
            )
        ]
        if invalid_suggestions:
            raise ValueError(
                "chat scenarios must mirror production suggestion behavior: "
                f"{invalid_suggestions}"
            )

        use_cases = {scenario.use_case for scenario in self.scenarios}
        missing_use_cases = set(UseCase) - use_cases
        if missing_use_cases:
            raise ValueError(f"missing use cases: {sorted(missing_use_cases)}")
        missing_confidence = [
            scenario.id
            for scenario in self.scenarios
            if scenario.use_case == UseCase.AUTONOMOUS_TUTOR
            and scenario.expectations.confidence_min is None
        ]
        if missing_confidence:
            raise ValueError(
                "autonomous tutor scenarios must check confidence: "
                f"{missing_confidence}"
            )
        for use_case in (UseCase.TUTOR_SUGGESTION, UseCase.AUTONOMOUS_TUTOR):
            covered_support = {
                scenario.support_level
                for scenario in self.scenarios
                if scenario.use_case == use_case
            }
            missing_support = {"low", "moderate", "high"} - covered_support
            if missing_support:
                raise ValueError(
                    f"{use_case.value} is missing support levels: "
                    f"{sorted(missing_support)}"
                )
        return self
