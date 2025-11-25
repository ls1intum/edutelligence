"""Tool for retrieving lecture content using RAG."""

from typing import Any, Callable, Dict, List, cast

from ..retrieval.lecture.lecture_retrieval import LectureRetrieval
from ..web.status.status_update import StatusCallback


def create_tool_lecture_content_retrieval(
    lecture_retriever: LectureRetrieval,
    course_id: int,
    base_url: str,
    callback: StatusCallback,
    query_text: str,
    history: List[Any],
    lecture_content_storage: Dict[str, Any],
) -> Callable[[], str]:
    """
    Create a tool that retrieves lecture content using RAG.

    Args:
        lecture_retriever: Lecture retrieval instance.
        course_id: Course ID.
        base_url: Base URL for Artemis.
        callback: Callback for status updates.
        query_text: The student's query text.
        history: Chat history messages.
        lecture_content_storage: Storage for retrieved content.

    Returns:
        Callable[[], str]: Function that returns lecture content string.
    """

    def lecture_content_retrieval() -> str:
        """
        Retrieve content from indexed lecture content.
        This will run a RAG retrieval based on the chat history on the indexed lecture slides,
        the indexed lecture transcriptions and the indexed lecture segments,
        which are summaries of the lecture slide content and lecture transcription content from one slide a
        nd return the most relevant paragraphs.
        Use this if you think it can be useful to answer the student's question, or if the student explicitly asks
        a question about the lecture content or slides.
        Only use this once.

        Returns:
            str: Concatenated lecture slide, transcription, and segment content.
        """
        callback.in_progress("Retrieving lecture content ...")
        lecture_content = lecture_retriever(
            query=query_text,
            course_id=course_id,
            chat_history=history,
            lecture_id=cast(int, None),
            lecture_unit_id=cast(int, None),
            base_url=base_url,
        )

        # Store the lecture content for later use (e.g., citation pipeline)
        lecture_content_storage["content"] = lecture_content

        result = "Lecture slide content:\n"
        for paragraph in lecture_content.lecture_unit_page_chunks:
            result += (
                f"Lecture: {paragraph.lecture_name}, Unit: {paragraph.lecture_unit_name}, "
                f"Page: {paragraph.page_number}\nContent:\n---{paragraph.page_text_content}---\n\n"
            )

        result += "Lecture transcription content:\n"
        for transcription in lecture_content.lecture_transcriptions:
            result += (
                f"Lecture: {transcription.lecture_name}, Unit: {transcription.lecture_unit_name}, "
                f"Page: {transcription.page_number}\nContent:\n---{transcription.segment_text}---\n\n"
            )

        result += "Lecture segment content:\n"
        for segment in lecture_content.lecture_unit_segments:
            result += (
                f"Lecture: {segment.lecture_name}, Unit: {segment.lecture_unit_name}, "
                f"Page: {segment.page_number}\nContent:\n---{segment.segment_summary}---\n\n"
            )

        return result

    return lecture_content_retrieval
