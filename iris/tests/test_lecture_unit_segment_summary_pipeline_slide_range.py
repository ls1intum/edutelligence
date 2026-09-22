"""Tests for LectureUnitSegmentSummaryPipeline._get_slide_range: the empty-content
case, and that a ghost row (scan-visible but object-store-missing) does not expand
the range."""

# pylint: disable=protected-access

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from iris.common.ingestion_errors import (
    NO_INGESTIBLE_CONTENT,
    PAGE_RANGE_FETCH_CAPPED,
    IngestionStageError,
)
from iris.config import settings
from iris.pipeline.lecture_unit_segment_summary_pipeline import (
    LectureUnitSegmentSummaryPipeline,
)


def _row(uuid: str, page_number: int) -> SimpleNamespace:
    return SimpleNamespace(uuid=uuid, properties={"page_number": page_number})


def _collection(rows: list, ghost_uuids: set = frozenset()) -> SimpleNamespace:
    def confirm_by_id(object_uuid):
        return None if object_uuid in ghost_uuids else SimpleNamespace()

    return SimpleNamespace(
        query=SimpleNamespace(
            fetch_objects=MagicMock(return_value=SimpleNamespace(objects=rows)),
            fetch_object_by_id=MagicMock(side_effect=confirm_by_id),
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
    pipeline = _pipeline(_collection([]), _collection([]))

    with pytest.raises(IngestionStageError) as exc_info:
        pipeline._get_slide_range()

    assert exc_info.value.error_code == NO_INGESTIBLE_CONTENT
    assert "no content to summarize" in str(exc_info.value)


def test_uses_the_pdf_span_when_page_chunks_exist():
    rows = [_row("a", 1), _row("b", 6)]
    pipeline = _pipeline(_collection(rows), _collection([]))

    assert pipeline._get_slide_range() == (1, 6)


def test_falls_back_to_the_transcript_span_without_a_pdf():
    rows = [_row("a", 1), _row("b", 4)]
    pipeline = _pipeline(_collection([]), _collection(rows))

    assert pipeline._get_slide_range() == (1, 4)


def test_a_ghost_row_does_not_expand_the_range():
    # A scan-visible-but-object-store-missing row on page 99 must not widen the
    # range: the confirmed rows top out at page 6, so the ghost's 99 is excluded.
    rows = [_row("a", 1), _row("b", 6), _row("ghost", 99)]
    pipeline = _pipeline(_collection(rows, ghost_uuids={"ghost"}), _collection([]))

    assert pipeline._get_slide_range() == (1, 6)


def test_all_ghost_rows_falls_back_like_no_rows_at_all():
    rows = [_row("ghost", 1), _row("ghost2", 6)]
    pipeline = _pipeline(
        _collection(rows, ghost_uuids={"ghost", "ghost2"}), _collection([])
    )

    with pytest.raises(IngestionStageError) as exc_info:
        pipeline._get_slide_range()

    assert exc_info.value.error_code == NO_INGESTIBLE_CONTENT


def test_a_capped_fetch_raises_instead_of_trusting_a_truncated_span():
    # The fetch limit counts rows, not pages: if the scan comes back with at least
    # as many rows as the cap, the true min/max could be in the untruncated
    # remainder, so this must fail loudly rather than derive a span from it.
    rows = [_row("a", 1), _row("b", 6)]
    pipeline = _pipeline(_collection(rows), _collection([]))

    with patch.object(settings.lecture_ingestion, "skip_check_fetch_limit", 2):
        with pytest.raises(IngestionStageError) as exc_info:
            pipeline._get_slide_range()

    assert exc_info.value.error_code == PAGE_RANGE_FETCH_CAPPED
