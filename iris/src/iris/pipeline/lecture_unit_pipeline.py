from threading import Event
from typing import Optional

from weaviate.classes.query import Filter

from iris.common.cancellation import raise_if_cancelled
from iris.common.logging_config import get_logger
from iris.config import settings
from iris.domain.lecture.lecture_unit_dto import LectureUnitDTO
from iris.ingestion.ingestion_job_handler import ingestion_job_handler
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
from iris.vector_database.write_retry import WeaviateWriteRetry
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

    def _try_reuse_stored_summary(
        self, lecture_unit: LectureUnitDTO, lecture_unit_filter
    ) -> Optional[tuple]:
        """Reuse the stored summary and vector when it provably fits the content.

        Only allowed when every content sub-pipeline structurally skipped this
        run AND the stored row's fingerprint stamp equals the current content
        fingerprint: same inputs, already summarized, already embedded. This is
        what makes a metadata-only or reconcile re-dispatch of an unchanged
        unit cost zero LLM calls. Any doubt falls through to a full recompute.

        A unit row written before fingerprints existed has no stamp. Its summary
        is reused only while every row of the unit predates the stamps too: the
        slide summaries it was built from, and the page chunks and transcript rows
        the content sub-pipelines just proved unchanged. Once any of them was
        written again (a slide summary regenerated, or a PDF or transcript
        replaced by a run that then failed before its summaries), the old unit
        summary no longer matches them.
        """
        if not lecture_unit.content_unchanged or not lecture_unit.content_fingerprint:
            return None
        stored_rows = self.lecture_unit_collection.query.fetch_objects(
            filters=lecture_unit_filter, limit=1, include_vector=True
        ).objects
        if not stored_rows:
            return None
        stored = stored_rows[0]
        stored_fingerprint = stored.properties.get(
            LectureUnitSchema.CONTENT_FINGERPRINT.value
        )
        if stored_fingerprint is None:
            if not self._all_unit_rows_unstamped(lecture_unit):
                return None
        elif stored_fingerprint != lecture_unit.content_fingerprint:
            return None
        summary = stored.properties.get(LectureUnitSchema.LECTURE_UNIT_SUMMARY.value)
        vector = stored.vector
        if isinstance(vector, dict):
            vector = vector.get("default") or next(iter(vector.values()), None)
        if not summary or not vector:
            return None
        return summary, vector

    def _all_unit_rows_unstamped(self, lecture_unit: LectureUnitDTO) -> bool:
        """Whether the unit still has source rows and no slide summary, page chunk or
        transcript row of it was written by a current run.

        Without any page chunk or transcript row, the old summary describes content
        that is gone: a run that removed the unit's last PDF or transcript and then
        failed must not leave it for the retry, which finds three empty collections.
        """
        segments_unstamped, _ = self._unit_rows_unstamped(
            lecture_unit,
            init_lecture_unit_segment_schema,
            LectureUnitSegmentSchema,
            LectureUnitSegmentSchema.CONTENT_FINGERPRINT,
        )
        chunks_unstamped, chunk_count = self._unit_rows_unstamped(
            lecture_unit,
            init_lecture_unit_page_chunk_schema,
            LectureUnitPageChunkSchema,
            LectureUnitPageChunkSchema.INGESTION_RUN_ID,
        )
        transcript_unstamped, transcript_count = self._unit_rows_unstamped(
            lecture_unit,
            init_lecture_transcription_schema,
            LectureTranscriptionSchema,
            LectureTranscriptionSchema.INGESTION_RUN_ID,
        )
        return (
            segments_unstamped
            and chunks_unstamped
            and transcript_unstamped
            and chunk_count + transcript_count > 0
        )

    def _unit_rows_unstamped(
        self, lecture_unit: LectureUnitDTO, init_schema, schema, stamp
    ) -> tuple[bool, int]:
        """Whether every row of the unit in one collection lacks the given stamp, and how many rows it has."""
        collection = init_schema(self.weaviate_client)
        unit_filter = (
            Filter.by_property(schema.COURSE_ID.value).equal(lecture_unit.course_id)
            & Filter.by_property(schema.LECTURE_ID.value).equal(lecture_unit.lecture_id)
            & Filter.by_property(schema.LECTURE_UNIT_ID.value).equal(
                lecture_unit.lecture_unit_id
            )
            & Filter.by_property(schema.BASE_URL.value).equal(lecture_unit.base_url)
        )
        limit = settings.lecture_ingestion.skip_check_fetch_limit
        rows = collection.query.fetch_objects(
            filters=unit_filter, limit=limit, return_properties=[stamp.value]
        ).objects
        if len(rows) >= limit:
            return False, len(rows)
        return all(row.properties.get(stamp.value) is None for row in rows), len(rows)

    @observe(name="Lecture Unit Pipeline")
    def __call__(
        self,
        lecture_unit: LectureUnitDTO,
        initial_properties: Optional[dict] = None,
    ):
        cancel_event = self.cancel_event
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
                    cancel_event=cancel_event,
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
            raise_if_cancelled(
                cancel_event, lecture_unit.lecture_unit_id, "lecture unit embedding"
            )
            embedding = self.llm_embedding.embed(lecture_unit.lecture_unit_summary)
            tokens = tokens_unit_summary + token_unit_segment_summary

        job_handler = getattr(self, "job_handler", ingestion_job_handler)

        with batch_update_lock:
            with job_handler.current_job_guard(
                lecture_unit.base_url,
                lecture_unit.course_id,
                lecture_unit.lecture_id,
                lecture_unit.lecture_unit_id,
                cancel_event,
                "lecture unit replacement",
            ):
                latest_units = self.lecture_unit_collection.query.fetch_objects(
                    filters=lecture_unit_filter, limit=1
                ).objects
                latest_properties = latest_units[0].properties if latest_units else {}

                def metadata_value(property_name: str, incoming_value):
                    """Keep metadata updated while this expensive re-ingestion was running."""
                    initial_value = initial_properties.get(property_name)
                    latest_value = latest_properties.get(property_name)
                    return (
                        latest_value
                        if latest_value != initial_value
                        else incoming_value
                    )

                def ledger_value(property_name: str, incoming_value):
                    """Preserve the stored ledger value when this run did not recompute it."""
                    if incoming_value is not None:
                        return incoming_value
                    return latest_properties.get(property_name)

                # A dispatch without a PDF purged every page chunk, so the page ledger
                # must say so: an empty manifest and no PDF quality verdict. Keeping the
                # stored values is only right when the PDF was present but skipped;
                # for a removed PDF it would leave the census reporting a chunk
                # expectation the index can never meet.
                if lecture_unit.has_pdf:
                    expected_chunk_counts = ledger_value(
                        LectureUnitSchema.EXPECTED_CHUNK_COUNTS.value,
                        lecture_unit.expected_chunk_counts_json,
                    )
                    quality_score = ledger_value(
                        LectureUnitSchema.QUALITY_SCORE.value,
                        lecture_unit.quality_score,
                    )
                    quality_flags = ledger_value(
                        LectureUnitSchema.QUALITY_FLAGS.value,
                        lecture_unit.quality_flags_json,
                    )
                else:
                    expected_chunk_counts = "{}"
                    quality_score = None
                    quality_flags = None

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
                    LectureUnitSchema.EXPECTED_CHUNK_COUNTS.value: expected_chunk_counts,
                    LectureUnitSchema.PIPELINE_VERSION.value: ledger_value(
                        LectureUnitSchema.PIPELINE_VERSION.value,
                        lecture_unit.pipeline_version,
                    ),
                    LectureUnitSchema.QUALITY_SCORE.value: quality_score,
                    LectureUnitSchema.QUALITY_FLAGS.value: quality_flags,
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
