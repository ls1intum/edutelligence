from __future__ import annotations

import hashlib
import json
from typing import Any, Sequence

from athena.schemas import (
    ExerciseType,
    GradingCriterion,
    LearnerProfile,
    ModelingExercise,
    ModelingFeedback,
    ModelingSubmission,
    TextExercise,
    TextFeedback,
    TextSubmission,
)
from athena.schemas.text_submission import TextLanguageEnum

from .models import ArtefactType, Criterion, EvaluateFeedback, EvaluateRequest, FeedbackTarget, Tone, Detail


class UnsupportedEvaluateRequestError(ValueError):
    """Raised when the current manager implementation cannot translate a µEd request."""

    def __init__(self, message: str, *, code: str = "NOT_IMPLEMENTED", status_code: int = 501):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def build_athena_feedback_suggestions_request(
    evaluate_request: EvaluateRequest,
) -> tuple[ExerciseType, dict[str, Any]]:
    """Translate a µEd evaluate request into Athena's /feedback_suggestions payload."""

    if evaluate_request.submission.type == ArtefactType.TEXT:
        return ExerciseType.text, _build_text_request(evaluate_request)
    if evaluate_request.submission.type == ArtefactType.MODEL:
        return ExerciseType.modeling, _build_model_request(evaluate_request)

    raise UnsupportedEvaluateRequestError(
        f"µEd /evaluate is currently only supported for TEXT and MODEL submissions. "
        f"Received {evaluate_request.submission.type.value}.",
    )


def convert_athena_feedbacks_to_med_feedbacks(
    artefact_type: ArtefactType,
    submission_format: str | None,
    athena_feedbacks: Sequence[dict[str, Any]],
) -> list[EvaluateFeedback]:
    """Translate Athena feedback objects back into µEd feedback objects."""

    if artefact_type == ArtefactType.TEXT:
        return [
            _convert_text_feedback(TextFeedback.model_validate(feedback), submission_format)
            for feedback in athena_feedbacks
        ]
    if artefact_type == ArtefactType.MODEL:
        return [
            _convert_model_feedback(ModelingFeedback.model_validate(feedback), submission_format)
            for feedback in athena_feedbacks
        ]

    raise UnsupportedEvaluateRequestError(
        f"µEd feedback conversion is currently not implemented for {artefact_type.value}.",
    )


def _build_text_request(evaluate_request: EvaluateRequest) -> dict[str, Any]:
    exercise_id = _stable_int_id(
        "exercise",
        _first_non_empty(
            evaluate_request.task.task_id if evaluate_request.task else None,
            evaluate_request.submission.task_id,
            evaluate_request.task.title if evaluate_request.task else None,
        ),
    )
    submission_id = _stable_int_id(
        "submission",
        _first_non_empty(
            evaluate_request.submission.submission_id,
            _canonical_json(evaluate_request.submission.content),
        ),
    )
    exercise = TextExercise(
        id=exercise_id,
        title=_build_exercise_title(evaluate_request),
        type=ExerciseType.text,
        max_points=_derive_max_points(evaluate_request.criteria),
        bonus_points=0.0,
        grading_instructions=_criteria_to_grading_instructions(evaluate_request.criteria),
        grading_criteria=_criteria_to_grading_criteria(evaluate_request.criteria),
        problem_statement=_extract_textual_content(
            evaluate_request.task.content if evaluate_request.task else None,
            preferred_keys=("text", "markdown", "html"),
        ),
        example_solution=_extract_textual_content(
            evaluate_request.task.reference_solution if evaluate_request.task else None,
            preferred_keys=("text", "markdown", "html"),
        ),
        meta={},
    )
    submission = TextSubmission(
        id=submission_id,
        exercise_id=exercise.id,
        text=_extract_textual_content(
            evaluate_request.submission.content,
            preferred_keys=("text", "markdown", "html"),
        ) or "",
        language=_to_text_language(evaluate_request),
        meta={},
    )
    return _build_feedback_request_payload(evaluate_request, exercise, submission)


def _build_model_request(evaluate_request: EvaluateRequest) -> dict[str, Any]:
    exercise_id = _stable_int_id(
        "exercise",
        _first_non_empty(
            evaluate_request.task.task_id if evaluate_request.task else None,
            evaluate_request.submission.task_id,
            evaluate_request.task.title if evaluate_request.task else None,
        ),
    )
    submission_id = _stable_int_id(
        "submission",
        _first_non_empty(
            evaluate_request.submission.submission_id,
            _canonical_json(evaluate_request.submission.content),
        ),
    )
    exercise = ModelingExercise(
        id=exercise_id,
        title=_build_exercise_title(evaluate_request),
        type=ExerciseType.modeling,
        max_points=_derive_max_points(evaluate_request.criteria),
        bonus_points=0.0,
        grading_instructions=_criteria_to_grading_instructions(evaluate_request.criteria),
        grading_criteria=_criteria_to_grading_criteria(evaluate_request.criteria),
        problem_statement=_extract_textual_content(
            evaluate_request.task.content if evaluate_request.task else None,
            preferred_keys=("text", "markdown", "model"),
        ),
        example_solution=_extract_textual_content(
            evaluate_request.task.reference_solution if evaluate_request.task else None,
            preferred_keys=("model", "text", "markdown"),
        ),
        meta={},
    )
    submission = ModelingSubmission(
        id=submission_id,
        exercise_id=exercise.id,
        model=_extract_textual_content(
            evaluate_request.submission.content,
            preferred_keys=("model", "text", "markdown"),
        ) or "",
        meta={},
    )
    return _build_feedback_request_payload(evaluate_request, exercise, submission)


def _build_feedback_request_payload(
    evaluate_request: EvaluateRequest,
    exercise: TextExercise | ModelingExercise,
    submission: TextSubmission | ModelingSubmission,
) -> dict[str, Any]:
    is_graded = not (
        evaluate_request.pre_submission_feedback
        and evaluate_request.pre_submission_feedback.enabled
    )
    payload: dict[str, Any] = {
        "exercise": exercise.model_dump(mode="json", by_alias=True),
        "submission": submission.model_dump(mode="json", by_alias=True),
        "isGraded": is_graded,
    }
    learner_profile = _to_learner_profile(evaluate_request)
    if learner_profile is not None:
        payload["learnerProfile"] = learner_profile.model_dump(mode="json", by_alias=True)
    return payload


def _convert_text_feedback(
    feedback: TextFeedback,
    submission_format: str | None,
) -> EvaluateFeedback:
    target = None
    if feedback.index_start is not None or feedback.index_end is not None:
        target = FeedbackTarget(
            artefact_type=ArtefactType.TEXT,
            format=submission_format,
            locator={
                "type": "span",
                "startIndex": feedback.index_start if feedback.index_start is not None else 0,
                "endIndex": (
                    feedback.index_end
                    if feedback.index_end is not None
                    else feedback.index_start
                ) or 0,
            },
        )
    return EvaluateFeedback(
        feedback_id=str(feedback.id) if feedback.id is not None else None,
        title=feedback.title,
        message=feedback.description,
        awarded_points=_maybe_awarded_points(feedback.credits, feedback.is_graded),
        target=target,
    )


def _convert_model_feedback(
    feedback: ModelingFeedback,
    submission_format: str | None,
) -> EvaluateFeedback:
    target = None
    reference = feedback.reference or next(iter(feedback.element_ids or []), None)
    if reference:
        element_type, _, element_id = reference.partition(":")
        target = FeedbackTarget(
            artefact_type=ArtefactType.MODEL,
            format=submission_format,
            locator={
                "type": "element",
                "elementId": element_id or reference,
                **({"elementType": element_type} if element_id else {}),
            },
        )
    return EvaluateFeedback(
        feedback_id=str(feedback.id) if feedback.id is not None else None,
        title=feedback.title,
        message=feedback.description,
        awarded_points=_maybe_awarded_points(feedback.credits, feedback.is_graded),
        target=target,
    )


def _derive_max_points(criteria: Sequence[Criterion] | None) -> float:
    total = sum(criterion.max_points or 0.0 for criterion in criteria or [])
    return float(total)


def _criteria_to_grading_instructions(criteria: Sequence[Criterion] | None) -> str | None:
    if not criteria:
        return None

    lines = []
    for criterion in criteria:
        context = _stringify_optional(criterion.context)
        if context:
            lines.append(f"{criterion.name}: {context}")
        else:
            lines.append(criterion.name)
    return "\n\n".join(lines) or None


def _criteria_to_grading_criteria(
    criteria: Sequence[Criterion] | None,
) -> list[GradingCriterion] | None:
    if not criteria:
        return None

    return [
        GradingCriterion(
            id=_stable_int_id(
                "criterion",
                _first_non_empty(criterion.criterion_id, criterion.name),
            ),
            title=criterion.name,
            structured_grading_instructions=[],
        )
        for criterion in criteria
    ]


def _to_learner_profile(evaluate_request: EvaluateRequest) -> LearnerProfile | None:
    preference = evaluate_request.user.preference if evaluate_request.user else None
    if preference is None:
        return None

    detail = {
        Detail.BRIEF: 1,
        Detail.MEDIUM: 2,
        Detail.DETAILED: 3,
    }.get(preference.detail, 2)
    tone = {
        Tone.FORMAL: 1,
        Tone.NEUTRAL: 2,
        Tone.FRIENDLY: 3,
    }.get(preference.tone, 2)
    return LearnerProfile(feedback_detail=detail, feedback_formality=tone)


def _to_text_language(evaluate_request: EvaluateRequest) -> TextLanguageEnum | None:
    preference = evaluate_request.user.preference if evaluate_request.user else None
    if preference is None or preference.language is None:
        return None

    language = preference.language.lower()
    if language == "en":
        return TextLanguageEnum.ENGLISH
    if language == "de":
        return TextLanguageEnum.GERMAN
    return None


def _build_exercise_title(evaluate_request: EvaluateRequest) -> str:
    return _first_non_empty(
        evaluate_request.task.title if evaluate_request.task else None,
        evaluate_request.task.task_id if evaluate_request.task else None,
        evaluate_request.submission.task_id,
        "Untitled task",
    )


def _extract_textual_content(
    content: dict[str, Any] | None,
    *,
    preferred_keys: Sequence[str],
) -> str | None:
    if content is None:
        return None

    for key in preferred_keys:
        if key not in content or content[key] is None:
            continue
        value = content[key]
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=True, sort_keys=True)

    if len(content) == 1:
        return _stringify_optional(next(iter(content.values())))

    return json.dumps(content, ensure_ascii=True, sort_keys=True)


def _stringify_optional(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _stable_int_id(namespace: str, source: str) -> int:
    digest = hashlib.sha256(f"{namespace}:{source}".encode("utf-8")).digest()
    identifier = int.from_bytes(digest[:8], "big") % 2_147_483_647
    return identifier or 1


def _first_non_empty(*values: str | None) -> str:
    for value in values:
        if value:
            return value
    return ""


def _maybe_awarded_points(credits: float, is_graded: bool | None) -> float | None:
    if is_graded is False and credits == 0.0:
        return None
    return credits
