"""Tests for LectureUnitSegmentSummaryPipeline._get_slide_range's empty-content case."""

# pylint: disable=protected-access

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from iris.common.ingestion_errors import (
    NO_INGESTIBLE_CONTENT,
    IngestionStageError,
)
from iris.pipeline.lecture_unit_segment_summary_pipeline import (
    LectureUnitSegmentSummaryPipeline,
)


def _empty_span_collection() -> SimpleNamespace:
    return SimpleNamespace(
        aggregate=SimpleNamespace(
            over_all=MagicMock(return_value=SimpleNamespace(total_count=0))
        )
    )


def _span_collection(minimum: int, maximum: int) -> SimpleNamespace:
    metric = SimpleNamespace(minimum=minimum, maximum=maximum)
    return SimpleNamespace(
        aggregate=SimpleNamespace(
            over_all=MagicMock(
                return_value=SimpleNamespace(
                    total_count=1, properties={"page_number": metric}
                )
            )
        )
    )


def _pipeline(page_chunks, transcriptions) -> LectureUnitSegmentSummaryPipeline:
    pipeline = object.__new__(LectureUnitSegmentSummaryPipeline)
    pipeline.lecture_unit_dto = SimpleNamespace(
        lecture_unit_id=3,
        course_id=1,
        lecture_id=2,
        base_url="https://artemis.example",
    )
    pipeline.lecture_unit_page_chunk_collection = page_chunks
    pipeline.lecture_transcription_collection = transcriptions
    return pipeline


def test_raises_when_neither_page_chunks_nor_transcript_rows_exist():
    pipeline = _pipeline(_empty_span_collection(), _empty_span_collection())

    with pytest.raises(IngestionStageError) as exc_info:
        pipeline._get_slide_range()

    assert exc_info.value.error_code == NO_INGESTIBLE_CONTENT
    assert "no content to summarize" in str(exc_info.value)


def test_uses_the_pdf_span_when_page_chunks_exist():
    pipeline = _pipeline(_span_collection(1, 6), _empty_span_collection())

    assert pipeline._get_slide_range() == (1, 6)


def test_falls_back_to_the_transcript_span_without_a_pdf():
    pipeline = _pipeline(_empty_span_collection(), _span_collection(1, 4))

    assert pipeline._get_slide_range() == (1, 4)
