"""Per-course census of what the index actually holds.

Artemis calls this to verify its ingestion ledger against reality: which
units have rows, under which fingerprint, with how many chunks over which
page range. Counts and ranges come from Weaviate aggregations grouped by
lecture unit, so a course costs four Weaviate calls regardless of its size,
and a unit that any collection still knows about is reported even when its
unit row is missing. The endpoint reads identity properties only.
"""

import json
from urllib.parse import unquote

from fastapi import APIRouter, Depends
from fastapi.params import Query
from weaviate.classes.aggregate import GroupByAggregate
from weaviate.collections.classes.filters import Filter

from iris.common.ingestion_version import INGESTION_PIPELINE_VERSION
from iris.common.logging_config import get_logger
from iris.dependencies import TokenValidator
from iris.domain.ingestion.ingestion_census_dto import (
    IngestionCensusDTO,
    IngestionCensusUnitDTO,
)

from ...vector_database.batch_verify import confirmed_generations, confirmed_rows
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

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["ingestion_census"])

_UNIT_ROW_LIMIT = 10_000


def _course_filter(schema, course_id: int, base_url: str):
    return Filter.by_property(schema.BASE_URL.value).equal(
        base_url
    ) & Filter.by_property(schema.COURSE_ID.value).equal(course_id)


def _discover_unit_ids(collection, schema, course_id: int, base_url: str) -> set[int]:
    """Unit ids that have at least one row in this collection for the course.

    The ``group_by`` is used only to *enumerate* which units are present — its
    per-group counts are unreliable in Weaviate (a course-wide group_by over- and
    under-reports per-unit totals versus a direct filtered fetch/aggregate), so
    the actual counting is done one unit at a time, confirmed against the object
    store, by each of this endpoint's per-collection loops.
    """
    groups = collection.aggregate.over_all(
        filters=_course_filter(schema, course_id, base_url),
        group_by=GroupByAggregate(prop=schema.LECTURE_UNIT_ID.value),
        total_count=True,
    ).groups
    return {
        int(group.grouped_by.value)
        for group in groups
        if group.grouped_by.value is not None
    }


def _int_values(rows, property_name: str) -> list[int]:
    """Integer values of ``property_name`` across ``rows``, skipping missing ones."""
    values = []
    for row in rows:
        value = row.properties.get(property_name)
        if value is not None:
            values.append(int(value))
    return values


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
            LectureUnitSchema.EXPECTED_CHUNK_COUNTS.value,
            LectureUnitSchema.COURSE_LANGUAGE.value,
            LectureUnitSchema.PIPELINE_VERSION.value,
            LectureUnitSchema.QUALITY_SCORE.value,
        ],
    ).objects
    # The unit-row scan is unscoped by unit (it discovers every unit in the
    # course), so hitting the cap here can silently drop whole units from this
    # response rather than just undercounting one -- surfaced at the course
    # level rather than attributed to any single unit.
    course_scan_truncated = len(unit_rows) >= _UNIT_ROW_LIMIT
    for row in unit_rows:
        # Skip object-store-only ghost unit rows: they are visible to this scan
        # but absent from the object store (and from retrieval), so counting them
        # would inflate unit_row_count into a false "duplicate rows" divergence
        # that a re-ingest can never clear, and reading their stale ledger values
        # could mislead the reconciler.
        if db.lecture_units.query.fetch_object_by_id(row.uuid) is None:
            continue
        lecture_unit_id = int(row.properties[LectureUnitSchema.LECTURE_UNIT_ID.value])
        entry = unit(lecture_unit_id)
        entry.unit_row_count += 1
        lecture_id = row.properties.get(LectureUnitSchema.LECTURE_ID.value)
        entry.lecture_id = int(lecture_id) if lecture_id is not None else None
        entry.content_fingerprint = row.properties.get(
            LectureUnitSchema.CONTENT_FINGERPRINT.value
        )
        expected_counts = row.properties.get(
            LectureUnitSchema.EXPECTED_CHUNK_COUNTS.value
        )
        if expected_counts:
            # The census exists so Artemis can reconcile a possibly-inconsistent
            # index; one unit's corrupt manifest must not abort the whole course.
            try:
                entry.expected_chunk_count = sum(json.loads(expected_counts).values())
            except (ValueError, TypeError, AttributeError):
                logger.warning(
                    "Unit %s has an unparseable expected-chunk-count manifest; "
                    "reporting it as unknown",
                    lecture_unit_id,
                )
                entry.expected_chunk_count = None
        entry.course_language = row.properties.get(
            LectureUnitSchema.COURSE_LANGUAGE.value
        )
        pipeline_version = row.properties.get(LectureUnitSchema.PIPELINE_VERSION.value)
        entry.pipeline_version = (
            int(pipeline_version) if pipeline_version is not None else None
        )
        quality_score = row.properties.get(LectureUnitSchema.QUALITY_SCORE.value)
        entry.quality_score = (
            float(quality_score) if quality_score is not None else None
        )

    # The chunk count is what the reconciler compares against the certified
    # expectation, so it must be exact for every certified unit: count the union of
    # units that have chunks and units that carry a unit row, one unit at a time.
    certified_unit_ids = set(units)
    chunk_unit_ids = (
        _discover_unit_ids(
            db.lectures, LectureUnitPageChunkSchema, course_id, decoded_base_url
        )
        | certified_unit_ids
    )
    for unit_id in sorted(chunk_unit_ids):
        entry = unit(unit_id)
        # Count generations, chunks, and the page range off object-store-confirmed
        # rows only: a raw scan/aggregate also sees inert ghost rows, which would
        # inflate the generation count (making a healed unit look perpetually
        # dirty and re-queued forever) and the chunk count and page range.
        real_generations, chunk_objects = confirmed_generations(
            db.lectures,
            _course_filter(LectureUnitPageChunkSchema, course_id, decoded_base_url)
            & Filter.by_property(
                LectureUnitPageChunkSchema.LECTURE_UNIT_ID.value
            ).equal(unit_id),
            LectureUnitPageChunkSchema.INGESTION_RUN_ID.value,
            limit=_UNIT_ROW_LIMIT,
            return_properties=[
                LectureUnitPageChunkSchema.PAGE_NUMBER.value,
                LectureUnitPageChunkSchema.PAGE_VERSION.value,
                LectureUnitPageChunkSchema.DISPLAY_PAGE_NUMBER.value,
            ],
        )
        generation_matches = [
            row
            for row in chunk_objects
            if row.properties.get(LectureUnitPageChunkSchema.INGESTION_RUN_ID.value)
            in real_generations
        ]
        # confirmed_generations only confirms one row per generation; a second,
        # row-level pass keeps an object-store-missing sibling in an otherwise-real
        # generation from inflating the exact chunk_count/page range below.
        real_rows = confirmed_rows(db.lectures, generation_matches)
        pages = _int_values(real_rows, LectureUnitPageChunkSchema.PAGE_NUMBER.value)
        versions = _int_values(real_rows, LectureUnitPageChunkSchema.PAGE_VERSION.value)
        # Scoped to this one unit, so a cap hit here only makes THIS unit's
        # chunk_count/generation_count/page range unreliable, unlike the
        # course-wide scan above.
        if len(chunk_objects) >= _UNIT_ROW_LIMIT:
            entry.truncated = True
        entry.chunk_count = len(real_rows)
        entry.generation_count = len(real_generations)
        entry.chunk_page_min = min(pages) if pages else None
        entry.chunk_page_max = max(pages) if pages else None
        entry.chunk_version_min = min(versions) if versions else None
        entry.chunk_version_max = max(versions) if versions else None
        # Interior page-coverage holes: pages in 1..max with no real chunk. A
        # successful run always covers 1..N contiguously (the pipeline's own
        # skip-check requires it), so any hole means a partial/lost write. This
        # needs no PDF page count — a trailing-drop check (max vs the true N)
        # belongs on the Artemis side, which owns the source document.
        if pages:
            covered = set(pages)
            entry.missing_page_count = sum(
                1 for page in range(1, max(pages) + 1) if page not in covered
            )
        # Real chunks whose display page number was never resolved (legacy null);
        # -1 is a valid "unknown/front-matter" marker and is not counted here.
        entry.null_display_count = sum(
            1
            for row in real_rows
            if row.properties.get(LectureUnitPageChunkSchema.DISPLAY_PAGE_NUMBER.value)
            is None
        )

    for unit_id in _discover_unit_ids(
        db.transcriptions, LectureTranscriptionSchema, course_id, decoded_base_url
    ):
        # Ghost-aware, like the page-chunk loop above: a raw aggregate total_count
        # also counts object-store-missing rows.
        real_generations, all_transcription_objects = confirmed_generations(
            db.transcriptions,
            _course_filter(LectureTranscriptionSchema, course_id, decoded_base_url)
            & Filter.by_property(
                LectureTranscriptionSchema.LECTURE_UNIT_ID.value
            ).equal(unit_id),
            LectureTranscriptionSchema.INGESTION_RUN_ID.value,
            limit=_UNIT_ROW_LIMIT,
        )
        entry = unit(unit_id)
        if len(all_transcription_objects) >= _UNIT_ROW_LIMIT:
            entry.truncated = True
        generation_matches = [
            row
            for row in all_transcription_objects
            if row.properties.get(LectureTranscriptionSchema.INGESTION_RUN_ID.value)
            in real_generations
        ]
        # See the page-chunk loop above for why a second, row-level pass is needed.
        confirmed_transcriptions = confirmed_rows(db.transcriptions, generation_matches)
        entry.transcription_count = len(confirmed_transcriptions)

    for unit_id in _discover_unit_ids(
        db.lecture_segments, LectureUnitSegmentSchema, course_id, decoded_base_url
    ):
        entry = unit(unit_id)
        # Segments carry no ingestion-generation property, so each row is
        # confirmed directly instead of grouping by generation (same approach
        # the ingestion audit uses for segments and the unit row).
        all_segment_rows = db.lecture_segments.query.fetch_objects(
            filters=_course_filter(
                LectureUnitSegmentSchema, course_id, decoded_base_url
            )
            & Filter.by_property(LectureUnitSegmentSchema.LECTURE_UNIT_ID.value).equal(
                unit_id
            ),
            limit=_UNIT_ROW_LIMIT,
            return_properties=[LectureUnitSegmentSchema.PAGE_NUMBER.value],
        ).objects
        if len(all_segment_rows) >= _UNIT_ROW_LIMIT:
            entry.truncated = True
        real_segment_rows = confirmed_rows(db.lecture_segments, all_segment_rows)
        segment_pages = _int_values(
            real_segment_rows, LectureUnitSegmentSchema.PAGE_NUMBER.value
        )
        entry.segment_count = len(real_segment_rows)
        entry.segment_page_min = min(segment_pages) if segment_pages else None
        entry.segment_page_max = max(segment_pages) if segment_pages else None

    return IngestionCensusDTO(
        courseId=course_id,
        currentPipelineVersion=INGESTION_PIPELINE_VERSION,
        truncated=course_scan_truncated,
        units=[units[unit_id] for unit_id in sorted(units)],
    )
