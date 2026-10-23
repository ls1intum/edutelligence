import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from weaviate.classes.query import Filter
from weaviate.collections import Collection

from iris.common.logging_config import get_logger
from iris.domain.ingestion.lecture_visibility_update_dto import (
    LectureUnitVisibilityUpdateDTO,
)
from iris.pipeline.lecture_update_lock import lecture_update_lock
from iris.vector_database.instance_filter import artemis_instance_filter
from iris.vector_database.lecture_unit_page_chunk_schema import (
    LectureUnitPageChunkSchema,
)
from iris.vector_database.lecture_unit_schema import LectureUnitSchema
from iris.vector_database.lecture_unit_segment_schema import LectureUnitSegmentSchema
from iris.vector_database.write_retry import WeaviateWriteRetry

logger = get_logger(__name__)

# Weaviate's default maximum for one query. A unit with more rows is read one
# slide at a time instead, so no row is skipped.
_ROW_FETCH_LIMIT = 10_000

SlideSchema = type[LectureUnitPageChunkSchema] | type[LectureUnitSegmentSchema]


@dataclass(frozen=True)
class LectureVisibilityUpdateResult:
    # Units found, not units written: zero means Pyris holds nothing for the unit,
    # which the endpoint reports as 404, so a no-op update must not report zero.
    lecture_units_updated: int
    page_chunks_updated: int
    segments_updated: int


class LectureVisibilityUpdatePipeline:
    """Update release and slide visibility without replacing stored vectors.

    Only rows whose stored visibility differs from the request are written. Artemis
    sends every slide of the unit on each update and repeats updates it is unsure
    about, so most requests change nothing and only read.

    Writes take only the unit's own lock. Every ingestion write for the unit holds
    the same lock (through the ingestion job guard), so they cannot interleave, and
    an update of one unit no longer waits for writes to any other unit.
    """

    def __init__(
        self,
        page_chunk_collection: Collection,
        lecture_unit_collection: Collection,
        lecture_unit_segment_collection: Collection,
        write_retry_factory: Callable[
            [], WeaviateWriteRetry
        ] = WeaviateWriteRetry.for_request,
    ):
        self.page_chunk_collection = page_chunk_collection
        self.lecture_unit_collection = lecture_unit_collection
        self.lecture_unit_segment_collection = lecture_unit_segment_collection
        self.write_retry_factory = write_retry_factory

    def __call__(
        self, dto: LectureUnitVisibilityUpdateDTO
    ) -> LectureVisibilityUpdateResult:
        started = time.monotonic()
        write_retry = self.write_retry_factory()
        with lecture_update_lock(
            dto.base_url, dto.course_id, dto.lecture_id, dto.lecture_unit_id
        ):
            lock_wait_ms = (time.monotonic() - started) * 1000
            units = self._find_units(dto)
            if not units:
                return LectureVisibilityUpdateResult(0, 0, 0)

            snapshot = self._merge_slide_visibility_snapshot(units, dto)
            hidden_until_by_page = {
                slide.slide_number: slide.hidden_until for slide in dto.slides
            }
            stale_pages, pages_checked = self._stale_rows(
                self.page_chunk_collection,
                LectureUnitPageChunkSchema,
                dto,
                hidden_until_by_page,
            )
            stale_segments, segments_checked = self._stale_rows(
                self.lecture_unit_segment_collection,
                LectureUnitSegmentSchema,
                dto,
                hidden_until_by_page,
            )

            if stale_pages or stale_segments:
                # Deny the whole unit while its slides are inconsistent, so a failure
                # part-way leaves it hidden rather than showing slides that should
                # still be hidden.
                self._update_units(
                    units,
                    {
                        LectureUnitSchema.RELEASE_DATE.value: datetime.max.replace(
                            tzinfo=timezone.utc
                        ),
                        LectureUnitSchema.SLIDE_VISIBILITY.value: snapshot,
                    },
                    write_retry,
                )
                self._update_rows(
                    self.page_chunk_collection,
                    LectureUnitPageChunkSchema,
                    stale_pages,
                    write_retry,
                )
                self._update_rows(
                    self.lecture_unit_segment_collection,
                    LectureUnitSegmentSchema,
                    stale_segments,
                    write_retry,
                )
                self._update_units(
                    units,
                    {LectureUnitSchema.RELEASE_DATE.value: dto.release_date},
                    write_retry,
                )
                units_written = len(units)
            else:
                # Also heals a unit an earlier failed update left denied.
                stale_units = [
                    unit
                    for unit in units
                    if self._unit_differs(unit, dto.release_date, snapshot)
                ]
                self._update_units(
                    stale_units,
                    {
                        LectureUnitSchema.RELEASE_DATE.value: dto.release_date,
                        LectureUnitSchema.SLIDE_VISIBILITY.value: snapshot,
                    },
                    write_retry,
                )
                units_written = len(stale_units)

        logger.info(
            "Lecture visibility updated | lecture_unit_id=%s slides=%s "
            "rows_checked=%s rows_written=%s units_written=%s lock_wait_ms=%.0f "
            "total_ms=%.0f",
            dto.lecture_unit_id,
            len(dto.slides),
            pages_checked + segments_checked,
            len(stale_pages) + len(stale_segments),
            units_written,
            lock_wait_ms,
            (time.monotonic() - started) * 1000,
        )
        return LectureVisibilityUpdateResult(
            len(units), len(stale_pages), len(stale_segments)
        )

    @staticmethod
    def _merge_slide_visibility_snapshot(
        units, dto: LectureUnitVisibilityUpdateDTO
    ) -> str:
        snapshot: dict[str, str | None] = {}
        for unit in units:
            serialized = getattr(unit, "properties", {}).get(
                LectureUnitSchema.SLIDE_VISIBILITY.value
            )
            if serialized is None:
                continue
            existing = json.loads(serialized)
            if not isinstance(existing, dict):
                raise ValueError("Stored slide visibility snapshot must be an object")
            snapshot.update(existing)

        snapshot.update(
            {
                str(slide.slide_number): (
                    slide.hidden_until.isoformat()
                    if slide.hidden_until is not None
                    else None
                )
                for slide in dto.slides
            }
        )
        return json.dumps(snapshot, sort_keys=True)

    def _find_units(self, dto: LectureUnitVisibilityUpdateDTO):
        return self.lecture_unit_collection.query.fetch_objects(
            filters=self._lecture_unit_filter(dto),
            limit=100,
        ).objects

    def _update_units(
        self,
        units,
        properties: dict,
        write_retry: WeaviateWriteRetry,
    ) -> None:
        for obj in units:
            write_retry.update(
                self.lecture_unit_collection,
                uuid=str(obj.uuid),
                properties=properties,
            )

    @staticmethod
    def _unit_differs(unit, release_date: datetime | None, snapshot: str) -> bool:
        properties = getattr(unit, "properties", {})
        return (
            properties.get(LectureUnitSchema.RELEASE_DATE.value) != release_date
            or properties.get(LectureUnitSchema.SLIDE_VISIBILITY.value) != snapshot
        )

    @staticmethod
    def _stale_rows(
        collection: Collection,
        schema: SlideSchema,
        dto: LectureUnitVisibilityUpdateDTO,
        hidden_until_by_page: dict[int, datetime | None],
    ) -> tuple[list[tuple[str, datetime | None]], int]:
        """Rows of the requested slides whose stored visibility differs.

        Rows of slides the request does not name are left alone: a partial update
        must not touch them.

        :return: the uuid and wanted value of each row to write, and the number of
            rows read
        """
        if not hidden_until_by_page:
            return [], 0
        return_properties = [schema.PAGE_NUMBER.value, schema.HIDDEN_UNTIL.value]
        rows = collection.query.fetch_objects(
            filters=LectureVisibilityUpdatePipeline._unit_rows_filter(schema, dto),
            limit=_ROW_FETCH_LIMIT,
            return_properties=return_properties,
        ).objects
        if len(rows) >= _ROW_FETCH_LIMIT:
            rows = [
                row
                for page_number in hidden_until_by_page
                for row in collection.query.fetch_objects(
                    filters=LectureVisibilityUpdatePipeline._unit_rows_filter(
                        schema, dto
                    )
                    & Filter.by_property(schema.PAGE_NUMBER.value).equal(page_number),
                    limit=_ROW_FETCH_LIMIT,
                    return_properties=return_properties,
                ).objects
            ]
        stale = []
        for row in rows:
            page_number = row.properties.get(schema.PAGE_NUMBER.value)
            if page_number is None or int(page_number) not in hidden_until_by_page:
                continue
            wanted = hidden_until_by_page[int(page_number)]
            if row.properties.get(schema.HIDDEN_UNTIL.value) != wanted:
                stale.append((str(row.uuid), wanted))
        return stale, len(rows)

    @staticmethod
    def _update_rows(
        collection: Collection,
        schema: SlideSchema,
        rows: list[tuple[str, datetime | None]],
        write_retry: WeaviateWriteRetry,
    ) -> None:
        for uuid, hidden_until in rows:
            write_retry.update(
                collection,
                uuid=uuid,
                properties={schema.HIDDEN_UNTIL.value: hidden_until},
            )

    @staticmethod
    def _lecture_unit_filter(dto: LectureUnitVisibilityUpdateDTO):
        return Filter.all_of(
            [
                artemis_instance_filter(LectureUnitSchema, dto.base_url),
                Filter.by_property(LectureUnitSchema.COURSE_ID.value).equal(
                    dto.course_id
                ),
                Filter.by_property(LectureUnitSchema.LECTURE_ID.value).equal(
                    dto.lecture_id
                ),
                Filter.by_property(LectureUnitSchema.LECTURE_UNIT_ID.value).equal(
                    dto.lecture_unit_id
                ),
            ]
        )

    @staticmethod
    def _unit_rows_filter(schema: SlideSchema, dto: LectureUnitVisibilityUpdateDTO):
        return Filter.all_of(
            [
                artemis_instance_filter(schema, dto.base_url),
                Filter.by_property(schema.COURSE_ID.value).equal(dto.course_id),
                Filter.by_property(schema.LECTURE_ID.value).equal(dto.lecture_id),
                Filter.by_property(schema.LECTURE_UNIT_ID.value).equal(
                    dto.lecture_unit_id
                ),
            ]
        )
