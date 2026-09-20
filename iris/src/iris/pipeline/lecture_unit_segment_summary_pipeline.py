from threading import Event
from typing import Optional, Tuple

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from weaviate.classes.query import Filter
from weaviate.client import WeaviateClient
from weaviate.exceptions import UnexpectedStatusCodeError
from weaviate.util import generate_uuid5

from iris.common.cancellation import raise_if_cancelled
from iris.common.ingestion_errors import (
    NO_INGESTIBLE_CONTENT,
    PAGE_RANGE_FETCH_CAPPED,
    IngestionStageError,
)
from iris.common.logging_config import get_logger
from iris.common.pipeline_enum import PipelineEnum
from iris.config import settings
from iris.domain.lecture.lecture_unit_dto import LectureUnitDTO
from iris.ingestion.ingestion_job_handler import ingestion_job_handler
from iris.llm import (
    CompletionArguments,
    LlmRequestHandler,
)
from iris.llm.langchain import IrisLangchainChatModel
from iris.llm.llm_configuration import resolve_model
from iris.pipeline.prompts.lecture_unit_segment_summary_prompt import (
    lecture_unit_segment_summary_prompt,
)
from iris.pipeline.sub_pipeline import SubPipeline
from iris.tracing import observe
from iris.vector_database.batch_verify import (
    confirmed_rows,
    delete_many_with_retry,
    fetch_with_retry,
)
from iris.vector_database.database import batch_update_lock
from iris.vector_database.lecture_transcription_schema import (
    LectureTranscriptionSchema,
    init_lecture_transcription_schema,
)
from iris.vector_database.lecture_unit_page_chunk_schema import (
    LectureUnitPageChunkSchema,
    init_lecture_unit_page_chunk_schema,
)
from iris.vector_database.lecture_unit_segment_schema import (
    LectureUnitSegmentSchema,
    init_lecture_unit_segment_schema,
)
from iris.vector_database.write_retry import WeaviateWriteRetry
from iris.web.status.status_update import StatusCallback

logger = get_logger(__name__)


class LectureUnitSegmentSummaryPipeline(SubPipeline):
    """LectureUnitSegmentSummaryPipeline processes lecture unit segments by summarizing the transcription and slide
     content.

    It combines lecture transcriptions and slide text to generate a summary that is then used for further processing or
     storage.
    """

    llm: IrisLangchainChatModel
    pipeline: Runnable
    prompt: ChatPromptTemplate

    def __init__(
        self,
        client: WeaviateClient,
        lecture_unit_dto: LectureUnitDTO,
        local: bool = False,
        callback: Optional[StatusCallback] = None,
        cancel_event: Optional[Event] = None,
    ) -> None:
        super().__init__(implementation_id="lecture_unit_segment_summary_pipeline")
        self.weaviate_client = client
        self.lecture_unit_dto = lecture_unit_dto
        self.callback = callback
        self.cancel_event = cancel_event

        self.lecture_unit_segment_collection = init_lecture_unit_segment_schema(client)
        self.lecture_transcription_collection = init_lecture_transcription_schema(
            client
        )
        self.lecture_unit_page_chunk_collection = init_lecture_unit_page_chunk_schema(
            client
        )

        pipeline_id = "lecture_unit_segment_summary_pipeline"
        embedding_model = resolve_model(
            pipeline_id, "default", "embedding", local=False
        )
        chat_model = resolve_model(pipeline_id, "default", "chat", local=local)

        self.llm_embedding = LlmRequestHandler(embedding_model)

        request_handler = LlmRequestHandler(model_id=chat_model)
        completion_args = CompletionArguments(temperature=0, max_tokens=2000)
        self.llm = IrisLangchainChatModel(
            request_handler=request_handler, completion_args=completion_args
        )
        self.pipeline = self.llm | StrOutputParser()
        self.tokens = []

    @observe(name="Lecture Unit Segment Summary Pipeline")
    def __call__(self) -> [str]:
        # One shared retry budget for every segment write and the stale prune.
        self._retry = WeaviateWriteRetry.for_request()
        cancel_event = self.cancel_event
        slide_number_start, slide_number_end = self._get_slide_range()

        summaries = []
        written_uuids = []
        total_slides = slide_number_end - slide_number_start + 1
        for slide_index in range(slide_number_start, slide_number_end + 1):
            raise_if_cancelled(
                cancel_event,
                self.lecture_unit_dto.lecture_unit_id,
                "lecture unit segment summary",
            )
            if self.callback is not None:
                self.callback.update(
                    stage_name="segment-summaries",
                    stage_progress=slide_index - slide_number_start + 1,
                    stage_total=total_slides,
                )
            transcriptions = self._get_transcriptions(slide_index)
            # PAGE_NUMBER is unique at the PDF page level, but the ingestion pipeline
            # stores one object per page chunk after splitting the page text. That is
            # why this returns a list even though the logical slide/page is unique.
            slides = self._get_slides(slide_index)
            display_page_number = slide_index

            if len(slides) != 0:
                # A stored display number can be null on legacy chunks (written
                # before the field existed), and .get(key, default) returns that
                # null rather than the default; int(None) would then crash the
                # whole segment stage. Fall back to the slide index when it is
                # absent or null.
                stored_display = slides[0].properties.get(
                    LectureUnitPageChunkSchema.DISPLAY_PAGE_NUMBER.value
                )
                display_page_number = (
                    int(stored_display) if stored_display is not None else slide_index
                )
                if display_page_number == -1:
                    transcriptions = []
                else:
                    transcriptions = self._get_transcriptions(display_page_number)

            summary = self._create_summary(transcriptions, slides)
            summaries.append(summary)
            hidden_until = (
                slides[0].properties.get(LectureUnitPageChunkSchema.HIDDEN_UNTIL.value)
                if slides
                else None
            )
            self._upsert_lecture_object(
                slide_index, summary, display_page_number, hidden_until
            )
            written_uuids.append(self._segment_uuid(slide_index))
        self._prune_stale_segments(slide_number_start, slide_number_end, written_uuids)
        return summaries, self.tokens

    def _prune_stale_segments(
        self, slide_number_start: int, slide_number_end: int, keep_uuids=()
    ):
        """Remove segments for slides that no longer exist.

        Segments are upserted per slide, so a unit whose PDF shrank would keep
        summaries for the removed slides forever without this sweep.

        Also removes any same-slide row that is not one of ``keep_uuids`` (the
        deterministic ids this run just upserted): a row written before the
        deterministic-uuid scheme existed used a random uuid for the same slide,
        so it falls inside the valid page range and would otherwise coexist with
        its replacement forever -- an upsert by a *different* id is never a
        replace, and this range check alone never looks at ids. Callers that
        don't pass ``keep_uuids`` (e.g. existing unit tests) get exactly the
        prior range-only behavior.
        """
        conditions = [
            Filter.by_property(LectureUnitSegmentSchema.PAGE_NUMBER.value).less_than(
                slide_number_start
            ),
            Filter.by_property(LectureUnitSegmentSchema.PAGE_NUMBER.value).greater_than(
                slide_number_end
            ),
        ]
        if keep_uuids:
            conditions.append(
                ~Filter.by_id().contains_any([str(uuid) for uuid in keep_uuids])
            )
        stale_filter = Filter.all_of(
            [
                self._get_segment_unit_filter(),
                Filter.any_of(conditions),
            ]
        )
        job_handler = getattr(self, "job_handler", ingestion_job_handler)
        with batch_update_lock:
            with job_handler.current_job_guard(
                self.lecture_unit_dto.base_url,
                self.lecture_unit_dto.course_id,
                self.lecture_unit_dto.lecture_id,
                self.lecture_unit_dto.lecture_unit_id,
                self.cancel_event,
                "lecture unit segment prune",
            ):
                delete_result = delete_many_with_retry(
                    self.lecture_unit_segment_collection,
                    stale_filter,
                    "stale lecture unit segments",
                    retry=getattr(self, "_retry", None),
                )
        if delete_result.matches:
            logger.info(
                "[%s / unit %d] Pruned %d stale segment(s) outside slides %d-%d",
                self.lecture_unit_dto.lecture_name,
                self.lecture_unit_dto.lecture_unit_id,
                delete_result.successful,
                slide_number_start,
                slide_number_end,
            )

    def _get_segment_unit_filter(self):
        segment_filter = Filter.by_property(
            LectureUnitSegmentSchema.COURSE_ID.value
        ).equal(self.lecture_unit_dto.course_id)
        segment_filter &= Filter.by_property(
            LectureUnitSegmentSchema.LECTURE_ID.value
        ).equal(self.lecture_unit_dto.lecture_id)
        segment_filter &= Filter.by_property(
            LectureUnitSegmentSchema.LECTURE_UNIT_ID.value
        ).equal(self.lecture_unit_dto.lecture_unit_id)
        if self.lecture_unit_dto.base_url is not None:
            segment_filter &= Filter.by_property(
                LectureUnitSegmentSchema.BASE_URL.value
            ).equal(self.lecture_unit_dto.base_url)
        return segment_filter

    def _get_transcriptions(self, slide_number: int):
        transcription_filter = self._get_lecture_transcription_filter()
        transcription_filter &= Filter.by_property(
            LectureTranscriptionSchema.PAGE_NUMBER.value
        ).equal(slide_number)
        return self.lecture_transcription_collection.query.fetch_objects(
            filters=transcription_filter
        ).objects

    def _get_slides(self, slide_number: int):
        slide_filter = self._get_lecture_slide_filter()
        slide_filter &= Filter.by_property(
            LectureUnitPageChunkSchema.PAGE_NUMBER.value
        ).equal(slide_number)
        return self.lecture_unit_page_chunk_collection.query.fetch_objects(
            filters=slide_filter
        ).objects

    def _get_slide_range(self) -> Tuple[int, int]:
        """Full page-number span of the unit, over every ghost-free chunk of every generation.

        Confirms scanned rows against the object store before deriving the range: a
        scan-visible-but-object-store-missing ghost row on an outlying page would
        otherwise expand the range, cause spurious segment summaries to be written
        for pages that don't exist, and make the final manifest-based audit fail on
        every retry, since a ghost can never be deleted.
        """
        slide_span = self._confirmed_page_number_span(
            self.lecture_unit_page_chunk_collection,
            self._get_lecture_slide_filter(),
            LectureUnitPageChunkSchema.PAGE_NUMBER.value,
        )
        if slide_span is not None:
            return slide_span

        transcript_span = self._confirmed_page_number_span(
            self.lecture_transcription_collection,
            self._get_lecture_transcription_filter(),
            LectureTranscriptionSchema.PAGE_NUMBER.value,
        )
        if transcript_span is not None:
            return transcript_span

        # Neither a page chunk nor a transcript row exists for this unit: there is
        # nothing to summarize. Silently proceeding used to write one placeholder
        # segment at page 0 and let the audit reject it with no indication of the
        # real cause; raising here fails the run explicitly and immediately, at
        # the same point the true problem (a corrupt or empty attachment, since
        # Artemis only checks the file extension, not that it has readable pages)
        # actually was.
        raise IngestionStageError(
            NO_INGESTIBLE_CONTENT,
            f"Lecture unit {self.lecture_unit_dto.lecture_unit_id} has no PDF "
            f"pages and no transcript; there is no content to summarize",
        )

    def _confirmed_page_number_span(
        self, collection, unit_filter, page_number_property
    ):
        """Object-store-confirmed (min, max) of a page-number property, or None when empty.

        Fetches rather than aggregates, unlike the raw min/max this replaced, because
        confirming against the object store needs the actual candidate ids; the fetch
        is bounded the same way confirmed_generations is elsewhere in this pipeline --
        a unit with more rows than that would mean an unrealistic page count.

        A capped scan raises rather than deriving a span from it: the limit counts rows,
        not pages, so the true minimum or maximum could sit in the untruncated remainder,
        which would silently write and prune the wrong segment span.
        """
        retry = getattr(self, "_retry", None)
        limit = settings.lecture_ingestion.skip_check_fetch_limit
        rows = fetch_with_retry(
            lambda: collection.query.fetch_objects(
                filters=unit_filter,
                limit=limit,
                return_properties=[page_number_property],
            ),
            retry=retry,
        ).objects
        if len(rows) >= limit:
            raise IngestionStageError(
                PAGE_RANGE_FETCH_CAPPED,
                f"Lecture unit {self.lecture_unit_dto.lecture_unit_id} has at least "
                f"{limit} rows for {page_number_property}; cannot confirm the true "
                f"page-number span from a capped scan",
            )
        confirmed = confirmed_rows(collection, rows, retry=retry)
        if not confirmed:
            return None
        numbers = [int(row.properties[page_number_property]) for row in confirmed]
        return min(numbers), max(numbers)

    def _get_lecture_slide_filter(self):
        slide_filter = Filter.by_property(
            LectureUnitPageChunkSchema.COURSE_ID.value
        ).equal(self.lecture_unit_dto.course_id)
        slide_filter &= Filter.by_property(
            LectureUnitPageChunkSchema.LECTURE_ID.value
        ).equal(self.lecture_unit_dto.lecture_id)
        slide_filter &= Filter.by_property(
            LectureUnitPageChunkSchema.LECTURE_UNIT_ID.value
        ).equal(self.lecture_unit_dto.lecture_unit_id)
        if self.lecture_unit_dto.base_url is not None:
            slide_filter &= Filter.by_property(
                LectureUnitPageChunkSchema.BASE_URL.value
            ).equal(self.lecture_unit_dto.base_url)
        return slide_filter

    def _get_lecture_transcription_filter(self):
        transcription_filter = Filter.by_property(
            LectureTranscriptionSchema.COURSE_ID.value
        ).equal(self.lecture_unit_dto.course_id)
        transcription_filter &= Filter.by_property(
            LectureTranscriptionSchema.LECTURE_ID.value
        ).equal(self.lecture_unit_dto.lecture_id)
        transcription_filter &= Filter.by_property(
            LectureTranscriptionSchema.LECTURE_UNIT_ID.value
        ).equal(self.lecture_unit_dto.lecture_unit_id)
        if self.lecture_unit_dto.base_url is not None:
            transcription_filter &= Filter.by_property(
                LectureTranscriptionSchema.BASE_URL.value
            ).equal(self.lecture_unit_dto.base_url)
        return transcription_filter

    def _create_summary(self, transcriptions, slides) -> str:
        transcriptions_slide_text = ""
        for transcription in transcriptions:
            transcriptions_slide_text += f"{transcription.properties[LectureTranscriptionSchema.SEGMENT_TEXT.value]}\n"

        slide_text = ""
        for slide in slides:
            slide_text += f"{slide.properties[LectureUnitPageChunkSchema.PAGE_TEXT_CONTENT.value]}\n"
        self.prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    lecture_unit_segment_summary_prompt(
                        self.lecture_unit_dto.lecture_name,
                        self.lecture_unit_dto.course_name,
                        transcription_content=transcriptions_slide_text,
                        slide_content=slide_text,
                    ),
                ),
            ]
        )
        formatted_prompt = self.prompt.format_messages()
        self.prompt = ChatPromptTemplate.from_messages(formatted_prompt)
        try:
            response = (self.prompt | self.pipeline).invoke({})
            self._append_tokens(
                self.llm.tokens, PipelineEnum.IRIS_LECTURE_SUMMARY_PIPELINE
            )
            return response
        except Exception as e:
            raise e

    def _segment_uuid(self, slide_number: int) -> str:
        """Deterministic id for a unit's slide segment.

        Deriving the id from the stable identity (base_url, course, lecture,
        unit, slide) makes the write idempotent: a retry after an ambiguous
        timeout — where the server actually committed the insert — replaces the
        same object instead of creating a duplicate row for the slide.
        """
        return generate_uuid5(
            {
                "base_url": self.lecture_unit_dto.base_url,
                "course_id": self.lecture_unit_dto.course_id,
                "lecture_id": self.lecture_unit_dto.lecture_id,
                "lecture_unit_id": self.lecture_unit_dto.lecture_unit_id,
                "page_number": slide_number,
            }
        )

    def _upsert_lecture_object(
        self,
        slide_number: int,
        summary: str,
        display_page_number: int,
        hidden_until=None,
    ):
        job_handler = getattr(self, "job_handler", ingestion_job_handler)
        retry = getattr(self, "_retry", None) or WeaviateWriteRetry.for_request()
        segment_uuid = self._segment_uuid(slide_number)
        properties = {
            LectureUnitSegmentSchema.COURSE_ID.value: self.lecture_unit_dto.course_id,
            LectureUnitSegmentSchema.LECTURE_ID.value: self.lecture_unit_dto.lecture_id,
            LectureUnitSegmentSchema.LECTURE_UNIT_ID.value: self.lecture_unit_dto.lecture_unit_id,
            LectureUnitSegmentSchema.SEGMENT_SUMMARY.value: summary,
            LectureUnitSegmentSchema.PAGE_NUMBER.value: slide_number,
            LectureUnitSegmentSchema.DISPLAY_PAGE_NUMBER.value: display_page_number,
            LectureUnitSegmentSchema.BASE_URL.value: self.lecture_unit_dto.base_url,
            LectureUnitSegmentSchema.HIDDEN_UNTIL.value: hidden_until,
            LectureUnitSegmentSchema.CONTENT_FINGERPRINT.value: self.lecture_unit_dto.content_fingerprint,
        }
        embedding = self.llm_embedding.embed(summary)

        def upsert():
            # Insert under the deterministic id; if it already exists (a prior
            # attempt landed, or a previous run wrote this slide) replace it in
            # place. Both paths are idempotent, so retrying is duplicate-safe.
            try:
                self.lecture_unit_segment_collection.data.insert(
                    uuid=segment_uuid, properties=properties, vector=embedding
                )
            except UnexpectedStatusCodeError as error:
                if "already exists" in str(error).lower():
                    self.lecture_unit_segment_collection.data.replace(
                        uuid=segment_uuid, properties=properties, vector=embedding
                    )
                else:
                    raise

        with batch_update_lock:
            with job_handler.current_job_guard(
                self.lecture_unit_dto.base_url,
                self.lecture_unit_dto.course_id,
                self.lecture_unit_dto.lecture_id,
                self.lecture_unit_dto.lecture_unit_id,
                self.cancel_event,
                "lecture unit segment write",
            ):
                retry.run(upsert, description=f"segment upsert slide {slide_number}")
