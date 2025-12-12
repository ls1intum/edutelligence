from weaviate.classes.query import Filter

from iris.domain.lecture.lecture_unit_dto import LectureUnitDTO
from iris.llm import ModelVersionRequestHandler
from iris.llm.llm_configuration import resolve_model
from iris.pipeline.lecture_unit_segment_summary_pipeline import (
    LectureUnitSegmentSummaryPipeline,
)
from iris.pipeline.lecture_unit_summary_pipeline import (
    LectureUnitSummaryPipeline,
)
from iris.pipeline.sub_pipeline import SubPipeline
from iris.tracing import observe
from iris.vector_database.database import VectorDatabase, batch_update_lock
from iris.vector_database.lecture_unit_schema import (
    LectureUnitSchema,
    init_lecture_unit_schema,
)


class LectureUnitPipeline(SubPipeline):
    """LectureUnitPipeline processes lecture unit data by generating summaries and embeddings,
    then updating the vector database with the processed lecture unit information.
    """

    def __init__(self, local: bool = False):
        super().__init__(implementation_id="lecture_unit_pipeline")
        vector_database = VectorDatabase()
        self.weaviate_client = vector_database.get_client()
        self.lecture_unit_collection = init_lecture_unit_schema(self.weaviate_client)
        self.local = local
        embedding_model = resolve_model(
            "lecture_unit_pipeline", "default", "embedding", local=local
        )
        self.llm_embedding = ModelVersionRequestHandler(embedding_model)

    @observe(name="Lecture Unit Pipeline")
    def __call__(self, lecture_unit: LectureUnitDTO):
        lecture_unit_segment_summaries, token_unit_segment_summary = (
            LectureUnitSegmentSummaryPipeline(
                self.weaviate_client, lecture_unit, local=self.local
            )()
        )
        lecture_unit.lecture_unit_summary, tokens_unit_summary = (
            LectureUnitSummaryPipeline(
                self.weaviate_client,
                lecture_unit,
                lecture_unit_segment_summaries,
                local=self.local,
            )()
        )

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
                    LectureUnitSchema.VIDEO_LINK.value: lecture_unit.video_link,
                    LectureUnitSchema.BASE_URL.value: lecture_unit.base_url,
                    LectureUnitSchema.LECTURE_UNIT_SUMMARY.value: lecture_unit.lecture_unit_summary,
                },
                vector=embedding,
            )

        return tokens_unit_summary + token_unit_segment_summary
