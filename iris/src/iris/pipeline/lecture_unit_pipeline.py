from typing import Optional

from weaviate.classes.query import Filter

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
from iris.vector_database.batch_verify import purge_other_rows
from iris.vector_database.database import VectorDatabase, batch_update_lock
from iris.vector_database.lecture_unit_schema import (
    LectureUnitSchema,
    init_lecture_unit_schema,
)
from iris.vector_database.write_retry import WeaviateWriteRetry
from iris.web.status.status_update import StatusCallback

logger = get_logger(__name__)


class LectureUnitPipeline(SubPipeline):
    """LectureUnitPipeline processes lecture unit data by generating summaries and embeddings,
    then updating the vector database with the processed lecture unit information.
    """

    def __init__(self, local: bool = False, callback: Optional[StatusCallback] = None):
        super().__init__(implementation_id="lecture_unit_pipeline")
        vector_database = VectorDatabase()
        self.weaviate_client = vector_database.get_client()
        self.lecture_unit_collection = init_lecture_unit_schema(self.weaviate_client)
        self.local = local
        self.callback = callback
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

    def _try_reuse_stored_summary(
        self, lecture_unit: LectureUnitDTO, lecture_unit_filter
    ) -> Optional[tuple]:
        """Reuse the stored summary and vector when it provably fits the content.

        Only allowed when every content sub-pipeline structurally skipped this
        run AND the stored row's fingerprint stamp equals the current content
        fingerprint: same inputs, already summarized, already embedded. This is
        what makes a metadata-only or reconcile re-dispatch of an unchanged
        unit cost zero LLM calls. Any doubt falls through to a full recompute.
        """
        if not lecture_unit.content_unchanged or not lecture_unit.content_fingerprint:
            return None
        stored_rows = self.lecture_unit_collection.query.fetch_objects(
            filters=lecture_unit_filter, limit=1, include_vector=True
        ).objects
        if not stored_rows:
            return None
        stored = stored_rows[0]
        if (
            stored.properties.get(LectureUnitSchema.CONTENT_FINGERPRINT.value)
            != lecture_unit.content_fingerprint
        ):
            return None
        summary = stored.properties.get(LectureUnitSchema.LECTURE_UNIT_SUMMARY.value)
        vector = stored.vector
        if isinstance(vector, dict):
            vector = vector.get("default") or next(iter(vector.values()), None)
        if not summary or not vector:
            return None
        return summary, vector

    @observe(name="Lecture Unit Pipeline")
    def __call__(
        self,
        lecture_unit: LectureUnitDTO,
        initial_properties: Optional[dict] = None,
    ):
        lecture_unit_filter = self._filter(lecture_unit)
        if initial_properties is None:
            initial_units = self.lecture_unit_collection.query.fetch_objects(
                filters=lecture_unit_filter, limit=1
            ).objects
            initial_properties = initial_units[0].properties if initial_units else {}

        reused = self._try_reuse_stored_summary(lecture_unit, lecture_unit_filter)
        if reused is not None:
            lecture_unit.lecture_unit_summary, embedding = reused
            tokens = []
            logger.info(
                "[unit %d] Content unchanged and fingerprint stamp matches, "
                "reusing the stored unit summary and vector",
                lecture_unit.lecture_unit_id,
            )
        else:
            lecture_unit_segment_summaries, token_unit_segment_summary = (
                LectureUnitSegmentSummaryPipeline(
                    self.weaviate_client,
                    lecture_unit,
                    local=self.local,
                    callback=self.callback,
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
            embedding = self.llm_embedding.embed(lecture_unit.lecture_unit_summary)
            tokens = tokens_unit_summary + token_unit_segment_summary

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

            def ledger_value(property_name: str, incoming_value):
                """Preserve the stored ledger value when this run did not recompute it."""
                if incoming_value is not None:
                    return incoming_value
                return latest_properties.get(property_name)

            # Write-new-then-sweep: insert this run's row first, then remove
            # every other row of the unit (previous generation, duplicates,
            # legacy rows). A crash between the two leaves a duplicate that the
            # next run's sweep and the audit's row-count check both catch,
            # instead of a window with no unit row at all. Both halves retry a
            # transient store condition in place rather than failing the run.
            retry = WeaviateWriteRetry.for_request()
            unit_row_properties = {
                LectureUnitSchema.COURSE_ID.value: lecture_unit.course_id,
                LectureUnitSchema.COURSE_NAME.value: metadata_value(
                    LectureUnitSchema.COURSE_NAME.value, lecture_unit.course_name
                ),
                LectureUnitSchema.COURSE_DESCRIPTION.value: metadata_value(
                    LectureUnitSchema.COURSE_DESCRIPTION.value,
                    lecture_unit.course_description,
                ),
                # The resolved language this run ingested under; the reconciler
                # compares it against the course's declared language to detect a
                # unit ingested in the wrong language and re-ingest it.
                LectureUnitSchema.COURSE_LANGUAGE.value: lecture_unit.course_language,
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
                LectureUnitSchema.CONTENT_FINGERPRINT.value: lecture_unit.content_fingerprint,
                LectureUnitSchema.INGESTION_RUN_ID.value: lecture_unit.ingestion_run_id,
                LectureUnitSchema.EXPECTED_CHUNK_COUNTS.value: ledger_value(
                    LectureUnitSchema.EXPECTED_CHUNK_COUNTS.value,
                    lecture_unit.expected_chunk_counts_json,
                ),
                LectureUnitSchema.PIPELINE_VERSION.value: ledger_value(
                    LectureUnitSchema.PIPELINE_VERSION.value,
                    lecture_unit.pipeline_version,
                ),
                LectureUnitSchema.QUALITY_SCORE.value: ledger_value(
                    LectureUnitSchema.QUALITY_SCORE.value,
                    lecture_unit.quality_score,
                ),
                LectureUnitSchema.QUALITY_FLAGS.value: ledger_value(
                    LectureUnitSchema.QUALITY_FLAGS.value,
                    lecture_unit.quality_flags_json,
                ),
            }
            new_uuid = retry.run(
                lambda: self.lecture_unit_collection.data.insert(
                    properties=unit_row_properties, vector=embedding
                ),
                description=f"unit row of lecture unit {lecture_unit.lecture_unit_id}",
            )
            # Keep the row just written and purge every other unit row by unit
            # identity: previous generations, legacy rows, and index-only ghost
            # rows that a delete-by-id or delete-by-run-id cannot reach. Writing
            # the new row first keeps the unit from ever losing its row on a crash.
            purge_other_rows(
                self.lecture_unit_collection,
                lecture_unit_filter,
                [new_uuid],
                f"unit row of lecture unit {lecture_unit.lecture_unit_id}",
                retry=retry,
            )

        return tokens
