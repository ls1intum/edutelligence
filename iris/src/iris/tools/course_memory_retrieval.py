"""Tool for retrieving verified prior answers from course memory."""

from typing import Any, Callable, Dict, List

from ..retrieval.course_memory_retrieval import CourseMemoryRetrieval
from ..retrieval.course_memory_retrieval_utils import format_course_memories
from ..web.status.status_update import StatusCallback


def create_tool_course_memory_retrieval(
    course_memory_retriever: CourseMemoryRetrieval,
    course_id: int,
    course_name: str,
    base_url: str,
    callback: StatusCallback,
    query_text: str,
    history: List[Any],
    memory_storage: Dict[str, Any],
) -> Callable[[], str]:
    """
    Create a tool that retrieves verified prior answers from course memory.

    Args:
        course_memory_retriever: Course memory retrieval instance.
        course_id: Course ID.
        course_name: Course name.
        base_url: Base URL for Artemis.
        callback: Callback for status updates.
        query_text: The student's query text.
        history: Chat history messages.
        memory_storage: Storage for retrieved memories (for backlinking/citation).

    Returns:
        Callable[[], str]: Function that returns formatted verified prior answers.
    """

    def course_memory_retrieval() -> str:
        """
        Use this tool to look up verified answers to questions that were previously
        asked and answered in this course's communication channels.
        These are tutor-verified Q/A pairs, so prefer them when a relevant one is found:
        reuse the verified answer for consistency rather than answering from scratch.
        Each result has the format: source message id, thread id, the past question, and
        the verified answer. When you use a verified answer, cite the source message id so
        the student can trace where it came from.
        This tool should only be used once per query.

        Returns:
            str: Formatted string containing relevant verified prior answers.
        """
        callback.in_progress("Retrieving verified course answers ...")
        retrieved_memories = course_memory_retriever(
            chat_history=history,
            student_query=query_text,
            course_name=course_name,
            course_id=course_id,
            base_url=base_url,
        )

        # Store the retrieved memories for later use (e.g., citation/backlinking).
        memory_storage["memories"] = retrieved_memories

        return format_course_memories(retrieved_memories)

    return course_memory_retrieval
