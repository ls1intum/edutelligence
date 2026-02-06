from sentry_sdk import capture_exception

from iris.common.logging_config import get_logger
from iris.domain.ingestion.ingestion_pipeline_execution_dto import (
    IngestionPipelineExecutionDto,
)
from iris.domain.lecture.lecture_unit_dto import LectureUnitDTO
from iris.domain.variant.abstract_variant import find_variant
from iris.domain.variant.variant import Dep
from iris.pipeline import Pipeline
from iris.pipeline.lecture_ingestion_pipeline import LectureUnitPageIngestionPipeline
from iris.pipeline.lecture_unit_pipeline import LectureUnitPipeline
from iris.pipeline.transcription_ingestion_pipeline import (
    TranscriptionIngestionPipeline,
)
from iris.tracing import observe
from iris.vector_database.database import VectorDatabase
from iris.web.status.ingestion_status_callback import IngestionStatusCallback

logger = get_logger(__name__)


class LectureIngestionUpdatePipeline(Pipeline):
    """Lecture Ingestion Update Pipeline to update or ingest lecture page chunks and lecture transcriptions at once"""

    PIPELINE_ID = "lecture_ingestion_update_pipeline"
    ROLES: set[str] = set()
    VARIANT_DEFS = [
        ("default", "Default", "Default lecture ingestion update variant."),
        ("advanced", "Advanced", "Advanced lecture ingestion update variant."),
    ]
    DEPENDENCIES = [
        Dep("lecture_unit_page_ingestion_pipeline", variant="same"),
        Dep("transcription_ingestion_pipeline"),
        Dep("lecture_unit_pipeline"),
        Dep("lecture_unit_segment_summary_pipeline"),
        Dep("lecture_unit_summary_pipeline"),
    ]

    def __init__(self, dto: IngestionPipelineExecutionDto):
        super().__init__(implementation_id=self.PIPELINE_ID)
        self.dto = dto

    @observe(name="Lecture Ingestion Update Pipeline")
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
            variant_id = self.dto.settings.variant if self.dto.settings else "default"
            is_local = bool(
                self.dto.settings
                and self.dto.settings.artemis_llm_selection == "LOCAL_AI"
            )
            if (
                self.dto.lecture_unit.pdf_file_base64 is not None
                and self.dto.lecture_unit.pdf_file_base64 != ""
            ):
                variant = find_variant(
                    LectureUnitPageIngestionPipeline.get_variants(), variant_id
                )
                page_content_pipeline = LectureUnitPageIngestionPipeline(
                    client=client,
                    dto=self.dto,
                    callback=callback,
                    variant=variant,
                    local=is_local,
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
                    client=client, dto=self.dto, callback=callback, local=is_local
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

            is_local = self.dto.settings is not None and self.dto.settings.is_local()
            tokens += LectureUnitPipeline(local=is_local)(lecture_unit=lecture_unit_dto)
            callback.done(
                "Ingested lecture unit summary into vector database",
                tokens=tokens,
            )

        except Exception as e:
            logger.error("Error in ingestion pipeline", exc_info=e)
            capture_exception(e)
