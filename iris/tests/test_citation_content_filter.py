"""Tests for relevance-gating lecture content before the citation pipeline."""

# pylint: skip-file

from uuid import uuid4

from iris.domain.retrieval.lecture.lecture_retrieval_dto import (
    LectureRetrievalDTO,
    LectureTranscriptionRetrievalDTO,
    LectureUnitPageChunkRetrievalDTO,
    LectureUnitSegmentRetrievalDTO,
)
from iris.pipeline.chat.chat_pipeline import _filter_lecture_content_by_score


def _chunk(page, score):
    return LectureUnitPageChunkRetrievalDTO(
        uuid=str(uuid4()),
        course_id=1,
        course_name="C",
        course_description="D",
        lecture_id=1,
        lecture_name="L",
        lecture_unit_id=1,
        lecture_unit_name="U",
        lecture_unit_link="x",
        course_language="en",
        page_number=page,
        display_page_number=page,
        page_text_content="text",
        base_url="b",
        rerank_score=score,
    )


def _transcription(score):
    return LectureTranscriptionRetrievalDTO(
        uuid=str(uuid4()),
        course_id=1,
        course_name="C",
        course_description="D",
        lecture_id=1,
        lecture_name="L",
        lecture_unit_id=1,
        lecture_unit_name="U",
        video_link="v",
        language="en",
        segment_start_time=0.0,
        segment_end_time=1.0,
        page_number=1,
        segment_summary="s",
        segment_text="t",
        base_url="b",
        rerank_score=score,
    )


def _segment():
    return LectureUnitSegmentRetrievalDTO(
        uuid=str(uuid4()),
        course_id=1,
        course_name="C",
        course_description="D",
        lecture_id=1,
        lecture_name="L",
        lecture_unit_id=1,
        lecture_unit_name="U",
        lecture_unit_link="x",
        video_link="v",
        page_number=1,
        display_page_number=1,
        segment_summary="s",
        base_url="b",
    )


def test_filter_keeps_only_scores_at_or_above_threshold():
    content = LectureRetrievalDTO(
        lecture_unit_segments=[_segment()],
        lecture_transcriptions=[_transcription(0.4), _transcription(0.1)],
        lecture_unit_page_chunks=[_chunk(1, 0.5), _chunk(2, 0.2), _chunk(3, None)],
    )

    filtered = _filter_lecture_content_by_score(content, 0.3)

    assert [c.display_page_number for c in filtered.lecture_unit_page_chunks] == [1]
    assert [t.rerank_score for t in filtered.lecture_transcriptions] == [0.4]
    # Segments are never cited, so they pass through untouched.
    assert len(filtered.lecture_unit_segments) == 1


def test_filter_drops_unscored_items():
    content = LectureRetrievalDTO(
        lecture_unit_segments=[],
        lecture_transcriptions=[],
        lecture_unit_page_chunks=[_chunk(1, None), _chunk(2, None)],
    )

    filtered = _filter_lecture_content_by_score(content, 0.15)

    assert filtered.lecture_unit_page_chunks == []


def test_filter_none_returns_none():
    assert _filter_lecture_content_by_score(None, 0.15) is None
