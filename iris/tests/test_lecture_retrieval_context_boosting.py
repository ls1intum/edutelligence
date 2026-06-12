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

    def mock_fetch_transcriptions(_course_id, _lecture_unit_id, _timestamp, _base_url):
        return [_make_transcription(1, 45.0, 55.0, "Context 45-55")]

    pipeline._fetch_transcriptions_by_timestamp = mock_fetch_transcriptions

    result = pipeline._boost_transcriptions_by_timestamps(
        lecture_unit, context_timestamps, rag_transcriptions
    )

    # Context segment should be first, then RAG results
    assert len(result) == 3
    assert result[0].segment_start_time == 45.0
    assert result[0].segment_text == "Context 45-55"
    assert result[1].segment_start_time == 100.0


def test_boost_transcriptions_finds_timestamp_outside_first_batch():
    """Timestamp beyond Weaviate's default page must still be found via direct DB query."""
    pipeline = _make_retrieval_pipeline()
    lecture_unit = _make_lecture_unit()

    # RAG results only contain the first ~100 segments (simulated as early timestamps)
    rag_transcriptions = [
        _make_transcription(1, float(i * 10), float(i * 10 + 10), f"RAG {i}")
        for i in range(10)  # segments 0-10s … 90-100s
    ]

    # Context: student is at timestamp 1500 — well beyond the first batch
    context_timestamps = [{"lecture_unit_id": 1, "timestamp": 1500.0}]

    fetch_calls = []

    def mock_fetch_by_timestamp(_course_id, _lecture_unit_id, timestamp, _base_url):
        fetch_calls.append(timestamp)
        if 1490.0 <= timestamp < 1510.0 or timestamp == 1500.0:
            return [_make_transcription(1, 1490.0, 1510.0, "Late segment 1490-1510")]
        return []

    pipeline._fetch_transcriptions_by_timestamp = mock_fetch_by_timestamp

    result = pipeline._boost_transcriptions_by_timestamps(
        lecture_unit, context_timestamps, rag_transcriptions
    )

    # The DB query must have been called with the exact timestamp
    assert fetch_calls == [1500.0]

    # Late segment should be first, then RAG results
    assert result[0].segment_start_time == 1490.0
    assert result[0].segment_text == "Late segment 1490-1510"


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


def test_boost_page_chunks_no_fetch_when_already_in_rag():
    """When context page is already in RAG results, no database fetch should occur."""
    pipeline = _make_retrieval_pipeline()
    lecture_unit = _make_lecture_unit()

    # RAG results include page 5
    context_page_chunk = _make_page_chunk(1, 5, "Page 5 content")
    rag_chunks = [
        context_page_chunk,
        _make_page_chunk(1, 6, "RAG page 6"),
        _make_page_chunk(1, 7, "RAG page 7"),
    ]

    # Context: student is viewing page 5 (already in RAG)
    context_pages = [{"lecture_unit_id": 1, "page": 5}]

    # Mock the fetch method and track if it was called
    fetch_mock = MagicMock(return_value=[])
    pipeline._fetch_page_chunks_by_page = fetch_mock

    result = pipeline._boost_page_chunks_by_pages(
        lecture_unit, context_pages, rag_chunks
    )

    # Fetch should NOT be called since page 5 is already in RAG
    fetch_mock.assert_not_called()

    # Page 5 should be first (boosted), then other RAG results
    assert len(result) == 3
    assert result[0].page_number == 5
    assert result[0].page_text_content == "Page 5 content"
    assert result[1].page_number == 6


def test_boost_transcriptions_no_fetch_when_already_in_rag():
    """When context timestamp is already in RAG results, no database fetch should occur."""
    pipeline = _make_retrieval_pipeline()
    lecture_unit = _make_lecture_unit()

    # RAG results include segment 100-110
    context_transcription = _make_transcription(1, 100.0, 110.0, "Segment 100-110")
    rag_transcriptions = [
        context_transcription,
        _make_transcription(1, 120.0, 130.0, "RAG 120-130"),
        _make_transcription(1, 140.0, 150.0, "RAG 140-150"),
    ]

    # Context: student is at timestamp 105 (within 100-110, already in RAG)
    context_timestamps = [{"lecture_unit_id": 1, "timestamp": 105.0}]

    # Mock the fetch method and track if it was called
    fetch_mock = MagicMock(return_value=[])
    pipeline._fetch_transcriptions_by_timestamp = fetch_mock

    result = pipeline._boost_transcriptions_by_timestamps(
        lecture_unit, context_timestamps, rag_transcriptions
    )

    # Fetch should NOT be called since timestamp 105 is in RAG segment 100-110
    fetch_mock.assert_not_called()

    # Segment 100-110 should be first (boosted), then other RAG results
    assert len(result) == 3
    assert result[0].segment_start_time == 100.0
    assert result[0].segment_text == "Segment 100-110"
    assert result[1].segment_start_time == 120.0


def test_merge_context_first_exceeds_limit_for_all_unique_context():
    """When unique context items exceed limit, all context should still be included."""
    pipeline = _make_retrieval_pipeline()

    # Create 5 unique context items
    context_items = [_make_page_chunk(1, i, f"Context {i}") for i in range(1, 6)]
    rag_items = [_make_page_chunk(1, i, f"RAG {i}") for i in range(10, 20)]

    # Limit is 3, but we have 5 unique context items
    result = pipeline._merge_context_first(context_items, rag_items, limit=3)

    # Should return max(limit, unique_context_count) = max(3, 5) = 5
    # All 5 unique context items should be included (no RAG items)
    assert len(result) == 5
    for i, item in enumerate(result):
        assert item.page_text_content == f"Context {i + 1}"


def test_merge_context_first_with_duplicates_exceeding_limit():
    """When context has duplicates but unique count exceeds limit, all unique context should be included."""
    pipeline = _make_retrieval_pipeline()

    chunk_a = _make_page_chunk(1, 1, "A")
    chunk_b = _make_page_chunk(1, 2, "B")
    chunk_c = _make_page_chunk(1, 3, "C")
    chunk_d = _make_page_chunk(1, 4, "D")

    # Context has 8 items, but only 4 unique (exceeds limit of 3)
    context_items = [
        chunk_a,
        chunk_b,
        chunk_c,
        chunk_d,
        chunk_a,
        chunk_b,
        chunk_c,
        chunk_d,
    ]
    rag_items = [_make_page_chunk(1, i, f"RAG {i}") for i in range(10, 20)]

    result = pipeline._merge_context_first(context_items, rag_items, limit=3)

    # Should return max(limit, unique_context_count) = max(3, 4) = 4
    # All 4 unique context items should be included (no RAG items)
    assert len(result) == 4
    context_texts = {item.page_text_content for item in result}
    assert context_texts == {"A", "B", "C", "D"}
