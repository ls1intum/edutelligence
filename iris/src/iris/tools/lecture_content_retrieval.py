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
    current_pdf_page: Optional[int] = None,
    current_video_timestamp: Optional[float] = None,
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

    def _format_timestamp(timestamp_seconds: float) -> str:
        total_seconds = int(timestamp_seconds)
        minutes, seconds = divmod(total_seconds, 60)
        return f"{minutes}:{seconds:02d}"

    contextual_query = query_text
    if current_pdf_page is not None or current_video_timestamp is not None:
        context_hints = []
        if current_pdf_page is not None:
            context_hints.append(
                f"Student currently views PDF slide/page {current_pdf_page}."
            )
        if current_video_timestamp is not None:
            context_hints.append(
                "Student currently watches video around "
                f"{_format_timestamp(current_video_timestamp)} "
                f"({current_video_timestamp:.1f}s)."
            )
        contextual_query += "\n\n[Lecture viewing context]\n" + " ".join(context_hints)

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
            query=contextual_query,
            course_id=course_id,
            chat_history=history,
            lecture_id=lecture_id,
            lecture_unit_id=lecture_unit_id,
            base_url=base_url,
        )

        # Store the lecture content for later use (e.g., citation pipeline)
        lecture_content_storage["content"] = lecture_content

        result = "Lecture viewing context:\n"
        result += (
            f"- Current PDF page: {current_pdf_page}\n"
            if current_pdf_page is not None
            else "- Current PDF page: not provided\n"
        )
        result += (
            "- Current video timestamp: "
            f"{_format_timestamp(current_video_timestamp)} "
            f"({current_video_timestamp:.1f}s)\n"
            if current_video_timestamp is not None
            else "- Current video timestamp: not provided\n"
        )
        result += (
            "Use this context to focus your answer. If the student asks a vague "
            "question like 'this slide' or 'just said', assume they mean this "
            "page/timestamp.\n\n"
        )

        result += "Lecture slide content:\n"
        for paragraph in lecture_content.lecture_unit_page_chunks:
            result += (
                f"Lecture: {paragraph.lecture_name}, Unit: {paragraph.lecture_unit_name}, "
                f"Page: {paragraph.page_number}\nContent:\n---{paragraph.page_text_content}---\n\n"
            )

        result += "Lecture transcription content:\n"
        for paragraph in lecture_content.lecture_transcriptions:
            result += (
                f"Lecture: {paragraph.lecture_name}, Unit: {paragraph.lecture_unit_name}, "
                f"Page: {paragraph.page_number}, "
                f"Timestamp: {_format_timestamp(paragraph.segment_start_time)}-"
                f"{_format_timestamp(paragraph.segment_end_time)}\n"
                f"Content:\n---{paragraph.segment_text}---\n\n"
            )

        result += "Lecture segment content:\n"
        for paragraph in lecture_content.lecture_unit_segments:
            result += (
                f"Lecture: {paragraph.lecture_name}, Unit: {paragraph.lecture_unit_name}, "
                f"Page: {paragraph.page_number}\nContent:\n---{paragraph.segment_summary}---\n\n"
            )

        return result

    return lecture_content_retrieval
