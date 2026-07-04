"""Combined-view point-out feature.

Runs *before* the agent whenever the chat is started from the lecture combined view.
It retrieves the lecture content relevant to the student's question (exactly like the
lecture retrieval tool would) and reranks it, then — if a slide page or video moment
is a close enough match — points the student there in the combined view via Artemis.

This is deliberately a pre-agent pipeline step, not an agent tool: in the combined
view the current slide/transcript is injected into the prompt, so the agent rarely
calls a retrieval tool, which means a tool-based point-out almost never fires. Doing
it up front guarantees the student is taken to the relevant position when it exists.

The retrieved content is stashed on the state so the lecture retrieval tool can be
skipped for the rest of the run (``combined_view_prefetched``) and reused for prompt
injection and citations.
"""

from typing import Optional

from iris.common.logging_config import get_logger
from iris.domain.data.lecture_context_dto import SlidesContextDTO, VideoContextDTO
from iris.domain.status.point_out_command_dto import PointOutCommandDTO
from iris.retrieval.lecture.lecture_retrieval import LectureRetrieval
from iris.tools.lecture_content_retrieval import (
    format_lecture_content_retrieval_result,
)

logger = get_logger(__name__)

# Minimum reranker relevance score for the top retrieval result before we point the
# student to it. Jumping the slides/video is intrusive, so we only do it when the
# retrieved content is a close match for the question. This is Cohere's rerank
# relevance score; tune empirically.
POINT_OUT_MIN_RERANK_SCORE = 0.3


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


def _pick_target(lecture_content):
    """Pick the best page/timestamp target from reranked retrieval, plus its score.

    Page and video results come from separate reranked lists; we take the top of
    each and return the governing reranker score (the closest match) for the gate.
    ``None`` score means no reranked item backs the target.

    The page is the technical ``page_number`` (index), not ``display_page_number``:
    it is what Artemis navigates by and what the current-view lookup filters on, and
    unlike the display number it is never the ``-1`` "unknown page" sentinel.
    """
    page: Optional[int] = None
    timestamp: Optional[float] = None
    scores: list[float] = []

    if lecture_content.lecture_unit_page_chunks:
        top_chunk = lecture_content.lecture_unit_page_chunks[0]
        page = top_chunk.page_number
        if top_chunk.rerank_score is not None:
            scores.append(top_chunk.rerank_score)
    elif lecture_content.lecture_unit_segments:
        page = lecture_content.lecture_unit_segments[0].page_number

    if lecture_content.lecture_transcriptions:
        first_transcription = lecture_content.lecture_transcriptions[0]
        if page is None or first_transcription.page_number == page:
            timestamp = first_transcription.segment_start_time
            if first_transcription.rerank_score is not None:
                scores.append(first_transcription.rerank_score)

    return page, timestamp, (max(scores) if scores else None)


def run_combined_view_point_out(state, retriever: LectureRetrieval) -> None:
    """Retrieve, optionally point the student to the best position, and stash content.

    Sets on ``state``:
    - ``combined_view_prefetched``: True once retrieval ran, so the lecture tool is
      skipped and the content is injected into the prompt instead.
    - ``prefetched_lecture_content``: the formatted content for prompt injection.
    - ``combined_view_action_note``: a note for the prompt describing what was shown
      (or that the student is already at the relevant position), or None when nothing
      should be said.
    """
    combined = get_combined_view_context(getattr(state, "lecture_contexts", None))
    if combined is None:
        return

    query = (state.query_text or "").strip()
    if not query:
        return

    state.callback.in_progress("Retrieving lecture content ...")
    base_url = state.dto.settings.artemis_base_url if state.dto.settings else ""
    try:
        lecture_content = retriever(
            query=query,
            course_id=state.dto.course.id,
            chat_history=state.message_history,
            lecture_id=state.dto.lecture.id if state.dto.lecture else None,
            lecture_unit_id=state.dto.lecture_unit_id,
            base_url=base_url,
        )
    except Exception as e:
        logger.error("Error retrieving combined-view lecture content", exc_info=e)
        return

    # Stash the content so the lecture retrieval tool is skipped for the rest of the
    # run, the prompt can show it, and citations can use it.
    state.lecture_content_storage["content"] = lecture_content
    state.combined_view_prefetched = True
    state.prefetched_lecture_content = format_lecture_content_retrieval_result(
        lecture_content
    )

    page, timestamp, score = _pick_target(lecture_content)

    if page is None and timestamp is None:
        return
    # Relatedness gate: only jump when the top result is a close enough match, so we
    # never move the student for greetings or off-topic questions.
    if score is None or score < POINT_OUT_MIN_RERANK_SCORE:
        return

    current_page = combined.slides.page if combined.slides is not None else None
    current_timestamp = combined.video.timestamp if combined.video is not None else None
    same_page = page is not None and page == current_page
    same_timestamp = timestamp is not None and timestamp == current_timestamp

    nav_page = None if same_page else page
    nav_timestamp = None if same_timestamp else timestamp

    if nav_page is None and nav_timestamp is None:
        # Case 1: the student is already exactly at the relevant position — no need
        # to ask Artemis to navigate; just let the agent build on it.
        already = _describe(
            page if same_page else None, timestamp if same_timestamp else None
        )
        state.combined_view_action_note = (
            f"The student is already at {already} — the most relevant position for "
            "this question. Refer to it naturally in your answer."
        )
        return

    # Case 3: navigate to the differing position via Artemis.
    result = state.callback.execute_command(
        PointOutCommandDTO(
            lecture_unit_id=combined.lecture_unit_id,
            page=nav_page,
            timestamp=nav_timestamp,
        )
    )
    if not result.applied:
        # Case 2 outcome: the student left the combined view — act as if nothing
        # happened and tell the prompt nothing.
        return

    shown = _describe(nav_page, nav_timestamp)
    state.combined_view_action_note = (
        f"You opened {shown} on the student's screen. Refer to it naturally in your "
        'answer (e.g. "as you can see on the slide I just opened …").'
    )
    # Keep the current position in sync with where we navigated. If the combined
    # view had no slides/video sub-context yet (e.g. the slides were only a
    # thumbnail), create it now: from this point on that material is actually being
    # shown, so the prompt's current-view block should include it.
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
