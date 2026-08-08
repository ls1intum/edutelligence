import json
from dataclasses import dataclass
from datetime import datetime, timezone

from weaviate.classes.query import Filter
from weaviate.collections import Collection

from iris.domain.ingestion.lecture_visibility_update_dto import (
    LectureUnitVisibilityUpdateDTO,
    SlideVisibilityDTO,
)
from iris.pipeline.lecture_update_lock import lecture_update_lock
from iris.vector_database.database import batch_update_lock
from iris.vector_database.lecture_unit_page_chunk_schema import (
    LectureUnitPageChunkSchema,
)
from iris.vector_database.lecture_unit_schema import LectureUnitSchema
from iris.vector_database.lecture_unit_segment_schema import LectureUnitSegmentSchema


@dataclass(frozen=True)
class LectureVisibilityUpdateResult:
    lecture_units_updated: int
    page_chunks_updated: int
    segments_updated: int


class LectureVisibilityUpdatePipeline:
    """Update release and slide visibility without replacing stored vectors."""

    def __init__(
        self,
        page_chunk_collection: Collection,
        lecture_unit_collection: Collection,
        lecture_unit_segment_collection: Collection,
    ):
        self.page_chunk_collection = page_chunk_collection
        self.lecture_unit_collection = lecture_unit_collection
        self.lecture_unit_segment_collection = lecture_unit_segment_collection

    def __call__(
        self, dto: LectureUnitVisibilityUpdateDTO
    ) -> LectureVisibilityUpdateResult:
        with batch_update_lock:
            with lecture_update_lock(
                dto.base_url, dto.course_id, dto.lecture_id, dto.lecture_unit_id
            ):
                units = self._find_units(dto)
                if not units:
                    return LectureVisibilityUpdateResult(0, 0, 0)

                snapshot = self._merge_slide_visibility_snapshot(units, dto)
                self._update_units(
                    units,
                    {
                        LectureUnitSchema.RELEASE_DATE.value: datetime.max.replace(
                            tzinfo=timezone.utc
                        ),
                        LectureUnitSchema.SLIDE_VISIBILITY.value: snapshot,
                    },
                )
                page_count = 0
                segment_count = 0
                for slide in dto.slides:
                    page_count += self._update_slide_visibility(
                        self.page_chunk_collection,
                        LectureUnitPageChunkSchema,
                        dto,
                        slide,
                    )
                    segment_count += self._update_slide_visibility(
                        self.lecture_unit_segment_collection,
                        LectureUnitSegmentSchema,
                        dto,
                        slide,
                    )
                self._update_units(
                    units, {LectureUnitSchema.RELEASE_DATE.value: dto.release_date}
                )
        return LectureVisibilityUpdateResult(len(units), page_count, segment_count)

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

    def _update_units(self, units, properties: dict) -> None:
        for obj in units:
            self.lecture_unit_collection.data.update(
                uuid=str(obj.uuid),
                properties=properties,
            )

    @staticmethod
    def _update_slide_visibility(
        collection: Collection,
        schema: type[LectureUnitPageChunkSchema] | type[LectureUnitSegmentSchema],
        dto: LectureUnitVisibilityUpdateDTO,
        slide: SlideVisibilityDTO,
    ) -> int:
        objects = collection.query.fetch_objects(
            filters=LectureVisibilityUpdatePipeline._slide_filter(schema, dto, slide),
            limit=10_000,
        ).objects
        for obj in objects:
            collection.data.update(
                uuid=str(obj.uuid),
                properties={schema.HIDDEN_UNTIL.value: slide.hidden_until},
            )
        return len(objects)

    @staticmethod
    def _lecture_unit_filter(dto: LectureUnitVisibilityUpdateDTO):
        return Filter.all_of(
            [
                Filter.by_property(LectureUnitSchema.BASE_URL.value).equal(
                    dto.base_url
                ),
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
    def _slide_filter(
        schema: type[LectureUnitPageChunkSchema] | type[LectureUnitSegmentSchema],
        dto: LectureUnitVisibilityUpdateDTO,
        slide: SlideVisibilityDTO,
    ):
        return Filter.all_of(
            [
                Filter.by_property(schema.BASE_URL.value).equal(dto.base_url),
                Filter.by_property(schema.COURSE_ID.value).equal(dto.course_id),
                Filter.by_property(schema.LECTURE_ID.value).equal(dto.lecture_id),
                Filter.by_property(schema.LECTURE_UNIT_ID.value).equal(
                    dto.lecture_unit_id
                ),
                Filter.by_property(schema.PAGE_NUMBER.value).equal(slide.slide_number),
            ]
        )
