"""Combined-view point-out tool.

An agent tool for the lecture combined view (slides + video + chat shown side by side). It does
not search and does not decide: the agent retrieves lecture content first, picks a slide page
and/or video moment from those results, and this tool asks Artemis to move the student's view
there and reports whether that worked.
"""

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from iris.domain.data.lecture_context_dto import CombinedViewContextDTO
from iris.domain.retrieval.lecture.lecture_retrieval_dto import (
    LectureRetrievalDTO,
    printed_page_number,
)
from iris.domain.status.point_out_command_dto import (
    PointOutCommandDTO,
    PointOutParametersDTO,
)
from iris.tools.current_view_content import MOVED_AWAY_KEY
from iris.web.status.status_update import StatusCallback

# How close the student's video position has to be to the requested one to count as already there.
# Sized to a seek nobody would notice: it absorbs the sub-second difference between the player
# position the client reports and the timestamp read off the retrieval results, and nothing more.
# Anything wider would start swallowing jumps to a genuinely different moment.
_SAME_TIMESTAMP_TOLERANCE_SECONDS = 0.5


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


def _find_retrieved_page(
    lecture_content: LectureRetrievalDTO, lecture_unit_id: Optional[int], page: int
) -> Optional[Any]:
    """Find the retrieved slide of ``lecture_unit_id`` whose point-out id is ``page``.

    ``page`` is the point-out id (the technical ``page_number`` Artemis navigates by), not the number
    printed on the slide. Looking it up in the results keeps the agent from pointing at a page that
    never appeared there, and yields the result that carries the printed number for it.

    Results from other units are skipped: retrieval is not always scoped to the unit the student is
    looking at, while the point-out always navigates within it, so a page valid only elsewhere would
    land in the wrong deck. Transcription segments are not consulted either — their ``page_number``
    is a printed number, not a deck index, and would resolve the wrong slide.

    Unit segments no longer show a point-out id in the results but are still accepted here: their
    page is a real page of this unit, so rejecting it would only fail a call that names a page the
    agent legitimately read about.

    Returns:
        The matching page chunk or unit segment, or None when the page was not retrieved.
    """
    for chunk in lecture_content.lecture_unit_page_chunks:
        if chunk.page_number == page and chunk.lecture_unit_id == lecture_unit_id:
            return chunk
    for segment in lecture_content.lecture_unit_segments:
        if segment.page_number == page and segment.lecture_unit_id == lecture_unit_id:
            return segment
    return None


def _timestamp_is_retrieved(
    lecture_content: LectureRetrievalDTO,
    lecture_unit_id: Optional[int],
    timestamp: float,
) -> bool:
    """Whether ``timestamp`` falls inside a retrieved segment of ``lecture_unit_id``.

    Grounds timestamps in the retrieval results the same way pages are grounded, including the
    restriction to the unit the point-out will navigate in. Only coverage is asked for: which
    segment covers the timestamp says nothing about where in the video it sits, since retrieved
    intervals may overlap and can span the whole lecture.

    Intervals are half-open (``start <= t < end``), so the end of a segment belongs to the segment
    starting there rather than being covered twice.
    """
    return any(
        segment.lecture_unit_id == lecture_unit_id
        and segment.segment_start_time <= timestamp < segment.segment_end_time
        for segment in lecture_content.lecture_transcriptions
    )


@dataclass(frozen=True)
class _Resolution:
    """One pane's own answer to "should this move, and where to?".

    Each pane is resolved without seeing the other, so a slide worth showing is no reason to leave
    the video behind. The two answers are assembled into a single command afterwards: Artemis can
    only reconcile a page with a timestamp when they arrive together.
    """

    # None means this pane stays put — nothing requested, refused, or already there.
    target: Optional[float] = None
    # Why the request was refused, phrased for the agent.
    problem: Optional[str] = None
    # Printed number of the slide moved to, for the chat-history chip. Slide side only.
    display_page: Optional[int] = None


def _resolve_slide(
    lecture_content: LectureRetrievalDTO,
    lecture_unit_id: Optional[int],
    page: Optional[int],
    current_page: Optional[int],
) -> _Resolution:
    """Decide on the slides alone, without consulting the video."""
    if page is None:
        return _Resolution()
    target_page = _find_retrieved_page(lecture_content, lecture_unit_id, page)
    if target_page is None:
        return _Resolution(
            problem=(
                f"slide page {page} is not among the retrieved results for the lecture unit "
                "the student is viewing"
            )
        )
    if page == current_page:
        return _Resolution()
    return _Resolution(
        target=page,
        display_page=printed_page_number(
            getattr(target_page, "display_page_number", None)
        ),
    )


def _resolve_video(
    lecture_content: LectureRetrievalDTO,
    lecture_unit_id: Optional[int],
    timestamp: Optional[float],
    current_timestamp: Optional[float],
) -> _Resolution:
    """Decide on the video alone, without consulting the slides."""
    if timestamp is None:
        return _Resolution()
    if not _timestamp_is_retrieved(lecture_content, lecture_unit_id, timestamp):
        return _Resolution(
            problem=(
                f"the video timestamp {timestamp:g}s does not fall within any retrieved "
                "video segment of the lecture unit the student is viewing"
            )
        )
    # Compared against the requested moment itself, not against the interval of the segment it was
    # resolved in: retrieved intervals may overlap and can be wide (ingestion groups every
    # appearance of one slide into a single span, and semantic chunks share time ranges), so one of
    # them covering both the student's position and the requested moment says nothing about the two
    # being the same place in the video.
    if (
        current_timestamp is not None
        and abs(current_timestamp - timestamp) <= _SAME_TIMESTAMP_TOLERANCE_SECONDS
    ):
        return _Resolution()
    return _Resolution(target=timestamp)


def create_tool_combined_view_point_out(
    callback: StatusCallback,
    lecture_content_storage: Dict[str, Any],
    combined_context: CombinedViewContextDTO,
    current_view_storage: Optional[Dict[str, Any]] = None,
) -> Callable[..., str]:
    """Create the combined-view point-out tool bound to the current chat state.

    Args:
        callback: Used to synchronously ask Artemis to navigate the client.
        lecture_content_storage: Where the lecture retrieval tool writes its results. Used to
            require that a retrieval happened first and to ground the requested position in it.
        combined_context: Describes the student's current position in the combined view.
        current_view_storage: Shared mutable state backing the current-position tool. Marked as
            moved away once this tool navigated the student, so that tool stops reporting the
            pre-navigation material as what the student is looking at right now.

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

        Call this tool at most once per answer. One call may name a slide and a video moment
        together, and that counts as the one point-out, not as two — when the slides and the video
        both have something to say about the question, showing both at once is better than picking
        one. If the student is already at the position you pass, their view is left untouched.

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

        # The unit the point-out will navigate in; retrieved results from other units cannot ground
        # a position here.
        lecture_unit_id = combined_context.lecture_unit_id
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

        # Each pane answers for itself, then one command is built from both answers.
        slide = _resolve_slide(lecture_content, lecture_unit_id, page, current_page)
        video = _resolve_video(
            lecture_content, lecture_unit_id, timestamp, current_timestamp
        )

        # Both refusals are reported together: neither may hide the other behind an early return,
        # or a call that got both wrong would learn about them one retry at a time.
        problems = [p for p in (slide.problem, video.problem) if p is not None]
        if problems:
            reason = " and ".join(problems)
            return (
                f"{reason[0].upper()}{reason[1:]}, so the student's view was not moved. Point "
                "only to a page or timestamp that appears in the retrieved results."
            )

        if slide.target is None and video.target is None:
            # Case 1: the student is already exactly at the requested position.
            return (
                "The student is already looking at that position, so their view was not moved. "
                "Refer to it naturally in your answer."
            )

        # Case 2/3: both answers become one command; a pane that resolved to None is left out of it.
        result = callback.execute_command(
            PointOutCommandDTO(
                parameters=PointOutParametersDTO(
                    lecture_unit_id=lecture_unit_id,
                    page=slide.target,
                    timestamp=video.target,
                    display_page=slide.display_page,
                )
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
        # The current-position tool reads out material captured before this navigation. Whatever
        # it holds now describes a position the student has left, so it is invalidated wholesale:
        # even a point-out that only moved the slides leaves its blocks labelled as what the
        # student sees "right now", and one stale block next to a still-valid one is exactly the
        # mix that produces an answer about the wrong view.
        if current_view_storage is not None:
            current_view_storage[MOVED_AWAY_KEY] = True
        shown = _describe(slide.target, video.target)
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
