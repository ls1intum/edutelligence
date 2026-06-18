"""Tests for the lecture content the student is currently viewing.

``LectureRetrieval.fetch_context_content`` looks up the exact slide page chunks
and transcription segments referenced by the student's current position so they
can be pasted directly into the prompt, independently of the RAG lecture tool.
This content is also stored for the citation pipeline so it can be cited without
the agent calling the lecture retrieval tool.
"""

# pylint: skip-file

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from iris.domain.data.lecture_context_dto import SlidesContextDTO, VideoContextDTO
from iris.domain.retrieval.lecture.lecture_retrieval_dto import (
    LectureRetrievalDTO,
    LectureTranscriptionRetrievalDTO,
    LectureUnitPageChunkRetrievalDTO,
)
from iris.pipeline.chat.chat_pipeline import ChatPipeline
from iris.retrieval.lecture.lecture_retrieval import LectureRetrieval
from iris.tools.lecture_content_retrieval import _merge_lecture_content


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


def test_current_view_content_is_stored_for_citations():
    """Current-view content must land in the citation storage without the tool."""
    pipeline = ChatPipeline.__new__(ChatPipeline)

    page_chunk = _make_page_chunk(3, "Page 3 content")
    transcription = _make_transcription(45.0, 55.0, "Transcript 45-55")

    retriever = MagicMock()
    retriever.fetch_context_content.return_value = ([page_chunk], [transcription])

    state = SimpleNamespace(
        lecture_contexts=[
            SlidesContextDTO(type="slides", lectureUnitId=1, page=3),
            VideoContextDTO(type="video", lectureUnitId=1, timestamp=50.0),
        ],
        lecture_retriever=retriever,
        lecture_content_storage={},
        dto=SimpleNamespace(
            settings=SimpleNamespace(artemis_base_url="http://example.com"),
            course=SimpleNamespace(id=1),
        ),
    )

    content = pipeline._build_current_view_content(state)

    assert content is not None
    stored = state.lecture_content_storage["content"]
    assert stored.lecture_unit_page_chunks == [page_chunk]
    assert stored.lecture_transcriptions == [transcription]
    assert stored.lecture_unit_segments == []


def test_lecture_tool_merges_with_current_view_content():
    """Retrieval-tool results merge with stored current-view content, deduped."""
    current_page = _make_page_chunk(3, "Current page 3")
    rag_page = _make_page_chunk(7, "RAG page 7")

    existing = LectureRetrievalDTO(
        lecture_unit_segments=[],
        lecture_transcriptions=[],
        lecture_unit_page_chunks=[current_page],
    )
    # RAG returns the current page again plus a new one.
    new = LectureRetrievalDTO(
        lecture_unit_segments=[],
        lecture_transcriptions=[],
        lecture_unit_page_chunks=[current_page, rag_page],
    )

    merged = _merge_lecture_content(existing, new)

    assert merged.lecture_unit_page_chunks == [current_page, rag_page]
