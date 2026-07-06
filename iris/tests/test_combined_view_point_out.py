"""Tests for the combined-view point-out agent tool.

The tool searches the lecture unit for the position that best answers the student's
question and, when it is a better fit than what the student currently sees, asks Artemis
to move the student there. These tests cover the three outcomes (already there, navigated,
not applied) plus the no-match and modality behaviour, without any network or LLM calls.
"""

# pylint: skip-file

from uuid import uuid4

from iris.domain.data.lecture_context_dto import (
    CombinedViewContextDTO,
    SlidesContextDTO,
    VideoContextDTO,
)
from iris.domain.retrieval.lecture.lecture_retrieval_dto import (
    LectureRetrievalDTO,
    LectureTranscriptionRetrievalDTO,
    LectureUnitPageChunkRetrievalDTO,
)
from iris.domain.status.command_result_dto import CommandResultDTO
from iris.tools.combined_view_point_out import create_tool_combined_view_point_out


class _FakeCallback:
    def __init__(self, applied=True):
        self.result = CommandResultDTO(applied=applied)
        self.commands = []

    def execute_command(self, command):
        self.commands.append(command)
        return self.result


def _page_chunk(page_number, text="content"):
    return LectureUnitPageChunkRetrievalDTO(
        uuid=str(uuid4()),
        course_id=1,
        course_name="Course",
        course_description="Desc",
        lecture_id=1,
        lecture_name="Lecture",
        lecture_unit_id=1,
        lecture_unit_name="Unit",
        lecture_unit_link="http://example.com/unit",
        course_language="en",
        page_number=page_number,
        display_page_number=page_number,
        page_text_content=text,
        base_url="http://example.com",
    )


def _transcription(page_number, start_time, text="spoken"):
    return LectureTranscriptionRetrievalDTO(
        uuid=str(uuid4()),
        course_id=1,
        course_name="Course",
        course_description="Desc",
        lecture_id=1,
        lecture_name="Lecture",
        lecture_unit_id=1,
        lecture_unit_name="Unit",
        video_link="http://example.com/video",
        language="en",
        segment_start_time=start_time,
        segment_end_time=start_time + 10,
        page_number=page_number,
        segment_summary="summary",
        segment_text=text,
        base_url="http://example.com",
    )


def _content(page_chunks=None, transcriptions=None):
    return LectureRetrievalDTO(
        lecture_unit_segments=[],
        lecture_transcriptions=transcriptions or [],
        lecture_unit_page_chunks=page_chunks or [],
    )


def _combined(page=None, timestamp=None):
    slides = (
        SlidesContextDTO(type="slides", lecture_unit_id=1, page=page)
        if page is not None
        else None
    )
    video = (
        VideoContextDTO(type="video", lecture_unit_id=1, timestamp=timestamp)
        if timestamp is not None
        else None
    )
    return CombinedViewContextDTO(type="combinedView", slides=slides, video=video)


def _make_tool(content, callback, combined):
    return create_tool_combined_view_point_out(
        lecture_retriever=lambda **kwargs: content,
        course_id=1,
        base_url="http://example.com",
        callback=callback,
        query_text="What is a hash map?",
        history=[],
        lecture_content_storage={},
        combined_context=combined,
        lecture_id=1,
        lecture_unit_id=1,
    )


def test_navigates_to_better_slide_and_reports_it():
    callback = _FakeCallback(applied=True)
    combined = _combined(page=2)
    tool = _make_tool(_content(page_chunks=[_page_chunk(7)]), callback, combined)

    result = tool(query="hash map", show="slide")

    assert len(callback.commands) == 1
    assert callback.commands[0].page == 7
    assert callback.commands[0].timestamp is None
    assert "brought up" in result.lower()
    # Current position is synced so a later call sees the student as already there.
    assert combined.slides.page == 7


def test_already_at_position_does_not_call_artemis():
    callback = _FakeCallback(applied=True)
    combined = _combined(page=5)
    tool = _make_tool(_content(page_chunks=[_page_chunk(5)]), callback, combined)

    result = tool(query="hash map", show="slide")

    assert callback.commands == []
    assert "already" in result.lower()


def test_not_applied_says_nothing_about_navigation():
    callback = _FakeCallback(applied=False)
    combined = _combined(page=1)
    tool = _make_tool(_content(page_chunks=[_page_chunk(9)]), callback, combined)

    result = tool(query="hash map", show="slide")

    assert len(callback.commands) == 1
    assert "brought up" not in result.lower()
    assert "could not" in result.lower()


def test_no_match_does_not_navigate():
    callback = _FakeCallback(applied=True)
    combined = _combined(page=1)
    tool = _make_tool(_content(), callback, combined)

    result = tool(query="unrelated", show="both")

    assert callback.commands == []
    assert "no specific" in result.lower()


def test_show_video_only_points_to_timestamp():
    callback = _FakeCallback(applied=True)
    combined = _combined(page=1, timestamp=0.0)
    content = _content(
        page_chunks=[_page_chunk(3)],
        transcriptions=[_transcription(page_number=3, start_time=42.0)],
    )
    tool = _make_tool(content, callback, combined)

    result = tool(query="hash map", show="video")

    assert len(callback.commands) == 1
    assert callback.commands[0].page is None
    assert callback.commands[0].timestamp == 42.0
    assert "brought up" in result.lower()
