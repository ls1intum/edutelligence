from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable

from iris.qa.schema import Scenario, UseCase

# pylint: disable=missing-class-docstring


_WORD_RE = re.compile(r"\b[\w'-]+\b", re.UNICODE)
_CODE_BLOCK_RE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)
# Exact seven-field citation block consumed by Artemis' citation-text parser:
# [cite:TYPE:ENTITY_ID:PAGE:START:END:KEYWORD:SUMMARY]
_CITATION_RE = re.compile(
    r"\[cite:[LF]:[^:\[\]]+:[^:\[\]]*:[^:\[\]]*:[^:\[\]]*:" r"[^:\[\]]*:[^\[\]]*\]"
)

_LANGUAGE_MARKERS = {
    "en": {
        "the",
        "you",
        "your",
        "what",
        "how",
        "this",
        "that",
        "with",
        "from",
        "could",
    },
    "de": {
        "der",
        "die",
        "das",
        "du",
        "dein",
        "was",
        "wie",
        "mit",
        "aus",
        "kannst",
        "welche",
    },
}


@dataclass(frozen=True)
class ActivityTrace:
    name: str
    state: str = "FINISHED"
    detail: str | None = None
    result: str | None = None


@dataclass(frozen=True)
class CheckResult:
    id: str
    passed: bool
    message: str
    critical: bool = False
    score: float = 1.0


@dataclass
class ScenarioEvaluation:
    scenario_id: str
    model: str
    response: str | None
    activities: list[ActivityTrace]
    checks: list[CheckResult] = field(default_factory=list)
    semantic_scores: dict[str, float] = field(default_factory=dict)
    semantic_weights: dict[str, float] = field(default_factory=dict)
    semantic_evidence: dict[str, str] = field(default_factory=dict)
    execution_error: str | None = None

    @property
    def deterministic_score(self) -> float:
        checks = [
            check for check in self.checks if not check.id.startswith("semantic:")
        ]
        if not checks:
            return 0.0
        return sum(check.score if check.passed else 0 for check in checks) / len(checks)

    @property
    def semantic_score(self) -> float | None:
        if not self.semantic_scores:
            return None
        total_weight = sum(
            self.semantic_weights.get(criterion, 1.0)
            for criterion in self.semantic_scores
        )
        return (
            sum(
                score * self.semantic_weights.get(criterion, 1.0)
                for criterion, score in self.semantic_scores.items()
            )
            / total_weight
        )

    @property
    def score(self) -> float:
        # A hard failure must not contribute a deceptively healthy partial
        # score to the suite mean. The individual deterministic and semantic
        # scores remain available in reports for diagnosis.
        if self.critical_failure:
            return 0.0
        semantic = self.semantic_score
        if semantic is None:
            return self.deterministic_score
        return 0.4 * self.deterministic_score + 0.6 * semantic

    @property
    def critical_failure(self) -> bool:
        return bool(self.execution_error) or any(
            check.critical and not check.passed for check in self.checks
        )

    @property
    def passed(self) -> bool:
        return not self.critical_failure and self.score >= 0.75


def _check(
    check_id: str,
    condition: bool,
    success: str,
    failure: str,
    *,
    critical: bool = False,
) -> CheckResult:
    return CheckResult(
        id=check_id,
        passed=condition,
        message=success if condition else failure,
        critical=critical,
    )


def _words(text: str) -> list[str]:
    return _WORD_RE.findall(text)


def _language_matches(text: str, expected: str) -> bool:
    words = [word.casefold() for word in _words(text)]
    if len(words) < 6:
        return True
    expected_hits = sum(word in _LANGUAGE_MARKERS[expected] for word in words)
    other = "de" if expected == "en" else "en"
    other_hits = sum(word in _LANGUAGE_MARKERS[other] for word in words)
    return expected_hits >= other_hits


def _questions_only(text: str) -> bool:
    stripped = re.sub(r"[`*_>#-]", "", text).strip()
    # Markdown/ordered-list markers are presentation, not declarative
    # sentences. Remove them before sentence splitting so a numbered series of
    # genuine coaching questions is not rejected as containing the statement
    # ``1.``.
    stripped = re.sub(r"(?m)^\s*\d+[.)]\s*", "", stripped)
    if not stripped:
        return False
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", stripped)
        if sentence.strip()
    ]
    if not sentences:
        return False
    questions = [sentence for sentence in sentences if sentence.endswith("?")]
    if len(questions) == len(sentences):
        return True
    # Permit one short opening acknowledgement such as "Good question!" or
    # "Gute Frage!". Explanatory statements and any later non-question still
    # fail the low-support guard.
    preamble = sentences[0]
    return (
        len(questions) == len(sentences) - 1
        and preamble.endswith("!")
        and len(_words(preamble)) <= 4
        and all(sentence.endswith("?") for sentence in sentences[1:])
    )


def _json_objects(text: str) -> Iterable[dict[str, Any]]:
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            value, _ = decoder.raw_decode(text[match.start() :])  # noqa: E203
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            yield value


def _valid_mcq_question(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    options = item.get("options")
    return (
        isinstance(item.get("question"), str)
        and bool(item["question"].strip())
        and isinstance(options, list)
        and len(options) == 4
        and all(
            isinstance(option, dict)
            and isinstance(option.get("text"), str)
            and isinstance(option.get("correct"), bool)
            for option in options
        )
        and sum(option["correct"] for option in options) == 1
        and isinstance(item.get("explanation"), str)
        and bool(item["explanation"].strip())
    )


def _has_expected_mcq(text: str, kind: str, expected_count: int | None) -> bool:
    for item in _json_objects(text):
        if kind == "single" and item.get("type") == "mcq":
            if _valid_mcq_question(item):
                return True
        if kind == "set" and item.get("type") == "mcq-set":
            questions = item.get("questions")
            if (
                isinstance(questions, list)
                and len(questions) == expected_count
                and all(_valid_mcq_question(question) for question in questions)
            ):
                return True
    return False


def _normalized_code(text: str) -> str:
    return " ".join(re.findall(r"[A-Za-z_][A-Za-z0-9_]*|\d+|[^\s]", text))


def _max_solution_similarity(
    response: str,
    solution_files: list[str],
    fixture_root: Path,
) -> tuple[float, str | None]:
    code_blocks = _CODE_BLOCK_RE.findall(response)
    if not response.strip() or not solution_files:
        return 0.0, None
    # Check each fenced block independently and the complete answer as a
    # fallback. Otherwise an unfenced solution, or extra harmless snippets
    # surrounding a copied solution, could dilute the similarity score.
    response_candidates = [
        normalized
        for candidate in (*code_blocks, response)
        if (normalized := _normalized_code(candidate))
    ]
    maximum = 0.0
    maximum_path = None
    root = fixture_root.resolve()
    for relative in solution_files:
        path = (root / relative).resolve()
        if root not in path.parents:
            raise ValueError(f"Solution file escapes fixture root: {relative}")
        solution = _normalized_code(path.read_text(encoding="utf-8"))
        for response_code in response_candidates:
            similarity = (
                1.0
                if solution and solution in response_code
                else SequenceMatcher(None, response_code, solution).ratio()
            )
            if similarity > maximum:
                maximum = similarity
                maximum_path = relative
    return maximum, maximum_path


def evaluate_deterministic(
    scenario: Scenario,
    *,
    model: str,
    response: str | None,
    activities: list[ActivityTrace],
    fixture_root: Path,
    product_diagnostics: dict[str, Any] | None = None,
) -> ScenarioEvaluation:
    result = ScenarioEvaluation(
        scenario_id=scenario.id,
        model=model,
        response=response,
        activities=activities,
    )
    expected = scenario.expectations
    diagnostics = product_diagnostics or {}
    text = response or ""
    folded = text.casefold()
    activity_names = [activity.name for activity in activities]

    if expected.no_answer_expected:
        result.checks.append(
            _check(
                "no_answer",
                not text.strip() or text.strip() == "NO_RESPONSE_NEEDED",
                "No answer was emitted as expected.",
                "An answer was emitted for a no-response scenario.",
                critical=True,
            )
        )
    else:
        result.checks.append(
            _check(
                "nonempty_response",
                bool(text.strip()),
                "A response was emitted.",
                "The model returned an empty response.",
                critical=True,
            )
        )

    if text.strip():
        result.checks.append(
            _check(
                "language",
                _language_matches(text, expected.language),
                f"Response language matches {expected.language}.",
                f"Response does not appear to be {expected.language}.",
            )
        )
        count = len(_words(text))
        if expected.min_words is not None:
            result.checks.append(
                _check(
                    "min_words",
                    count >= expected.min_words,
                    f"Response contains at least {expected.min_words} words.",
                    f"Response has {count} words; expected at least {expected.min_words}.",
                )
            )
        if expected.max_words is not None:
            result.checks.append(
                _check(
                    "max_words",
                    count <= expected.max_words,
                    f"Response stays within {expected.max_words} words.",
                    f"Response has {count} words; expected at most {expected.max_words}.",
                )
            )
        if expected.questions_only:
            result.checks.append(
                _check(
                    "questions_only",
                    _questions_only(text),
                    "Response contains guiding questions only.",
                    "Low-support response contains statements or explanations.",
                    critical=True,
                )
            )

    if expected.require_citation:
        result.checks.append(
            _check(
                "citation",
                bool(_CITATION_RE.search(text)),
                "Response contains a valid Artemis citation block.",
                "Expected a valid Artemis citation block.",
                critical=True,
            )
        )
    if expected.require_mcq:
        result.checks.append(
            _check(
                "mcq",
                _has_expected_mcq(text, expected.require_mcq, expected.mcq_count),
                f"Response contains a valid {expected.require_mcq} MCQ payload.",
                f"Expected a valid {expected.require_mcq} MCQ payload.",
                critical=True,
            )
        )
    if expected.require_session_title:
        title = diagnostics.get("sessionTitle")
        result.checks.append(
            _check(
                "session_title",
                isinstance(title, str) and bool(title.strip()),
                "A session title was generated.",
                "Expected a generated session title.",
                critical=True,
            )
        )
    if expected.suggestion_count is not None:
        suggestions = diagnostics.get("suggestions")
        valid_suggestions = (
            isinstance(suggestions, list)
            and len(suggestions) == expected.suggestion_count
            and all(
                isinstance(suggestion, str) and bool(suggestion.strip())
                for suggestion in suggestions
            )
            and len(set(suggestions)) == len(suggestions)
        )
        result.checks.append(
            _check(
                "interaction_suggestions",
                valid_suggestions,
                f"Generated {expected.suggestion_count} distinct suggestions.",
                f"Expected {expected.suggestion_count} distinct suggestions.",
                critical=True,
            )
        )
    if expected.confidence_min is not None and expected.confidence_max is not None:
        confidence = diagnostics.get("confidence")
        valid_confidence = (
            isinstance(confidence, (int, float))
            and not isinstance(confidence, bool)
            and expected.confidence_min <= float(confidence) <= expected.confidence_max
        )
        result.checks.append(
            _check(
                "confidence",
                valid_confidence,
                "Autonomous confidence is within the expected range.",
                f"Expected confidence in [{expected.confidence_min:.2f}, "
                f"{expected.confidence_max:.2f}], got {confidence!r}.",
                critical=True,
            )
        )
    if expected.source_count_min is not None and expected.source_count_max is not None:
        sources = diagnostics.get("sources")
        valid_sources = isinstance(sources, list) and (
            expected.source_count_min <= len(sources) <= expected.source_count_max
        )
        result.checks.append(
            _check(
                "global_search_sources",
                valid_sources,
                "Global search returned the expected number of sources.",
                f"Expected {expected.source_count_min}..{expected.source_count_max} "
                f"sources, got {len(sources) if isinstance(sources, list) else None}.",
                critical=True,
            )
        )
    if (
        scenario.use_case == UseCase.GLOBAL_SEARCH
        and scenario.payload.get("intent") == "SKIP_AI"
    ):
        candidate_calls = diagnostics.get("candidateProviderCalls")
        result.checks.append(
            _check(
                "global_search_candidate_skip",
                candidate_calls == 0,
                "Navigation search skipped the candidate answer model.",
                f"Expected zero candidate calls for SKIP_AI, got {candidate_calls!r}.",
                critical=True,
            )
        )

    for tool in expected.required_tools:
        completed = any(
            activity.name == tool and activity.state == "FINISHED"
            for activity in activities
        )
        result.checks.append(
            _check(
                f"required_tool:{tool}",
                completed,
                f"Required tool {tool} was used.",
                f"Required tool {tool} did not finish successfully.",
                critical=True,
            )
        )
    for tool in expected.forbidden_tools:
        result.checks.append(
            _check(
                f"forbidden_tool:{tool}",
                tool not in activity_names,
                f"Forbidden tool {tool} was not used.",
                f"Forbidden tool {tool} was used.",
                critical=True,
            )
        )
    if expected.tool_order:
        positions = [
            activity_names.index(tool) if tool in activity_names else -1
            for tool in expected.tool_order
        ]
        ordered = all(position >= 0 for position in positions) and positions == sorted(
            positions
        )
        result.checks.append(
            _check(
                "tool_order",
                ordered,
                "Tool activity order matches the expected investigation path.",
                f"Expected tool order {expected.tool_order}; got {activity_names}.",
            )
        )

    for phrase in expected.must_include_all:
        result.checks.append(
            _check(
                f"include:{phrase}",
                phrase.casefold() in folded,
                f"Response includes required concept {phrase!r}.",
                f"Response omits required concept {phrase!r}.",
            )
        )
    if expected.must_include_any:
        result.checks.append(
            _check(
                "include_any",
                any(
                    phrase.casefold() in folded for phrase in expected.must_include_any
                ),
                "Response includes at least one expected concept.",
                f"Response includes none of {expected.must_include_any}.",
            )
        )
    for phrase in expected.must_not_include:
        result.checks.append(
            _check(
                f"exclude:{phrase}",
                phrase.casefold() not in folded,
                f"Response does not disclose forbidden phrase {phrase!r}.",
                f"Response discloses forbidden phrase {phrase!r}.",
                critical=True,
            )
        )

    code = "\n".join(_CODE_BLOCK_RE.findall(text))
    for identifier in expected.forbidden_code_identifiers:
        result.checks.append(
            _check(
                f"forbidden_identifier:{identifier}",
                not re.search(rf"\b{re.escape(identifier)}\b", code),
                f"Code does not expose exercise identifier {identifier}.",
                f"Code exposes exercise identifier {identifier}.",
                critical=True,
            )
        )
    similarity, similar_path = _max_solution_similarity(
        text, expected.solution_files, fixture_root
    )
    if expected.solution_files:
        result.checks.append(
            _check(
                "solution_similarity",
                similarity <= expected.max_solution_similarity,
                f"Code similarity stays below {expected.max_solution_similarity:.2f}.",
                f"Code similarity {similarity:.2f} to {similar_path} exceeds "
                f"{expected.max_solution_similarity:.2f}.",
                critical=True,
            )
        )

    return result
