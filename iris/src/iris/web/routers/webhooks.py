from multiprocessing import Process
from threading import Semaphore, Thread

from fastapi import APIRouter, Depends, status
from sentry_sdk import capture_exception

from iris.common.logging_config import get_logger
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
from ...ingestion.ingestion_job_handler import IngestionJobHandler
from ...pipeline.delete_lecture_units_pipeline import LectureUnitDeletionPipeline
from ...pipeline.faq_ingestion_pipeline import FaqIngestionPipeline
from ...pipeline.lecture_ingestion_update_pipeline import LectureIngestionUpdatePipeline
from ...vector_database.database import VectorDatabase
from ..status.faq_ingestion_status_callback import FaqIngestionStatus
from ..status.lecture_deletion_status_callback import (
    LecturesDeletionStatusCallback,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])

semaphore = Semaphore(5)

ingestion_job_handler = IngestionJobHandler()


def run_lecture_update_pipeline_worker(dto: IngestionPipelineExecutionDto):
    """
    Run the lecture unit ingestion pipeline in a separate thread
    """
    with semaphore:
        lecture_ingestion_update_pipeline = LectureIngestionUpdatePipeline(dto)
        lecture_ingestion_update_pipeline()
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
        pipeline = LectureUnitDeletionPipeline(
            client=client,
            lecture_units=dto.lecture_units,
            callback=callback,
            artemis_base_url=dto.settings.artemis_base_url,
        )
        pipeline()
    except Exception as e:
        logger.error("Error while deleting lectures", exc_info=e)


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
            logger.error("Error in FAQ ingestion pipeline", exc_info=e)
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
            pipeline = FaqIngestionPipeline(client=client, dto=None, callback=callback)
            pipeline.delete_faq(dto.faq.faq_id, dto.faq.course_id)

        except Exception as e:
            logger.error("Error in FAQ deletion pipeline", exc_info=e)
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
    validate_pipeline_variant(dto.settings, LectureIngestionUpdatePipeline)

    process = Process(target=run_lecture_update_pipeline_worker, args=(dto,))
    ingestion_job_handler.add_job(
        process=process,
        course_id=dto.lecture_unit.course_id,
        lecture_id=dto.lecture_unit.lecture_id,
        lecture_unit_id=dto.lecture_unit.lecture_unit_id,
    )


@router.post(
    "/lectures/delete",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(TokenValidator())],
)
def lecture_deletion_webhook(dto: LecturesDeletionExecutionDto):
    """
    Webhook endpoint to trigger the lecture deletion
    """
    validate_pipeline_variant(dto.settings, LectureUnitDeletionPipeline)

    thread = Thread(target=run_lecture_deletion_pipeline_worker, args=(dto,))
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
