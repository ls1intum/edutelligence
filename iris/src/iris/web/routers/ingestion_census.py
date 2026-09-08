"""Per-course census of what the index actually holds.

Artemis calls this to verify its ingestion ledger against reality: which
units have rows, under which fingerprint, with how many chunks over which
page range. Counts and ranges come from Weaviate aggregations grouped by
lecture unit, so a course costs four Weaviate calls regardless of its size,
and a unit that any collection still knows about is reported even when its
unit row is missing. The endpoint reads identity properties only.
"""

from urllib.parse import unquote

from fastapi import APIRouter, Depends
from fastapi.params import Query
from weaviate.classes.aggregate import GroupByAggregate
from weaviate.classes.query import Metrics
from weaviate.collections.classes.filters import Filter

from iris.dependencies import TokenValidator
from iris.domain.ingestion.ingestion_census_dto import (
    IngestionCensusDTO,
    IngestionCensusUnitDTO,
)

from ...vector_database.database import VectorDatabase
from ...vector_database.lecture_transcription_schema import (
    LectureTranscriptionSchema,
)
from ...vector_database.lecture_unit_page_chunk_schema import (
    LectureUnitPageChunkSchema,
)
from ...vector_database.lecture_unit_schema import LectureUnitSchema
from ...vector_database.lecture_unit_segment_schema import (
    LectureUnitSegmentSchema,
)

router = APIRouter(prefix="/api/v1", tags=["ingestion_census"])

_UNIT_ROW_LIMIT = 10_000


def _course_filter(schema, course_id: int, base_url: str):
    return Filter.by_property(schema.BASE_URL.value).equal(
        base_url
    ) & Filter.by_property(schema.COURSE_ID.value).equal(course_id)


def _aggregate_by_unit(collection, schema, course_id: int, base_url: str, metrics):
    return collection.aggregate.over_all(
        filters=_course_filter(schema, course_id, base_url),
        group_by=GroupByAggregate(prop=schema.LECTURE_UNIT_ID.value),
        total_count=True,
        return_metrics=metrics,
    ).groups


def _metric(group, property_name: str, metric_name: str):
    metric = group.properties.get(property_name)
    if metric is None:
        return None
    value = getattr(metric, metric_name, None)
    return int(value) if value is not None else None


@router.get(
    "/courses/{course_id}/ingestion-census",
    response_model=IngestionCensusDTO,
    dependencies=[Depends(TokenValidator())],
)
def get_course_ingestion_census(
    course_id: int,
    base_url: str = Query(...),
) -> IngestionCensusDTO:
    """Report the aggregated index state of every lecture unit in the course."""
    db = VectorDatabase()
    decoded_base_url = unquote(base_url)
    units: dict[int, IngestionCensusUnitDTO] = {}

    def unit(lecture_unit_id: int) -> IngestionCensusUnitDTO:
        if lecture_unit_id not in units:
            units[lecture_unit_id] = IngestionCensusUnitDTO(
                lectureUnitId=lecture_unit_id
            )
        return units[lecture_unit_id]

    unit_rows = db.lecture_units.query.fetch_objects(
        filters=_course_filter(LectureUnitSchema, course_id, decoded_base_url),
        limit=_UNIT_ROW_LIMIT,
        return_properties=[
            LectureUnitSchema.LECTURE_ID.value,
            LectureUnitSchema.LECTURE_UNIT_ID.value,
            LectureUnitSchema.CONTENT_FINGERPRINT.value,
        ],
    ).objects
    for row in unit_rows:
        lecture_unit_id = int(row.properties[LectureUnitSchema.LECTURE_UNIT_ID.value])
        entry = unit(lecture_unit_id)
        entry.unit_row_count += 1
        lecture_id = row.properties.get(LectureUnitSchema.LECTURE_ID.value)
        entry.lecture_id = int(lecture_id) if lecture_id is not None else None
        entry.content_fingerprint = row.properties.get(
            LectureUnitSchema.CONTENT_FINGERPRINT.value
        )

    chunk_groups = _aggregate_by_unit(
        db.lectures,
        LectureUnitPageChunkSchema,
        course_id,
        decoded_base_url,
        [
            Metrics(LectureUnitPageChunkSchema.PAGE_NUMBER.value).integer(
                minimum=True, maximum=True
            ),
            Metrics(LectureUnitPageChunkSchema.PAGE_VERSION.value).integer(
                minimum=True, maximum=True
            ),
        ],
    )
    for group in chunk_groups:
        entry = unit(int(group.grouped_by.value))
        entry.chunk_count = group.total_count or 0
        entry.chunk_page_min = _metric(
            group, LectureUnitPageChunkSchema.PAGE_NUMBER.value, "minimum"
        )
        entry.chunk_page_max = _metric(
            group, LectureUnitPageChunkSchema.PAGE_NUMBER.value, "maximum"
        )
        entry.chunk_version_min = _metric(
            group, LectureUnitPageChunkSchema.PAGE_VERSION.value, "minimum"
        )
        entry.chunk_version_max = _metric(
            group, LectureUnitPageChunkSchema.PAGE_VERSION.value, "maximum"
        )

    transcription_groups = _aggregate_by_unit(
        db.transcriptions,
        LectureTranscriptionSchema,
        course_id,
        decoded_base_url,
        [],
    )
    for group in transcription_groups:
        unit(int(group.grouped_by.value)).transcription_count = group.total_count or 0

    segment_groups = _aggregate_by_unit(
        db.lecture_segments,
        LectureUnitSegmentSchema,
        course_id,
        decoded_base_url,
        [
            Metrics(LectureUnitSegmentSchema.PAGE_NUMBER.value).integer(
                minimum=True, maximum=True
            )
        ],
    )
    for group in segment_groups:
        entry = unit(int(group.grouped_by.value))
        entry.segment_count = group.total_count or 0
        entry.segment_page_min = _metric(
            group, LectureUnitSegmentSchema.PAGE_NUMBER.value, "minimum"
        )
        entry.segment_page_max = _metric(
            group, LectureUnitSegmentSchema.PAGE_NUMBER.value, "maximum"
        )

    return IngestionCensusDTO(
        courseId=course_id,
        units=[units[unit_id] for unit_id in sorted(units)],
    )
