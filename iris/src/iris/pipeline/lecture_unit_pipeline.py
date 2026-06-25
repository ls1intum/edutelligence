from threading import Event
from typing import Optional

from weaviate.classes.query import Filter

from iris.common.custom_exceptions import IngestionCancelledException
from iris.common.logging_config import get_logger
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

logger = get_logger(__name__)


class LectureUnitPipeline(SubPipeline):
    """LectureUnitPipeline processes lecture unit data by generating summaries and embeddings,
    then updating the vector database with the processed lecture unit information.
    """

    def __init__(
        self,
        local: bool = False,
        callback: Optional[StatusCallback] = None,
        cancel_event: Optional[Event] = None,
        metadata_only: bool = False,
    ):
        super().__init__(implementation_id="lecture_unit_pipeline")
        vector_database = VectorDatabase()
        self.weaviate_client = vector_database.get_client()
        self.lecture_unit_collection = init_lecture_unit_schema(self.weaviate_client)
        self.local = local
        self.callback = callback
        self.cancel_event = cancel_event
        self.metadata_only = metadata_only
        embedding_model = resolve_model(
            "lecture_unit_pipeline", "default", "embedding", local=local
        )
        self.llm_embedding = LlmRequestHandler(embedding_model)

    def _check_cancellation(self):
        """Check if job has been cancelled."""
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise IngestionCancelledException(
                0, "Cancelled during lecture unit summary"
            )

    def _get_unit_filter(self, lecture_unit: LectureUnitDTO):
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

    def _build_properties(self, lecture_unit: LectureUnitDTO) -> dict:
        properties = {
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
        }
        if lecture_unit.release_date is not None:
            properties[LectureUnitSchema.RELEASE_DATE.value] = lecture_unit.release_date
        return properties

    def _update_metadata_only(self, lecture_unit: LectureUnitDTO) -> list:
        """Skip LLM summary regeneration and only update LectureUnits metadata.

        Fetches the existing summary text from Weaviate and re-embeds it with
        the updated metadata so the access filter and name fields stay current
        without burning LLM tokens on segment/unit summary regeneration.
        Falls back to the full pipeline if no existing entry is found.
        """
        existing = self.lecture_unit_collection.query.fetch_objects(
            filters=self._get_unit_filter(lecture_unit), limit=1
        ).objects

        if not existing:
            logger.info(
                "No existing LectureUnits entry for unit %d — falling back to full pipeline",
                lecture_unit.lecture_unit_id,
            )
            return self._run_full_pipeline(lecture_unit)

        existing_summary = existing[0].properties.get(
            LectureUnitSchema.LECTURE_UNIT_SUMMARY.value, ""
        )
        lecture_unit.lecture_unit_summary = existing_summary

        logger.info(
            "Metadata-only update for unit %d — skipping segment/unit summary LLM calls",
            lecture_unit.lecture_unit_id,
        )

        self._check_cancellation()
        embedding = self.llm_embedding.embed(existing_summary)

        with batch_update_lock:
            self._check_cancellation()
            self.lecture_unit_collection.data.delete_many(
                where=self._get_unit_filter(lecture_unit)
            )
            self.lecture_unit_collection.data.insert(
                properties=self._build_properties(lecture_unit),
                vector=embedding,
            )

        return []

    def _run_full_pipeline(self, lecture_unit: LectureUnitDTO) -> list:
        """Run full segment + unit summary generation and update LectureUnits."""
        self._check_cancellation()

        lecture_unit_segment_summaries, token_unit_segment_summary = (
            LectureUnitSegmentSummaryPipeline(
                self.weaviate_client,
                lecture_unit,
                local=self.local,
                callback=self.callback,
                cancel_event=self.cancel_event,
            )()
        )

        self._check_cancellation()

        lecture_unit.lecture_unit_summary, tokens_unit_summary = (
            LectureUnitSummaryPipeline(
                self.weaviate_client,
                lecture_unit,
                lecture_unit_segment_summaries,
                local=self.local,
            )()
        )

        self._check_cancellation()

        # Generate embedding (cancellable, outside lock for efficiency)
        embedding = self.llm_embedding.embed(lecture_unit.lecture_unit_summary)

        # Final check before atomic DELETE + INSERT operation
        self._check_cancellation()

        # Atomic DELETE + INSERT - both in lock to prevent race conditions
        # No cancellation check between DELETE and INSERT!
        with batch_update_lock:
            self._check_cancellation()
            self.lecture_unit_collection.data.delete_many(
                where=self._get_unit_filter(lecture_unit)
            )
            self.lecture_unit_collection.data.insert(
                properties=self._build_properties(lecture_unit),
                vector=embedding,
            )

        return tokens_unit_summary + token_unit_segment_summary

    @observe(name="Lecture Unit Pipeline")
    def __call__(self, lecture_unit: LectureUnitDTO):
        if self.metadata_only:
            return self._update_metadata_only(lecture_unit)
        return self._run_full_pipeline(lecture_unit)
