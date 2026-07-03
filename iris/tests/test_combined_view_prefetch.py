"""Tests for combined-view lecture prefetching before the agent answers."""

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
from iris.pipeline.chat.chat_pipeline import ChatPipeline


class _FakeCallback:
    def __init__(self, applied=True):
        self.result = CommandResultDTO(applied=applied)
        self.commands = []
        self.progress_messages = []

    def in_progress(self, *args, **kwargs):
        self.progress_messages.append((args, kwargs))

    def execute_command(self, command):
        self.commands.append(command)
        return self.result


def _make_page_chunk(page_number: int, text: str) -> LectureUnitPageChunkRetrievalDTO:
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
        display_page_number=page_number,
        page_text_content=text,
        base_url="http://example.com",
    )


def _state(query_text: str, context: CombinedViewContextDTO, callback: _FakeCallback):
    return SimpleNamespace(
        allow_lecture_tool=True,
        lecture_contexts=[context],
        query_text=query_text,
        message_history=[],
        lecture_content_storage={},
        callback=callback,
        dto=SimpleNamespace(
            settings=SimpleNamespace(artemis_base_url="http://example.com"),
            course=SimpleNamespace(id=1),
            lecture=SimpleNamespace(id=1),
            lecture_unit_id=1,
        ),
    )


def test_prefetch_retrieves_content_and_points_out_before_agent():
    pipeline = ChatPipeline.__new__(ChatPipeline)
    lecture_content = LectureRetrievalDTO(
        lecture_unit_segments=[],
        lecture_transcriptions=[],
        lecture_unit_page_chunks=[_make_page_chunk(2, "Challenges live here")],
    )
    retriever = MagicMock(return_value=lecture_content)
    pipeline._get_lecture_retriever = MagicMock(return_value=retriever)

    context = CombinedViewContextDTO(
        type="combinedView",
        slides=SlidesContextDTO(type="slides", lectureUnitId=1, page=1),
    )
    callback = _FakeCallback(applied=True)
    state = _state("can you tell me more about the challenges?", context, callback)

    pipeline._prefetch_combined_view_support(state)

    assert state.lecture_content_storage["content"] is lecture_content
    assert "Page: 2" in state.prefetched_lecture_content
    assert state.combined_view_action_note == (
        "Successfully showed the student page 2 of the slides."
    )
    assert len(callback.commands) == 1
    assert callback.commands[0].page == 2
    assert callback.commands[0].timestamp is None
    assert context.slides.page == 2


def test_prefetch_skips_obvious_smalltalk():
    pipeline = ChatPipeline.__new__(ChatPipeline)
    retriever = MagicMock()
    pipeline._get_lecture_retriever = MagicMock(return_value=retriever)

    context = CombinedViewContextDTO(
        type="combinedView",
        slides=SlidesContextDTO(type="slides", lectureUnitId=1, page=1),
    )
    callback = _FakeCallback(applied=True)
    state = _state("Hello, how are you?", context, callback)

    pipeline._prefetch_combined_view_support(state)

    retriever.assert_not_called()
    assert "content" not in state.lecture_content_storage
    assert getattr(state, "prefetched_lecture_content", None) is None
    assert getattr(state, "combined_view_action_note", None) is None
    assert not callback.commands


def test_prefetch_notes_when_current_page_is_already_best():
    pipeline = ChatPipeline.__new__(ChatPipeline)
    lecture_content = LectureRetrievalDTO(
        lecture_unit_segments=[],
        lecture_transcriptions=[],
        lecture_unit_page_chunks=[_make_page_chunk(2, "Challenges live here")],
    )
    retriever = MagicMock(return_value=lecture_content)
    pipeline._get_lecture_retriever = MagicMock(return_value=retriever)

    context = CombinedViewContextDTO(
        type="combinedView",
        slides=SlidesContextDTO(type="slides", lectureUnitId=1, page=2),
        video=VideoContextDTO(type="video", lectureUnitId=1, timestamp=5.0),
    )
    callback = _FakeCallback(applied=True)
    state = _state("can you tell me more about the challenges?", context, callback)

    pipeline._prefetch_combined_view_support(state)

    assert "already at page 2 of the slides" in state.combined_view_action_note
    assert (
        "most relevant lecture position for answering the student's question"
        in state.combined_view_action_note
    )
    assert not callback.commands
