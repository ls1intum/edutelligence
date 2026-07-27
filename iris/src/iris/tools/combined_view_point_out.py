"""Combined-view point-out tool.

An agent tool for the lecture combined view (slides + video + chat shown side by side).

This tool does **not** decide anything and does **not** search. The agent first retrieves
lecture content (the lecture content retrieval tool is a precondition), then decides — from
that retrieved material — whether a different slide page or video moment fits the student's
question better than what they are currently looking at. If so, the agent calls this tool as a
plain "pointing" method, passing the ``page`` and/or ``timestamp`` it wants to show. The tool
only asks Artemis to move the student's view there and reports whether that worked.

It runs three cases based on the student's current position (taken from the combined-view
context):

1. The student is already at the requested position (same slide page, or a video moment inside
   the same retrieved segment) -> Artemis is not asked; the agent is told the student is
   already there.
2. The requested position differs and Artemis navigated there -> the agent is told what was shown.
3. The requested position differs but Artemis could not navigate (the student left the combined
   view, or a timeout) -> the agent is told the view was not moved.
"""

from typing import Any, Callable, Dict, List, Optional

from iris.common.logging_config import get_logger
from iris.domain.data.lecture_context_dto import (
    CombinedViewContextDTO,
    SlidesContextDTO,
    VideoContextDTO,
)
from iris.domain.retrieval.lecture.lecture_retrieval_dto import (
    LectureRetrievalDTO,
    LectureTranscriptionRetrievalDTO,
)
from iris.domain.status.point_out_command_dto import PointOutCommandDTO
from iris.web.status.status_update import StatusCallback

logger = get_logger(__name__)


def get_combined_view_context(
    lecture_contexts: Optional[List[Any]],
) -> Optional[CombinedViewContextDTO]:
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
    """Describe what was brought up, for the agent's benefit.

    Deliberately names no page number: the agent addresses pages by their point-out id, which must
    never reach the student, so repeating it here would invite the agent to copy it into its answer.
    The page argument therefore only decides *whether* the slides are mentioned, not how.
    """
    parts = []
    if page is not None:
        parts.append("the requested slide page")
    if timestamp is not None:
        parts.append(f"the video at {timestamp:.0f} seconds")
    return " and ".join(parts)


def _is_retrieved_page(lecture_content: LectureRetrievalDTO, page: int) -> bool:
    """Whether the requested page appears among the retrieved slides.

    The agent passes the technical ``page_number`` — the value shown in the retrieval results as the
    slide's point-out id, and the value Artemis navigates by. (The number printed on the slide is a
    separate thing, used only when talking to the student.) Checking it against the retrieved content
    keeps the agent from pointing at a page that never appeared in the results.
    """
    return any(
        chunk.page_number == page for chunk in lecture_content.lecture_unit_page_chunks
    ) or any(
        segment.page_number == page for segment in lecture_content.lecture_unit_segments
    )


def _resolve_timestamp_segment(
    lecture_content: LectureRetrievalDTO, timestamp: float
) -> Optional[LectureTranscriptionRetrievalDTO]:
    """Find the retrieved transcription segment whose time interval contains ``timestamp``.

    Timestamps are grounded in the retrieval results the same way pages are: the agent can only
    point to a video moment that lies within a segment that actually appeared there. Returns the
    matching segment, or ``None`` if no retrieved segment covers the timestamp.
    """
    for segment in lecture_content.lecture_transcriptions:
        if segment.segment_start_time <= timestamp <= segment.segment_end_time:
            return segment
    return None


def _sync_current_position(
    combined: CombinedViewContextDTO,
    moved_page: Optional[int],
    moved_timestamp: Optional[float],
) -> None:
    """Keep the combined-view context's current position in sync with where we navigated, so a
    later tool call sees the student as already being at this position."""
    if moved_page is not None:
        if combined.slides is not None:
            combined.slides.page = moved_page
        else:
            combined.slides = SlidesContextDTO(
                type="slides",
                lecture_unit_id=combined.lecture_unit_id,
                page=moved_page,
            )
    if moved_timestamp is not None:
        if combined.video is not None:
            combined.video.timestamp = moved_timestamp
        else:
            combined.video = VideoContextDTO(
                type="video",
                lecture_unit_id=combined.lecture_unit_id,
                timestamp=moved_timestamp,
            )


def create_tool_combined_view_point_out(
    callback: StatusCallback,
    lecture_content_storage: Dict[str, Any],
    combined_context: CombinedViewContextDTO,
) -> Callable[..., str]:
    """Create the combined-view point-out tool bound to the current chat state.

    The tool is a plain navigation method: it does not search and does not decide. The agent
    supplies the slide page and/or video timestamp it wants to show (chosen from the lecture
    content it retrieved earlier), and the tool asks Artemis to move the student's view there.

    Args:
        callback: Status callback, used to synchronously ask Artemis to navigate the client.
        lecture_content_storage: Storage the lecture retrieval tool writes its results into.
            Used here to enforce that a retrieval happened first and to check the requested
            position against what was actually retrieved.
        combined_context: The combined-view context describing the student's current position.

    Returns:
        The point-out tool function.
    """

    def point_out_relevant_lecture_position(
        page: Optional[int] = None, timestamp: Optional[float] = None
    ) -> str:
        """Move the student's combined-view to a specific slide page and/or video moment.

        The student is viewing this lecture unit in the combined view (slides and/or video shown
        next to the chat), and this tool is the only way to move what they see. It does not search
        and does not decide anything for you: you must first retrieve the lecture content (with the
        lecture content retrieval tool), then judge from those results whether a different position
        fits the student's question better than what they are currently looking at. If it does,
        call this tool with the page and/or timestamp you want to show.

        Pass values taken straight from the retrieval results: ``page`` is the slide's point-out id
        ("point-out id: N"), not the page number printed on the slide, and ``timestamp`` is the
        video time in seconds of the segment you want ("Video timestamp: Ns"). Give a page, a
        timestamp, or both — whichever fits the student's question best. Both are checked against
        the retrieved results: a page must appear there, and a timestamp must fall within a
        retrieved video segment. If the student is already at that position (for the video: already
        within that segment), the tool leaves their view untouched and tells you so.

        System notes in the chat history record where you pointed the student earlier in this
        conversation, naming the slide by its index page (the point-out id). Refer back to them
        naturally, and point to that spot again whenever it answers the question — the student may
        have moved on since, and this tool does nothing if they are in fact still there.

        Args:
            page: The point-out id of the slide to show (as it appears in the retrieval results).
                Omit to not move the slides.
            timestamp: The video time in seconds to jump to. Omit to not move the video.

        Returns:
            A short note describing whether the student's view was moved.
        """
        if page is None and timestamp is None:
            return (
                "Nothing to point to. Pass a slide page and/or a video timestamp taken from the "
                "retrieved lecture results."
            )

        lecture_content = lecture_content_storage.get("content")
        if lecture_content is None:
            return (
                "No lecture content has been retrieved yet, so there is nothing to point to. "
                "Call the lecture content retrieval tool first, then point the student to a page "
                "or timestamp from its results."
            )

        if page is not None and not _is_retrieved_page(lecture_content, page):
            return (
                f"Slide page {page} is not among the retrieved lecture results, so it cannot "
                "be shown. Point only to a page that appears in the results. If you also "
                "passed a valid timestamp, call again with just that."
            )

        target_segment = None
        if timestamp is not None:
            target_segment = _resolve_timestamp_segment(lecture_content, timestamp)
            if target_segment is None:
                return (
                    f"The video timestamp {timestamp:.0f}s does not fall within any retrieved "
                    "video segment, so it cannot be shown. Point only to a timestamp that appears "
                    "in the results. If you also passed a valid page, call again with just that."
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
        # The student counts as already at the video position when they are anywhere inside the
        # targeted segment's time interval, not only at its exact start.
        same_timestamp = (
            target_segment is not None
            and current_timestamp is not None
            and target_segment.segment_start_time
            <= current_timestamp
            <= target_segment.segment_end_time
        )

        move_page = None if same_page else page
        move_timestamp = None if same_timestamp else timestamp

        if move_page is None and move_timestamp is None:
            # Case 1: the student is already exactly at the requested position.
            return (
                "The student is already looking at that position, so their view was not moved. "
                "Refer to it naturally in your answer."
            )

        # Case 2/3: ask Artemis to move the student to the requested position.
        result = callback.execute_command(
            PointOutCommandDTO(
                lecture_unit_id=combined_context.lecture_unit_id,
                page=move_page,
                timestamp=move_timestamp,
            )
        )
        if not result.applied:
            # Case 3: the student left the combined view (or a timeout).
            return (
                "The student's view could not be moved (they may have left the combined view). "
                "Do not tell the student you moved their view."
            )

        # Case 2: navigated successfully. Keep the tracked current position in sync so a later call
        # sees the student as already being here.
        _sync_current_position(combined_context, move_page, move_timestamp)
        shown = _describe(move_page, move_timestamp)
        return (
            f"You brought up {shown} on the student's screen. Refer to it naturally in your "
            'answer (e.g. "as you can see on the slide I just opened ...").'
        )

    return point_out_relevant_lecture_position
