"""Tests for LectureUnitSegmentSummaryPipeline._get_slides and _get_transcriptions:
a ghost row (scan-visible but object-store-missing) sitting alongside a real one
for the same slide must not be concatenated into the regenerated summary."""

# pylint: disable=protected-access

from types import SimpleNamespace
from unittest.mock import MagicMock

from iris.pipeline.lecture_unit_segment_summary_pipeline import (
    LectureUnitSegmentSummaryPipeline,
)


def _row(uuid: str, text: str) -> SimpleNamespace:
    return SimpleNamespace(uuid=uuid, properties={"page_text_content": text})


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


def test_get_slides_excludes_a_ghost_sibling_of_a_real_row():
    rows = [_row("real", "actual slide text"), _row("ghost", "stale slide text")]
    pipeline = _pipeline(_collection(rows, ghost_uuids={"ghost"}), _collection([]))

    slides = pipeline._get_slides(1)

    assert [row.uuid for row in slides] == ["real"]


def test_get_slides_returns_empty_when_only_a_ghost_exists():
    rows = [_row("ghost", "stale slide text")]
    pipeline = _pipeline(_collection(rows, ghost_uuids={"ghost"}), _collection([]))

    assert not pipeline._get_slides(1)


def test_get_transcriptions_excludes_a_ghost_sibling_of_a_real_row():
    rows = [
        _row("real", "actual transcript text"),
        _row("ghost", "stale transcript text"),
    ]
    pipeline = _pipeline(_collection([]), _collection(rows, ghost_uuids={"ghost"}))

    transcriptions = pipeline._get_transcriptions(1)

    assert [row.uuid for row in transcriptions] == ["real"]
