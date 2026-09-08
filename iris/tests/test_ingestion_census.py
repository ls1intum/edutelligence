"""Tests for the per-course ingestion census and fingerprint stamping."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.domain.lecture.lecture_unit_dto import LectureUnitDTO
from iris.pipeline.lecture_unit_pipeline import LectureUnitPipeline
from iris.vector_database.lecture_unit_schema import LectureUnitSchema
from iris.web.routers.ingestion_census import get_course_ingestion_census


def _aggregate_group(unit_id: int, total_count: int, **metrics) -> SimpleNamespace:
    properties = {
        name: SimpleNamespace(minimum=bounds[0], maximum=bounds[1])
        for name, bounds in metrics.items()
    }
    return SimpleNamespace(
        grouped_by=SimpleNamespace(value=str(unit_id)),
        total_count=total_count,
        properties=properties,
    )


def _aggregating_collection(groups: list) -> SimpleNamespace:
    return SimpleNamespace(
        aggregate=SimpleNamespace(
            over_all=MagicMock(return_value=SimpleNamespace(groups=groups))
        )
    )


def test_census_merges_all_collections_and_reports_orphans():
    unit_row = SimpleNamespace(
        properties={
            LectureUnitSchema.LECTURE_ID.value: 2,
            LectureUnitSchema.LECTURE_UNIT_ID.value: 3,
            LectureUnitSchema.CONTENT_FINGERPRINT.value: "v1:abc",
        }
    )
    db = SimpleNamespace(
        lecture_units=SimpleNamespace(
            query=SimpleNamespace(
                fetch_objects=MagicMock(
                    return_value=SimpleNamespace(objects=[unit_row])
                )
            )
        ),
        lectures=_aggregating_collection(
            [
                _aggregate_group(3, 12, page_number=(1, 4), attachment_version=(2, 2)),
                # Unit 9 has chunks but no unit row: an orphan that must
                # still appear in the census.
                _aggregate_group(9, 5, page_number=(1, 2), attachment_version=(1, 1)),
            ]
        ),
        transcriptions=_aggregating_collection([_aggregate_group(3, 7)]),
        lecture_segments=_aggregating_collection(
            [_aggregate_group(3, 4, page_number=(1, 4))]
        ),
    )

    with patch("iris.web.routers.ingestion_census.VectorDatabase", return_value=db):
        census = get_course_ingestion_census(1, base_url="https://artemis.example")

    assert census.course_id == 1
    assert [entry.lecture_unit_id for entry in census.units] == [3, 9]

    complete = census.units[0]
    assert complete.lecture_id == 2
    assert complete.content_fingerprint == "v1:abc"
    assert complete.unit_row_count == 1
    assert complete.chunk_count == 12
    assert (complete.chunk_page_min, complete.chunk_page_max) == (1, 4)
    assert (complete.chunk_version_min, complete.chunk_version_max) == (2, 2)
    assert complete.transcription_count == 7
    assert complete.segment_count == 4
    assert (complete.segment_page_min, complete.segment_page_max) == (1, 4)

    orphan = census.units[1]
    assert orphan.unit_row_count == 0
    assert orphan.content_fingerprint is None
    assert orphan.chunk_count == 5


def test_census_wire_format_uses_camel_case():
    db = SimpleNamespace(
        lecture_units=SimpleNamespace(
            query=SimpleNamespace(
                fetch_objects=MagicMock(return_value=SimpleNamespace(objects=[]))
            )
        ),
        lectures=_aggregating_collection([]),
        transcriptions=_aggregating_collection([]),
        lecture_segments=_aggregating_collection([]),
    )

    with patch("iris.web.routers.ingestion_census.VectorDatabase", return_value=db):
        census = get_course_ingestion_census(1, base_url="https://artemis.example")

    dumped = census.model_dump(by_alias=True)
    assert dumped == {"courseId": 1, "units": []}


def test_unit_pipeline_stamps_the_fingerprint_verbatim():
    pipeline = object.__new__(LectureUnitPipeline)
    insert = MagicMock()
    pipeline.lecture_unit_collection = SimpleNamespace(
        query=SimpleNamespace(
            fetch_objects=MagicMock(return_value=SimpleNamespace(objects=[]))
        ),
        data=SimpleNamespace(delete_many=MagicMock(), insert=insert),
    )
    pipeline.weaviate_client = MagicMock()
    pipeline.local = False
    pipeline.callback = None
    pipeline.llm_embedding = SimpleNamespace(embed=MagicMock(return_value=[0.1]))
    lecture_unit = LectureUnitDTO(
        course_id=1,
        course_name="Course",
        course_description="",
        course_language="en",
        lecture_id=2,
        lecture_name="Lecture",
        lecture_unit_id=3,
        lecture_unit_name="Unit",
        base_url="https://artemis.example",
        content_fingerprint="v1:abc",
    )

    with (
        patch(
            "iris.pipeline.lecture_unit_pipeline.LectureUnitSegmentSummaryPipeline"
        ) as segment_pipeline_cls,
        patch(
            "iris.pipeline.lecture_unit_pipeline.LectureUnitSummaryPipeline"
        ) as summary_pipeline_cls,
    ):
        segment_pipeline_cls.return_value.return_value = ([], [])
        summary_pipeline_cls.return_value.return_value = ("summary", [])
        pipeline(lecture_unit=lecture_unit, initial_properties={})

    stored = insert.call_args.kwargs["properties"]
    assert stored[LectureUnitSchema.CONTENT_FINGERPRINT.value] == "v1:abc"
