"""Tool for retrieving lecture content using RAG."""

import math
from typing import Any, Callable, Dict, List, Optional

from ..retrieval.lecture.lecture_retrieval import LectureRetrieval
from ..web.status.status_update import StatusCallback


def _format_page_reference(
    display_page_number: Optional[int], point_out_id: Optional[int] = None
) -> str:
    """Render the page reference of a retrieved result as plain ``key: value`` fields.

    The number printed on the slide is what the student sees and what the agent should name when
    talking about it. Results that can also be navigated to pass their ``point_out_id`` — the slide's
    index in the deck, the only number the point-out tool accepts. Transcription segments know the
    printed number of the slide that was on screen but no deck index, so they omit it.

    Both kinds of result can end up without a printed number — no number was visible on the slide or
    in the video frame (``-1``), or the transcript was never enriched with slide numbers (``0``) —
    and both are marked as unnumbered by the same rule here, so the agent refers to them without
    naming a page instead of quoting a nonsensical "-1".
    """
    page = (
        "Page: unnumbered"
        if display_page_number is None or display_page_number <= 0
        else f"Page: {display_page_number}"
    )
    return page if point_out_id is None else f"{page}, point-out id: {point_out_id}"


def _format_video_timestamp(start_time: float, end_time: float) -> str:
    """Render a transcription segment's start as a timestamp that still points back at it.

    The agent is told to pass a displayed timestamp to the point-out tool exactly as shown, and that
    tool matches segments half-open (``start <= t < end``). Rounding a fractional start to the
    nearest whole second can move it before its own segment — 42.4 displayed as 42 lands in the
    preceding segment, or nowhere — leaving the segment impossible to point at. So the value is
    rounded up instead: never earlier than the start, and whole seconds wherever they fit, since a
    round number is what the agent can also name to the student.

    A segment too short to contain the next whole second falls back to its exact start: repr round-
    trips a float, so that value is inside the segment by construction.
    """
    whole_second = math.ceil(start_time)
    if whole_second < end_time:
        return str(whole_second)
    return repr(start_time)


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
                # A transcription segment's page_number is the slide number read off the video frame
                # during ingestion — the number printed on the slide, not its index in the deck. So it
                # is rendered as the printed page, which the agent may name to the student, and never
                # as a point-out id: passing it as one would navigate to the wrong slide wherever the
                # two numberings diverge. What this segment can be pointed at by is its timestamp.
                f"Lecture: {paragraph.lecture_name}, Unit: {paragraph.lecture_unit_name}, "
                + _format_page_reference(paragraph.page_number)
                + ", Video timestamp: "
                + _format_video_timestamp(
                    paragraph.segment_start_time, paragraph.segment_end_time
                )
                + "s"
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
