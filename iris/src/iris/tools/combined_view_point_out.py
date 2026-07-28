"""Combined-view point-out tool.

An agent tool for the lecture combined view (slides + video + chat shown side by side). It does
not search and does not decide: the agent retrieves lecture content first, picks a slide page
and/or video moment from those results, and this tool asks Artemis to move the student's view
there and reports whether that worked.
"""

from typing import Any, Callable, Dict, List, Optional

from iris.domain.data.lecture_context_dto import CombinedViewContextDTO
from iris.domain.retrieval.lecture.lecture_retrieval_dto import (
    LectureRetrievalDTO,
    LectureTranscriptionRetrievalDTO,
)
from iris.domain.status.point_out_command_dto import PointOutCommandDTO
from iris.web.status.status_update import StatusCallback


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

    Deliberately names no page number: point-out ids must never reach the student, so repeating one
    here would invite the agent to copy it into its answer.
    """
    parts = []
    if page is not None:
        parts.append("the requested slide page")
    if timestamp is not None:
        parts.append(f"the video at {timestamp:.0f} seconds")
    return " and ".join(parts)


def _is_retrieved_page(
    lecture_content: LectureRetrievalDTO, lecture_unit_id: Optional[int], page: int
) -> bool:
    """Whether the requested page appears among the retrieved slides of ``lecture_unit_id``.

    ``page`` is the point-out id (the technical ``page_number`` Artemis navigates by), not the number
    printed on the slide. Checking it against the results keeps the agent from pointing at a page
    that never appeared there.

    Retrieval is not always scoped to the unit the student is looking at, while the point-out always
    navigates within that unit — so results from other units are skipped here, or a page valid only
    elsewhere would be navigated to in the wrong deck.
    """
    return any(
        chunk.page_number == page and chunk.lecture_unit_id == lecture_unit_id
        for chunk in lecture_content.lecture_unit_page_chunks
    ) or any(
        segment.page_number == page and segment.lecture_unit_id == lecture_unit_id
        for segment in lecture_content.lecture_unit_segments
    )


def _resolve_timestamp_segment(
    lecture_content: LectureRetrievalDTO,
    lecture_unit_id: Optional[int],
    timestamp: float,
) -> Optional[LectureTranscriptionRetrievalDTO]:
    """Find the retrieved transcription segment of ``lecture_unit_id`` containing ``timestamp``.

    Grounds timestamps in the retrieval results the same way pages are grounded, including the
    restriction to the unit the point-out will navigate in. Returns None when no such segment was
    retrieved.
    """
    for segment in lecture_content.lecture_transcriptions:
        if (
            segment.lecture_unit_id == lecture_unit_id
            and segment.segment_start_time <= timestamp <= segment.segment_end_time
        ):
            return segment
    return None


def create_tool_combined_view_point_out(
    callback: StatusCallback,
    lecture_content_storage: Dict[str, Any],
    combined_context: CombinedViewContextDTO,
) -> Callable[..., str]:
    """Create the combined-view point-out tool bound to the current chat state.

    Args:
        callback: Used to synchronously ask Artemis to navigate the client.
        lecture_content_storage: Where the lecture retrieval tool writes its results. Used to
            require that a retrieval happened first and to ground the requested position in it.
        combined_context: Describes the student's current position in the combined view.

    Returns:
        The point-out tool function.
    """
    # Whether this run already moved the student's view. At most one point-out per answer: jumping
    # the view around mid-answer is confusing, and enforcing it here means the tool never has to
    # track where an earlier point-out left the student.
    already_moved = False

    def point_out_relevant_lecture_position(
        page: Optional[int] = None, timestamp: Optional[float] = None
    ) -> str:
        """Show the student a specific slide page and/or video moment in their combined view.

        This is the only way to move what the student sees. It does not search and decides nothing
        for you: retrieve the lecture content first, then judge from those results which position
        fits the student's question better than the one they are currently looking at, and pass it
        here. Take the values straight from the results — ``page`` is the slide's "point-out id: N"
        (not the page number printed on the slide), ``timestamp`` is the "Video timestamp: Ns".
        Give a page, a timestamp, or both; values that do not appear in the results for the lecture
        unit the student is viewing are rejected.

        Point out at most one position per answer. If the student is already at the position you
        pass (for the video: anywhere inside that segment), their view is left untouched.

        System notes in the chat history record where you pointed the student earlier in this
        conversation. They are a record of what happened, not a restriction: point to a spot again
        whenever the current question calls for it.

        Args:
            page: Point-out id of the slide to show. Omit to leave the slides untouched.
            timestamp: Video time in seconds to jump to. Omit to leave the video untouched.

        Returns:
            Whether the student's view was moved. Only claim you showed something if it was.
        """
        nonlocal already_moved

        if already_moved:
            return (
                "You already moved the student's view in this answer, and only one point-out per "
                "answer is allowed. Describe any further positions in your text instead."
            )

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

        # Page and timestamp are checked independently and reported together: neither one may hide
        # the other's failure behind an early return, or a call that got both wrong would learn
        # about them one retry at a time.
        # The unit the point-out will navigate in; retrieved results from other units cannot ground
        # a position here.
        lecture_unit_id = combined_context.lecture_unit_id

        problems = []
        if page is not None and not _is_retrieved_page(
            lecture_content, lecture_unit_id, page
        ):
            problems.append(
                f"slide page {page} is not among the retrieved results for the lecture unit "
                "the student is viewing"
            )

        # Kept beyond the check: the segment's interval decides further down whether the student is
        # already inside it.
        target_segment = (
            _resolve_timestamp_segment(lecture_content, lecture_unit_id, timestamp)
            if timestamp is not None
            else None
        )
        if timestamp is not None and target_segment is None:
            problems.append(
                f"the video timestamp {timestamp:.0f}s does not fall within any retrieved "
                "video segment of the lecture unit the student is viewing"
            )

        if problems:
            reason = " and ".join(problems)
            return (
                f"{reason[0].upper()}{reason[1:]}, so the student's view was not moved. Point "
                "only to a page or timestamp that appears in the retrieved results."
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
                lecture_unit_id=lecture_unit_id,
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

        # Case 2: navigated successfully. This answer's one point-out is now spent.
        already_moved = True
        shown = _describe(move_page, move_timestamp)
        # The system prompt describes where the student stood when this run started and cannot be
        # re-rendered mid-run. This message is the agent's last input before it answers, so it is
        # where that description gets superseded.
        return (
            f"You brought up {shown} on the student's screen. This is what the student sees now, "
            "so any earlier description of their current position is out of date. Refer to what "
            'you just opened naturally in your answer (e.g. "as you can see on the slide I just '
            'opened ...").'
        )

    return point_out_relevant_lecture_position
