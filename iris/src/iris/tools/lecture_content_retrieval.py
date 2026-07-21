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
    del callback

    def lecture_content_retrieval() -> str:
        """
        Retrieve content from indexed lecture content.
        This runs RAG retrieval over indexed lecture slides, transcriptions, and summarized segments and returns
        the most relevant excerpts. Treat the returned excerpts as the complete evidence boundary for claims about
        what the lecture teaches: use only claims explicitly present in the result. Do not fill missing steps with
        general textbook knowledge or expand a sparse recurrence, theorem name, or formula into unstated derivations,
        level counts, formulas, cases, or conclusions. If the tool reports that no indexed evidence was retrieved,
        ask for the relevant material, slide, or section without making claims about the requested topic.
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

        sections = []
        for paragraph in lecture_content.lecture_unit_page_chunks:
            if not paragraph.page_text_content:
                continue
            sections.append(
                "Lecture slide evidence:\n"
                f"Lecture: {paragraph.lecture_name}, "
                f"Unit: {paragraph.lecture_unit_name}, "
                f"Page: {paragraph.display_page_number}\n"
                f"Content:\n---{paragraph.page_text_content}---"
            )

        for paragraph in lecture_content.lecture_transcriptions:
            if not paragraph.segment_text:
                continue
            sections.append(
                "Lecture transcription evidence:\n"
                f"Lecture: {paragraph.lecture_name}, "
                f"Unit: {paragraph.lecture_unit_name}, "
                f"Page: {paragraph.page_number}\n"
                f"Content:\n---{paragraph.segment_text}---"
            )

        for paragraph in lecture_content.lecture_unit_segments:
            if not paragraph.segment_summary:
                continue
            sections.append(
                "Lecture segment evidence:\n"
                f"Lecture: {paragraph.lecture_name}, "
                f"Unit: {paragraph.lecture_unit_name}, "
                f"Page: {paragraph.display_page_number}\n"
                f"Content:\n---{paragraph.segment_summary}---"
            )

        if not sections:
            return (
                "No indexed lecture evidence was retrieved. Do not infer lecture-topic "
                "claims from general knowledge; ask for the relevant material, slide, "
                "or section."
            )
        return (
            "Retrieved lecture evidence follows. Claims not explicitly present in "
            "these excerpts are unsupported.\n\n" + "\n\n".join(sections)
        )

    return lecture_content_retrieval
