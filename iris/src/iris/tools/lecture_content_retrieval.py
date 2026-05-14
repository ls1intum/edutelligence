"""Tool for retrieving lecture content using RAG."""

from typing import Any, Callable, Dict, List, Optional

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

        The returned content includes:
        - Page numbers where available (use these when referencing slides)
        - Academic descriptions of slide content (vision-generated interpretations of diagrams, formulas, and layout)
        - Extracted text content

        Use the academic descriptions to understand visual elements that aren't captured in plain text.

        Returns:
            str: Concatenated lecture slide, transcription, and segment content.
        """
        callback.in_progress("Retrieving lecture content ...")
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
            page_ref = (
                f"Page {paragraph.display_page_number}"
                if paragraph.display_page_number != -1
                else ""
            )
            description_section = (
                f"\nAcademic Description: {paragraph.academic_description}\n"
                if paragraph.academic_description
                else ""
            )
            result += (
                f"Lecture: {paragraph.lecture_name}, Unit: {paragraph.lecture_unit_name}"
                + (f", {page_ref}" if page_ref else "")
                + description_section
                + f"\nContent:\n---{paragraph.page_text_content}---\n\n"
            )

        result += "Lecture transcription content:\n"
        for paragraph in lecture_content.lecture_transcriptions:
            page_ref = (
                f"Page {paragraph.display_page_number}"
                if paragraph.display_page_number != -1
                else ""
            )
            description_section = (
                f"\nAcademic Description: {paragraph.academic_description}\n"
                if paragraph.academic_description
                else ""
            )
            result += (
                f"Lecture: {paragraph.lecture_name}, Unit: {paragraph.lecture_unit_name}"
                + (f", {page_ref}" if page_ref else "")
                + description_section
                + f"\nContent:\n---{paragraph.segment_text}---\n\n"
            )

        result += "Lecture segment content:\n"
        for paragraph in lecture_content.lecture_unit_segments:
            page_ref = (
                f"Page {paragraph.display_page_number}"
                if paragraph.display_page_number != -1
                else ""
            )
            description_section = (
                f"\nAcademic Description: {paragraph.academic_description}\n"
                if paragraph.academic_description
                else ""
            )
            result += (
                f"Lecture: {paragraph.lecture_name}, Unit: {paragraph.lecture_unit_name}"
                + (f", {page_ref}" if page_ref else "")
                + description_section
                + f"\nContent:\n---{paragraph.segment_summary}---\n\n"
            )

        return result

    return lecture_content_retrieval
