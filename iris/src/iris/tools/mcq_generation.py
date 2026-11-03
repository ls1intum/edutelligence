"""Tool for generating MCQ questions via the MCQ subpipeline."""

import json
from typing import Callable, Dict, List, Optional

from ..common.pyris_message import PyrisMessage
from ..common.token_usage_dto import TokenUsageDTO
from ..pipeline.shared.mcq_generation_pipeline import (
    MCQ_PLACEHOLDER,
    McqGenerationPipeline,
)
from ..web.status.status_update import StatusCallback

MAX_QUESTIONS = 10


def _questions(mcq_json: str) -> list[dict]:
    parsed = json.loads(mcq_json)
    if parsed.get("type") == "mcq-set":
        return list(parsed.get("questions", []))
    return [parsed]


def merge_quizzes(existing_json: Optional[str], new_json: str) -> str:
    """One quiz for the answer: the questions of an earlier call of the turn and the new ones.

    The answer has a single quiz widget, so a second call adds its questions to the
    first quiz instead of replacing it.
    """
    if not existing_json:
        return new_json
    questions = _questions(existing_json) + _questions(new_json)
    return json.dumps({"type": "mcq-set", "questions": questions[:MAX_QUESTIONS]})


def create_tool_generate_mcq_questions(
    mcq_pipeline: McqGenerationPipeline,
    chat_history: Optional[List[PyrisMessage]],
    callback: StatusCallback,
    mcq_result_storage: Dict[str, str],
    language: str = "English",
    lecture_content_supplier: Optional[Callable[[], Optional[str]]] = None,
    track_usage: Optional[Callable[[TokenUsageDTO], None]] = None,
) -> Callable[[str], str]:
    """
    Create a tool that generates MCQ questions using the MCQ subpipeline.

    Args:
        mcq_pipeline: The MCQ generation subpipeline instance.
        chat_history: Recent chat history for context.
        callback: Callback for status updates.
        mcq_result_storage: Shared dict to store the generated MCQ JSON.
        language: Name of the language the conversation uses, such as "German".
        lecture_content_supplier: Lazily fetches lecture content to ground MCQ
            generation. Only invoked when the tool is actually called, so the
            (potentially large) content fetch is not paid on every chat turn.
        track_usage: Records the usage of the quiz calls in the run as soon as the
            tool returns, so it is billed also when the run fails afterwards.

    Returns:
        Callable[[str], str]: Function that generates MCQ questions.
    """

    def generate_mcq_questions(command: str, count: int = 1) -> str:
        """
        Generate interactive multiple-choice questions for the student.

        Use this tool when the student asks you to quiz them, to generate quiz or
        multiple-choice questions, or to test their knowledge. Do not use it for
        questions about quizzes (for example when a quiz opens or how it is graded);
        answer those yourself.
        Pass a command describing what to generate (topic and any constraints from
        the student's request) and the number of questions: 1 unless the student
        asks for more, at most 10.

        Args:
            command: Free-text instruction describing what to generate.
            count: Number of questions, 1 to 10.

        Returns:
            str: A placeholder that will be replaced with the MCQ widget.
        """
        existing = mcq_result_storage.get("mcq_json")
        remaining = MAX_QUESTIONS - (len(_questions(existing)) if existing else 0)
        if remaining <= 0:
            return (
                f"The quiz of this answer already has {MAX_QUESTIONS} questions, "
                "the most it can hold. No question was added."
            )
        requested = max(1, count)
        count = min(requested, remaining)
        if count < requested:
            # The command may still ask for the original number.
            fit = "questions fit" if count > 1 else "question fits"
            command = (
                f"{command}\n\nOnly {count} more {fit} into this quiz: "
                f"generate exactly {count}."
            )
        try:
            lecture_content = (
                lecture_content_supplier() if lecture_content_supplier else None
            )
            if count == 1:
                result_json = mcq_pipeline(
                    command=command,
                    chat_history=chat_history,
                    language=language,
                    callback=callback,
                    lecture_content=lecture_content,
                )
            else:
                if callback:
                    callback.update()
                result_json = mcq_pipeline.generate_set(
                    command,
                    count,
                    chat_history=chat_history,
                    language=language,
                    lecture_content=lecture_content,
                )
        finally:
            if track_usage is not None:
                while mcq_pipeline.tokens:
                    track_usage(mcq_pipeline.tokens.pop(0))
        mcq_result_storage["mcq_json"] = merge_quizzes(existing, result_json)
        return MCQ_PLACEHOLDER

    return generate_mcq_questions
