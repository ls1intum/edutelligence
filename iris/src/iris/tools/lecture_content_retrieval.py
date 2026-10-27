"""Tool for retrieving lecture content using RAG."""

import math
from typing import Any, Callable, Dict, Optional

from ..domain.retrieval.lecture.lecture_retrieval_dto import printed_page_number
from ..pipeline.shared.citation_sources import (
    CitationSourceRegistry,
    framed_content,
    source_id_line,
)
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
    """
    printed = printed_page_number(display_page_number)
    page = "Page: unnumbered" if printed is None else f"Page: {printed}"
    return page if point_out_id is None else f"{page}, point-out id: {point_out_id}"


def _format_video_timestamp(start_time: float, end_time: float) -> str:
    """Render a transcription segment's start as a timestamp that still points back at it.

    The agent passes a displayed timestamp to the point-out tool exactly as shown, and that tool
    matches segments half-open (``start <= t < end``). Rounding a fractional start to the nearest
    whole second can move it before its own segment — 42.4 shown as 42 lands in the preceding one,
    or nowhere — so it is rounded up instead: never earlier than the start, and a round number the
    agent can also name to the student. A segment too short to contain the next whole second falls
    back to its exact start, which ``repr`` round-trips and is inside the segment by construction.
    """
    whole_second = math.ceil(start_time)
    if whole_second < end_time:
        return str(whole_second)
    return repr(start_time)


def _merge(previous, current):
    """Union of two retrieval results, de-duplicated by uuid, previous first."""
    if previous is None:
        return current

    def union(first, second):
        seen = {item.uuid for item in first}
        return list(first) + [item for item in second if item.uuid not in seen]

    return type(current)(
        lecture_unit_segments=union(
            previous.lecture_unit_segments, current.lecture_unit_segments
        ),
        lecture_transcriptions=union(
            previous.lecture_transcriptions, current.lecture_transcriptions
        ),
        lecture_unit_page_chunks=union(
            previous.lecture_unit_page_chunks, current.lecture_unit_page_chunks
        ),
    )


def format_lecture_content(
    lecture_content, citation_sources: Optional[CitationSourceRegistry] = None
) -> str:
    """Render retrieved lecture content for the agent.

    With a source registry, every slide chunk and transcription segment gets a
    source id the agent can cite. Segment summaries get none: they are
    orientation, not a position.
    """
    result = "Lecture slide content:\n"
    for paragraph in lecture_content.lecture_unit_page_chunks:
        source_id = (
            citation_sources.register_page_chunk(paragraph)
            if citation_sources is not None
            else None
        )
        result += (
            f"Lecture: {paragraph.lecture_name} (lecture ID {paragraph.lecture_id}), "
            f"Unit: {paragraph.lecture_unit_name}, "
            + _format_page_reference(
                paragraph.display_page_number, paragraph.page_number
            )
            + "\n"
            + source_id_line(source_id)
            + framed_content(paragraph.page_text_content)
            + "\n\n"
        )

    result += "Lecture transcription content:\n"
    for paragraph in lecture_content.lecture_transcriptions:
        source_id = (
            citation_sources.register_transcription(paragraph)
            if citation_sources is not None
            else None
        )
        result += (
            # A transcription segment's page_number is the slide number read off the video frame
            # during ingestion — the number printed on the slide, not its index in the deck. So it
            # is rendered as the printed page, which the agent may name to the student, and never
            # as a point-out id: passing it as one would navigate to the wrong slide wherever the
            # two numberings diverge. What this segment can be pointed at by is its timestamp.
            f"Lecture: {paragraph.lecture_name} (lecture ID {paragraph.lecture_id}), "
            f"Unit: {paragraph.lecture_unit_name}, "
            + _format_page_reference(paragraph.page_number)
            + ", Video timestamp: "
            + _format_video_timestamp(
                paragraph.segment_start_time, paragraph.segment_end_time
            )
            + "s\n"
            + source_id_line(source_id)
            + framed_content(paragraph.segment_text)
            + "\n\n"
        )

    result += "Lecture segment content:\n"
    for paragraph in lecture_content.lecture_unit_segments:
        result += (
            # No point-out id: a summary of a whole slide plus what was said over it is
            # orientation, not a position. Pointing runs off the page chunks and the
            # transcriptions, which name one of their own.
            f"Lecture: {paragraph.lecture_name} (lecture ID {paragraph.lecture_id}), "
            f"Unit: {paragraph.lecture_unit_name}, "
            + _format_page_reference(paragraph.display_page_number)
            + f"\nContent:\n---{paragraph.segment_summary}---\n\n"
        )

    return result


MAX_SEARCHES_PER_SCOPE = 3

EMPTY_QUERY_REPLY = (
    "Write a search query: name the concept or question you need from the lecture "
    "material."
)

SEARCH_LIMIT_REPLY = (
    f"You already searched {MAX_SEARCHES_PER_SCOPE} times for this lecture. Answer with "
    "the material you have, and say what it does not cover."
)

_TOOL_DESCRIPTION = """
Search the indexed lecture material of the course: slides, lecture video
transcripts, and summaries of each slide with what was said about it.
Returns the most relevant passages.

Write `query` as a self-contained search query: name the concept or
question in full (resolve "it" or "this" from the conversation), {language},
without filler words. You may search again with a different query when the
first results do not cover the question, at most {limit} times per answer.
In a lecture chat this returns content of the active lecture only, and it
never returns lecture IDs. Use the lecture list tool to find another
lecture and its ID.

Returns:
    str: Lecture slide, transcription, and segment content.
"""


def create_tool_lecture_content_retrieval(
    lecture_retriever: LectureRetrieval,
    course_id: int,
    base_url: str,
    callback: StatusCallback,
    lecture_content_storage: Dict[str, Any],
    lecture_id: Optional[int] = None,
    lecture_unit_id: Optional[int] = None,
    scope_supplier: Optional[Callable[[], tuple[Optional[int], Optional[int]]]] = None,
    citation_sources: Optional[CitationSourceRegistry] = None,
    material_language: Optional[str] = None,
) -> Callable[[str], str]:
    """
    Create a tool that searches the lecture material for a query the agent writes.

    Args:
        lecture_retriever: Lecture retrieval instance.
        course_id: Course ID.
        base_url: Base URL for Artemis.
        callback: Callback for status updates.
        lecture_content_storage: Storage for retrieved content.
        lecture_id: Lecture the retrieval is scoped to, if any.
        lecture_unit_id: Lecture unit the retrieval is scoped to, if any.
        scope_supplier: Resolves the scope at call time instead of at creation
            time, so a context switch during the same run redirects retrieval
            to the new lecture. Overrides lecture_id and lecture_unit_id.
        citation_sources: When given, every slide chunk and transcription segment
            gets a source id the agent can cite. Pipelines without citations pass
            nothing and get the plain output.
        material_language: Language of the course material, when known; the
            agent is asked to write the query in it.

    Returns:
        The tool function.
    """
    del callback

    def lecture_content_retrieval(query: str) -> str:
        scope = (
            scope_supplier()
            if scope_supplier is not None
            else (lecture_id, lecture_unit_id)
        )
        if not query.strip():
            return EMPTY_QUERY_REPLY
        # The count lives next to the content: a context switch (also a cancelled
        # one) clears the content, and with it the searches of the old scope.
        same_scope = (
            lecture_content_storage.get("scope") == scope
            and "content" in lecture_content_storage
        )
        searches = lecture_content_storage.get("searches", 0) if same_scope else 0
        if searches >= MAX_SEARCHES_PER_SCOPE:
            return SEARCH_LIMIT_REPLY

        lecture_content = lecture_retriever(
            search_query=query,
            course_id=course_id,
            lecture_id=scope[0],
            lecture_unit_id=scope[1],
            base_url=base_url,
        )

        # Read by the combined-view point-out tool, which points to a retrieved
        # position. Several searches in the same scope add up; a search after a
        # context switch starts over, so no position of the previous lecture stays.
        previous = lecture_content_storage.get("content") if same_scope else None
        lecture_content_storage["content"] = _merge(previous, lecture_content)
        lecture_content_storage["scope"] = scope
        lecture_content_storage["searches"] = searches + 1

        return format_lecture_content(lecture_content, citation_sources)

    lecture_content_retrieval.__doc__ = _TOOL_DESCRIPTION.format(
        language=(
            f"in {material_language}, the language of the course material"
            if material_language
            else "in the language of the course material"
        ),
        limit=MAX_SEARCHES_PER_SCOPE,
    )
    return lecture_content_retrieval
