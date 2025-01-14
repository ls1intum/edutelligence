import traceback
from asyncio.log import logger
from threading import Thread, Semaphore

from sentry_sdk import capture_exception

from fastapi import APIRouter, status, Depends
from app.dependencies import TokenValidator
from app.domain.ingestion.ingestion_pipeline_execution_dto import (
    IngestionPipelineExecutionDto,
)
from ..status.ingestion_status_callback import IngestionStatusCallback
from ..status.lecture_deletion_status_callback import LecturesDeletionStatusCallback
from ...domain.ingestion.deletionPipelineExecutionDto import (
    LecturesDeletionExecutionDto,
)
from ...domain.ingestion.transcription_ingestion.transcription_ingestion_pipeline_execution_dto import \
    TranscriptionIngestionPipelineExecutionDto
from ...pipeline.lecture_ingestion_pipeline import LectureIngestionPipeline
from ...vector_database.database import VectorDatabase

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])

semaphore = Semaphore(5)


def run_lecture_update_pipeline_worker(dto: IngestionPipelineExecutionDto):
    """
    Run the exercise chat pipeline in a separate thread
    """
    with semaphore:
        try:
            callback = IngestionStatusCallback(
                run_id=dto.settings.authentication_token,
                base_url=dto.settings.artemis_base_url,
                initial_stages=dto.initial_stages,
                lecture_unit_id=dto.lecture_unit.lecture_unit_id,
            )
            db = VectorDatabase()
            client = db.get_client()
            pipeline = LectureIngestionPipeline(
                client=client, dto=dto, callback=callback
            )
            pipeline()
        except Exception as e:
            logger.error(f"Error Ingestion pipeline: {e}")
            logger.error(traceback.format_exc())
            capture_exception(e)
        finally:
            semaphore.release()


def run_lecture_deletion_pipeline_worker(dto: LecturesDeletionExecutionDto):
    """
    Run the exercise chat pipeline in a separate thread
    """
    try:
        callback = LecturesDeletionStatusCallback(
            run_id=dto.settings.authentication_token,
            base_url=dto.settings.artemis_base_url,
            initial_stages=dto.initial_stages,
        )
        db = VectorDatabase()
        client = db.get_client()
        pipeline = LectureIngestionPipeline(client=client, dto=None, callback=callback)
        pipeline.delete_old_lectures(dto.lecture_units, dto.settings.artemis_base_url)
    except Exception as e:
        logger.error(f"Error while deleting lectures: {e}")
        logger.error(traceback.format_exc())


@router.post(
    "/lectures/fullIngestion",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(TokenValidator())],
)
def lecture_ingestion_webhook(dto: IngestionPipelineExecutionDto):
    """
    Webhook endpoint to trigger the exercise chat pipeline
    """
    thread = Thread(target=run_lecture_update_pipeline_worker, args=(dto,))
    thread.start()


@router.post(
    "/lectures/delete",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(TokenValidator())],
)
def lecture_deletion_webhook(dto: LecturesDeletionExecutionDto):
    """
    Webhook endpoint to trigger the lecture deletion
    """
    thread = Thread(target=run_lecture_deletion_pipeline_worker, args=(dto,))
    thread.start()

@router.post(
    "/transcriptions/fullIngestion",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(TokenValidator())],
)
def transcription_ingestion_webhook(dto: TranscriptionIngestionPipelineExecutionDto):
    """
    Webhook endpoint to trigger the exercise chat pipeline
    """
    # thread = Thread(target=run_lecture_update_pipeline_worker, args=(dto,))
    # thread.start()
    print(f"transcription ingestion got DTO {dto}")