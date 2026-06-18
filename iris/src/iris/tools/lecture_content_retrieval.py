"""Tool for retrieving lecture content using RAG."""

from typing import Any, Callable, Dict, List, Optional

from ..domain.retrieval.lecture.lecture_retrieval_dto import LectureRetrievalDTO
from ..retrieval.lecture.lecture_retrieval import LectureRetrieval
from ..web.status.status_update import StatusCallback


def _dedup_by_uuid(items: List[Any]) -> List[Any]:
    """Return items de-duplicated by their ``uuid``, preserving order."""
    seen: set = set()
    result = []
    for item in items:
        if item.uuid not in seen:
            result.append(item)
            seen.add(item.uuid)
    return result


def _merge_lecture_content(
    existing: Optional[LectureRetrievalDTO], new: LectureRetrievalDTO
) -> LectureRetrievalDTO:
    """Merge previously stored lecture content with freshly retrieved content.

    ``existing`` is typically the student's current-view content injected into
    the prompt before the agent ran. Items already present (e.g. the current
    slide page also returned by RAG) are de-duplicated by uuid so they are not
    cited twice.
    """
    if existing is None:
        return new
    return LectureRetrievalDTO(
        lecture_unit_segments=_dedup_by_uuid(
            existing.lecture_unit_segments + new.lecture_unit_segments
        ),
        lecture_transcriptions=_dedup_by_uuid(
            existing.lecture_transcriptions + new.lecture_transcriptions
        ),
        lecture_unit_page_chunks=_dedup_by_uuid(
            existing.lecture_unit_page_chunks + new.lecture_unit_page_chunks
        ),
    )


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

        # Store the lecture content for later use (e.g., citation pipeline).
        # Merge with any content already stored for the student's current view
        # (injected into the prompt before the agent ran) so both get cited,
        # de-duplicating by uuid to avoid citing the same paragraph twice.
        lecture_content = _merge_lecture_content(
            lecture_content_storage.get("content"), lecture_content
        )
        lecture_content_storage["content"] = lecture_content

        result = "Lecture slide content:\n"
        for paragraph in lecture_content.lecture_unit_page_chunks:
            result += (
                f"Lecture: {paragraph.lecture_name}, Unit: {paragraph.lecture_unit_name}, "
                f"Page: {paragraph.display_page_number}"
                + f"\nContent:\n---{paragraph.page_text_content}---\n\n"
            )

        result += "Lecture transcription content:\n"
        for paragraph in lecture_content.lecture_transcriptions:
            result += (
                f"Lecture: {paragraph.lecture_name}, Unit: {paragraph.lecture_unit_name}, "
                f"Page: {paragraph.page_number}\nContent:\n---{paragraph.segment_text}---\n\n"
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
