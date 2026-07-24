"""Tests for the per-request lecture unit metadata cache in the sub-retrievals.

``generate_retrieval_dtos`` used to look up the same lecture unit metadata in
Weaviate once per search hit (an N+1 pattern that dominated lecture retrieval
latency). The cache must collapse identical lookups while keeping negative
results (unknown units are skipped, not retried).
"""

# pylint: skip-file

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.retrieval.lecture.lecture_unit_segment_retrieval import (  # noqa: E402
    LectureUnitSegmentRetrieval,
)
from iris.vector_database.lecture_unit_schema import LectureUnitSchema  # noqa: E402
from iris.vector_database.lecture_unit_segment_schema import (  # noqa: E402
    LectureUnitSegmentSchema,
)


def _make_retrieval() -> LectureUnitSegmentRetrieval:
    retrieval = LectureUnitSegmentRetrieval.__new__(LectureUnitSegmentRetrieval)
    retrieval._lecture_unit_cache = {}
    retrieval.lecture_unit_collection = MagicMock()
    return retrieval


def _segment_properties(course_id=1, lecture_id=2, lecture_unit_id=3):
    return {
        LectureUnitSegmentSchema.COURSE_ID.value: course_id,
        LectureUnitSegmentSchema.LECTURE_ID.value: lecture_id,
        LectureUnitSegmentSchema.LECTURE_UNIT_ID.value: lecture_unit_id,
        LectureUnitSegmentSchema.PAGE_NUMBER.value: 4,
        LectureUnitSegmentSchema.SEGMENT_SUMMARY.value: "summary",
        LectureUnitSegmentSchema.BASE_URL.value: "http://example.com",
    }


def _unit_fetch_result():
    unit_properties = {
        LectureUnitSchema.COURSE_ID.value: 1,
        LectureUnitSchema.COURSE_NAME.value: "Course",
        LectureUnitSchema.COURSE_DESCRIPTION.value: "Description",
        LectureUnitSchema.LECTURE_ID.value: 2,
        LectureUnitSchema.LECTURE_NAME.value: "Lecture",
        LectureUnitSchema.LECTURE_UNIT_ID.value: 3,
        LectureUnitSchema.LECTURE_UNIT_NAME.value: "Unit",
        LectureUnitSchema.LECTURE_UNIT_LINK.value: "http://example.com/unit",
        LectureUnitSchema.VIDEO_LINK.value: None,
    }
    return SimpleNamespace(
        objects=[SimpleNamespace(properties=unit_properties, uuid=uuid4())]
    )


def test_repeated_hits_from_same_unit_fetch_metadata_once():
    retrieval = _make_retrieval()
    retrieval.lecture_unit_collection.query.fetch_objects.return_value = (
        _unit_fetch_result()
    )

    first = retrieval.generate_retrieval_dtos(_segment_properties(), str(uuid4()))
    second = retrieval.generate_retrieval_dtos(_segment_properties(), str(uuid4()))

    assert retrieval.lecture_unit_collection.query.fetch_objects.call_count == 1
    assert first is not None and second is not None
    assert first.lecture_unit_name == second.lecture_unit_name == "Unit"


def test_different_units_fetch_metadata_separately():
    retrieval = _make_retrieval()
    retrieval.lecture_unit_collection.query.fetch_objects.return_value = (
        _unit_fetch_result()
    )

    retrieval.generate_retrieval_dtos(_segment_properties(), str(uuid4()))
    retrieval.generate_retrieval_dtos(
        _segment_properties(lecture_unit_id=99), str(uuid4())
    )

    assert retrieval.lecture_unit_collection.query.fetch_objects.call_count == 2


def test_missing_unit_is_cached_as_negative_result():
    retrieval = _make_retrieval()
    retrieval.lecture_unit_collection.query.fetch_objects.return_value = (
        SimpleNamespace(objects=[])
    )

    first = retrieval.generate_retrieval_dtos(_segment_properties(), str(uuid4()))
    second = retrieval.generate_retrieval_dtos(_segment_properties(), str(uuid4()))

    assert first is None and second is None
    assert retrieval.lecture_unit_collection.query.fetch_objects.call_count == 1
