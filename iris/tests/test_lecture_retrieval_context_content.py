"""Tests for fetching the lecture content the student is currently viewing.

``LectureRetrieval.fetch_context_content`` looks up the exact slide page chunks
and transcription segments referenced by the student's current position so they
can be pasted directly into the prompt, independently of the RAG lecture tool.
"""

# pylint: skip-file

from unittest.mock import MagicMock
from uuid import uuid4

from iris.domain.retrieval.lecture.lecture_retrieval_dto import (
    LectureTranscriptionRetrievalDTO,
    LectureUnitPageChunkRetrievalDTO,
)
from iris.retrieval.lecture.lecture_retrieval import LectureRetrieval


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
        lecture_unit_link="http://example.com",
        course_language="en",
        page_number=page_number,
        display_page_number=page_number,
        page_text_content=text,
        base_url="http://example.com",
    )


def _make_transcription(
    start_time: float, end_time: float, text: str
) -> LectureTranscriptionRetrievalDTO:
    return LectureTranscriptionRetrievalDTO(
        uuid=str(uuid4()),
        course_id=1,
        course_name="Test Course",
        course_description="Test Description",
        lecture_id=1,
        lecture_name="Test Lecture",
        lecture_unit_id=1,
        lecture_unit_name="Test Unit",
        video_link="http://example.com/video",
        language="en",
        segment_start_time=start_time,
        segment_end_time=end_time,
        page_number=1,
        segment_summary="summary",
        segment_text=text,
        base_url="http://example.com",
    )


def _make_retrieval_pipeline() -> LectureRetrieval:
    """Create a LectureRetrieval instance without running its heavy __init__."""
    pipeline = LectureRetrieval.__new__(LectureRetrieval)
    pipeline._fetch_page_chunks_by_page = MagicMock(return_value=[])
    pipeline._fetch_transcriptions_by_timestamp = MagicMock(return_value=[])
    return pipeline


def test_fetch_context_content_returns_current_slide_and_transcript():
    pipeline = _make_retrieval_pipeline()
    pipeline._fetch_page_chunks_by_page.return_value = [
        _make_page_chunk(3, "Page 3 content")
    ]
    pipeline._fetch_transcriptions_by_timestamp.return_value = [
        _make_transcription(45.0, 55.0, "Transcript 45-55")
    ]

    page_chunks, transcriptions = pipeline.fetch_context_content(
        course_id=1,
        base_url="http://example.com",
        context_pages=[{"lecture_unit_id": 1, "page": 3}],
        context_timestamps=[{"lecture_unit_id": 1, "timestamp": 50.0}],
    )

    assert [c.page_text_content for c in page_chunks] == ["Page 3 content"]
    assert [t.segment_text for t in transcriptions] == ["Transcript 45-55"]
