from app import VectorDatabase, batch_update_lock
from weaviate.classes.query import Filter

from src.iris.domain.lecture.lecture_unit_dto import LectureUnitDTO
from src.iris.llm import BasicRequestHandler
from src.iris.pipeline import Pipeline
from src.iris.pipeline.lecture_unit_segment_summary_pipeline import (
    LectureUnitSegmentSummaryPipeline,
)
from src.iris.pipeline.lecture_unit_summary_pipeline import LectureUnitSummaryPipeline
from src.iris.vector_database.lecture_unit_schema import (
    LectureUnitSchema,
    init_lecture_unit_schema,
)


class LectureUnitPipeline(Pipeline):
    def __init__(self):
        super().__init__()
        vector_database = VectorDatabase()
        self.weaviate_client = vector_database.get_client()
        self.lecture_unit_collection = init_lecture_unit_schema(self.weaviate_client)
        self.llm_embedding = BasicRequestHandler("embedding-small")

    def __call__(self, lecture_unit: LectureUnitDTO):
        lecture_unit_segment_summaries = LectureUnitSegmentSummaryPipeline(
            self.weaviate_client, lecture_unit
        )()
        lecture_unit.lecture_unit_summary = LectureUnitSummaryPipeline(
            self.weaviate_client, lecture_unit, lecture_unit_segment_summaries
        )()

        # Delete existing lecture unit
        self.lecture_unit_collection.data.delete_many(
            where=Filter.by_property(LectureUnitSchema.COURSE_ID.value).equal(
                lecture_unit.course_id
            )
            & Filter.by_property(LectureUnitSchema.LECTURE_ID.value).equal(
                lecture_unit.lecture_id
            )
            & Filter.by_property(LectureUnitSchema.LECTURE_UNIT_ID.value).equal(
                lecture_unit.lecture_unit_id
            )
            & Filter.by_property(LectureUnitSchema.BASE_URL.value).equal(
                lecture_unit.base_url
            ),
        )

        embedding = self.llm_embedding.embed(lecture_unit.lecture_unit_summary)

        with batch_update_lock:
            self.lecture_unit_collection.data.insert(
                properties={
                    LectureUnitSchema.COURSE_ID.value: lecture_unit.course_id,
                    LectureUnitSchema.COURSE_NAME.value: lecture_unit.course_name,
                    LectureUnitSchema.COURSE_DESCRIPTION.value: lecture_unit.course_description,
                    LectureUnitSchema.LECTURE_ID.value: lecture_unit.lecture_id,
                    LectureUnitSchema.LECTURE_NAME.value: lecture_unit.lecture_name,
                    LectureUnitSchema.LECTURE_UNIT_ID.value: lecture_unit.lecture_unit_id,
                    LectureUnitSchema.LECTURE_UNIT_NAME.value: lecture_unit.lecture_unit_name,
                    LectureUnitSchema.LECTURE_UNIT_LINK.value: lecture_unit.lecture_unit_link,
                    LectureUnitSchema.BASE_URL.value: lecture_unit.base_url,
                    LectureUnitSchema.LECTURE_UNIT_SUMMARY.value: lecture_unit.lecture_unit_summary,
                },
                vector=embedding,
            )
