from weaviate.classes.query import Filter
from weaviate.collections import Collection

from iris.domain.ingestion.lecture_metadata_update_dto import (
    LectureUnitMetadataUpdateDTO,
)
from iris.vector_database.database import batch_update_lock
from iris.vector_database.lecture_unit_schema import LectureUnitSchema


class LectureMetadataUpdatePipeline:
    """Update lecture-unit metadata without replacing its vector or summary."""

    def __init__(self, lecture_unit_collection: Collection):
        self.lecture_unit_collection = lecture_unit_collection

    def __call__(self, dto: LectureUnitMetadataUpdateDTO) -> int:
        with batch_update_lock:
            objects = self.lecture_unit_collection.query.fetch_objects(
                filters=self._filter(dto),
                limit=100,
            ).objects
            properties = {
                LectureUnitSchema.COURSE_NAME.value: dto.course_name,
                LectureUnitSchema.COURSE_DESCRIPTION.value: dto.course_description,
                LectureUnitSchema.LECTURE_NAME.value: dto.lecture_name,
                LectureUnitSchema.LECTURE_UNIT_NAME.value: dto.lecture_unit_name,
                LectureUnitSchema.LECTURE_UNIT_LINK.value: dto.lecture_unit_link,
                LectureUnitSchema.VIDEO_LINK.value: dto.video_link,
            }
            for obj in objects:
                self.lecture_unit_collection.data.update(
                    uuid=str(obj.uuid),
                    properties=properties,
                )
        return len(objects)

    @staticmethod
    def _filter(dto: LectureUnitMetadataUpdateDTO):
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
