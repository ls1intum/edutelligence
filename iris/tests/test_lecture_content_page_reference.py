"""Tests for the page reference rendered into the lecture retrieval results.

Two numbers describe the same slide and the agent must not mix them up: the number printed on the
slide (what it may tell the student) and the slide's index in the deck (the point-out id, which the
point-out tool navigates by). Slides carrying no printed number are stored with a sentinel, which
must not leak into the results as a page number.
"""

from uuid import uuid4

import pytest

from iris.domain.retrieval.lecture.lecture_retrieval_dto import (
    LectureRetrievalDTO,
    LectureTranscriptionRetrievalDTO,
)
from iris.tools.lecture_content_retrieval import (
    _format_page_reference,
    create_tool_lecture_content_retrieval,
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
    transcription = LectureTranscriptionRetrievalDTO(
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
        segment_start_time=42.0,
        segment_end_time=52.0,
        page_number=3,
        segment_summary="summary",
        segment_text="spoken words",
        base_url="http://example.com",
    )
    tool = create_tool_lecture_content_retrieval(
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
        lecture_content_storage={},
    )

    transcription_section = tool().split("Lecture transcription content:")[1]

    assert "Page: 3, Video timestamp: 42s" in transcription_section
    assert "point-out id" not in transcription_section
