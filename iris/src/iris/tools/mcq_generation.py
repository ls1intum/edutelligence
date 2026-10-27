"""Tool for generating MCQ questions via the MCQ subpipeline."""

from typing import Callable, Dict, List, Optional

from ..common.pyris_message import PyrisMessage
from ..pipeline.shared.mcq_generation_pipeline import McqGenerationPipeline
from ..web.status.status_update import StatusCallback

MAX_QUESTIONS = 10


def create_tool_generate_mcq_questions(
    mcq_pipeline: McqGenerationPipeline,
    chat_history: Optional[List[PyrisMessage]],
    callback: StatusCallback,
    mcq_result_storage: Dict[str, str],
    language: str = "English",
    lecture_content_supplier: Optional[Callable[[], Optional[str]]] = None,
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
        lecture_content = (
            lecture_content_supplier() if lecture_content_supplier else None
        )
        count = max(1, min(count, MAX_QUESTIONS))
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
        mcq_result_storage["mcq_json"] = result_json
        return "[MCQ_RESULT]"

    return generate_mcq_questions
