import traceback
from asyncio.log import logger
from threading import Semaphore, Thread

from fastapi import APIRouter, Depends, status
from sentry_sdk import capture_exception

from iris.dependencies import TokenValidator
from iris.domain.ingestion.ingestion_pipeline_execution_dto import (
    FaqIngestionPipelineExecutionDto,
    IngestionPipelineExecutionDto,
)
from iris.web.utils import validate_pipeline_variant

from ...domain.ingestion.deletion_pipeline_execution_dto import (
    FaqDeletionExecutionDto,
    LecturesDeletionExecutionDto,
)
from ...domain.ingestion.transcription_ingestion.transcription_ingestion_pipeline_execution_dto import (
    TranscriptionIngestionPipelineExecutionDto,
)
from ...pipeline.faq_ingestion_pipeline import FaqIngestionPipeline
from ...pipeline.lecture_ingestion_pipeline import (
    LectureUnitPageIngestionPipeline,
)
from ...pipeline.transcription_ingestion_pipeline import (
    TranscriptionIngestionPipeline,
)
from ...vector_database.database import VectorDatabase
from ..status.faq_ingestion_status_callback import FaqIngestionStatus
from ..status.ingestion_status_callback import IngestionStatusCallback
from ..status.lecture_deletion_status_callback import (
    LecturesDeletionStatusCallback,
)
from ..status.transcription_ingestion_callback import (
    TranscriptionIngestionStatus,
)

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
            pipeline = LectureUnitPageIngestionPipeline(
                client=client, dto=dto, callback=callback
            )
            pipeline()

        except Exception as e:
            logger.error("Error Ingestion pipeline: %s", e)
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
        pipeline = LectureUnitPageIngestionPipeline(
            client=client, dto=None, callback=callback
        )
        pipeline.delete_old_lectures(dto.lecture_units, dto.settings.artemis_base_url)
    except Exception as e:
        logger.error("Error while deleting lectures: %s", e)
        logger.error(traceback.format_exc())


def run_transcription_ingestion_pipeline_worker(
    dto: TranscriptionIngestionPipelineExecutionDto,
):
    """
    Run the transcription ingestion pipeline in a separate thread
    """
    with semaphore:
        try:
            callback = TranscriptionIngestionStatus(
                run_id=dto.settings.authentication_token,
                base_url=dto.settings.artemis_base_url,
                initial_stages=dto.initial_stages,
                lecture_id=dto.lecture_unit_id,
            )
            db = VectorDatabase()
            client = db.get_client()
            pipeline = TranscriptionIngestionPipeline(
                client=client, dto=dto, callback=callback
            )
            pipeline()
        except Exception as e:
            logger.error("Error while deleting lectures: %s", e)
            logger.error(traceback.format_exc())
            capture_exception(e)
        finally:
            semaphore.release()


def run_faq_update_pipeline_worker(dto: FaqIngestionPipelineExecutionDto):
    """
    Run the exercise chat pipeline in a separate thread
    """
    with semaphore:
        try:
            callback = FaqIngestionStatus(
                run_id=dto.settings.authentication_token,
                base_url=dto.settings.artemis_base_url,
                initial_stages=dto.initial_stages,
                faq_id=dto.faq.faq_id,
            )
            db = VectorDatabase()
            client = db.get_client()
            pipeline = FaqIngestionPipeline(client=client, dto=dto, callback=callback)
            pipeline()

        except Exception as e:
            logger.error("Error Faq Ingestion pipeline: %s", e)
            logger.error(traceback.format_exc())
            capture_exception(e)
        finally:
            semaphore.release()


def run_faq_delete_pipeline_worker(dto: FaqDeletionExecutionDto):
    """
    Run the faq deletion in a separate thread
    """
    with semaphore:
        try:
            callback = FaqIngestionStatus(
                run_id=dto.settings.authentication_token,
                base_url=dto.settings.artemis_base_url,
                initial_stages=dto.initial_stages,
                faq_id=dto.faq.faq_id,
            )
            db = VectorDatabase()
            client = db.get_client()
            # Hier würd dann die Methode zum entfernen aus der Datenbank kommen
            pipeline = FaqIngestionPipeline(client=client, dto=None, callback=callback)
            pipeline.delete_faq(dto.faq.faq_id, dto.faq.course_id)

        except Exception as e:
            logger.error("Error Ingestion pipeline: %s", e)
            logger.error(traceback.format_exc())
            capture_exception(e)
        finally:
            semaphore.release()


@router.post(
    "/lectures/ingest",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(TokenValidator())],
)
def lecture_ingestion_webhook(dto: IngestionPipelineExecutionDto):
    """
    Webhook endpoint to trigger the exercise chat pipeline
    """
    validate_pipeline_variant(dto.settings, LectureUnitPageIngestionPipeline)

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
    validate_pipeline_variant(dto.settings, LectureUnitPageIngestionPipeline)

    thread = Thread(target=run_lecture_deletion_pipeline_worker, args=(dto,))
    thread.start()


@router.post(
    "/transcriptions/ingest",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(TokenValidator())],
)
def transcription_ingestion_webhook(
    dto: TranscriptionIngestionPipelineExecutionDto,
):
    """
    Webhook endpoint to trigger the lecture transcription ingestion pipeline
    """
    validate_pipeline_variant(dto.settings, TranscriptionIngestionPipeline)

    logger.info("transcription ingestion got DTO %s", dto)
    thread = Thread(target=run_transcription_ingestion_pipeline_worker, args=(dto,))
    thread.start()


@router.post(
    "/faqs/ingest",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(TokenValidator())],
)
def faq_ingestion_webhook(dto: FaqIngestionPipelineExecutionDto):
    """
    Webhook endpoint to trigger the faq ingestion pipeline
    """
    validate_pipeline_variant(dto.settings, FaqIngestionPipeline)

    thread = Thread(target=run_faq_update_pipeline_worker, args=(dto,))
    thread.start()
    return


@router.post(
    "/faqs/delete",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(TokenValidator())],
)
def faq_deletion_webhook(dto: FaqDeletionExecutionDto):
    """
    Webhook endpoint to trigger the faq deletion pipeline
    """
    validate_pipeline_variant(dto.settings, FaqIngestionPipeline)

    thread = Thread(target=run_faq_delete_pipeline_worker, args=(dto,))
    thread.start()
    return
