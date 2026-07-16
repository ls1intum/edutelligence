"""Tool for generating MCQ questions via the MCQ subpipeline."""

from typing import Callable, Dict, List, Optional

from ..common.pyris_message import PyrisMessage
from ..pipeline.shared.mcq_generation_pipeline import McqGenerationPipeline
from ..web.status.status_update import StatusCallback


def create_tool_generate_mcq_questions(
    mcq_pipeline: McqGenerationPipeline,
    chat_history: Optional[List[PyrisMessage]],
    callback: StatusCallback,
    mcq_result_storage: Dict[str, str],
    user_language: str = "en",
    lecture_content_supplier: Optional[Callable[[], Optional[str]]] = None,
) -> Callable[[str], str]:
    """
    Create a tool that generates MCQ questions using the MCQ subpipeline.

    Args:
        mcq_pipeline: The MCQ generation subpipeline instance.
        chat_history: Recent chat history for context.
        callback: Callback for status updates.
        mcq_result_storage: Shared dict to store the generated MCQ JSON.
        user_language: The user's preferred language ("en" or "de").
        lecture_content_supplier: Lazily fetches lecture content to ground MCQ
            generation. Only invoked when the tool is actually called, so the
            (potentially large) content fetch is not paid on every chat turn.

    Returns:
        Callable[[str], str]: Function that generates MCQ questions.
    """

    def generate_mcq_questions(command: str) -> str:
        """
        Generate interactive multiple-choice questions for the student.
        Use this tool when the student asks for quiz questions, MCQs, or
        wants to test their knowledge. Pass a command describing what to
        generate (topic and any constraints from the student's request).
        Default to 1 question unless the student explicitly asks for
        multiple questions or specifies a number.

        Args:
            command: Free-text instruction describing what to generate.

        Returns:
            str: A placeholder that will be replaced with the MCQ widget.
        """
        lecture_content = (
            lecture_content_supplier() if lecture_content_supplier else None
        )
        result_json = mcq_pipeline(
            command=command,
            chat_history=chat_history,
            user_language=user_language,
            callback=callback,
            lecture_content=lecture_content,
        )
        mcq_result_storage["mcq_json"] = result_json
        return "[MCQ_RESULT]"

    return generate_mcq_questions
