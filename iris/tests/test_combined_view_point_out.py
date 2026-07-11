"""Tests for the combined-view point-out agent tool.

The tool is a plain navigation method: the agent retrieves lecture content first, then calls
this tool with the slide page and/or video timestamp it chose from those results. The tool maps
the agent's display page to the technical page Artemis navigates by and asks Artemis to move the
student's view. These tests cover the outcomes (navigated, already there, not applied) plus the
preconditions (no retrieval yet, page or timestamp not in results, nothing requested), without
any network or LLM calls.
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


def _page_chunk(page_number, display_page_number=None, text="content"):
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
        display_page_number=(
            page_number if display_page_number is None else display_page_number
        ),
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


def _make_tool(callback, combined, content=None):
    storage = {} if content is None else {"content": content}
    return create_tool_combined_view_point_out(
        callback=callback,
        lecture_content_storage=storage,
        combined_context=combined,
    )


def test_navigates_to_requested_slide_mapping_display_to_technical_page():
    callback = _FakeCallback(applied=True)
    combined = _combined(page=2)
    # Display page 8 maps to technical page 7 (what Artemis navigates by).
    content = _content(page_chunks=[_page_chunk(page_number=7, display_page_number=8)])
    tool = _make_tool(callback, combined, content)

    result = tool(page=8)

    assert len(callback.commands) == 1
    assert callback.commands[0].page == 7
    assert callback.commands[0].timestamp is None
    assert "brought up" in result.lower()
    # The human-facing page number is used when describing the move to the agent.
    assert "page 8" in result.lower()
    # Current position is synced (to the technical page) for a later call.
    assert combined.slides.page == 7


def test_already_at_position_does_not_call_artemis():
    callback = _FakeCallback(applied=True)
    combined = _combined(page=5)
    tool = _make_tool(callback, combined, _content(page_chunks=[_page_chunk(5)]))

    result = tool(page=5)

    assert callback.commands == []
    assert "already" in result.lower()


def test_not_applied_says_nothing_about_navigation():
    callback = _FakeCallback(applied=False)
    combined = _combined(page=1)
    tool = _make_tool(callback, combined, _content(page_chunks=[_page_chunk(9)]))

    result = tool(page=9)

    assert len(callback.commands) == 1
    assert "brought up" not in result.lower()
    assert "could not" in result.lower()


def test_requires_retrieval_first():
    callback = _FakeCallback(applied=True)
    combined = _combined(page=1)
    tool = _make_tool(callback, combined, content=None)

    result = tool(page=3)

    assert callback.commands == []
    assert "retriev" in result.lower()


def test_page_not_in_results_is_rejected():
    callback = _FakeCallback(applied=True)
    combined = _combined(page=1)
    tool = _make_tool(callback, combined, _content(page_chunks=[_page_chunk(3)]))

    result = tool(page=99)

    assert callback.commands == []
    assert "not among" in result.lower()


def test_video_only_points_to_timestamp():
    callback = _FakeCallback(applied=True)
    combined = _combined(page=1, timestamp=0.0)
    content = _content(
        page_chunks=[_page_chunk(3)],
        transcriptions=[_transcription(page_number=3, start_time=42.0)],
    )
    tool = _make_tool(callback, combined, content)

    result = tool(timestamp=42.0)

    assert len(callback.commands) == 1
    assert callback.commands[0].page is None
    assert callback.commands[0].timestamp == 42.0
    assert "brought up" in result.lower()


def test_points_to_page_and_timestamp_together():
    callback = _FakeCallback(applied=True)
    combined = _combined(page=1, timestamp=0.0)
    content = _content(
        page_chunks=[_page_chunk(3)],
        transcriptions=[_transcription(page_number=3, start_time=42.0)],
    )
    tool = _make_tool(callback, combined, content)

    result = tool(page=3, timestamp=42.0)

    assert len(callback.commands) == 1
    assert callback.commands[0].page == 3
    assert callback.commands[0].timestamp == 42.0
    assert "brought up" in result.lower()


def test_timestamp_not_in_results_is_rejected():
    callback = _FakeCallback(applied=True)
    combined = _combined(page=1, timestamp=0.0)
    content = _content(
        page_chunks=[_page_chunk(3)],
        transcriptions=[_transcription(page_number=3, start_time=42.0)],
    )
    tool = _make_tool(callback, combined, content)

    result = tool(timestamp=600.0)

    assert callback.commands == []
    assert "does not fall within" in result.lower()


def test_timestamp_inside_segment_is_accepted():
    callback = _FakeCallback(applied=True)
    combined = _combined(page=1, timestamp=0.0)
    # Segment covers [42s, 52s]; pointing to 45s (mid-segment) is valid.
    content = _content(
        page_chunks=[_page_chunk(3)],
        transcriptions=[_transcription(page_number=3, start_time=42.0)],
    )
    tool = _make_tool(callback, combined, content)

    result = tool(timestamp=45.0)

    assert len(callback.commands) == 1
    assert callback.commands[0].timestamp == 45.0
    assert "brought up" in result.lower()


def test_student_already_within_target_segment_does_not_call_artemis():
    callback = _FakeCallback(applied=True)
    # Student is at 45s, inside the targeted segment [42s, 52s]: no navigation.
    combined = _combined(timestamp=45.0)
    content = _content(
        page_chunks=[_page_chunk(3)],
        transcriptions=[_transcription(page_number=3, start_time=42.0)],
    )
    tool = _make_tool(callback, combined, content)

    result = tool(timestamp=42.0)

    assert callback.commands == []
    assert "already" in result.lower()


def test_nothing_requested_does_not_navigate():
    callback = _FakeCallback(applied=True)
    combined = _combined(page=1)
    tool = _make_tool(callback, combined, _content(page_chunks=[_page_chunk(3)]))

    result = tool()

    assert callback.commands == []
    assert "nothing to point to" in result.lower()
