import traceback
from typing import List

from sentry_sdk import capture_exception

from iris.common.logging_config import get_logger
from iris.domain.ingestion.ingestion_pipeline_execution_dto import (
    IngestionPipelineExecutionDto,
)
from iris.domain.lecture.lecture_unit_dto import LectureUnitDTO
from iris.domain.variant.lecture_ingestion_update_variant import (
    LectureIngestionUpdateVariant,
)
from iris.pipeline import Pipeline
from iris.pipeline.lecture_ingestion_pipeline import LectureUnitPageIngestionPipeline
from iris.pipeline.lecture_unit_pipeline import LectureUnitPipeline
from iris.pipeline.transcription_ingestion_pipeline import (
    TranscriptionIngestionPipeline,
)
from iris.vector_database.database import VectorDatabase
from iris.web.status.ingestion_status_callback import IngestionStatusCallback

logger = get_logger(__name__)


class LectureIngestionUpdatePipeline(Pipeline[LectureIngestionUpdateVariant]):
    """Lecture Ingestion Update Pipeline to update or ingest lecture page chunks and lecture transcriptions at once"""

    def __init__(self, dto: IngestionPipelineExecutionDto):
        super().__init__()
        self.dto = dto

    def __call__(self):
        try:
            callback = IngestionStatusCallback(
                run_id=self.dto.settings.authentication_token,
                base_url=self.dto.settings.artemis_base_url,
                initial_stages=self.dto.initial_stages,
                lecture_unit_id=self.dto.lecture_unit.lecture_unit_id,
            )
            db = VectorDatabase()
            client = db.get_client()
            language = ""
            tokens = []
            if (
                self.dto.lecture_unit.pdf_file_base64 is not None
                and self.dto.lecture_unit.pdf_file_base64 != ""
            ):
                page_content_pipeline = LectureUnitPageIngestionPipeline(
                    client=client, dto=self.dto, callback=callback
                )
                language, tokens_page_content_pipeline = page_content_pipeline()
                tokens += tokens_page_content_pipeline
            else:
                callback.in_progress("skipping slide removal")
                callback.done()
                callback.in_progress("skipping slide interpretation")
                callback.done()
                callback.in_progress("skipping slide ingestion")
                callback.done()
            if (
                self.dto.lecture_unit.transcription is not None
                and self.dto.lecture_unit.transcription.segments is not None
            ):
                transcription_pipeline = TranscriptionIngestionPipeline(
                    client=client, dto=self.dto, callback=callback
                )
                language, tokens_transcription_pipeline = transcription_pipeline()
                tokens += tokens_transcription_pipeline
            else:
                callback.in_progress("skipping transcription removal")
                callback.done()
                callback.in_progress("skipping transcription chunking")
                callback.done()
                callback.in_progress("skipping transcription summarization")
                callback.done()
                callback.in_progress("skipping transcription ingestion")
                callback.done()

            callback.in_progress("Ingesting lecture unit summary into vector database")
            lecture_unit_dto = LectureUnitDTO(
                course_id=self.dto.lecture_unit.course_id,
                course_name=self.dto.lecture_unit.course_name,
                course_description=self.dto.lecture_unit.course_description,
                course_language=language,
                lecture_id=self.dto.lecture_unit.lecture_id,
                lecture_name=self.dto.lecture_unit.lecture_name,
                lecture_unit_id=self.dto.lecture_unit.lecture_unit_id,
                lecture_unit_name=self.dto.lecture_unit.lecture_unit_name,
                lecture_unit_link=self.dto.lecture_unit.lecture_unit_link,
                video_link=self.dto.lecture_unit.video_link,
                base_url=self.dto.settings.artemis_base_url,
            )

            tokens += LectureUnitPipeline()(lecture_unit=lecture_unit_dto)
            callback.done(
                "Ingested lecture unit summary into vector database",
                tokens=tokens,
            )

        except Exception as e:
            logger.error("Error Ingestion pipeline: %s", e)
            logger.error(traceback.format_exc())
            capture_exception(e)

    @classmethod
    def get_variants(cls) -> List[LectureIngestionUpdateVariant]:
        """
        Returns available variants for the LectureIngestionUpdatePipeline.

        Returns:
            List of LectureIngestionUpdateVariant objects representing available variants
        """
        return [
            LectureIngestionUpdateVariant(
                variant_id="default",
                name="Default",
                description="Default lecture ingestion update variant using efficient models "
                "for processing and embeddings.",
                chat_model="gpt-4.1-mini",
                embedding_model="text-embedding-3-small",
            ),
            LectureIngestionUpdateVariant(
                variant_id="advanced",
                name="Advanced",
                description="Advanced lecture ingestion update variant using higher-quality models "
                "for improved accuracy.",
                chat_model="gpt-4.1",
                embedding_model="text-embedding-3-large",
            ),
        ]
