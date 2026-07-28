"""Tool for retrieving lecture content using RAG."""

from typing import Any, Callable, Dict, List, Optional

from ..retrieval.lecture.lecture_retrieval import LectureRetrieval
from ..web.status.status_update import StatusCallback


def _format_page_reference(display_page_number: Optional[int], page_number: int) -> str:
    """Render the page reference of a retrieved slide.

    Two numbers describe the same slide and they serve different purposes: the number printed on the
    slide is what the student sees and what the agent should name when talking about it, while the
    slide's index in the deck is what the point-out tool navigates by. Many slides carry no printed
    number — the ingestion pipeline stores ``-1`` for those — and they are marked as unnumbered here
    so the agent refers to them without naming a page instead of quoting a nonsensical "-1".

    The two numbers are listed side by side as plain ``key: value`` fields, the same way the
    transcription results below list theirs, so every retrieval line reads alike.
    """
    if display_page_number is None or display_page_number <= 0:
        return f"Page: unnumbered, point-out id: {page_number}"
    return f"Page: {display_page_number}, point-out id: {page_number}"


def create_tool_lecture_content_retrieval(
    lecture_retriever: LectureRetrieval,
    course_id: int,
    base_url: str,
    callback: StatusCallback,
    query_text: str,
    history: List[Any],
    lecture_content_storage: Dict[str, Any],
    lecture_id: Optional[int] = None,
    lecture_unit_id: Optional[int] = None,
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
    del callback

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
        lecture_content = lecture_retriever(
            query=query_text,
            course_id=course_id,
            chat_history=history,
            lecture_id=lecture_id,
            lecture_unit_id=lecture_unit_id,
            base_url=base_url,
        )

        # Store the lecture content for later use (e.g., citation pipeline)
        lecture_content_storage["content"] = lecture_content

        result = "Lecture slide content:\n"
        for paragraph in lecture_content.lecture_unit_page_chunks:
            result += (
                f"Lecture: {paragraph.lecture_name}, Unit: {paragraph.lecture_unit_name}, "
                + _format_page_reference(
                    paragraph.display_page_number, paragraph.page_number
                )
                + f"\nContent:\n---{paragraph.page_text_content}---\n\n"
            )

        result += "Lecture transcription content:\n"
        for paragraph in lecture_content.lecture_transcriptions:
            result += (
                # Transcription segments carry no printed page number, only the slide index, so the
                # point-out id is offered on its own rather than under a "Page:" label the agent is
                # told to quote to the student.
                f"Lecture: {paragraph.lecture_name}, Unit: {paragraph.lecture_unit_name}, "
                f"point-out id: {paragraph.page_number}, "
                f"Video timestamp: {paragraph.segment_start_time:.0f}s"
                f"\nContent:\n---{paragraph.segment_text}---\n\n"
            )

        result += "Lecture segment content:\n"
        for paragraph in lecture_content.lecture_unit_segments:
            result += (
                f"Lecture: {paragraph.lecture_name}, Unit: {paragraph.lecture_unit_name}, "
                + _format_page_reference(
                    paragraph.display_page_number, paragraph.page_number
                )
                + f"\nContent:\n---{paragraph.segment_summary}---\n\n"
            )

        return result

    return lecture_content_retrieval
