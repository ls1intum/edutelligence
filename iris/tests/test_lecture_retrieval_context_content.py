"""Tests for fetching the lecture content the student is currently viewing.

These tests verify that ``LectureRetrieval.fetch_context_content`` looks up the
exact slide page chunks and transcription segments referenced by the student's
current position so they can be pasted directly into the prompt. This is fully
independent of the RAG lecture retrieval tool.
"""

# pylint: skip-file

from unittest.mock import MagicMock
from uuid import uuid4

from iris.domain.retrieval.lecture.lecture_retrieval_dto import (
    LectureTranscriptionRetrievalDTO,
    LectureUnitPageChunkRetrievalDTO,
)
from iris.retrieval.lecture.lecture_retrieval import LectureRetrieval


def _make_page_chunk(
    lecture_unit_id: int, page_number: int, text: str = "test"
) -> LectureUnitPageChunkRetrievalDTO:
    """Create a test page chunk DTO."""
    return LectureUnitPageChunkRetrievalDTO(
        uuid=str(uuid4()),
        course_id=1,
        course_name="Test Course",
        course_description="Test Description",
        lecture_id=1,
        lecture_name="Test Lecture",
        lecture_unit_id=lecture_unit_id,
        lecture_unit_name="Test Unit",
        lecture_unit_link="http://example.com",
        course_language="en",
        page_number=page_number,
        display_page_number=page_number,
        page_text_content=text,
        base_url="http://example.com",
    )


def _make_transcription(
    lecture_unit_id: int, start_time: float, end_time: float, text: str = "test"
) -> LectureTranscriptionRetrievalDTO:
    """Create a test transcription DTO."""
    return LectureTranscriptionRetrievalDTO(
        uuid=str(uuid4()),
        course_id=1,
        course_name="Test Course",
        course_description="Test Description",
        lecture_id=1,
        lecture_name="Test Lecture",
        lecture_unit_id=lecture_unit_id,
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
    """Create a LectureRetrieval instance with mocked dependencies."""
    pipeline = LectureRetrieval.__new__(LectureRetrieval)
    pipeline.implementation_id = "lecture_retrieval_pipeline"
    pipeline.tokens = []
    pipeline.lecture_unit_page_chunk_collection = MagicMock()
    pipeline.lecture_transcription_collection = MagicMock()
    pipeline.lecture_unit_page_chunk_pipeline = MagicMock()
    pipeline.lecture_transcription_pipeline = MagicMock()
    return pipeline


def test_fetch_context_content_returns_page_and_transcription():
    """The current slide page and video segment should both be fetched."""
    pipeline = _make_retrieval_pipeline()

    def mock_fetch_page_chunks(_course_id, _lecture_unit_id, page, _base_url):
        return [_make_page_chunk(1, page, f"Page {page} content")]

    def mock_fetch_transcriptions(_course_id, _lecture_unit_id, timestamp, _base_url):
        return [_make_transcription(1, 45.0, 55.0, "Transcript 45-55")]

    pipeline._fetch_page_chunks_by_page = mock_fetch_page_chunks
    pipeline._fetch_transcriptions_by_timestamp = mock_fetch_transcriptions

    page_chunks, transcriptions = pipeline.fetch_context_content(
        course_id=1,
        base_url="http://example.com",
        context_pages=[{"lecture_unit_id": 1, "page": 3}],
        context_timestamps=[{"lecture_unit_id": 1, "timestamp": 50.0}],
    )

    assert len(page_chunks) == 1
    assert page_chunks[0].page_number == 3
    assert page_chunks[0].page_text_content == "Page 3 content"

    assert len(transcriptions) == 1
    assert transcriptions[0].segment_start_time == 45.0
    assert transcriptions[0].segment_text == "Transcript 45-55"


def test_fetch_context_content_deduplicates_by_uuid():
    """Duplicate chunks returned for different positions are de-duplicated."""
    pipeline = _make_retrieval_pipeline()

    shared_chunk = _make_page_chunk(1, 3, "Shared page 3")

    pipeline._fetch_page_chunks_by_page = MagicMock(return_value=[shared_chunk])
    pipeline._fetch_transcriptions_by_timestamp = MagicMock(return_value=[])

    page_chunks, transcriptions = pipeline.fetch_context_content(
        course_id=1,
        base_url="http://example.com",
        context_pages=[
            {"lecture_unit_id": 1, "page": 3},
            {"lecture_unit_id": 1, "page": 3},
        ],
    )

    assert len(page_chunks) == 1
    assert transcriptions == []


def test_fetch_context_content_skips_incomplete_positions():
    """Positions missing a page/timestamp are ignored without fetching."""
    pipeline = _make_retrieval_pipeline()

    page_fetch = MagicMock(return_value=[])
    transcription_fetch = MagicMock(return_value=[])
    pipeline._fetch_page_chunks_by_page = page_fetch
    pipeline._fetch_transcriptions_by_timestamp = transcription_fetch

    page_chunks, transcriptions = pipeline.fetch_context_content(
        course_id=1,
        base_url="http://example.com",
        context_pages=[{"lecture_unit_id": 1}],
        context_timestamps=[{"lecture_unit_id": 1}],
    )

    page_fetch.assert_not_called()
    transcription_fetch.assert_not_called()
    assert page_chunks == []
    assert transcriptions == []


def test_fetch_context_content_empty_when_no_positions():
    """No contexts means nothing is fetched."""
    pipeline = _make_retrieval_pipeline()

    page_chunks, transcriptions = pipeline.fetch_context_content(
        course_id=1,
        base_url="http://example.com",
    )

    assert page_chunks == []
    assert transcriptions == []
