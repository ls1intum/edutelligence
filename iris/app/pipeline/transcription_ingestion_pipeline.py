import threading
from typing import Optional, List, Dict, Any

from weaviate import WeaviateClient

from asyncio.log import logger

from app.domain.data.metrics.transcription_dto import (
    TranscriptionWebhookDTO,
)
from app.domain.ingestion.transcription_ingestion.transcription_ingestion_pipeline_execution_dto import (
    TranscriptionIngestionPipelineExecutionDto,
)
from app.ingestion.abstract_ingestion import AbstractIngestion
from app.llm import BasicRequestHandler
from app.pipeline import Pipeline
from app.vector_database.lecture_transcription_schema import (
    init_lecture_transcription_schema,
    LectureTranscriptionSchema,
)
from app.web.status.ingestion_status_callback import IngestionStatusCallback

batch_insert_lock = threading.Lock()


class TranscriptionIngestionPipeline(AbstractIngestion, Pipeline):
    def __init__(
        self,
        client: WeaviateClient,
        dto: Optional[TranscriptionIngestionPipelineExecutionDto],
        callback: IngestionStatusCallback,
    ) -> None:
        super().__init__()
        self.client = client
        self.dto = dto
        self.callback = callback
        self.collection = init_lecture_transcription_schema(client)
        self.llm_embedding = BasicRequestHandler("embedding-small")

    def __call__(self) -> None:
        try:
            self.callback.in_progress("Chunking transcriptions...")
            chunks = self.chunk_data(self.dto.transcriptions)
            self.batch_insert(chunks)
            self.callback.done("Transcriptions ingested successfully")

        except Exception as e:
            print(e)

    def batch_insert(self, chunks):
        global batch_insert_lock
        with batch_insert_lock:
            with self.collection.batch.rate_limit(requests_per_minute=600) as batch:
                try:
                    for (
                        index,
                        chunk,
                    ) in enumerate(chunks):
                        embed_chunk = self.llm_embedding.embed(
                            chunk[LectureTranscriptionSchema.SEGMENT_TEXT.value]
                        )
                        print(f"Embedding chunk {index}")
                        print(chunk)
                        batch.add_object(properties=chunk, vector=embed_chunk)
                except Exception as e:
                    logger.error(f"Error embedding lecture transcription chunk: {e}")
                    self.callback.error(
                        f"Failed to ingest lecture transcriptions into the database: {e}",
                        exception=e,
                        tokens=self.tokens,
                    )

    def chunk_data(
        self, transcriptions: List[TranscriptionWebhookDTO]
    ) -> List[Dict[str, Any]]:
        slide_chunks = {}
        for transcription in transcriptions:
            for segment in transcription.transcription.segments:
                slide_key = f"{transcription.lecture_id}_{segment.lecture_unit_id}_{segment.slide_number}"

                if slide_key not in slide_chunks:
                    chunk = {
                        LectureTranscriptionSchema.COURSE_ID.value: transcription.course_id,
                        LectureTranscriptionSchema.COURSE_NAME.value: transcription.course_name,
                        LectureTranscriptionSchema.LECTURE_ID.value: transcription.lecture_id,
                        LectureTranscriptionSchema.LECTURE_NAME.value: transcription.lecture_name,
                        LectureTranscriptionSchema.LANGUAGE.value: transcription.transcription.language,
                        LectureTranscriptionSchema.SEGMENT_START.value: segment.start_time,
                        LectureTranscriptionSchema.SEGMENT_END.value: segment.end_time,
                        LectureTranscriptionSchema.SEGMENT_TEXT.value: segment.text,
                        LectureTranscriptionSchema.SEGMENT_LECTURE_UNIT_SLIDES_ID.value: segment.lecture_unit_id,
                        LectureTranscriptionSchema.SEGMENT_LECTURE_UNIT_SLIDE_NUMBER.value: segment.slide_number,
                    }

                    slide_chunks[slide_key] = chunk
                else:
                    slide_chunks[slide_key][
                        LectureTranscriptionSchema.SEGMENT_TEXT.value
                    ] += (" " + segment.text)
                    slide_chunks[slide_key][
                        LectureTranscriptionSchema.SEGMENT_END.value
                    ] = segment.end_time
        return list(slide_chunks.values())
