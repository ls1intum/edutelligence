from typing import List

from weaviate import WeaviateClient
from weaviate.classes.query import Filter

from iris.common.logging_config import get_logger
from iris.domain.data.lecture_unit_page_dto import LectureUnitPageDTO
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


class LectureUnitDeletionPipeline(Pipeline):
    """LectureUnitDeletionPipeline deletes weaviate entries from page chunks,
    transcriptions and lecture unit segments."""

    PIPELINE_ID = "lecture_unit_deletion_pipeline"
    ROLES: set[str] = set()
    VARIANT_DEFS = [
        (
            "default",
            "Default",
            "Standard lecture unit deletion with no model requirements.",
        ),
    ]

    def __init__(
        self,
        client: WeaviateClient,
        lecture_units: List[LectureUnitPageDTO],
        artemis_base_url: str,
        callback: LecturesDeletionStatusCallback,
    ):
        super().__init__(implementation_id=self.PIPELINE_ID)
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
        self.callback.update()
        if self.delete_entries_for_lecture_units():
            self.callback.finish()
        else:
            self.callback.fail("Error while removing old slides")

    def delete_entries_for_lecture_units(self):
        all_succeeded = True
        delete_steps = (
            (self.delete_page_chunk, "page chunks"),
            (self.delete_transcriptions, "transcriptions"),
            (self.delete_lecture_unit_segments, "lecture unit segments"),
            (self.delete_lecture_unit, "lecture units"),
        )
        for lecture_unit in self.lecture_units:
            unit_succeeded = True
            for delete_step, label in delete_steps:
                try:
                    if not delete_step(lecture_unit):
                        unit_succeeded = False
                except Exception as e:
                    logger.error("Error deleting %s: %s", label, e, exc_info=True)
                    unit_succeeded = False
            all_succeeded = all_succeeded and unit_succeeded
        return all_succeeded

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
            logger.error("Error deleting %s: %s", log_context, e, exc_info=True)
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
