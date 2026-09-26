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
from iris.tools.chat_tool_providers import (
    provide_combined_view_point_out,
    provide_current_view_content,
)
from iris.tools.combined_view_point_out import create_tool_combined_view_point_out
from iris.tools.current_view_content import (
    CONTENT_BLOCKS_KEY,
    create_tool_current_view_content,
)


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


def _transcription(
    page_number, start_time, text="spoken", lecture_unit_id=1, end_time=None
):
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
        segment_end_time=start_time + 10 if end_time is None else end_time,
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


def _make_tool(callback, combined, content=None, current_view_storage=None):
    storage = {} if content is None else {"content": content}
    return create_tool_combined_view_point_out(
        callback=callback,
        lecture_content_storage=storage,
        combined_context=combined,
        current_view_storage=current_view_storage,
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


def test_already_at_the_requested_timestamp_does_not_call_artemis():
    """Only the requested moment itself counts as "already there", within a seek-sized tolerance.

    The student's player position (45.2s) and the timestamp read off the results (45s) describe
    the same moment; seeking two tenths of a second would change nothing on screen.
    """
    callback = _FakeCallback(applied=True)
    combined = _combined(timestamp=45.2)
    content = _content(
        page_chunks=[_page_chunk(3)],
        transcriptions=[_transcription(page_number=3, start_time=42.0)],
    )
    tool = _make_tool(callback, combined, content)

    result = tool(timestamp=45.0)

    assert callback.commands == []
    assert "already" in result.lower()


def test_another_moment_in_the_same_segment_is_still_navigated_to():
    """Sharing a segment with the target is not being at it — the student is 7 seconds away."""
    callback = _FakeCallback(applied=True)
    # Student at 45s, target 52s; the segment [42s, 62s) covers both.
    combined = _combined(timestamp=45.0)
    content = _content(
        page_chunks=[_page_chunk(3)],
        transcriptions=[_transcription(page_number=3, start_time=42.0, end_time=62.0)],
    )
    tool = _make_tool(callback, combined, content)

    result = tool(timestamp=52.0)

    assert len(callback.commands) == 1
    assert callback.commands[0].parameters.timestamp == 52.0
    assert "brought up" in result.lower()


def test_a_broad_overlapping_segment_does_not_suppress_navigation():
    """Retrieved intervals overlap, so segment membership cannot stand in for "already there".

    Ingestion groups every appearance of one slide into a single span, and semantic chunks share
    time ranges — so a wide interval ([0s, 600s) here) can cover both where the student sits (5s)
    and the moment being pointed at (10s), which are ten minutes of lecture apart in the worst
    case. Deciding by that interval leaves the student behind with no command sent at all.
    """
    callback = _FakeCallback(applied=True)
    combined = _combined(timestamp=5.0)
    content = _content(
        page_chunks=[_page_chunk(3)],
        transcriptions=[
            _transcription(page_number=3, start_time=0.0, end_time=600.0),
            _transcription(page_number=4, start_time=8.0, end_time=20.0),
        ],
    )
    tool = _make_tool(callback, combined, content)

    result = tool(timestamp=10.0)

    assert len(callback.commands) == 1
    assert callback.commands[0].parameters.timestamp == 10.0
    assert "brought up" in result.lower()


def test_a_timestamp_on_a_segment_boundary_is_grounded_by_the_segment_starting_there():
    """Half-open intervals: with [0s, 10s) and [10s, 20s), 10s is covered by the second one.

    Were the end treated as inclusive too, the boundary would sit in both — harmless here, but the
    coverage check is the only thing standing between the agent and a timestamp Artemis never saw,
    so it stays exact.
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


def test_a_timestamp_past_the_last_retrieved_segment_is_rejected():
    """The end of the last segment is outside it, so nothing covers it."""
    callback = _FakeCallback(applied=True)
    combined = _combined(timestamp=5.0)
    content = _content(
        page_chunks=[_page_chunk(3)],
        transcriptions=[_transcription(page_number=3, start_time=0.0)],
    )
    tool = _make_tool(callback, combined, content)

    result = tool(timestamp=10.0)

    assert callback.commands == []
    assert "does not fall within" in result.lower()


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


def _current_view_storage(
    block="The student is currently viewing page 3 ... old content",
):
    return {CONTENT_BLOCKS_KEY: [block]}


def test_a_successful_point_out_invalidates_the_current_position_tool():
    """The material of the position the student just left must not be read out as "right now".

    Both tools share the current-view storage: it is captured before the run starts, so after a
    navigation it describes a position the student is no longer at. Left intact, a later call to
    the current-position tool would overwrite this tool's warning with the stale slide, and the
    agent would answer about the wrong view.
    """
    callback = _FakeCallback(applied=True)
    storage = _current_view_storage(
        "The student is currently viewing page 3 ... old content"
    )
    current_position = create_tool_current_view_content(storage)
    tool = _make_tool(
        callback,
        _combined(page=1),
        _content(page_chunks=[_page_chunk(7)]),
        current_view_storage=storage,
    )

    assert "brought up" in tool(page=7).lower()
    result = current_position()

    assert "old content" not in result
    assert "already moved" in result.lower()


def test_a_point_out_that_moved_nothing_leaves_the_current_position_tool_intact():
    """Nothing moved, nothing stale: the student is still at the position the blocks describe.

    Covers both ways a call can end without navigation — Artemis refusing to apply the command,
    and the student already sitting at the requested position.
    """
    for callback, requested_page in (
        (_FakeCallback(applied=False), 7),
        (_FakeCallback(applied=True), 1),
    ):
        storage = _current_view_storage()
        current_position = create_tool_current_view_content(storage)
        tool = _make_tool(
            callback,
            _combined(page=1),
            _content(page_chunks=[_page_chunk(1), _page_chunk(7)]),
            current_view_storage=storage,
        )

        tool(page=requested_page)

        assert "old content" in current_position()


def _provider_state(
    lecture_contexts, allow_lecture_tool=True, current_view_storage=None
):
    return SimpleNamespace(
        allow_lecture_tool=allow_lecture_tool,
        lecture_contexts=lecture_contexts,
        callback=_FakeCallback(),
        lecture_content_storage={},
        current_view_storage=(
            {} if current_view_storage is None else current_view_storage
        ),
    )


def test_the_providers_hand_both_tools_the_same_current_view_storage():
    """Wiring regression: the invalidation only works if both tools share one storage object."""
    storage = _current_view_storage()
    state = _provider_state([_combined(page=1)], current_view_storage=storage)
    state.lecture_content_storage["content"] = _content(page_chunks=[_page_chunk(7)])
    point_out = provide_combined_view_point_out(state)
    current_position = provide_current_view_content(state)

    assert "brought up" in point_out(page=7).lower()

    assert "old content" not in current_position()


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
