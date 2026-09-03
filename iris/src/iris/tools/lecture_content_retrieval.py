"""Tool for retrieving lecture content using RAG."""

from typing import Any, Callable, Dict, List, Optional

from ..pipeline.shared.citation_registry import CITE_TYPE_LECTURE, CitationRegistry
from ..retrieval.lecture.lecture_retrieval import LectureRetrieval
from ..web.status.status_update import StatusCallback


def _as_seconds(value) -> Optional[int]:
    """Convert transcript timestamps to whole seconds."""
    return None if value is None else int(value)


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
    citation_registry: Optional[CitationRegistry] = None,
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
        citation_registry: Optional registry for inline citation handles.

    Returns:
        Callable[[], str]: Function that returns lecture content string.
    """
    del callback

    def citation_hint(cite_type: str, entity_id, content: str, **coordinates) -> str:
        """Return this paragraph's citation suffix."""
        if citation_registry is None or not content:
            return ""
        handle = citation_registry.register(
            cite_type, entity_id, content, **coordinates
        )
        return f", Citation id: {handle}"

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

        lecture_content_storage["content"] = lecture_content

        result = "Lecture slide content:\n"
        for paragraph in lecture_content.lecture_unit_page_chunks:
            hint = citation_hint(
                CITE_TYPE_LECTURE,
                paragraph.lecture_unit_id,
                paragraph.page_text_content,
                page=paragraph.page_number,
                dedup_key=str(paragraph.uuid),
            )
            result += (
                f"Lecture: {paragraph.lecture_name}, Unit: {paragraph.lecture_unit_name}, "
                f"Page: {paragraph.display_page_number}{hint}"
                + f"\nContent:\n---{paragraph.page_text_content}---\n\n"
            )

        result += "Lecture transcription content:\n"
        for paragraph in lecture_content.lecture_transcriptions:
            hint = citation_hint(
                CITE_TYPE_LECTURE,
                paragraph.lecture_unit_id,
                paragraph.segment_text,
                page=paragraph.page_number,
                start=_as_seconds(paragraph.segment_start_time),
                end=_as_seconds(paragraph.segment_end_time),
                dedup_key=str(paragraph.uuid),
            )
            result += (
                f"Lecture: {paragraph.lecture_name}, Unit: {paragraph.lecture_unit_name}, "
                f"Page: {paragraph.page_number}{hint}"
                f"\nContent:\n---{paragraph.segment_text}---\n\n"
            )

        result += "Lecture segment content:\n"
        for paragraph in lecture_content.lecture_unit_segments:
            result += (
                f"Lecture: {paragraph.lecture_name}, Unit: {paragraph.lecture_unit_name}, "
                f"Page: {paragraph.display_page_number}"
                + f"\nContent:\n---{paragraph.segment_summary}---\n\n"
            )

        return result

    return lecture_content_retrieval
