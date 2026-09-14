"""Tests for the per-course ingestion census and fingerprint stamping."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.domain.lecture.lecture_unit_dto import LectureUnitDTO
from iris.pipeline.lecture_unit_pipeline import LectureUnitPipeline
from iris.vector_database.lecture_unit_page_chunk_schema import (
    LectureUnitPageChunkSchema,
)
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
    """Fake collection for transcripts/segments (aggregate-only).

    ``over_all(group_by=...)`` enumerates units; a filtered ``over_all`` (no
    ``group_by``) returns the single unit's aggregate — a group object doubles as
    the result because it already carries ``total_count`` and ``properties``.
    """

    def over_all(*_args, group_by=None, **_kwargs):
        if group_by is not None:
            return SimpleNamespace(groups=groups)
        return groups[0] if groups else SimpleNamespace(total_count=0, properties={})

    return SimpleNamespace(
        aggregate=SimpleNamespace(over_all=MagicMock(side_effect=over_all))
    )


_UNSET = object()


def _chunk_row(
    unit_id, run_id, page, version, object_uuid, display=_UNSET
) -> SimpleNamespace:
    return SimpleNamespace(
        uuid=object_uuid,
        properties={
            LectureUnitPageChunkSchema.LECTURE_UNIT_ID.value: unit_id,
            LectureUnitPageChunkSchema.INGESTION_RUN_ID.value: run_id,
            LectureUnitPageChunkSchema.PAGE_NUMBER.value: page,
            LectureUnitPageChunkSchema.PAGE_VERSION.value: version,
            LectureUnitPageChunkSchema.DISPLAY_PAGE_NUMBER.value: (
                page if display is _UNSET else display
            ),
        },
    )


def _chunk_collection(rows_by_unit_sorted, present_uuids) -> SimpleNamespace:
    """Fake page-chunk collection with ghost-aware object-store confirmation.

    ``aggregate.over_all(group_by=...)`` enumerates the units; the query scans one
    unit per call (in the census's sorted-unit order) and confirms uuids against
    the object store — ``fetch_object_by_id`` returns ``None`` for ghost uuids,
    exactly as store corruption presents them.
    """
    groups = [
        SimpleNamespace(
            grouped_by=SimpleNamespace(value=str(unit_id)),
            total_count=len(rows),
            properties={},
        )
        for unit_id, rows in rows_by_unit_sorted
    ]
    return SimpleNamespace(
        aggregate=SimpleNamespace(
            over_all=MagicMock(return_value=SimpleNamespace(groups=groups))
        ),
        query=SimpleNamespace(
            fetch_objects=MagicMock(
                side_effect=[
                    SimpleNamespace(objects=rows) for _, rows in rows_by_unit_sorted
                ]
            ),
            fetch_object_by_id=MagicMock(
                side_effect=lambda object_uuid: (
                    SimpleNamespace() if object_uuid in present_uuids else None
                )
            ),
        ),
    )


def _unit_rows_collection(rows, present_uuids=None) -> SimpleNamespace:
    """Fake unit-row collection with ghost-aware object-store confirmation.

    ``present_uuids=None`` treats every row as real; otherwise a row's uuid must be
    listed to be confirmed (a ghost unit row returns ``None`` from fetch_object_by_id).
    """

    def confirm(object_uuid):
        if present_uuids is None or object_uuid in present_uuids:
            return SimpleNamespace()
        return None

    return SimpleNamespace(
        query=SimpleNamespace(
            fetch_objects=MagicMock(return_value=SimpleNamespace(objects=rows)),
            fetch_object_by_id=MagicMock(side_effect=confirm),
        )
    )


def test_census_merges_all_collections_and_reports_orphans():
    unit_row = SimpleNamespace(
        uuid="ur-3",
        properties={
            LectureUnitSchema.LECTURE_ID.value: 2,
            LectureUnitSchema.LECTURE_UNIT_ID.value: 3,
            LectureUnitSchema.CONTENT_FINGERPRINT.value: "v1:abc",
        },
    )
    # Unit 3: 12 real chunks on pages 1..4 (version 2). Unit 9: 5 real chunks on
    # pages 1..2 (version 1) but no unit row — an orphan that must still appear.
    unit3_rows = [
        _chunk_row(3, "r3", (index % 4) + 1, 2, f"u3-{index}") for index in range(12)
    ]
    unit9_rows = [
        _chunk_row(9, "r9", (index % 2) + 1, 1, f"u9-{index}") for index in range(5)
    ]
    present = {row.uuid for row in unit3_rows + unit9_rows}
    db = SimpleNamespace(
        lecture_units=_unit_rows_collection([unit_row]),
        lectures=_chunk_collection([(3, unit3_rows), (9, unit9_rows)], present),
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
    assert complete.generation_count == 1
    assert (complete.chunk_page_min, complete.chunk_page_max) == (1, 4)
    assert (complete.chunk_version_min, complete.chunk_version_max) == (2, 2)
    assert complete.transcription_count == 7
    assert complete.segment_count == 4
    assert (complete.segment_page_min, complete.segment_page_max) == (1, 4)

    orphan = census.units[1]
    assert orphan.unit_row_count == 0
    assert orphan.content_fingerprint is None
    assert orphan.chunk_count == 5
    assert orphan.generation_count == 1


def test_census_reports_interior_page_gap_and_null_display():
    """The census reports an interior hole in the page coverage (a page in 1..max
    with no chunk) and the count of chunks whose display number was never
    resolved (legacy null)."""
    unit_row = SimpleNamespace(
        uuid="ur-4",
        properties={
            LectureUnitSchema.LECTURE_UNIT_ID.value: 4,
            LectureUnitSchema.COURSE_LANGUAGE.value: "de",
        },
    )
    # Real chunks cover pages 1, 2, 4, 5 (page 3 was dropped); page 4's chunk has
    # a null display number.
    rows = [
        _chunk_row(4, "r", 1, 2, "c1", display=1),
        _chunk_row(4, "r", 2, 2, "c2", display=2),
        _chunk_row(4, "r", 4, 2, "c3", display=None),
        _chunk_row(4, "r", 5, 2, "c4", display=5),
    ]
    present = {row.uuid for row in rows}
    db = SimpleNamespace(
        lecture_units=_unit_rows_collection([unit_row]),
        lectures=_chunk_collection([(4, rows)], present),
        transcriptions=_aggregating_collection([]),
        lecture_segments=_aggregating_collection([]),
    )

    with patch("iris.web.routers.ingestion_census.VectorDatabase", return_value=db):
        census = get_course_ingestion_census(1, base_url="https://artemis.example")

    entry = census.units[0]
    assert entry.missing_page_count == 1  # page 3 is missing (interior hole in 1..5)
    assert entry.null_display_count == 1  # page 4's chunk has no display number
    assert entry.course_language == "de"


def test_census_excludes_object_store_ghost_generations():
    """Ghost generations (scan-visible, object-store-absent) must not inflate the
    generation count, chunk count, or page range the reconciler trusts."""
    real_rows = [
        _chunk_row(5, "real", (index % 3) + 1, 4, f"real-{index}") for index in range(9)
    ]
    ghost_rows = [
        _chunk_row(5, "ghost", (index % 3) + 1, 3, f"ghost-{index}")
        for index in range(6)
    ]
    present = {row.uuid for row in real_rows}  # ghost uuids absent from the store
    db = SimpleNamespace(
        lecture_units=_unit_rows_collection([]),
        lectures=_chunk_collection([(5, real_rows + ghost_rows)], present),
        transcriptions=_aggregating_collection([]),
        lecture_segments=_aggregating_collection([]),
    )

    with patch("iris.web.routers.ingestion_census.VectorDatabase", return_value=db):
        census = get_course_ingestion_census(1, base_url="https://artemis.example")

    entry = census.units[0]
    assert entry.generation_count == 1  # the ghost generation is excluded
    assert entry.chunk_count == 9  # only real rows counted
    assert (entry.chunk_page_min, entry.chunk_page_max) == (1, 3)
    # The version range reflects the real generation (4), not the ghost's (3).
    assert (entry.chunk_version_min, entry.chunk_version_max) == (4, 4)


def test_census_wire_format_uses_camel_case():
    db = SimpleNamespace(
        lecture_units=_unit_rows_collection([]),
        lectures=_aggregating_collection([]),
        transcriptions=_aggregating_collection([]),
        lecture_segments=_aggregating_collection([]),
    )

    with patch("iris.web.routers.ingestion_census.VectorDatabase", return_value=db):
        census = get_course_ingestion_census(1, base_url="https://artemis.example")

    dumped = census.model_dump(by_alias=True)
    assert dumped == {"courseId": 1, "currentPipelineVersion": 1, "units": []}


def test_unit_pipeline_stamps_the_fingerprint_verbatim():
    pipeline = object.__new__(LectureUnitPipeline)
    insert = MagicMock(return_value="33333333-3333-3333-3333-333333333333")
    pipeline.lecture_unit_collection = SimpleNamespace(
        query=SimpleNamespace(
            fetch_objects=MagicMock(return_value=SimpleNamespace(objects=[]))
        ),
        data=SimpleNamespace(
            delete_many=MagicMock(
                return_value=SimpleNamespace(failed=0, matches=0, successful=0)
            ),
            insert=insert,
        ),
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
