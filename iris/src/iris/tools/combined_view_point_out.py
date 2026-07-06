"""Combined-view point-out tool.

An agent tool for the lecture combined view (slides + video + chat shown side by side).
The agent decides, from the context it already has, whether what the student is currently
looking at fits their question. If it does, the agent does not need this tool. If it does
*not*, the agent calls this tool to look through the lecture unit's material for a better
position and — if a better slide page and/or video moment exists — bring it up on the
student's screen via Artemis.

Unlike a plain retrieval tool, this tool also *acts*: it points the student to the found
position. It runs three cases based on the student's current position (taken from the
combined-view context):

1. The best position is exactly where the student already is -> Artemis is not asked; the
   agent is told the student is already at the ideal position.
2. The best position differs and Artemis navigated there -> the agent is told what was shown.
3. The best position differs but Artemis could not navigate (the student left the combined
   view, or a timeout) -> the agent is told nothing about navigation, only the content.
"""

from typing import Any, Callable, Dict, List, Optional

from iris.common.logging_config import get_logger
from iris.domain.data.lecture_context_dto import (
    SlidesContextDTO,
    VideoContextDTO,
)
from iris.domain.status.point_out_command_dto import PointOutCommandDTO
from iris.retrieval.lecture.lecture_retrieval import LectureRetrieval
from iris.web.status.status_update import StatusCallback

logger = get_logger(__name__)


def get_combined_view_context(lecture_contexts):
    """Return the ``combinedView`` context (with a resolvable lecture unit), or None."""
    combined = next(
        (
            ctx
            for ctx in (lecture_contexts or [])
            if getattr(ctx, "type", None) == "combinedView"
        ),
        None,
    )
    if combined is None or not combined.lecture_unit_id:
        return None
    return combined


def _describe(page: Optional[int], timestamp: Optional[float]) -> str:
    parts = []
    if page is not None:
        parts.append(f"page {page} of the slides")
    if timestamp is not None:
        parts.append(f"the video at {timestamp:.0f} seconds")
    return " and ".join(parts)


def _format_lecture_content(lecture_content) -> str:
    """Format retrieved lecture content for the agent, mirroring the lecture retrieval tool."""
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


def _pick_target(lecture_content, want_slide: bool, want_video: bool):
    """Pick the best slide page and/or video timestamp from the reranked retrieval.

    Page and video candidates come from separate reranked lists (top of each). The video
    timestamp is only taken when it belongs to the same slide as the chosen page (or when no
    page is chosen), so the student is not sent to a slide and an unrelated video moment.

    The page is the technical ``page_number`` (the value Artemis navigates by and that the
    current-view lookup filters on), not the ``display_page_number``.
    """
    page: Optional[int] = None
    if want_slide and lecture_content.lecture_unit_page_chunks:
        page = lecture_content.lecture_unit_page_chunks[0].page_number
    elif want_slide and lecture_content.lecture_unit_segments:
        page = lecture_content.lecture_unit_segments[0].page_number

    timestamp: Optional[float] = None
    if want_video and lecture_content.lecture_transcriptions:
        first_transcription = lecture_content.lecture_transcriptions[0]
        if page is None or first_transcription.page_number == page:
            timestamp = first_transcription.segment_start_time

    return page, timestamp


def _sync_current_position(
    combined, nav_page: Optional[int], nav_timestamp: Optional[float]
) -> None:
    """Keep the combined-view context's current position in sync with where we navigated, so a
    later tool call sees the student as already being at this position."""
    if nav_page is not None:
        if combined.slides is not None:
            combined.slides.page = nav_page
        else:
            combined.slides = SlidesContextDTO(
                type="slides",
                lecture_unit_id=combined.lecture_unit_id,
                page=nav_page,
            )
    if nav_timestamp is not None:
        if combined.video is not None:
            combined.video.timestamp = nav_timestamp
        else:
            combined.video = VideoContextDTO(
                type="video",
                lecture_unit_id=combined.lecture_unit_id,
                timestamp=nav_timestamp,
            )


def create_tool_combined_view_point_out(
    lecture_retriever: LectureRetrieval,
    course_id: int,
    base_url: str,
    callback: StatusCallback,
    query_text: str,
    history: List[Any],
    lecture_content_storage: Dict[str, Any],
    combined_context,
    lecture_id: Optional[int] = None,
    lecture_unit_id: Optional[int] = None,
) -> Callable[..., str]:
    """Create the combined-view point-out tool bound to the current chat state.

    Args:
        lecture_retriever: Lecture retrieval instance (searches this unit's material).
        course_id: Course ID.
        base_url: Base URL for Artemis.
        callback: Status callback, used to synchronously ask Artemis to navigate the client.
        query_text: The student's latest question (fallback search query).
        history: Chat history messages.
        lecture_content_storage: Storage for retrieved content (reused by the citation pipeline).
        combined_context: The combined-view context describing the student's current position.
        lecture_id: The lecture the student is viewing.
        lecture_unit_id: The lecture unit the student is viewing.

    Returns:
        The point-out tool function.
    """

    def point_out_relevant_lecture_position(query: str = "", show: str = "both") -> str:
        """Search this lecture unit for the position that best answers the student's question and,
        if it is a better fit than what the student is currently looking at, bring it up on their
        screen in the combined view.

        The student is viewing this lecture unit in the combined view (slides and/or video shown
        next to the chat). Whenever the student asks anything about the lecture content, your
        default should be to call this tool: it looks through the whole lecture unit for you and,
        if it finds a more relevant slide page and/or video moment, scrolls the student straight
        there. Pointing the student to the exact relevant spot is one of the most helpful things
        you can do here, and this tool is the only way to move their view — so lean towards using
        it rather than not.

        Only skip it when you are genuinely confident that what the student is currently looking at
        already fits their question very well. If there is any real chance the answer lives on a
        different slide or at a different point in the video, call the tool. When in doubt, call it:
        it is cheap, it never moves the student if they are already at the best position, and it
        tells you exactly what it found and whether the student is now looking at it, so you can
        refer to it naturally.

        Args:
            query: What to look for, in a few words (defaults to the student's latest question).
            show: Whether to point to a "slide", the "video", or "both" (default "both").

        Returns:
            A note describing what was found and whether the student's view was moved, followed by
            the relevant lecture content.
        """
        effective_query = (query or "").strip() or (query_text or "").strip()
        if not effective_query:
            return "No question was available to search the lecture material for."

        lecture_content = lecture_retriever(
            query=effective_query,
            course_id=course_id,
            chat_history=history,
            lecture_id=lecture_id,
            lecture_unit_id=lecture_unit_id,
            base_url=base_url,
        )
        # Stash for the citation pipeline, like the lecture retrieval tool does.
        lecture_content_storage["content"] = lecture_content
        formatted = _format_lecture_content(lecture_content)

        show_normalized = (show or "both").strip().lower()
        want_slide = show_normalized in ("slide", "slides", "both")
        want_video = show_normalized in ("video", "both")

        page, timestamp = _pick_target(lecture_content, want_slide, want_video)

        if page is None and timestamp is None:
            return (
                "No specific slide or video position in this lecture unit matched the question. "
                "Do not tell the student you moved their view.\n\n" + formatted
            )

        current_page = (
            combined_context.slides.page
            if combined_context.slides is not None
            else None
        )
        current_timestamp = (
            combined_context.video.timestamp
            if combined_context.video is not None
            else None
        )
        same_page = page is not None and page == current_page
        same_timestamp = timestamp is not None and timestamp == current_timestamp

        nav_page = None if same_page else page
        nav_timestamp = None if same_timestamp else timestamp

        if nav_page is None and nav_timestamp is None:
            # Case 1: the student is already exactly at the most relevant position.
            return (
                "The student is already looking at the most relevant position in this lecture "
                "unit for their question. Refer to it naturally in your answer.\n\n"
                + formatted
            )

        # Case 2/3: ask Artemis to move the student to the better position.
        result = callback.execute_command(
            PointOutCommandDTO(
                lecture_unit_id=combined_context.lecture_unit_id,
                page=nav_page,
                timestamp=nav_timestamp,
            )
        )
        if not result.applied:
            # Case 3: the student left the combined view (or a timeout) — say nothing about it.
            return (
                "Found relevant content, but the student's view could not be moved. Do not tell "
                "the student you moved their view.\n\n" + formatted
            )

        # Case 2: navigated successfully. Keep the tracked current position in sync.
        _sync_current_position(combined_context, nav_page, nav_timestamp)
        shown = _describe(nav_page, nav_timestamp)
        return (
            f"You brought up {shown} on the student's screen. Refer to it naturally in your "
            'answer (e.g. "as you can see on the slide I just opened ...").\n\n'
            + formatted
        )

    return point_out_relevant_lecture_position
