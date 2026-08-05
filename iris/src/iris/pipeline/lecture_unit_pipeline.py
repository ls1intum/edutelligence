from threading import Event
from typing import Optional

from weaviate.classes.query import Filter

from iris.common.cancellation import raise_if_cancelled
from iris.domain.lecture.lecture_unit_dto import LectureUnitDTO
from iris.llm import LlmRequestHandler
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
from iris.web.status.status_update import StatusCallback


class LectureUnitPipeline(SubPipeline):
    """LectureUnitPipeline processes lecture unit data by generating summaries and embeddings,
    then updating the vector database with the processed lecture unit information.
    """

    def __init__(
        self,
        local: bool = False,
        callback: Optional[StatusCallback] = None,
        cancel_event: Optional[Event] = None,
    ):
        super().__init__(implementation_id="lecture_unit_pipeline")
        vector_database = VectorDatabase()
        self.weaviate_client = vector_database.get_client()
        self.lecture_unit_collection = init_lecture_unit_schema(self.weaviate_client)
        self.local = local
        self.callback = callback
        self.cancel_event = cancel_event
        embedding_model = resolve_model(
            "lecture_unit_pipeline", "default", "embedding", local=local
        )
        self.llm_embedding = LlmRequestHandler(embedding_model)

    @staticmethod
    def fetch_existing_properties(client, lecture_unit: LectureUnitDTO) -> dict:
        """Read the current unit properties without constructing the embedding stack."""
        collection = init_lecture_unit_schema(client)
        lecture_unit_filter = LectureUnitPipeline._filter(lecture_unit)
        existing_units = collection.query.fetch_objects(
            filters=lecture_unit_filter, limit=1
        ).objects
        return existing_units[0].properties if existing_units else {}

    @staticmethod
    def _filter(lecture_unit: LectureUnitDTO):
        return (
            Filter.by_property(LectureUnitSchema.COURSE_ID.value).equal(
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
            )
        )

    @observe(name="Lecture Unit Pipeline")
    def __call__(
        self,
        lecture_unit: LectureUnitDTO,
        initial_properties: Optional[dict] = None,
    ):
        if initial_properties is None:
            lecture_unit_filter = self._filter(lecture_unit)
            initial_units = self.lecture_unit_collection.query.fetch_objects(
                filters=lecture_unit_filter, limit=1
            ).objects
            initial_properties = initial_units[0].properties if initial_units else {}

        segment_pipeline = LectureUnitSegmentSummaryPipeline(
            self.weaviate_client,
            lecture_unit,
            local=self.local,
            callback=self.callback,
            cancel_event=self.cancel_event,
        )
        lecture_unit_segment_summaries, token_unit_segment_summary = segment_pipeline()

        tokens_unit_summary, embedding = self.prepare_replacement(
            lecture_unit,
            lecture_unit_segment_summaries,
        )
        self.commit_prepared_replacement(lecture_unit, initial_properties, embedding)

        return tokens_unit_summary + token_unit_segment_summary

    def prepare_replacement(
        self,
        lecture_unit: LectureUnitDTO,
        lecture_unit_segment_summaries: list[str],
    ) -> tuple[list, list[float]]:
        """Build the unit summary and embedding outside the commit lock."""
        raise_if_cancelled(
            self.cancel_event, lecture_unit.lecture_unit_id, "lecture unit summary"
        )
        lecture_unit.lecture_unit_summary, tokens_unit_summary = (
            LectureUnitSummaryPipeline(
                self.weaviate_client,
                lecture_unit,
                lecture_unit_segment_summaries,
                local=self.local,
            )()
        )

        raise_if_cancelled(
            self.cancel_event, lecture_unit.lecture_unit_id, "lecture unit embedding"
        )
        embedding = self.llm_embedding.embed(lecture_unit.lecture_unit_summary)
        return tokens_unit_summary, embedding

    def commit_prepared_replacement(
        self,
        lecture_unit: LectureUnitDTO,
        initial_properties: dict,
        embedding: list[float],
    ) -> None:
        """Replace the lecture unit while preserving latest metadata and visibility."""
        lecture_unit_filter = self._filter(lecture_unit)
        raise_if_cancelled(
            self.cancel_event, lecture_unit.lecture_unit_id, "lecture unit replacement"
        )
        with batch_update_lock:
            latest_units = self.lecture_unit_collection.query.fetch_objects(
                filters=lecture_unit_filter, limit=1
            ).objects
            latest_properties = latest_units[0].properties if latest_units else {}

            def metadata_value(property_name: str, incoming_value):
                """Keep metadata updated while this expensive re-ingestion was running."""
                initial_value = initial_properties.get(property_name)
                latest_value = latest_properties.get(property_name)
                return latest_value if latest_value != initial_value else incoming_value

            self.lecture_unit_collection.data.delete_many(where=lecture_unit_filter)
            self.lecture_unit_collection.data.insert(
                properties={
                    LectureUnitSchema.COURSE_ID.value: lecture_unit.course_id,
                    LectureUnitSchema.COURSE_NAME.value: metadata_value(
                        LectureUnitSchema.COURSE_NAME.value, lecture_unit.course_name
                    ),
                    LectureUnitSchema.COURSE_DESCRIPTION.value: metadata_value(
                        LectureUnitSchema.COURSE_DESCRIPTION.value,
                        lecture_unit.course_description,
                    ),
                    LectureUnitSchema.LECTURE_ID.value: lecture_unit.lecture_id,
                    LectureUnitSchema.LECTURE_NAME.value: metadata_value(
                        LectureUnitSchema.LECTURE_NAME.value, lecture_unit.lecture_name
                    ),
                    LectureUnitSchema.LECTURE_UNIT_ID.value: lecture_unit.lecture_unit_id,
                    LectureUnitSchema.LECTURE_UNIT_NAME.value: metadata_value(
                        LectureUnitSchema.LECTURE_UNIT_NAME.value,
                        lecture_unit.lecture_unit_name,
                    ),
                    LectureUnitSchema.LECTURE_UNIT_LINK.value: metadata_value(
                        LectureUnitSchema.LECTURE_UNIT_LINK.value,
                        lecture_unit.lecture_unit_link,
                    ),
                    LectureUnitSchema.VIDEO_LINK.value: metadata_value(
                        LectureUnitSchema.VIDEO_LINK.value, lecture_unit.video_link
                    ),
                    LectureUnitSchema.BASE_URL.value: lecture_unit.base_url,
                    LectureUnitSchema.LECTURE_UNIT_SUMMARY.value: lecture_unit.lecture_unit_summary,
                    LectureUnitSchema.RELEASE_DATE.value: latest_properties.get(
                        LectureUnitSchema.RELEASE_DATE.value
                    ),
                    LectureUnitSchema.SLIDE_VISIBILITY.value: latest_properties.get(
                        LectureUnitSchema.SLIDE_VISIBILITY.value, "{}"
                    ),
                },
                vector=embedding,
            )
