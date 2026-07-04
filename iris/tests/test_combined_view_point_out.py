"""Tests for the pre-agent combined-view point-out feature.

When the chat is opened from the lecture combined view, the feature retrieves the
relevant lecture content up front, stashes it (so the lecture tool is skipped), and
— gated on the reranker relevance score — points the student to the most relevant
slide/timestamp via Artemis.
"""

# pylint: skip-file

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from iris.domain.data.lecture_context_dto import (
    CombinedViewContextDTO,
    SlidesContextDTO,
    VideoContextDTO,
)
from iris.domain.retrieval.lecture.lecture_retrieval_dto import (
    LectureRetrievalDTO,
    LectureUnitPageChunkRetrievalDTO,
)
from iris.domain.status.command_result_dto import CommandResultDTO
from iris.pipeline.chat.combined_view_point_out import (
    POINT_OUT_MIN_RERANK_SCORE,
    run_combined_view_point_out,
)


class _FakeCallback:
    def __init__(self, applied=True):
        self.result = CommandResultDTO(applied=applied)
        self.commands = []

    def in_progress(self, *args, **kwargs):
        pass

    def execute_command(self, command):
        self.commands.append(command)
        return self.result


def _make_page_chunk(page_number, text, rerank_score=None, display_page_number=None):
    return LectureUnitPageChunkRetrievalDTO(
        uuid=str(uuid4()),
        course_id=1,
        course_name="Test Course",
        course_description="Test Description",
        lecture_id=1,
        lecture_name="Test Lecture",
        lecture_unit_id=1,
        lecture_unit_name="Test Unit",
        lecture_unit_link="http://example.com/unit",
        course_language="en",
        page_number=page_number,
        display_page_number=(
            page_number if display_page_number is None else display_page_number
        ),
        page_text_content=text,
        base_url="http://example.com",
        rerank_score=rerank_score,
    )


def _content(page_chunks):
    return LectureRetrievalDTO(
        lecture_unit_segments=[],
        lecture_transcriptions=[],
        lecture_unit_page_chunks=page_chunks,
    )


def _state(context, callback, query="tell me about the challenges"):
    return SimpleNamespace(
        lecture_contexts=[context] if context is not None else [],
        query_text=query,
        message_history=[],
        lecture_content_storage={},
        combined_view_action_note=None,
        combined_view_prefetched=False,
        prefetched_lecture_content=None,
        callback=callback,
        dto=SimpleNamespace(
            settings=SimpleNamespace(artemis_base_url="http://example.com"),
            course=SimpleNamespace(id=1),
            lecture=SimpleNamespace(id=1),
            lecture_unit_id=1,
        ),
    )


def _combined(page=1, timestamp=None):
    video = (
        VideoContextDTO(type="video", lectureUnitId=1, timestamp=timestamp)
        if timestamp is not None
        else None
    )
    return CombinedViewContextDTO(
        type="combinedView",
        slides=SlidesContextDTO(type="slides", lectureUnitId=1, page=page),
        video=video,
    )


def test_navigates_and_stashes_when_score_clears_threshold():
    context = _combined(page=1)
    callback = _FakeCallback(applied=True)
    state = _state(context, callback)
    retriever = MagicMock(
        return_value=_content([_make_page_chunk(2, "Challenges", rerank_score=0.9)])
    )

    run_combined_view_point_out(state, retriever)

    # Case 3: navigated to a different page.
    assert len(callback.commands) == 1
    assert callback.commands[0].page == 2
    assert state.combined_view_action_note.startswith("You opened page 2 of the slides")
    assert context.slides.page == 2  # current position synced
    # Content stashed + tool-skip flag set + prompt injection prepared.
    assert state.combined_view_prefetched is True
    assert "content" in state.lecture_content_storage
    assert state.prefetched_lecture_content


def test_targets_technical_page_number_not_display_number():
    context = _combined(page=1)
    callback = _FakeCallback(applied=True)
    state = _state(context, callback)
    # Technical page 5, but the slide displays "3" (or -1 for unknown). We must
    # navigate by the technical page_number.
    retriever = MagicMock(
        return_value=_content(
            [
                _make_page_chunk(
                    5, "Challenges", rerank_score=0.9, display_page_number=-1
                )
            ]
        )
    )

    run_combined_view_point_out(state, retriever)

    assert callback.commands[0].page == 5
    assert context.slides.page == 5


def test_creates_slides_context_when_missing():
    # Combined view with only a video sub-context (slides were a thumbnail).
    context = CombinedViewContextDTO(
        type="combinedView",
        slides=None,
        video=VideoContextDTO(type="video", lectureUnitId=1, timestamp=0.0),
    )
    callback = _FakeCallback(applied=True)
    state = _state(context, callback)
    retriever = MagicMock(
        return_value=_content([_make_page_chunk(2, "Challenges", rerank_score=0.9)])
    )

    run_combined_view_point_out(state, retriever)

    assert len(callback.commands) == 1
    assert callback.commands[0].page == 2
    # A slides sub-context is now attached so the current-view block can show it.
    assert context.slides is not None
    assert context.slides.page == 2
    assert context.slides.lecture_unit_id == 1


def test_case1_already_at_target_does_not_call_artemis():
    context = _combined(page=2)
    callback = _FakeCallback(applied=True)
    state = _state(context, callback)
    retriever = MagicMock(
        return_value=_content([_make_page_chunk(2, "Challenges", rerank_score=0.9)])
    )

    run_combined_view_point_out(state, retriever)

    assert not callback.commands
    assert "already at page 2 of the slides" in state.combined_view_action_note
    assert "Refer to it naturally" in state.combined_view_action_note
    # Content is still prefetched so the tool is skipped.
    assert state.combined_view_prefetched is True


def test_case2_low_score_says_nothing_but_still_prefetches():
    context = _combined(page=1)
    callback = _FakeCallback(applied=True)
    state = _state(context, callback)
    low = POINT_OUT_MIN_RERANK_SCORE - 0.1
    retriever = MagicMock(
        return_value=_content([_make_page_chunk(2, "Loosely related", low)])
    )

    run_combined_view_point_out(state, retriever)

    assert not callback.commands
    assert state.combined_view_action_note is None
    # Retrieval still ran, so the tool is skipped and content is available.
    assert state.combined_view_prefetched is True
    assert "content" in state.lecture_content_storage


def test_no_score_says_nothing():
    context = _combined(page=1)
    callback = _FakeCallback(applied=True)
    state = _state(context, callback)
    retriever = MagicMock(
        return_value=_content([_make_page_chunk(2, "No score", rerank_score=None)])
    )

    run_combined_view_point_out(state, retriever)

    assert not callback.commands
    assert state.combined_view_action_note is None


def test_not_applied_says_nothing():
    context = _combined(page=1)
    callback = _FakeCallback(applied=False)
    state = _state(context, callback)
    retriever = MagicMock(
        return_value=_content([_make_page_chunk(2, "Challenges", rerank_score=0.9)])
    )

    run_combined_view_point_out(state, retriever)

    # Artemis was asked but declined (student left the combined view).
    assert len(callback.commands) == 1
    assert state.combined_view_action_note is None
    assert context.slides.page == 1  # not synced since nothing was shown


def test_not_combined_view_does_not_retrieve():
    context = SlidesContextDTO(type="slides", lectureUnitId=1, page=1)
    callback = _FakeCallback(applied=True)
    state = _state(context, callback)
    retriever = MagicMock()

    run_combined_view_point_out(state, retriever)

    retriever.assert_not_called()
    assert state.combined_view_prefetched is False
    assert state.combined_view_action_note is None


def test_empty_query_does_not_retrieve():
    context = _combined(page=1)
    callback = _FakeCallback(applied=True)
    state = _state(context, callback, query="   ")
    retriever = MagicMock()

    run_combined_view_point_out(state, retriever)

    retriever.assert_not_called()
    assert state.combined_view_prefetched is False
