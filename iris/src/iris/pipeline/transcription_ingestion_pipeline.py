from functools import reduce
from typing import Any, Dict, List, Optional

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from weaviate import WeaviateClient
from weaviate.classes.query import Filter

from iris.common.ingestion_errors import (
    TRANSCRIPT_INGESTION_FAILED,
    IngestionStageError,
)
from iris.common.logging_config import get_logger
from iris.common.pipeline_enum import PipelineEnum
from iris.domain.data.lecture_unit_page_dto import LectureUnitPageDTO
from iris.domain.data.metrics.transcription_dto import (
    TranscriptionSegmentDTO,
)
from iris.domain.ingestion.ingestion_pipeline_execution_dto import (
    IngestionPipelineExecutionDto,
)
from iris.llm import (
    CompletionArguments,
    LlmRequestHandler,
)
from iris.llm.langchain import IrisLangchainChatModel
from iris.llm.llm_configuration import resolve_model
from iris.pipeline.prompts.transcription_ingestion_prompts import (
    transcription_summary_prompt,
)
from iris.pipeline.sub_pipeline import SubPipeline
from iris.tracing import observe
from iris.vector_database.batch_verify import (
    fetch_with_retry,
    sweep_other_generations,
    write_batch_with_retry,
)
from iris.vector_database.database import batch_update_lock
from iris.vector_database.lecture_transcription_schema import (
    LectureTranscriptionSchema,
    init_lecture_transcription_schema,
)
from iris.vector_database.write_retry import WeaviateWriteRetry
from iris.web.status.ingestion_status_callback import IngestionStatusCallback

logger = get_logger(__name__)

CHUNK_SEPARATOR_CHAR = "\31"

# Upper bound on the structural skip-check read. A truncated read must never look
# "complete" and wrongly skip a genuinely incomplete unit, so hitting the cap forces
# re-ingestion instead. Mirrors the PDF page-chunk skip-check.
_TRANSCRIPTION_SKIP_CHECK_FETCH_LIMIT = 10_000


class TranscriptionIngestionPipeline(SubPipeline):
    """TranscriptionIngestionPipeline orchestrates the process of ingesting lecture transcription data.

    It deletes existing transcription data, chunks and summarizes the transcription,
    and ingests the processed transcription into the vector database while updating the relevant callbacks.
    """

    llm: IrisLangchainChatModel
    pipeline: Runnable
    prompt: ChatPromptTemplate

    def __init__(
        self,
        client: WeaviateClient,
        dto: Optional[IngestionPipelineExecutionDto],
        callback: IngestionStatusCallback,
        local: bool = False,
    ) -> None:
        super().__init__(implementation_id="transcription_ingestion_pipeline")
        self.client = client
        self.dto = dto
        self.callback = callback
        self.collection = init_lecture_transcription_schema(client)
        pipeline_id = "transcription_ingestion_pipeline"
        embedding_model = resolve_model(
            pipeline_id, "default", "embedding", local=local
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
        self.skipped = False

    @observe(name="Transcription Ingestion Pipeline")
    def __call__(self) -> (str, []):
        try:
            self.callback.update()
            if (
                not self.dto.lecture_unit.force_reingest
                and not self.check_if_transcription_needs_update()
            ):
                # The stored rows provably derive from the current content
                # (fingerprint stamps match) and cover exactly the expected
                # slides, so re-running the summary and embedding work would
                # reproduce what is already there.
                logger.info(
                    "[%s / %s] Stored transcription rows are current and "
                    "complete, skipping transcription ingestion",
                    self.dto.lecture_unit.lecture_name,
                    self.dto.lecture_unit.lecture_unit_name,
                )
                self.skipped = True
                for _ in range(7):
                    self.callback.update()
                return self.dto.lecture_unit.transcription.language, self.tokens
            self.callback.update()

            self.callback.update()
            chunks = self.chunk_transcription(self.dto.lecture_unit)
            self.callback.update()

            self.callback.update()
            chunks = self.summarize_chunks(chunks)
            self.callback.update()

            self.callback.update()
            logger.info(
                "[%s / %s] Embedding and indexing %d transcription chunks into Weaviate",
                self.dto.lecture_unit.lecture_name,
                self.dto.lecture_unit.lecture_unit_name,
                len(chunks),
            )
            self.batch_insert(chunks)
            self.callback.update()

            return self.dto.lecture_unit.transcription.language, self.tokens
        except IngestionStageError as e:
            if not e.tokens:
                e.tokens = list(self.tokens)
            raise
        except Exception as e:
            logger.error(
                "Error processing transcription ingestion pipeline: %s",
                e,
                exc_info=True,
            )
            raise IngestionStageError(
                TRANSCRIPT_INGESTION_FAILED,
                f"Failed to ingest the transcription into the database: {e}",
                tokens=list(self.tokens),
            ) from e

    def _get_unit_filter(self, transcription: LectureUnitPageDTO):
        return (
            Filter.by_property(LectureTranscriptionSchema.COURSE_ID.value).equal(
                transcription.course_id
            )
            & Filter.by_property(LectureTranscriptionSchema.LECTURE_ID.value).equal(
                transcription.lecture_id
            )
            & Filter.by_property(
                LectureTranscriptionSchema.LECTURE_UNIT_ID.value
            ).equal(transcription.lecture_unit_id)
            & Filter.by_property(LectureTranscriptionSchema.BASE_URL.value).equal(
                self.dto.settings.artemis_base_url
            )
        )

    def check_if_transcription_needs_update(self) -> bool:
        """Decide structurally whether the stored transcription rows are current.

        Skipping is only safe when every stored row carries the current
        content fingerprint (an unstamped row is a legacy row of unknown
        origin), all rows belong to a single ingestion generation, and the
        stored slide numbers cover exactly the transcript's slide set.
        """
        expected_fingerprint = self.dto.lecture_unit.content_fingerprint
        if expected_fingerprint is None:
            return True
        rows = fetch_with_retry(
            lambda: self.collection.query.fetch_objects(
                filters=self._get_unit_filter(self.dto.lecture_unit),
                limit=_TRANSCRIPTION_SKIP_CHECK_FETCH_LIMIT,
                return_properties=[
                    LectureTranscriptionSchema.PAGE_NUMBER.value,
                    LectureTranscriptionSchema.CONTENT_FINGERPRINT.value,
                    LectureTranscriptionSchema.INGESTION_RUN_ID.value,
                ],
            )
        ).objects
        if not rows:
            return True

        # A truncated read must never look "complete" and skip a genuinely incomplete
        # unit. If we hit the cap, re-ingest rather than trust a possibly partial sample.
        if len(rows) >= _TRANSCRIPTION_SKIP_CHECK_FETCH_LIMIT:
            return True

        stored_pages: set[int] = set()
        run_ids: set = set()
        for row in rows:
            if (
                row.properties.get(LectureTranscriptionSchema.CONTENT_FINGERPRINT.value)
                != expected_fingerprint
            ):
                return True
            run_ids.add(
                row.properties.get(LectureTranscriptionSchema.INGESTION_RUN_ID.value)
            )
            page_number = row.properties.get(
                LectureTranscriptionSchema.PAGE_NUMBER.value
            )
            if page_number is not None:
                stored_pages.add(int(page_number))

        if len(run_ids) > 1:
            return True
        expected_pages = {
            segment.slide_number
            for segment in self.dto.lecture_unit.transcription.segments
        }
        return stored_pages != expected_pages

    def batch_insert(self, chunks):
        """Embed outside the shared write lock, then write-new-then-sweep.

        The new generation is inserted and verified first; only then is
        everything that does not belong to this run removed. A crash mid-write
        never leaves the unit without a transcription: at worst two
        generations coexist briefly until the next run's sweep.
        """
        prepared_chunks = []
        try:
            total = len(chunks)
            for i, chunk in enumerate(chunks):
                if i % 5 == 0:
                    self.callback.update(
                        stage_name="transcript-embedding",
                        stage_progress=i,
                        stage_total=total,
                    )
                embed_chunk = self.llm_embedding.embed(
                    chunk[LectureTranscriptionSchema.SEGMENT_TEXT.value]
                )
                prepared_chunks.append((chunk, embed_chunk))
        except Exception as e:
            logger.error("Error embedding lecture transcription chunk: %s", e)
            raise

        with batch_update_lock:
            # One retry budget for the swap: a transient store condition re-submits
            # only the dropped chunks, never the summary/embedding work above.
            retry = WeaviateWriteRetry.for_request()
            write_batch_with_retry(
                self.collection,
                prepared_chunks,
                "transcription chunks",
                retry=retry,
                open_batch=lambda collection: collection.batch.dynamic(),
            )
            sweep_other_generations(
                self.collection,
                self._get_unit_filter(self.dto.lecture_unit),
                LectureTranscriptionSchema.INGESTION_RUN_ID.value,
                self.dto.lecture_unit.ingestion_run_id,
                "outdated transcription chunks",
                retry=retry,
            )

    def chunk_transcription(
        self, transcription: LectureUnitPageDTO
    ) -> List[Dict[str, Any]]:
        chunks = []

        slide_chunks = {}
        for segment in transcription.transcription.segments:
            slide_key = f"{transcription.lecture_id}_{transcription.lecture_unit_id}_{segment.slide_number}"

            if slide_key not in slide_chunks:
                chunk = {
                    LectureTranscriptionSchema.COURSE_ID.value: transcription.course_id,
                    LectureTranscriptionSchema.LECTURE_ID.value: transcription.lecture_id,
                    LectureTranscriptionSchema.LECTURE_UNIT_ID.value: transcription.lecture_unit_id,
                    LectureTranscriptionSchema.LANGUAGE.value: transcription.transcription.language,
                    LectureTranscriptionSchema.SEGMENT_START_TIME.value: segment.start_time,
                    LectureTranscriptionSchema.SEGMENT_END_TIME.value: segment.end_time,
                    LectureTranscriptionSchema.SEGMENT_TEXT.value: segment.text,
                    LectureTranscriptionSchema.PAGE_NUMBER.value: segment.slide_number,
                    LectureTranscriptionSchema.BASE_URL.value: self.dto.settings.artemis_base_url,
                    LectureTranscriptionSchema.CONTENT_FINGERPRINT.value: transcription.content_fingerprint,
                    LectureTranscriptionSchema.INGESTION_RUN_ID.value: transcription.ingestion_run_id,
                }

                slide_chunks[slide_key] = chunk
            else:
                slide_chunks[slide_key][
                    LectureTranscriptionSchema.SEGMENT_TEXT.value
                ] += (CHUNK_SEPARATOR_CHAR + segment.text)
                slide_chunks[slide_key][
                    LectureTranscriptionSchema.SEGMENT_END_TIME.value
                ] = segment.end_time

        logger.info(
            "[%s / %s] Chunked %d segments → %d slide groups",
            transcription.lecture_name,
            transcription.lecture_unit_name,
            len(transcription.transcription.segments),
            len(slide_chunks),
        )
        for i, segment in enumerate(slide_chunks.values()):
            # If the segment is shorter than 1200 characters, we can just add it as is
            if len(segment[LectureTranscriptionSchema.SEGMENT_TEXT.value]) < 1200:
                # Add the segment to the chunks list and replace the chunk separator character with a space
                segment[LectureTranscriptionSchema.SEGMENT_TEXT.value] = (
                    self.replace_separator_char(
                        segment[LectureTranscriptionSchema.SEGMENT_TEXT.value]
                    )
                )
                chunks.append(segment)
                continue

            semantic_chunks = self.llm_embedding.split_text_semantically(
                segment[LectureTranscriptionSchema.SEGMENT_TEXT.value],
                breakpoint_threshold_type="gradient",
                breakpoint_threshold_amount=60.0,
                min_chunk_size=512,
            )

            # Calculate the offset of the current slide chunk to the start of the transcript
            offset_slide_chunk = reduce(
                lambda acc, txt: acc + len(self.remove_separator_char(txt)),
                map(
                    lambda seg: seg[LectureTranscriptionSchema.SEGMENT_TEXT.value],
                    list(slide_chunks.values())[:i],
                ),
                0,
            )
            offset_start = offset_slide_chunk
            for _, chunk in enumerate(semantic_chunks):
                offset_end = offset_start + len(self.remove_separator_char(chunk))

                start_time = self.get_transcription_segment_of_char_position(
                    offset_start, transcription.transcription.segments
                ).start_time
                end_time = self.get_transcription_segment_of_char_position(
                    offset_end, transcription.transcription.segments
                ).end_time

                chunks.append(
                    {
                        **segment,
                        LectureTranscriptionSchema.SEGMENT_START_TIME.value: start_time,
                        LectureTranscriptionSchema.SEGMENT_END_TIME.value: end_time,
                        LectureTranscriptionSchema.SEGMENT_TEXT.value: self.cleanup_chunk(
                            self.replace_separator_char(chunk)
                        ),
                    }
                )
                offset_start = offset_end + 1

        logger.info(
            "[%s / %s] Chunking complete: %d final chunks",
            transcription.lecture_name,
            transcription.lecture_unit_name,
            len(chunks),
        )
        return chunks

    @staticmethod
    def get_transcription_segment_of_char_position(
        char_position: int, segments: List[TranscriptionSegmentDTO]
    ):
        offset_lookup_counter = 0
        segment_index = 0
        while (
            segment_index < len(segments)
            and offset_lookup_counter + len(segments[segment_index].text)
            < char_position
        ):
            offset_lookup_counter += len(segments[segment_index].text)
            segment_index += 1

        if segment_index >= len(segments):
            return segments[-1]
        return segments[segment_index]

    @staticmethod
    def cleanup_chunk(text: str):
        return text.replace("  ", " ").strip()

    @staticmethod
    def replace_separator_char(text: str, replace_with: str = " ") -> str:
        return text.replace(CHUNK_SEPARATOR_CHAR, replace_with)

    def remove_separator_char(self, text: str) -> str:
        return self.replace_separator_char(text, "")

    def summarize_chunks(self, chunks: List[Dict[str, Any]]):
        chunks_with_summaries = []
        total = len(chunks)
        for i, chunk in enumerate(chunks):
            slide = chunk.get(LectureTranscriptionSchema.PAGE_NUMBER.value, "?")
            logger.info(
                "[%s / %s] Summarizing chunk %d/%d (slide %s)",
                self.dto.lecture_unit.lecture_name,
                self.dto.lecture_unit.lecture_unit_name,
                i + 1,
                total,
                slide,
            )
            self.callback.update(
                stage_name="transcript-summaries",
                stage_progress=i + 1,
                stage_total=total,
            )
            self.prompt = ChatPromptTemplate.from_messages(
                [
                    (
                        "system",
                        transcription_summary_prompt(
                            self.dto.lecture_unit.lecture_name,
                            chunk[LectureTranscriptionSchema.SEGMENT_TEXT.value],
                        ),
                    ),
                ]
            )
            prompt_val = self.prompt.format_messages()
            self.prompt = ChatPromptTemplate.from_messages(prompt_val)
            try:
                response = (self.prompt | self.pipeline).invoke({})
                self._append_tokens(
                    self.llm.tokens,
                    PipelineEnum.IRIS_VIDEO_TRANSCRIPTION_INGESTION,
                )
                chunks_with_summaries.append(
                    {
                        **chunk,
                        LectureTranscriptionSchema.SEGMENT_SUMMARY.value: response,
                    }
                )
            except Exception as e:
                raise e
        return chunks_with_summaries
