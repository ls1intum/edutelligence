"""Tests for lecture retrieval context boosting logic.

These tests verify that context-aware boosting correctly places items from
the student's current position (pages, timestamps) at the top of results.
"""

# pylint: skip-file

from unittest.mock import MagicMock
from uuid import uuid4

from iris.domain.retrieval.lecture.lecture_retrieval_dto import (
    LectureTranscriptionRetrievalDTO,
    LectureUnitPageChunkRetrievalDTO,
    LectureUnitRetrievalDTO,
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


def _make_lecture_unit() -> LectureUnitRetrievalDTO:
    """Create a test lecture unit DTO."""
    return LectureUnitRetrievalDTO(
        uuid=str(uuid4()),
        course_id=1,
        course_name="Test Course",
        course_description="Test Description",
        course_language="en",
        lecture_id=1,
        lecture_name="Test Lecture",
        lecture_unit_id=1,
        lecture_unit_name="Test Unit",
        lecture_unit_link="http://example.com",
        video_link="http://example.com/video",
        base_url="http://example.com",
        lecture_unit_summary="Test summary",
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


def test_boost_page_chunks_places_context_first():
    """Context pages should appear before RAG results."""
    pipeline = _make_retrieval_pipeline()
    lecture_unit = _make_lecture_unit()

    # RAG results: pages 5, 6
    rag_chunks = [
        _make_page_chunk(1, 5, "RAG page 5"),
        _make_page_chunk(1, 6, "RAG page 6"),
    ]

    # Context: student is viewing page 3 (NOT in RAG results)
    context_pages = [{"lecture_unit_id": 1, "page": 3}]

    def mock_fetch_page_chunks(_course_id, _lecture_unit_id, page, _base_url):
        if page == 3:
            return [_make_page_chunk(1, 3, "Context page 3")]
        return []

    pipeline._fetch_page_chunks_by_page = mock_fetch_page_chunks

    result = pipeline._boost_page_chunks_by_pages(
        lecture_unit, context_pages, rag_chunks
    )

    # Context page should be first, then RAG results
    assert len(result) == 3
    assert result[0].page_number == 3
    assert result[0].page_text_content == "Context page 3"
    assert result[1].page_number == 5


def test_boost_transcriptions_places_context_first():
    """Context transcriptions should appear before RAG results."""
    pipeline = _make_retrieval_pipeline()
    lecture_unit = _make_lecture_unit()

    # RAG results: segments at 100-110, 120-130
    rag_transcriptions = [
        _make_transcription(1, 100.0, 110.0, "RAG 100-110"),
        _make_transcription(1, 120.0, 130.0, "RAG 120-130"),
    ]

    # Context: student is at timestamp 50 (NOT in RAG)
    context_timestamps = [{"lecture_unit_id": 1, "timestamp": 50}]

    def mock_fetch_transcriptions(_course_id, _lecture_unit_id, _base_url):
        return [_make_transcription(1, 45.0, 55.0, "Context 45-55")]

    pipeline._fetch_transcriptions_by_lecture_unit = mock_fetch_transcriptions

    result = pipeline._boost_transcriptions_by_timestamps(
        lecture_unit, context_timestamps, rag_transcriptions
    )

    # Context segment should be first, then RAG results
    assert len(result) == 3
    assert result[0].segment_start_time == 45.0
    assert result[0].segment_text == "Context 45-55"
    assert result[1].segment_start_time == 100.0


def test_merge_context_first_handles_duplicates_correctly():
    """unique_context_count should count unique UUIDs to ensure all context items are included."""
    pipeline = _make_retrieval_pipeline()

    chunk_a = _make_page_chunk(1, 1, "A")
    chunk_b = _make_page_chunk(1, 2, "B")

    # Context has duplicates (4 items, but only 2 unique)
    context_items = [chunk_a, chunk_b, chunk_a, chunk_b]
    rag_items = [_make_page_chunk(1, i, f"RAG {i}") for i in range(10, 20)]

    result = pipeline._merge_context_first(context_items, rag_items, limit=5)

    # Should have 2 unique context + 3 RAG = 5 total (respecting limit)
    assert len(result) == 5
    # First two should be unique context items
    assert result[0].page_text_content in ["A", "B"]
    assert result[1].page_text_content in ["A", "B"]
    # Rest should be RAG
    assert result[2].page_text_content == "RAG 10"
