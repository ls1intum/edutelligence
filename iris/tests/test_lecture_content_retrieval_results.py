"""Tests for what the lecture retrieval results render for the agent to act on.

The results are not just text: the agent copies numbers out of them and passes them to the point-out
tool verbatim. Two numbers describe the same slide and must not be mixed up — the number printed on
the slide (what it may tell the student) and the slide's index in the deck (the point-out id, which
the point-out tool navigates by) — and slides carrying no printed number are stored with a sentinel
that must not leak into the results. A transcription's video timestamp is the same kind of handle,
and the point-out tool only accepts one that falls inside a retrieved segment's half-open interval.
"""

import re
from uuid import uuid4

import pytest

from iris.domain.data.lecture_context_dto import (
    CombinedViewContextDTO,
    VideoContextDTO,
)
from iris.domain.retrieval.lecture.lecture_retrieval_dto import (
    LectureRetrievalDTO,
    LectureTranscriptionRetrievalDTO,
)
from iris.domain.status.command_result_dto import CommandResultDTO
from iris.tools.combined_view_point_out import create_tool_combined_view_point_out
from iris.tools.lecture_content_retrieval import (
    _format_page_reference,
    _format_video_timestamp,
    create_tool_lecture_content_retrieval,
)


class _FakeCallback:
    def __init__(self):
        self.commands = []

    def execute_command(self, command):
        self.commands.append(command)
        return CommandResultDTO(applied=True)


def _transcription(start_time=42.0, end_time=52.0, page_number=3):
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
        segment_end_time=end_time,
        page_number=page_number,
        segment_summary="summary",
        segment_text="spoken words",
        base_url="http://example.com",
    )


def _retrieval_tool(transcription, storage=None):
    return create_tool_lecture_content_retrieval(
        lecture_retriever=lambda **_kwargs: LectureRetrievalDTO(
            lecture_unit_segments=[],
            lecture_transcriptions=[transcription],
            lecture_unit_page_chunks=[],
        ),
        course_id=1,
        base_url="http://example.com",
        callback=None,
        query_text="query",
        history=[],
        lecture_content_storage={} if storage is None else storage,
    )


@pytest.mark.parametrize(
    "display_page_number, expected",
    [
        (2, "Page: 2"),
        # -1 is the ingestion sentinel for "no page number visible", 0 the one for a transcript that
        # was never enriched with slide numbers; rendering either verbatim would make the agent tell
        # the student about "page -1".
        (-1, "Page: unnumbered"),
        (0, "Page: unnumbered"),
        (None, "Page: unnumbered"),
    ],
)
def test_format_page_reference_without_a_point_out_id(display_page_number, expected):
    assert _format_page_reference(display_page_number) == expected


def test_format_page_reference_lists_both_numbers():
    # A title page shifts the printed numbering against the deck index; only the index navigates.
    assert _format_page_reference(1, 2) == "Page: 1, point-out id: 2"
    assert _format_page_reference(-1, 7) == "Page: unnumbered, point-out id: 7"


def test_transcription_page_is_the_printed_number_not_a_point_out_id():
    """A transcription segment's page_number is the printed number and is rendered as such.

    Ingestion stores the slide number read off the video frame there — the number printed on the
    slide, not its index in the deck. It is worth naming to the student, so it appears as "Page: N",
    but offering it as a point-out id would navigate to whichever slide sits at that index instead.
    """
    transcription_section = _retrieval_tool(_transcription())().split(
        "Lecture transcription content:"
    )[1]

    assert "Page: 3, Video timestamp: 42s" in transcription_section
    assert "point-out id" not in transcription_section


@pytest.mark.parametrize(
    "start_time, end_time, expected",
    [
        # Rounding to nearest would display 42, which is before this segment even starts — and
        # since segments are adjacent, that timestamp points into the preceding one.
        (42.4, 52.0, "43"),
        # Too short for the next whole second, so the exact start is kept instead.
        (42.4, 42.8, "42.4"),
    ],
)
def test_video_timestamp_never_falls_before_its_own_segment(
    start_time, end_time, expected
):
    assert _format_video_timestamp(start_time, end_time) == expected


def test_a_fractional_segment_start_can_still_be_pointed_out():
    """End to end: the agent copies the displayed timestamp and the student's view moves.

    Rounding a fractional start down used to render a timestamp that fell outside its own segment,
    so the point-out tool rejected it and the segment could never be shown.
    """
    transcription = _transcription(start_time=42.4, end_time=52.0)
    storage = {}
    results = _retrieval_tool(transcription, storage)()
    displayed = re.search(r"Video timestamp: ([0-9.]+)s", results)
    assert displayed, f"no video timestamp rendered in: {results}"
    timestamp = float(displayed.group(1))

    callback = _FakeCallback()
    point_out = create_tool_combined_view_point_out(
        callback=callback,
        lecture_content_storage=storage,
        combined_context=CombinedViewContextDTO(
            type="combinedView",
            slides=None,
            # Watching an earlier moment, so this is a real jump rather than a no-op.
            video=VideoContextDTO(type="video", lecture_unit_id=1, timestamp=5.0),
        ),
    )

    result = point_out(timestamp=timestamp)

    assert len(callback.commands) == 1
    assert callback.commands[0].parameters.timestamp == timestamp
    assert "does not fall within" not in result
