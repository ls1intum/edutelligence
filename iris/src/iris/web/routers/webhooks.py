from threading import Thread

from fastapi import APIRouter, Depends, HTTPException, status
from sentry_sdk import capture_exception

from iris.common.cancellation import CancellationSignal
from iris.common.custom_exceptions import IngestionCancelledException
from iris.common.logging_config import get_logger
from iris.dependencies import TokenValidator
from iris.domain.ingestion.ingestion_pipeline_execution_dto import (
    FaqIngestionPipelineExecutionDto,
    IngestionPipelineExecutionDto,
)
from iris.domain.ingestion.lecture_metadata_update_dto import (
    LectureUnitMetadataUpdateDTO,
)
from iris.domain.ingestion.lecture_visibility_update_dto import (
    LectureUnitVisibilityUpdateDTO,
)
from iris.domain.variant.abstract_variant import find_variant
from iris.pipeline.lecture_metadata_update_pipeline import (
    LectureMetadataUpdatePipeline,
)
from iris.pipeline.lecture_update_lock import lecture_update_lock
from iris.pipeline.lecture_visibility_update_pipeline import (
    LectureVisibilityUpdatePipeline,
)
from iris.tracing import observe
from iris.vector_database.lecture_unit_page_chunk_schema import (
    init_lecture_unit_page_chunk_schema,
)
from iris.vector_database.lecture_unit_schema import init_lecture_unit_schema
from iris.vector_database.lecture_unit_segment_schema import (
    init_lecture_unit_segment_schema,
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
from ..status.ingestion_status_callback import IngestionStatusCallback
from ..status.lecture_deletion_status_callback import (
    LecturesDeletionStatusCallback,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])

ingestion_job_handler = IngestionJobHandler()


def run_lecture_update_pipeline_worker(
    dto: IngestionPipelineExecutionDto,
    variant_id: str,
    cancel_event: CancellationSignal,
):
    """Run the lecture unit ingestion pipeline in a separate thread.

    No concurrency throttling here — Artemis controls how many jobs are
    dispatched via MAX_CONCURRENT_PROCESSING. Jobs for the same lecture unit may
    overlap during preprocessing; the write phase is serialized deeper in the
    ingestion pipeline.
    """
    lecture_unit_id = (
        dto.lecture_unit.lecture_unit_id
        if dto.lecture_unit is not None
        else dto.lecture_unit_id
    )
    try:
        pipeline = LectureIngestionUpdatePipeline(
            dto, variant_id=variant_id, cancel_event=cancel_event
        )
        pipeline()
    except IngestionCancelledException as e:
        # Controlled stop: a newer request for this lecture unit took over.
        # It reports on its own token, so this run stays silent.
        logger.info("[Lecture %s] Worker cancelled: %s", lecture_unit_id, e.reason)
        return
    except Exception as e:
        logger.error(
            "[Lecture %s] Worker failed: %s",
            lecture_unit_id,
            e,
            exc_info=True,
        )
        IngestionStatusCallback(
            run_id=dto.settings.authentication_token,
            base_url=dto.settings.artemis_base_url,
            lecture_unit_id=lecture_unit_id,
        ).fail(str(e), exception=e)
        capture_exception(e)


def run_lecture_deletion_pipeline_worker(dto: LecturesDeletionExecutionDto):
    """Run the lecture deletion pipeline in a separate thread."""
    callback = None
    try:
        callback = LecturesDeletionStatusCallback(
            run_id=dto.settings.authentication_token,
            base_url=dto.settings.artemis_base_url,
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
        if callback is not None:
            callback.fail(str(e), exception=e)
        capture_exception(e)


def run_faq_update_pipeline_worker(
    dto: FaqIngestionPipelineExecutionDto, variant_id: str
):
    """Run the FAQ ingestion pipeline in a separate thread."""
    callback = None
    try:
        callback = FaqIngestionStatus(
            run_id=dto.settings.authentication_token,
            base_url=dto.settings.artemis_base_url,
            faq_id=dto.faq.faq_id,
        )
        db = VectorDatabase()
        client = db.get_client()
        variant = find_variant(FaqIngestionPipeline.get_variants(), variant_id)
        is_local = bool(
            dto.settings and dto.settings.artemis_llm_selection == "LOCAL_AI"
        )
        pipeline = FaqIngestionPipeline(
            client=client,
            dto=dto,
            callback=callback,
            variant=variant,
            local=is_local,
        )
        pipeline()
    except Exception as e:
        logger.error("Error in FAQ ingestion pipeline", exc_info=e)
        if callback is not None:
            callback.fail(str(e), exception=e)
        capture_exception(e)


def run_faq_delete_pipeline_worker(dto: FaqDeletionExecutionDto, variant_id: str):
    """Run the FAQ deletion in a separate thread."""
    callback = None
    try:
        callback = FaqIngestionStatus(
            run_id=dto.settings.authentication_token,
            base_url=dto.settings.artemis_base_url,
            faq_id=dto.faq.faq_id,
        )
        db = VectorDatabase()
        client = db.get_client()
        variant = find_variant(FaqIngestionPipeline.get_variants(), variant_id)
        is_local = bool(
            dto.settings and dto.settings.artemis_llm_selection == "LOCAL_AI"
        )
        pipeline = FaqIngestionPipeline(
            client=client,
            dto=None,
            callback=callback,
            variant=variant,
            local=is_local,
        )
        if pipeline.delete_faq(dto.faq.faq_id, dto.faq.course_id):
            callback.finish()
        else:
            callback.fail("Error while removing old faqs")
    except Exception as e:
        logger.error("Error in FAQ deletion pipeline", exc_info=e)
        if callback is not None:
            callback.fail(str(e), exception=e)
        capture_exception(e)


@router.post(
    "/lectures/ingest",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(TokenValidator())],
)
@observe(name="POST /webhooks/lectures/ingest")
def lecture_ingestion_webhook(dto: IngestionPipelineExecutionDto):
    """Webhook endpoint to trigger the lecture ingestion pipeline."""
    variant = validate_pipeline_variant(dto.settings, LectureIngestionUpdatePipeline)

    cancel_event = ingestion_job_handler.create_cancellation_event()
    thread = Thread(
        target=run_lecture_update_pipeline_worker,
        args=(dto, variant, cancel_event),
    )
    ingestion_job_handler.add_job(
        process=thread,
        course_id=dto.lecture_unit.course_id,
        lecture_id=dto.lecture_unit.lecture_id,
        lecture_unit_id=dto.lecture_unit.lecture_unit_id,
        cancel_event=cancel_event,
    )


@router.post(
    "/lectures/metadata",
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        status.HTTP_404_NOT_FOUND: {
            "description": "Lecture unit has not been ingested",
        }
    },
    dependencies=[Depends(TokenValidator())],
)
@observe(name="POST /webhooks/lectures/metadata")
def lecture_metadata_webhook(dto: LectureUnitMetadataUpdateDTO):
    """Update lecture-unit metadata without reprocessing its content."""
    with lecture_update_lock(
        dto.base_url, dto.course_id, dto.lecture_id, dto.lecture_unit_id
    ):
        db = VectorDatabase()
        collection = init_lecture_unit_schema(db.get_client())
        updated = LectureMetadataUpdatePipeline(collection)(dto)
    if updated == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lecture unit has not been ingested",
        )


@router.post(
    "/lectures/visibility",
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        status.HTTP_404_NOT_FOUND: {
            "description": "Lecture unit has not been ingested",
        }
    },
    dependencies=[Depends(TokenValidator())],
)
@observe(name="POST /webhooks/lectures/visibility")
def lecture_visibility_webhook(dto: LectureUnitVisibilityUpdateDTO):
    """Update release and slide visibility without reprocessing content."""
    with lecture_update_lock(
        dto.base_url, dto.course_id, dto.lecture_id, dto.lecture_unit_id
    ):
        db = VectorDatabase()
        client = db.get_client()
        result = LectureVisibilityUpdatePipeline(
            init_lecture_unit_page_chunk_schema(client),
            init_lecture_unit_schema(client),
            init_lecture_unit_segment_schema(client),
        )(dto)
    if result.lecture_units_updated == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lecture unit has not been ingested",
        )


@router.post(
    "/lectures/delete",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(TokenValidator())],
)
@observe(name="POST /webhooks/lectures/delete")
def lecture_deletion_webhook(dto: LecturesDeletionExecutionDto):
    """Webhook endpoint to trigger the lecture deletion."""
    validate_pipeline_variant(dto.settings, LectureUnitDeletionPipeline)

    thread = Thread(target=run_lecture_deletion_pipeline_worker, args=(dto,))
    thread.start()


@router.post(
    "/faqs/ingest",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(TokenValidator())],
)
@observe(name="POST /webhooks/faqs/ingest")
def faq_ingestion_webhook(dto: FaqIngestionPipelineExecutionDto):
    """Webhook endpoint to trigger the FAQ ingestion pipeline."""
    variant = validate_pipeline_variant(dto.settings, FaqIngestionPipeline)

    thread = Thread(target=run_faq_update_pipeline_worker, args=(dto, variant))
    thread.start()


@router.post(
    "/faqs/delete",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(TokenValidator())],
)
@observe(name="POST /webhooks/faqs/delete")
def faq_deletion_webhook(dto: FaqDeletionExecutionDto):
    """Webhook endpoint to trigger the FAQ deletion pipeline."""
    variant = validate_pipeline_variant(dto.settings, FaqIngestionPipeline)

    thread = Thread(target=run_faq_delete_pipeline_worker, args=(dto, variant))
    thread.start()
