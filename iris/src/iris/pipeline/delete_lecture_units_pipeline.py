from typing import List

from weaviate import WeaviateClient
from weaviate.classes.query import Filter

from iris.common.logging_config import get_logger
from iris.domain.data.lecture_unit_page_dto import LectureUnitPageDTO
from iris.domain.variant.lecture_unit_deletion_variant import LectureUnitDeletionVariant
from iris.pipeline import Pipeline
from iris.tracing import observe
from iris.vector_database.lecture_transcription_schema import (
    LectureTranscriptionSchema,
    init_lecture_transcription_schema,
)
from iris.vector_database.lecture_unit_page_chunk_schema import (
    LectureUnitPageChunkSchema,
    init_lecture_unit_page_chunk_schema,
)
from iris.vector_database.lecture_unit_schema import (
    LectureUnitSchema,
    init_lecture_unit_schema,
)
from iris.vector_database.lecture_unit_segment_schema import (
    LectureUnitSegmentSchema,
    init_lecture_unit_segment_schema,
)
from iris.web.status.lecture_deletion_status_callback import (
    LecturesDeletionStatusCallback,
)

logger = get_logger(__name__)


class LectureUnitDeletionPipeline(Pipeline[LectureUnitDeletionVariant]):
    """LectureUnitDeletionPipeline deletes weaviate entries from page chunks,
    transcriptions and lecture unit segments."""

    def __init__(
        self,
        client: WeaviateClient,
        lecture_units: List[LectureUnitPageDTO],
        artemis_base_url: str,
        callback: LecturesDeletionStatusCallback,
    ):
        super().__init__(implementation_id="lecture_unit_deletion_pipeline")
        self.page_chunk_collection = init_lecture_unit_page_chunk_schema(client)
        self.transcription_collection = init_lecture_transcription_schema(client)
        self.lecture_unit_segment_summary_collection = init_lecture_unit_segment_schema(
            client
        )
        self.lecture_unit_collection = init_lecture_unit_schema(client)
        self.lecture_units = lecture_units
        self.artemis_base_url = artemis_base_url
        self.callback = callback

    @observe(name="Lecture Unit Deletion Pipeline")
    def __call__(self) -> None:
        self.callback.in_progress("deleting lecture units...")
        self.delete_entries_for_lecture_units()
        self.callback.done("lecture unit deletion done")

    def delete_entries_for_lecture_units(self):
        try:
            for lecture_unit in self.lecture_units:
                self.delete_page_chunk(lecture_unit)

                self.delete_transcriptions(lecture_unit)

                self.delete_lecture_unit_segments(lecture_unit)

                self.delete_lecture_unit(lecture_unit)
            self.callback.done("Lecture unit removed")
        except Exception as e:
            logger.error("Error deleting lecture unit: %s", e)
            self.callback.error("Error while removing old slides")
            return False

    def _delete_with_filter(
        self, collection, schema, lecture_unit: LectureUnitPageDTO, log_context: str
    ):
        """
        Delete a collection from the database
        """
        try:
            collection.data.delete_many(
                where=Filter.by_property(schema.BASE_URL.value).equal(
                    self.artemis_base_url
                )
                & Filter.by_property(schema.COURSE_ID.value).equal(
                    lecture_unit.course_id
                )
                & Filter.by_property(schema.LECTURE_ID.value).equal(
                    lecture_unit.lecture_id
                )
                & Filter.by_property(schema.LECTURE_UNIT_ID.value).equal(
                    lecture_unit.lecture_unit_id
                )
            )
            logger.info("%s deleted successfully", log_context)
            return True
        except Exception as e:
            logger.error(f"Error deleting {log_context}: %s", e, exc_info=True)
            return False

    def delete_page_chunk(self, lecture_unit: LectureUnitPageDTO):
        """
        Delete a page chunk from the database
        """
        return self._delete_with_filter(
            self.page_chunk_collection,
            LectureUnitPageChunkSchema,
            lecture_unit,
            "Page chunks",
        )

    def delete_transcriptions(self, lecture_unit: LectureUnitPageDTO):
        """
        Delete the transcription from the database
        """
        return self._delete_with_filter(
            self.transcription_collection,
            LectureTranscriptionSchema,
            lecture_unit,
            "Transcriptions",
        )

    def delete_lecture_unit_segments(self, lecture_unit: LectureUnitPageDTO):
        """
        Delete the lecture unit segments from the database
        """
        return self._delete_with_filter(
            self.lecture_unit_segment_summary_collection,
            LectureUnitSegmentSchema,
            lecture_unit,
            "Lecture unit segments",
        )

    def delete_lecture_unit(self, lecture_unit: LectureUnitPageDTO):
        """
        Delete the lecture unit from the database
        """
        return self._delete_with_filter(
            self.lecture_unit_collection,
            LectureUnitSchema,
            lecture_unit,
            "Lecture units",
        )

    @classmethod
    def get_variants(cls) -> List[LectureUnitDeletionVariant]:
        return [
            LectureUnitDeletionVariant(
                variant_id="default",
                name="Default",
                description="Standard lecture unit deletion with no model requirements.",
            ),
        ]
