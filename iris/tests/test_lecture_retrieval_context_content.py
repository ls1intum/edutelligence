"""Tests for the lecture content the student is currently viewing.

``LectureRetrieval.fetch_context_content`` looks up the exact slide page chunks
and transcription segments referenced by the student's current position so they
can be pasted directly into the prompt, independently of the RAG lecture tool.
This content also gets source ids, so it can be cited without the agent calling
the lecture retrieval tool.
"""

# pylint: skip-file

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from iris.domain.data.lecture_context_dto import SlidesContextDTO, VideoContextDTO
from iris.domain.retrieval.lecture.lecture_retrieval_dto import (
    LectureTranscriptionRetrievalDTO,
    LectureUnitPageChunkRetrievalDTO,
)
from iris.pipeline.chat.chat_pipeline import ChatPipeline
from iris.pipeline.shared.citation_sources import CitationSourceRegistry
from iris.retrieval.lecture.lecture_retrieval import LectureRetrieval
from iris.tools.current_view_content import CONTENT_BLOCKS_KEY


def _make_page_chunk(
    page_number: int, text: str, display_page_number: int | None = None
) -> LectureUnitPageChunkRetrievalDTO:
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
        display_page_number=(
            page_number if display_page_number is None else display_page_number
        ),
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
    pipeline._is_lecture_unit_released = MagicMock(return_value=True)
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


def test_fetch_context_content_suppresses_unreleased_unit():
    pipeline = _make_retrieval_pipeline()
    pipeline._is_lecture_unit_released.return_value = False
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

    assert page_chunks == []
    assert transcriptions == []
    pipeline._fetch_page_chunks_by_page.assert_not_called()
    pipeline._fetch_transcriptions_by_timestamp.assert_not_called()


def test_current_view_content_gets_source_ids():
    """Current-view content must be citable without the lecture retrieval tool."""
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
        current_view_storage={},
        citation_sources=CitationSourceRegistry(),
        dto=SimpleNamespace(
            settings=SimpleNamespace(artemis_base_url="http://example.com"),
            course=SimpleNamespace(id=1),
        ),
    )

    blocks = pipeline._build_current_view(state)

    # The prompt gets the position only. Spelling the material out there makes the prompt end
    # on something that reads like a finished answer, and the agent stops calling tools.
    assert blocks == [
        "The student is currently viewing page 3 of the lecture slides of the "
        "lecture unit Test Unit (lecture unit ID: 1).",
        "The student is currently at 50.0 seconds in the lecture video of the "
        "lecture unit Test Unit (lecture unit ID: 1).",
    ]
    # The material stays reachable, but through the current-position tool.
    assert state.current_view_storage[CONTENT_BLOCKS_KEY] == [
        "The student is currently viewing page 3 of the lecture slides of the "
        "lecture unit Test Unit (lecture unit ID: 1). The content of this slide:"
        "\n---\nSource id: [src:1]\nPage 3 content\n---",
        "The student is currently at 50.0 seconds in the lecture video of the "
        "lecture unit Test Unit (lecture unit ID: 1). The transcript at this "
        "point:\n---\nSource id: [src:2]\nTranscript 45-55\n---",
    ]
    slide = state.citation_sources.get(1)
    assert slide.cite_block() == "[cite:L:1:3::::]"
    assert slide.content == "Page 3 content"
    segment = state.citation_sources.get(2)
    assert segment.cite_block() == "[cite:L:1::45:55::]"
    assert segment.content == "Transcript 45-55"


def test_multiple_chunks_on_same_page_share_one_block():
    """Chunks of the same slide page are bundled into a single position block."""
    pipeline = ChatPipeline.__new__(ChatPipeline)

    retriever = MagicMock()
    retriever.fetch_context_content.return_value = (
        [_make_page_chunk(2, "First half"), _make_page_chunk(2, "Second half")],
        [],
    )

    state = SimpleNamespace(
        lecture_contexts=[SlidesContextDTO(type="slides", lectureUnitId=1, page=2)],
        lecture_retriever=retriever,
        lecture_content_storage={},
        current_view_storage={},
        dto=SimpleNamespace(
            settings=SimpleNamespace(artemis_base_url="http://example.com"),
            course=SimpleNamespace(id=1),
        ),
    )

    blocks = pipeline._build_current_view(state)

    # One position in the prompt, and both chunks of page 2 bundled under that one position in
    # what the current-position tool reads out.
    assert blocks == [
        "The student is currently viewing page 2 of the lecture slides of the "
        "lecture unit Test Unit (lecture unit ID: 1)."
    ]
    assert state.current_view_storage[CONTENT_BLOCKS_KEY] == [
        "The student is currently viewing page 2 of the lecture slides of the "
        "lecture unit Test Unit (lecture unit ID: 1). The content of this slide:"
        "\n---\nFirst half\nSecond half\n---"
    ]


def test_current_position_is_labelled_with_the_printed_page_number():
    """A deck whose printed numbering is shifted must be described by what the student reads.

    The technical page index (5, used to look the chunk up) stays internal; the slide itself says
    3, and that is the number the agent may repeat in its answer.
    """
    pipeline = ChatPipeline.__new__(ChatPipeline)

    retriever = MagicMock()
    retriever.fetch_context_content.return_value = (
        [_make_page_chunk(5, "Shifted deck", display_page_number=3)],
        [],
    )

    state = SimpleNamespace(
        lecture_contexts=[SlidesContextDTO(type="slides", lectureUnitId=1, page=5)],
        lecture_retriever=retriever,
        lecture_content_storage={},
        current_view_storage={},
        dto=SimpleNamespace(
            settings=SimpleNamespace(artemis_base_url="http://example.com"),
            course=SimpleNamespace(id=1),
        ),
    )

    blocks = pipeline._build_current_view(state)

    assert blocks == [
        "The student is currently viewing page 3 of the lecture slides of the "
        "lecture unit Test Unit (lecture unit ID: 1)."
    ]
    # The technical index must not leak into the prompt: the agent would quote it as the page.
    assert "page 5" not in blocks[0]
    # The lookup itself still runs off the technical index.
    assert retriever.fetch_context_content.call_args.kwargs["context_pages"] == [
        {"lecture_unit_id": 1, "page": 5}
    ]


@pytest.mark.parametrize("unnumbered", [-1, 0])
def test_current_position_names_no_page_for_an_unnumbered_slide(unnumbered):
    """Ingestion marks an unreadable slide number as -1 (older records as 0).

    Neither is a number the student can read off the slide, so the position is described without
    one rather than by the technical index.
    """
    pipeline = ChatPipeline.__new__(ChatPipeline)

    retriever = MagicMock()
    retriever.fetch_context_content.return_value = (
        [_make_page_chunk(5, "Cover slide", display_page_number=unnumbered)],
        [],
    )

    state = SimpleNamespace(
        lecture_contexts=[SlidesContextDTO(type="slides", lectureUnitId=1, page=5)],
        lecture_retriever=retriever,
        lecture_content_storage={},
        current_view_storage={},
        dto=SimpleNamespace(
            settings=SimpleNamespace(artemis_base_url="http://example.com"),
            course=SimpleNamespace(id=1),
        ),
    )

    blocks = pipeline._build_current_view(state)

    assert blocks == [
        "The student is currently viewing an unnumbered page of the lecture slides "
        "of the lecture unit Test Unit (lecture unit ID: 1)."
    ]


def test_position_omitted_when_material_not_ingested():
    """A viewed unit that is not in the vector DB is not described at all."""
    pipeline = ChatPipeline.__new__(ChatPipeline)

    retriever = MagicMock()
    retriever.fetch_context_content.return_value = ([], [])

    state = SimpleNamespace(
        lecture_contexts=[
            SlidesContextDTO(type="slides", lectureUnitId=42, page=7),
        ],
        lecture_retriever=retriever,
        lecture_content_storage={},
        current_view_storage={},
        dto=SimpleNamespace(
            settings=SimpleNamespace(artemis_base_url="http://example.com"),
            course=SimpleNamespace(id=1),
        ),
    )

    blocks = pipeline._build_current_view(state)

    # Without ingested content there is no position to describe.
    assert blocks == []


def test_only_ingested_positions_are_described():
    """A viewed page with content is described; a sibling page without is not."""
    pipeline = ChatPipeline.__new__(ChatPipeline)

    # Only page 3 of unit 1 is ingested; page 5 returns nothing.
    retriever = MagicMock()
    retriever.fetch_context_content.return_value = (
        [_make_page_chunk(3, "Page 3 content")],
        [],
    )

    state = SimpleNamespace(
        lecture_contexts=[
            SlidesContextDTO(type="slides", lectureUnitId=1, page=3),
            SlidesContextDTO(type="slides", lectureUnitId=1, page=5),
        ],
        lecture_retriever=retriever,
        lecture_content_storage={},
        current_view_storage={},
        dto=SimpleNamespace(
            settings=SimpleNamespace(artemis_base_url="http://example.com"),
            course=SimpleNamespace(id=1),
        ),
    )

    blocks = pipeline._build_current_view(state)

    assert blocks == [
        "The student is currently viewing page 3 of the lecture slides of the "
        "lecture unit Test Unit (lecture unit ID: 1)."
    ]
    assert state.current_view_storage[CONTENT_BLOCKS_KEY] == [
        "The student is currently viewing page 3 of the lecture slides of the "
        "lecture unit Test Unit (lecture unit ID: 1). The content of this slide:"
        "\n---\nPage 3 content\n---",
    ]
