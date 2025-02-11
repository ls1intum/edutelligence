import threading
from functools import reduce
from typing import Optional, List, Dict, Any

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from langchain_text_splitters import RecursiveCharacterTextSplitter
from weaviate import WeaviateClient

from asyncio.log import logger

from app.common.PipelineEnum import PipelineEnum
from app.domain.data.metrics.transcription_dto import (
    TranscriptionWebhookDTO,
    TranscriptionSegmentDTO,
)
from app.domain.ingestion.transcription_ingestion.transcription_ingestion_pipeline_execution_dto import (
    TranscriptionIngestionPipelineExecutionDto,
)
from app.llm import (
    BasicRequestHandler,
    CapabilityRequestHandler,
    RequirementList,
    CompletionArguments,
)
from app.llm.langchain import IrisLangchainChatModel
from app.pipeline import Pipeline
from app.pipeline.faq_ingestion_pipeline import batch_update_lock
from app.pipeline.prompts.transcription_ingestion_prompts import (
    transcription_summary_prompt,
)
from app.vector_database.lecture_transcription_schema import (
    init_lecture_transcription_schema,
    LectureTranscriptionSchema,
)
from app.web.status.transcription_ingestion_callback import TranscriptionIngestionStatus

batch_insert_lock = batch_update_lock


class TranscriptionIngestionPipeline(Pipeline):
    llm: IrisLangchainChatModel
    pipeline: Runnable
    prompt: ChatPromptTemplate

    def __init__(
        self,
        client: WeaviateClient,
        dto: Optional[TranscriptionIngestionPipelineExecutionDto],
        callback: TranscriptionIngestionStatus,
    ) -> None:
        super().__init__()
        self.client = client
        self.dto = dto
        self.callback = callback
        self.collection = init_lecture_transcription_schema(client)
        self.llm_embedding = BasicRequestHandler("embedding-small")

        request_handler = CapabilityRequestHandler(
            requirements=RequirementList(
                gpt_version_equivalent=4.5,
                context_length=16385,
                privacy_compliance=True,
            )
        )
        completion_args = CompletionArguments(temperature=0, max_tokens=2000)
        self.llm = IrisLangchainChatModel(
            request_handler=request_handler, completion_args=completion_args
        )
        self.pipeline = self.llm | StrOutputParser()
        self.tokens = []

    def __call__(self) -> None:
        try:
            self.callback.in_progress("Chunking transcriptions")
            chunks = self.chunk_transcriptions(self.dto.transcriptions)
            logger.info("chunked data")
            self.callback.in_progress("Summarizing transcriptions")
            chunks = self.summarize_chunks(chunks)

            self.callback.in_progress("Ingesting transcriptions into vector database")
            self.batch_insert(chunks)
            self.callback.done("Transcriptions ingested successfully")

        except Exception as e:
            logger.error(f"Error processing transcription ingestion pipeline: {e}")
            self.callback.error(
                f"Error processing transcription ingestion pipeline: {e}",
                exception=e,
                tokens=self.tokens,
            )

    def batch_insert(self, chunks):
        global batch_insert_lock
        with batch_insert_lock:
            with self.collection.batch.rate_limit(requests_per_minute=600) as batch:
                try:
                    for chunk in chunks:
                        embed_chunk = self.llm_embedding.embed(
                            chunk[LectureTranscriptionSchema.SEGMENT_TEXT.value]
                        )
                        batch.add_object(properties=chunk, vector=embed_chunk)
                except Exception as e:
                    logger.error(f"Error embedding lecture transcription chunk: {e}")
                    self.callback.error(
                        f"Failed to ingest lecture transcriptions into the database: {e}",
                        exception=e,
                        tokens=self.tokens,
                    )

    def chunk_transcriptions(
        self, transcriptions: List[TranscriptionWebhookDTO]
    ) -> List[Dict[str, Any]]:
        CHUNK_SEPARATOR_CHAR = "\x1F"
        chunks = []

        for transcription in transcriptions:
            slide_chunks = {}
            for segment in transcription.transcription.segments:
                slide_key = f"{transcription.lecture_id}_{segment.lecture_unit_id}_{segment.slide_number}"

                if slide_key not in slide_chunks:
                    chunk = {
                        LectureTranscriptionSchema.COURSE_ID.value: transcription.course_id,
                        LectureTranscriptionSchema.COURSE_NAME.value: transcription.course_name,
                        LectureTranscriptionSchema.LECTURE_ID.value: transcription.lecture_id,
                        LectureTranscriptionSchema.LECTURE_NAME.value: transcription.lecture_name,
                        LectureTranscriptionSchema.LANGUAGE.value: transcription.transcription.language,
                        LectureTranscriptionSchema.SEGMENT_START_TIME.value: segment.start_time,
                        LectureTranscriptionSchema.SEGMENT_END_TIME.value: segment.end_time,
                        LectureTranscriptionSchema.SEGMENT_TEXT.value: segment.text,
                        LectureTranscriptionSchema.SEGMENT_LECTURE_UNIT_SLIDES_ID.value: segment.lecture_unit_id,
                        LectureTranscriptionSchema.SEGMENT_LECTURE_UNIT_SLIDE_NUMBER.value: segment.slide_number,
                    }

                    slide_chunks[slide_key] = chunk
                else:
                    slide_chunks[slide_key][
                        LectureTranscriptionSchema.SEGMENT_TEXT.value
                    ] += (CHUNK_SEPARATOR_CHAR + segment.text)
                    slide_chunks[slide_key][
                        LectureTranscriptionSchema.SEGMENT_END_TIME.value
                    ] = segment.end_time

            for i, segment in enumerate(slide_chunks.values()):
                if len(segment[LectureTranscriptionSchema.SEGMENT_TEXT.value]) < 1200:
                    segment[LectureTranscriptionSchema.SEGMENT_TEXT.value] = segment[
                        LectureTranscriptionSchema.SEGMENT_TEXT.value
                    ].replace(CHUNK_SEPARATOR_CHAR, " ")
                    chunks.append(segment)
                    continue

                text_splitter = RecursiveCharacterTextSplitter(
                    chunk_size=1024, chunk_overlap=0
                )

                semantic_chunks = text_splitter.split_text(
                    segment[LectureTranscriptionSchema.SEGMENT_TEXT.value]
                )

                for j, chunk in enumerate(semantic_chunks):
                    offset_slide_chunk = reduce(
                        lambda acc, txt: acc
                        + len(txt.replace(CHUNK_SEPARATOR_CHAR, "")),
                        map(
                            lambda seg: seg[
                                LectureTranscriptionSchema.SEGMENT_TEXT.value
                            ],
                            list(slide_chunks.values())[:i],
                        ),
                        0,
                    )

                    offset_semantic_chunk = reduce(
                        lambda acc, txt: acc
                        + len(txt.replace(CHUNK_SEPARATOR_CHAR, "")),
                        semantic_chunks[:j],
                        0,
                    )

                    offset_start = offset_slide_chunk + offset_semantic_chunk + 1
                    offset_end = offset_start + len(
                        chunk.replace(CHUNK_SEPARATOR_CHAR, "")
                    )

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
                            LectureTranscriptionSchema.SEGMENT_TEXT.value: chunk.replace(
                                CHUNK_SEPARATOR_CHAR, " "
                            ).strip(),
                        }
                    )

        return chunks

    @staticmethod
    def get_transcription_segment_of_char_position(
        char_position: int, segments: List[TranscriptionSegmentDTO]
    ):
        offset_lookup_counter = 0
        segment_index = 0
        while offset_lookup_counter < char_position and segment_index < len(segments):
            offset_lookup_counter += len(segments[segment_index].text)
            segment_index += 1

        if segment_index >= len(segments):
            return segments[-1]
        return segments[segment_index]

    def summarize_chunks(self, chunks):
        chunks_with_summaries = []
        for chunk in chunks:
            self.prompt = ChatPromptTemplate.from_messages(
                [
                    (
                        "system",
                        transcription_summary_prompt(
                            chunk[LectureTranscriptionSchema.LECTURE_NAME.value],
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
                    self.llm.tokens, PipelineEnum.IRIS_VIDEO_TRANSCRIPTION_INGESTION
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
