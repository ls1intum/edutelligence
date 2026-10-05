from threading import Event, Thread
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sentry_sdk import capture_exception

from iris.common.custom_exceptions import IngestionCancelledException
from iris.common.logging_config import get_logger
from iris.dependencies import TokenValidator
from iris.domain.ingestion.course_memory_ingestion_dto import (
    CourseMemoryIngestionExecutionDTO,
)
from iris.domain.ingestion.course_memory_sync_dto import (
    CourseMemoryCourseSyncDTO,
    CourseMemoryInstanceSyncDTO,
)
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
from iris.vector_database.write_retry import WeaviateRateLimitExhausted
from iris.web.utils import validate_pipeline_variant

from ...domain.ingestion.deletion_pipeline_execution_dto import (
    CourseMemoryDeletionExecutionDto,
    FaqDeletionExecutionDto,
    LecturesDeletionExecutionDto,
)
from ...ingestion.ingestion_job_handler import ingestion_job_handler
from ...pipeline.course_memory_ingestion_pipeline import (
    CourseMemoryDeleter,
    CourseMemoryIngestionPipeline,
)
from ...pipeline.delete_lecture_units_pipeline import LectureUnitDeletionPipeline
from ...pipeline.faq_ingestion_pipeline import FaqIngestionPipeline
from ...pipeline.lecture_ingestion_update_pipeline import LectureIngestionUpdatePipeline
from ...vector_database.database import VectorDatabase
from ..status.course_memory_ingestion_status_callback import (
    CourseMemoryIngestionStatus,
)
from ..status.faq_ingestion_status_callback import FaqIngestionStatus
from ..status.ingestion_status_callback import IngestionStatusCallback
from ..status.lecture_deletion_status_callback import (
    LecturesDeletionStatusCallback,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


def run_lecture_update_pipeline_worker(
    dto: IngestionPipelineExecutionDto,
    variant_id: str,
    cancel_event: Optional[Event] = None,
):
    """Run the lecture unit ingestion pipeline in a separate thread.

    No concurrency throttling here — Artemis controls how many jobs are
    dispatched via MAX_CONCURRENT_PROCESSING. Every job Iris receives
    starts immediately so Artemis has an accurate view of what's running.
    """
    lecture_unit_id = (
        dto.lecture_unit.lecture_unit_id
        if dto.lecture_unit is not None
        else dto.lecture_unit_id
    )
    lecture_unit = dto.lecture_unit
    try:
        pipeline = LectureIngestionUpdatePipeline(
            dto, variant_id=variant_id, cancel_event=cancel_event
        )
        pipeline()
    except IngestionCancelledException as e:
        logger.info("[Lecture %s] Worker cancelled: %s", lecture_unit_id, e.reason)
        return
    except Exception as e:
        logger.error(
            "[Lecture %s] Worker failed: %s",
            lecture_unit_id,
            e,
            exc_info=True,
        )
        callback = IngestionStatusCallback(
            run_id=dto.settings.authentication_token,
            base_url=dto.settings.artemis_base_url,
            lecture_unit_id=lecture_unit_id,
        )
        callback.fail(str(e), exception=e)
        capture_exception(e)
    finally:
        if lecture_unit is not None and cancel_event is not None:
            ingestion_job_handler.complete_job(
                base_url=dto.settings.artemis_base_url,
                course_id=lecture_unit.course_id,
                lecture_id=lecture_unit.lecture_id,
                lecture_unit_id=lecture_unit.lecture_unit_id,
                cancel_event=cancel_event,
            )


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
        base_url=dto.settings.artemis_base_url,
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
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": "Weaviate remained rate-limited past the request budget",
        },
    },
    dependencies=[Depends(TokenValidator())],
)
@observe(name="POST /webhooks/lectures/visibility")
def lecture_visibility_webhook(dto: LectureUnitVisibilityUpdateDTO):
    """Update release and slide visibility without reprocessing content."""
    try:
        db = VectorDatabase()
        client = db.get_client()
        result = LectureVisibilityUpdatePipeline(
            init_lecture_unit_page_chunk_schema(client),
            init_lecture_unit_schema(client),
            init_lecture_unit_segment_schema(client),
        )(dto)
    except WeaviateRateLimitExhausted as error:
        logger.error(
            "Weaviate remained rate-limited during a lecture visibility update | "
            "lecture_unit_id=%s attempts=%s",
            dto.lecture_unit_id,
            error.attempts,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "errorMessage": "Weaviate is temporarily rate-limited; retry later"
            },
        ) from error
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


def run_course_memory_ingestion_worker(
    dto: CourseMemoryIngestionExecutionDTO, variant_id: str
):
    """Run the course memory ingestion pipeline in a separate thread.

    Ordering against other operations on the same thread needs no sampling: the
    payload carries the Artemis operation version and the write compares against the
    stored one (see ``CourseMemoryIngestionPipeline.upsert``).
    """
    callback = None
    try:
        callback = CourseMemoryIngestionStatus(
            run_id=dto.settings.authentication_token,
            base_url=dto.settings.artemis_base_url,
        )
        db = VectorDatabase()
        client = db.get_client()
        variant = find_variant(CourseMemoryIngestionPipeline.get_variants(), variant_id)
        is_local = bool(
            dto.settings and dto.settings.artemis_llm_selection == "LOCAL_AI"
        )
        pipeline = CourseMemoryIngestionPipeline(
            client=client,
            dto=dto,
            callback=callback,
            variant=variant,
            local=is_local,
        )
        pipeline()
    except Exception as e:
        logger.error("Error in course memory ingestion pipeline", exc_info=e)
        # If the pipeline never ran (e.g. Weaviate/variant init failed), its own
        # error handling did not fire; notify Artemis so the job doesn't hang.
        if callback is not None:
            callback.fail(str(e), exception=e)
        capture_exception(e)


@router.post(
    "/course-memory/ingest",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(TokenValidator())],
)
@observe(name="POST /webhooks/course-memory/ingest")
def course_memory_ingestion_webhook(dto: CourseMemoryIngestionExecutionDTO):
    """Webhook endpoint to trigger course memory ingestion (Triggers A and B).

    The ``source`` field on the DTO distinguishes tutor verification
    (IRIS_AUTO / TUTOR_WRITTEN / IRIS_CORRECTED) from thread resolution
    (THREAD_RESOLVED).
    """
    # Logged before anything else runs: this is the line that says an ingestion was
    # *requested*, so a silent skip further down can be told apart from a trigger that
    # never fired at all. Rejected payloads never reach here — the validation handler in
    # main.py logs those at ERROR with the request path.
    logger.info(
        "Course memory ingestion webhook received: course=%s thread=%s message=%s "
        "version=%s source=%s public=%s thread_size=%d verified_flags=%d "
        "resolving_flags=%d",
        dto.course_id,
        dto.post_id,
        dto.message_id,
        dto.version,
        dto.source.value,
        dto.is_public_channel,
        len(dto.thread),
        sum(1 for message in dto.thread if message.is_verified_answer),
        sum(1 for message in dto.thread if message.resolves_post),
    )
    variant = validate_pipeline_variant(dto.settings, CourseMemoryIngestionPipeline)

    thread = Thread(
        target=run_course_memory_ingestion_worker,
        args=(dto, variant),
    )
    thread.start()


def run_course_memory_deletion_worker(dto: CourseMemoryDeletionExecutionDto):
    """Retract the entry of one thread, in a separate thread.

    Uses :class:`CourseMemoryDeleter` rather than the ingestion pipeline on
    purpose: the pipeline resolves a chat *and* an embedding model in its
    constructor, so a deployment running only local models — or one whose cloud
    variant is misconfigured — would ingest happily while every retraction failed
    on model resolution. Deleting needs nothing but the Weaviate collection.
    """
    callback = None
    try:
        callback = CourseMemoryIngestionStatus(
            run_id=dto.settings.authentication_token,
            base_url=dto.settings.artemis_base_url,
        )
        db = VectorDatabase()
        deleter = CourseMemoryDeleter(db.get_client())
        if deleter.delete_for_thread(
            dto.base_url, dto.post_id, dto.course_id, dto.version
        ):
            callback.finish()
        else:
            callback.fail("Error while deleting course memory entry")
    except Exception as e:
        logger.error("Error in course memory deletion pipeline", exc_info=e)
        if callback is not None:
            callback.fail(str(e), exception=e)
        capture_exception(e)


@router.post(
    "/course-memory/delete",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(TokenValidator())],
)
@observe(name="POST /webhooks/course-memory/delete")
def course_memory_deletion_webhook(dto: CourseMemoryDeletionExecutionDto):
    """Webhook endpoint to remove a course memory entry when its source answer is
    deleted or its verification is retracted in Artemis."""
    logger.info(
        "Course memory deletion webhook received: course=%s thread=%s version=%s",
        dto.course_id,
        dto.post_id,
        dto.version,
    )
    # No variant validation here, unlike the ingestion route: deletion resolves no
    # model, so rejecting a request over a variant nothing reads would only turn a
    # working retraction into a failed one.

    thread = Thread(target=run_course_memory_deletion_worker, args=(dto,))
    thread.start()


def run_course_memory_sync_worker(dto):
    """Reconcile Course Memory with the state Artemis reported, in a separate thread.

    No status callback: the sync is a nightly backstop that Artemis does not wait for;
    its outcome is logged here.
    """
    try:
        deleter = CourseMemoryDeleter(VectorDatabase().get_client())
        if isinstance(dto, CourseMemoryCourseSyncDTO):
            deleter.sync_course(dto)
        else:
            deleter.sync_instance(dto)
    except Exception as e:
        logger.error("Error in course memory sync", exc_info=e)
        capture_exception(e)


@router.post(
    "/course-memory/sync/course",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(TokenValidator())],
)
@observe(name="POST /webhooks/course-memory/sync/course")
def course_memory_course_sync_webhook(dto: CourseMemoryCourseSyncDTO):
    """Nightly sync of one course: retract every entry that is outdated, no longer
    eligible or belongs to a deleted thread. The list must be complete for the course.
    """
    logger.info(
        "Course memory course sync received: course=%s threads=%d",
        dto.course_id,
        len(dto.threads),
    )
    Thread(target=run_course_memory_sync_worker, args=(dto,)).start()


@router.post(
    "/course-memory/sync/instance",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(TokenValidator())],
)
@observe(name="POST /webhooks/course-memory/sync/instance")
def course_memory_instance_sync_webhook(dto: CourseMemoryInstanceSyncDTO):
    """Nightly sync of one Artemis instance: retract every entry of a deleted course."""
    logger.info("Course memory instance sync received: courses=%d", len(dto.course_ids))
    Thread(target=run_course_memory_sync_worker, args=(dto,)).start()
