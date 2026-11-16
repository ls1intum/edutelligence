"""Response Assessment Service: assesses the answer of Iris with an LLM judge.

The judge receives the test case, the answer of Iris and the criteria, and returns a rating per
criterion as structured JSON (one of yes / to_some_extent / no / not_applicable plus reasoning).
"""

import json
from typing import Protocol

from ...logos.model_inference_service import ModelInferenceService
from ..models import Assessment, CriterionScore, Rating, TestCase
from .criteria import CRITERIA

SYSTEM_PROMPT = """You assess the answer of Iris, an AI tutor for programming courses, to a student.
Rate the answer on each criterion with one of:
- yes: the answer fully meets the criterion
- to_some_extent: the answer partly meets the criterion
- no: the answer does not meet the criterion
- not_applicable: the criterion does not apply to this situation
Give a short reasoning for every rating.

Criteria:
{criteria}"""


class ResponseAssessmentService(Protocol):
    def assess(self, test_case: TestCase, response: str) -> Assessment: ...


class LlmJudgeAssessmentService:
    def __init__(self, inference: ModelInferenceService, model: str, attempts: int = 3):
        self.inference = inference
        self.model = model
        self.attempts = attempts

    def assess(self, test_case: TestCase, response: str) -> Assessment:
        criteria = "\n".join(f"- {c.id} ({c.name}): {c.description}" for c in CRITERIA)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT.format(criteria=criteria)},
            {"role": "user", "content": _describe(test_case, response)},
        ]
        # the judge may return invalid or incomplete JSON now and then: ask again
        error: Exception | None = None
        for _ in range(self.attempts):
            answer = self.inference.complete(self.model, messages, json_schema=_schema())
            try:
                return _parse(test_case.id, answer)
            except (ValueError, KeyError, TypeError) as e:  # JSON or validation error
                error = e
        raise ValueError(f"no valid assessment after {self.attempts} attempts: {error}")


def _parse(test_case_id: int, answer: str) -> Assessment:
    ratings = json.loads(answer)
    return Assessment(
        test_case_id=test_case_id,
        scores=[
            CriterionScore(
                criterion=c.id,
                rating=ratings[c.id]["rating"],
                reasoning=ratings[c.id].get("reasoning", ""),
            )
            for c in CRITERIA
        ],
    )


def _schema() -> dict:
    """JSON schema of the judge's answer (strict structured output)."""
    rating = {
        "type": "object",
        "properties": {
            "rating": {"type": "string", "enum": [r.value for r in Rating]},
            "reasoning": {"type": "string"},
        },
        "required": ["rating", "reasoning"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {c.id: rating for c in CRITERIA},
        "required": [c.id for c in CRITERIA],
        "additionalProperties": False,
    }


def _describe(test_case: TestCase, response: str) -> str:
    """Puts everything the judge needs to know into one text."""
    parts = [f"Chat mode: {test_case.chat_mode.value}"]
    if test_case.exercise:
        parts.append(f"Exercise: {test_case.exercise.title}")
        if test_case.exercise.problem_statement:
            parts.append(f"Problem statement:\n{test_case.exercise.problem_statement}")
    if test_case.submission:
        for path, content in test_case.submission.repository.items():
            parts.append(f"Student file {path}:\n{content}")
        if test_case.submission.build_failed:
            parts.append("Build log:\n" + "\n".join(test_case.submission.build_log))
    conversation = "\n".join(f"{m.sender.upper()}: {m.text}" for m in test_case.conversation)
    parts.append(f"Conversation:\n{conversation}")
    parts.append(f"Answer of Iris to assess:\n{response}")
    return "\n\n".join(parts)
