"""Tests for the combined-view point-out agent tool.

The tool is a plain navigation method: the agent retrieves lecture content first, then calls this
tool with the slide page and/or video timestamp it chose from those results. These tests cover the
tool's decision table — navigated, already there, not applied — plus the preconditions (no retrieval
yet, position not in the results), without any network or LLM calls.
"""

# pylint: skip-file

from types import SimpleNamespace
from uuid import uuid4

import pytest

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
from iris.tools.chat_tool_providers import provide_combined_view_point_out
from iris.tools.combined_view_point_out import create_tool_combined_view_point_out


class _FakeCallback:
    def __init__(self, applied=True):
        self.result = CommandResultDTO(applied=applied)
        self.commands = []

    def execute_command(self, command):
        self.commands.append(command)
        return self.result


def _page_chunk(
    page_number, display_page_number=None, text="content", lecture_unit_id=1
):
    return LectureUnitPageChunkRetrievalDTO(
        uuid=str(uuid4()),
        course_id=1,
        course_name="Course",
        course_description="Desc",
        lecture_id=1,
        lecture_name="Lecture",
        lecture_unit_id=lecture_unit_id,
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


def _transcription(page_number, start_time, text="spoken", lecture_unit_id=1):
    return LectureTranscriptionRetrievalDTO(
        uuid=str(uuid4()),
        course_id=1,
        course_name="Course",
        course_description="Desc",
        lecture_id=1,
        lecture_name="Lecture",
        lecture_unit_id=lecture_unit_id,
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


def _combined(page=None, timestamp=None, lecture_unit_id=1):
    slides = (
        SlidesContextDTO(type="slides", lecture_unit_id=lecture_unit_id, page=page)
        if page is not None
        else None
    )
    video = (
        VideoContextDTO(
            type="video", lecture_unit_id=lecture_unit_id, timestamp=timestamp
        )
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


def test_navigates_to_requested_page():
    callback = _FakeCallback(applied=True)
    combined = _combined(page=2)
    # The agent passes the technical page number (7, its point-out id); its printed number (8) is
    # only for referring to the slide in the answer text and is not involved in navigation.
    content = _content(page_chunks=[_page_chunk(page_number=7, display_page_number=8)])
    tool = _make_tool(callback, combined, content)

    result = tool(page=7)

    assert len(callback.commands) == 1
    assert callback.commands[0].parameters.page == 7
    assert callback.commands[0].parameters.timestamp is None
    assert "brought up" in result.lower()
    # The frozen "# Current Position" section of the system prompt is explicitly superseded.
    assert "out of date" in result.lower()


def test_navigates_to_a_timestamp_inside_a_retrieved_segment():
    callback = _FakeCallback(applied=True)
    combined = _combined(page=1, timestamp=0.0)
    # Segment covers [42s, 52s); pointing to 45s (mid-segment, not its start) is valid.
    content = _content(
        page_chunks=[_page_chunk(3)],
        transcriptions=[_transcription(page_number=3, start_time=42.0)],
    )
    tool = _make_tool(callback, combined, content)

    result = tool(timestamp=45.0)

    assert len(callback.commands) == 1
    assert callback.commands[0].parameters.page is None
    assert callback.commands[0].parameters.timestamp == 45.0
    assert "brought up" in result.lower()


def test_already_at_page_does_not_call_artemis():
    callback = _FakeCallback(applied=True)
    combined = _combined(page=5)
    tool = _make_tool(callback, combined, _content(page_chunks=[_page_chunk(5)]))

    result = tool(page=5)

    assert callback.commands == []
    assert "already" in result.lower()


def test_already_within_target_segment_does_not_call_artemis():
    callback = _FakeCallback(applied=True)
    # Student is at 45s, inside the targeted segment [42s, 52s): no navigation.
    combined = _combined(timestamp=45.0)
    content = _content(
        page_chunks=[_page_chunk(3)],
        transcriptions=[_transcription(page_number=3, start_time=42.0)],
    )
    tool = _make_tool(callback, combined, content)

    result = tool(timestamp=42.0)

    assert callback.commands == []
    assert "already" in result.lower()


def test_boundary_timestamp_resolves_to_the_later_of_two_adjacent_segments():
    """Segment intervals are half-open, so a shared boundary belongs to the segment starting there.

    With adjacent segments [0s, 10s) and [10s, 20s), pointing at 10s must resolve to the second one.
    Were the end treated as inclusive, 10s would resolve to the first segment, and the student
    sitting at 5s would count as already inside it — leaving them behind with no navigation at all.
    """
    callback = _FakeCallback(applied=True)
    combined = _combined(timestamp=5.0)
    content = _content(
        page_chunks=[_page_chunk(3)],
        transcriptions=[
            _transcription(page_number=3, start_time=0.0),
            _transcription(page_number=4, start_time=10.0),
        ],
    )
    tool = _make_tool(callback, combined, content)

    result = tool(timestamp=10.0)

    assert len(callback.commands) == 1
    assert callback.commands[0].parameters.timestamp == 10.0
    assert "brought up" in result.lower()


def test_student_sitting_on_a_segment_boundary_is_not_counted_as_inside_it():
    """The student at 10s is in [10s, 20s), not in the [0s, 10s) segment being pointed at."""
    callback = _FakeCallback(applied=True)
    combined = _combined(timestamp=10.0)
    content = _content(
        page_chunks=[_page_chunk(3)],
        transcriptions=[
            _transcription(page_number=3, start_time=0.0),
            _transcription(page_number=4, start_time=10.0),
        ],
    )
    tool = _make_tool(callback, combined, content)

    result = tool(timestamp=0.0)

    assert len(callback.commands) == 1
    assert callback.commands[0].parameters.timestamp == 0.0
    assert "brought up" in result.lower()


def test_only_one_point_out_per_answer():
    """A second successful point-out in the same run is refused without touching the view."""
    callback = _FakeCallback(applied=True)
    combined = _combined(page=1)
    content = _content(page_chunks=[_page_chunk(4), _page_chunk(9)])
    tool = _make_tool(callback, combined, content)

    assert "brought up" in tool(page=4).lower()
    result = tool(page=9)

    assert len(callback.commands) == 1
    assert "already moved" in result.lower()


def test_a_refused_point_out_does_not_use_up_the_answer_s_one_move():
    """Only a move that actually happened counts; a rejected position leaves the budget intact."""
    callback = _FakeCallback(applied=True)
    combined = _combined(page=1)
    tool = _make_tool(callback, combined, _content(page_chunks=[_page_chunk(4)]))

    assert "not among" in tool(page=99).lower()
    assert "brought up" in tool(page=4).lower()
    assert len(callback.commands) == 1


def test_not_applied_says_nothing_about_navigation():
    """Artemis could not navigate — the agent must not claim it showed the student anything."""
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


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        ({"page": 99}, "not among"),
        ({"timestamp": 600.0}, "does not fall within"),
    ],
)
def test_position_outside_the_retrieval_results_is_rejected(kwargs, expected):
    callback = _FakeCallback(applied=True)
    combined = _combined(page=1, timestamp=0.0)
    content = _content(
        page_chunks=[_page_chunk(3)],
        transcriptions=[_transcription(page_number=3, start_time=42.0)],
    )
    tool = _make_tool(callback, combined, content)

    result = tool(**kwargs)

    assert callback.commands == []
    assert expected in result.lower()


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        ({"page": 3}, "not among"),
        ({"timestamp": 45.0}, "does not fall within"),
    ],
)
def test_position_retrieved_from_another_lecture_unit_is_rejected(kwargs, expected):
    """Retrieval is not always scoped to the viewed unit, but the point-out always navigates in it.

    A page or timestamp that only exists in another unit's results must not be accepted: Artemis
    would be asked to open it in the unit the student is actually viewing.
    """
    callback = _FakeCallback(applied=True)
    combined = _combined(page=1, timestamp=0.0, lecture_unit_id=1)
    content = _content(
        page_chunks=[_page_chunk(3, lecture_unit_id=2)],
        transcriptions=[
            _transcription(page_number=3, start_time=42.0, lecture_unit_id=2)
        ],
    )
    tool = _make_tool(callback, combined, content)

    result = tool(**kwargs)

    assert callback.commands == []
    assert expected in result.lower()


def test_sends_the_printed_page_number_along_for_the_chat_history_chip():
    """Artemis labels its chip with the printed number so it agrees with the answer text.

    Navigation still runs off the point-out id; the printed number rides along purely as a label.
    """
    callback = _FakeCallback(applied=True)
    combined = _combined(page=1)
    content = _content(page_chunks=[_page_chunk(page_number=7, display_page_number=8)])
    tool = _make_tool(callback, combined, content)

    tool(page=7)

    assert callback.commands[0].parameters.page == 7
    assert callback.commands[0].parameters.display_page == 8


def test_takes_the_printed_number_from_the_slide_actually_pointed_at():
    callback = _FakeCallback(applied=True)
    combined = _combined(page=1)
    content = _content(
        page_chunks=[
            _page_chunk(page_number=7, display_page_number=8),
            _page_chunk(page_number=9, display_page_number=10),
        ]
    )
    tool = _make_tool(callback, combined, content)

    tool(page=9)

    assert callback.commands[0].parameters.display_page == 10


@pytest.mark.parametrize("unnumbered", [-1, 0])
def test_sends_no_printed_page_number_for_an_unnumbered_slide(unnumbered):
    """Ingestion marks a slide whose number could not be read as -1 (older records as 0).

    Neither is a number the student can read off the slide, so none is sent and Artemis falls back
    to labelling the chip with the deck index.
    """
    callback = _FakeCallback(applied=True)
    combined = _combined(page=1)
    content = _content(
        page_chunks=[_page_chunk(page_number=7, display_page_number=unnumbered)]
    )
    tool = _make_tool(callback, combined, content)

    tool(page=7)

    assert callback.commands[0].parameters.page == 7
    assert callback.commands[0].parameters.display_page is None


def test_sends_no_printed_page_number_for_a_timestamp_only_point_out():
    callback = _FakeCallback(applied=True)
    combined = _combined(timestamp=0.0)
    content = _content(
        page_chunks=[_page_chunk(page_number=7, display_page_number=8)],
        transcriptions=[_transcription(page_number=8, start_time=42.0)],
    )
    tool = _make_tool(callback, combined, content)

    tool(timestamp=45.0)

    assert callback.commands[0].parameters.page is None
    assert callback.commands[0].parameters.display_page is None


def _provider_state(lecture_contexts, allow_lecture_tool=True):
    return SimpleNamespace(
        allow_lecture_tool=allow_lecture_tool,
        lecture_contexts=lecture_contexts,
        callback=_FakeCallback(),
        lecture_content_storage={},
    )


def test_provider_offers_the_tool_in_the_combined_view():
    tool = provide_combined_view_point_out(_provider_state([_combined(page=3)]))

    assert tool is not None
    assert tool.__name__ == "point_out_relevant_lecture_position"


def test_provider_stays_silent_outside_the_combined_view():
    """The tool moves the combined view, so anywhere else it has nothing to move.

    A plain slides/video context is not the combined view: the student is looking at the unit on
    the lecture page, where no pane is standing by to be navigated.
    """
    assert provide_combined_view_point_out(_provider_state(None)) is None
    assert provide_combined_view_point_out(_provider_state([])) is None
    assert (
        provide_combined_view_point_out(
            _provider_state(
                [SlidesContextDTO(type="slides", lecture_unit_id=1, page=3)]
            )
        )
        is None
    )


def test_provider_stays_silent_when_the_lecture_tool_is_not_allowed():
    """Gated like every other lecture provider: the point-out navigates lecture material."""
    assert (
        provide_combined_view_point_out(
            _provider_state([_combined(page=3)], allow_lecture_tool=False)
        )
        is None
    )


def test_provider_stays_silent_without_a_resolvable_lecture_unit():
    """A combined view naming no unit gives the point-out no deck to navigate in.

    ``lecture_unit_id`` is derived from the nested slides/video objects, so a context carrying
    neither leaves it None. The command would then name no unit at all and Artemis would reject
    it after the full ack timeout, with the pipeline standing still for it — better not to offer
    the tool than to let the agent spend an answer on a point-out that cannot land.
    """
    empty_combined = CombinedViewContextDTO(
        type="combinedView", slides=None, video=None
    )

    assert empty_combined.lecture_unit_id is None
    assert provide_combined_view_point_out(_provider_state([empty_combined])) is None
