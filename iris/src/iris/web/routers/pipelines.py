from threading import Thread
from typing import List

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sentry_sdk import capture_exception

from iris.common.logging_config import get_logger, get_request_id, set_request_id
from iris.dependencies import TokenValidator
from iris.domain import (
    CompetencyExtractionPipelineExecutionDTO,
    CourseChatPipelineExecutionDTO,
    ExerciseChatPipelineExecutionDTO,
    FeatureDTO,
    InconsistencyCheckPipelineExecutionDTO,
)
from iris.domain.autonomous_tutor.autonomous_tutor_pipeline_execution_dto import (
    AutonomousTutorPipelineExecutionDTO,
)
from iris.domain.chat.lecture_chat.lecture_chat_pipeline_execution_dto import (
    LectureChatPipelineExecutionDTO,
)
from iris.domain.chat.text_exercise_chat.text_exercise_chat_pipeline_execution_dto import (
    TextExerciseChatPipelineExecutionDTO,
)
from iris.domain.communication.communication_tutor_suggestion_pipeline_execution_dto import (
    CommunicationTutorSuggestionPipelineExecutionDTO,
)
from iris.domain.rewriting_pipeline_execution_dto import (
    RewritingPipelineExecutionDTO,
)
from iris.domain.variant.abstract_variant import AbstractVariant, find_variant
from iris.llm.external.model import LanguageModel
from iris.llm.llm_configuration import LlmConfigurationError
from iris.llm.llm_manager import LlmManager
from iris.llm.llm_requirements import missing_llm_requirements
from iris.pipeline.autonomous_tutor_pipeline import AutonomousTutorPipeline
from iris.pipeline.chat.course_chat_pipeline import CourseChatPipeline
from iris.pipeline.chat.exercise_chat_agent_pipeline import (
    ExerciseChatAgentPipeline,
)
from iris.pipeline.chat.lecture_chat_pipeline import LectureChatPipeline
from iris.pipeline.chat.text_exercise_chat_pipeline import TextExerciseChatPipeline
from iris.pipeline.competency_extraction_pipeline import (
    CompetencyExtractionPipeline,
)
from iris.pipeline.faq_ingestion_pipeline import FaqIngestionPipeline
from iris.pipeline.inconsistency_check_pipeline import (
    InconsistencyCheckPipeline,
)
from iris.pipeline.lecture_ingestion_update_pipeline import (
    LectureIngestionUpdatePipeline,
)
from iris.pipeline.rewriting_pipeline import RewritingPipeline
from iris.pipeline.tutor_suggestion_pipeline import TutorSuggestionPipeline
from iris.web.status.status_update import (
    AutonomousTutorCallback,
    CompetencyExtractionCallback,
    CourseChatStatusCallback,
    ExerciseChatStatusCallback,
    InconsistencyCheckCallback,
    LectureChatCallback,
    RewritingCallback,
    TextExerciseChatCallback,
    TutorSuggestionCallback,
)
from iris.web.utils import validate_pipeline_variant

router = APIRouter(prefix="/api/v1/pipelines", tags=["pipelines"])
logger = get_logger(__name__)


def run_exercise_chat_pipeline_worker(
    dto: ExerciseChatPipelineExecutionDTO,
    variant_id: str,
    event: str | None,
    request_id: str,
):
    set_request_id(request_id)
    try:
        callback = ExerciseChatStatusCallback(
            run_id=dto.settings.authentication_token,
            base_url=dto.settings.artemis_base_url,
            initial_stages=dto.initial_stages,
        )
        is_local = bool(getattr(dto, "settings", None) and dto.settings.is_local())
        pipeline = ExerciseChatAgentPipeline(local=is_local)
    except Exception as e:
        logger.error("Error preparing exercise chat pipeline", exc_info=e)
        capture_exception(e)
        return

    try:
        variant = find_variant(ExerciseChatAgentPipeline.get_variants(), variant_id)

        pipeline(dto=dto, variant=variant, callback=callback, event=event)
    except Exception as e:
        logger.error("Error running exercise chat pipeline", exc_info=e)
        callback.error("Fatal error.", exception=e)


@router.post(
    "/programming-exercise-chat/run",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(TokenValidator())],
)
def run_exercise_chat_pipeline(
    event: str | None = Query(None, description="Event query parameter"),
    dto: ExerciseChatPipelineExecutionDTO = Body(
        description="Exercise Chat Pipeline Execution DTO"
    ),
):
    variant = validate_pipeline_variant(dto.settings, ExerciseChatAgentPipeline)
    request_id = get_request_id()
    thread = Thread(
        target=run_exercise_chat_pipeline_worker,
        args=(dto, variant, event, request_id),
    )
    thread.start()


def run_course_chat_pipeline_worker(dto, variant_id, event, request_id: str):
    set_request_id(request_id)
    try:
        callback = CourseChatStatusCallback(
            run_id=dto.settings.authentication_token,
            base_url=dto.settings.artemis_base_url,
            initial_stages=dto.initial_stages,
        )
        variant = find_variant(CourseChatPipeline.get_variants(), variant_id)
        is_local = bool(getattr(dto, "settings", None) and dto.settings.is_local())
        pipeline = CourseChatPipeline(event=event, local=is_local)
    except Exception as e:
        logger.error("Error preparing course chat pipeline", exc_info=e)
        capture_exception(e)
        return

    try:
        pipeline(dto=dto, callback=callback, variant=variant)
    except Exception as e:
        logger.error("Error running course chat pipeline", exc_info=e)
        callback.error("Fatal error.", exception=e)


@router.post(
    "/course-chat/run",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(TokenValidator())],
)
def run_course_chat_pipeline(
    event: str | None = Query(None, description="Event query parameter"),
    dto: CourseChatPipelineExecutionDTO = Body(
        description="Course Chat Pipeline Execution DTO"
    ),
):
    variant = validate_pipeline_variant(dto.settings, CourseChatPipeline)
    request_id = get_request_id()
    thread = Thread(
        target=run_course_chat_pipeline_worker,
        args=(dto, variant, event, request_id),
    )
    thread.start()


def run_text_exercise_chat_pipeline_worker(dto, variant_id, request_id: str):
    set_request_id(request_id)
    try:
        callback = TextExerciseChatCallback(
            run_id=dto.settings.authentication_token,
            base_url=dto.settings.artemis_base_url,
            initial_stages=dto.initial_stages,
        )
        variant = find_variant(TextExerciseChatPipeline.get_variants(), variant_id)
        is_local = bool(getattr(dto, "settings", None) and dto.settings.is_local())
        pipeline = TextExerciseChatPipeline(local=is_local)
    except Exception as e:
        logger.error("Error preparing text exercise chat pipeline", exc_info=e)
        capture_exception(e)
        return

    try:
        pipeline(dto=dto, variant=variant, callback=callback)
    except Exception as e:
        logger.error("Error running text exercise chat pipeline", exc_info=e)
        callback.error("Fatal error.", exception=e)


def run_lecture_chat_pipeline_worker(dto, variant_id, request_id: str):
    set_request_id(request_id)
    try:
        is_local = bool(getattr(dto, "settings", None) and dto.settings.is_local())
        callback = LectureChatCallback(
            run_id=dto.settings.authentication_token,
            base_url=dto.settings.artemis_base_url,
            initial_stages=dto.initial_stages,
        )
        variant = find_variant(LectureChatPipeline.get_variants(), variant_id)
        pipeline = LectureChatPipeline(local=is_local)
    except Exception as e:
        logger.error("Error preparing lecture chat pipeline", exc_info=e)
        capture_exception(e)
        return

    try:
        pipeline(dto=dto, variant=variant, callback=callback)
    except Exception as e:
        logger.error("Error running lecture chat pipeline", exc_info=e)
        callback.error("Fatal error.", exception=e)


@router.post(
    "/text-exercise-chat/run",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(TokenValidator())],
)
def run_text_exercise_chat_pipeline(dto: TextExerciseChatPipelineExecutionDTO):
    variant = validate_pipeline_variant(dto.settings, TextExerciseChatPipeline)
    request_id = get_request_id()
    thread = Thread(
        target=run_text_exercise_chat_pipeline_worker,
        args=(dto, variant, request_id),
    )
    thread.start()


@router.post(
    "/lecture-chat/run",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(TokenValidator())],
)
def run_lecture_chat_pipeline(dto: LectureChatPipelineExecutionDTO):
    variant = validate_pipeline_variant(dto.settings, LectureChatPipeline)
    request_id = get_request_id()
    thread = Thread(
        target=run_lecture_chat_pipeline_worker,
        args=(dto, variant, request_id),
    )
    thread.start()


def run_competency_extraction_pipeline_worker(
    dto: CompetencyExtractionPipelineExecutionDTO, _variant: str, request_id: str
):  # pylint: disable=invalid-name
    set_request_id(request_id)
    try:
        callback = CompetencyExtractionCallback(
            run_id=dto.execution.settings.authentication_token,
            base_url=dto.execution.settings.artemis_base_url,
            initial_stages=dto.execution.initial_stages,
        )
        variant = find_variant(CompetencyExtractionPipeline.get_variants(), _variant)
        is_local = bool(
            getattr(dto.execution, "settings", None)
            and dto.execution.settings.is_local()
        )
        pipeline = CompetencyExtractionPipeline(
            callback=callback, variant=variant, local=is_local
        )
    except Exception as e:
        logger.error("Error preparing competency extraction pipeline", exc_info=e)
        capture_exception(e)
        return

    try:
        pipeline(dto=dto)
    except Exception as e:
        logger.error("Error running competency extraction pipeline", exc_info=e)
        callback.error("Fatal error.", exception=e)


@router.post(
    "/competency-extraction/run",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(TokenValidator())],
)
def run_competency_extraction_pipeline(dto: CompetencyExtractionPipelineExecutionDTO):
    variant = validate_pipeline_variant(
        dto.execution.settings, CompetencyExtractionPipeline
    )
    request_id = get_request_id()
    thread = Thread(
        target=run_competency_extraction_pipeline_worker,
        args=(dto, variant, request_id),
    )
    thread.start()


def run_rewriting_pipeline_worker(
    dto: RewritingPipelineExecutionDTO, variant: str, request_id: str
):
    set_request_id(request_id)
    try:
        callback = RewritingCallback(
            run_id=dto.execution.settings.authentication_token,
            base_url=dto.execution.settings.artemis_base_url,
            initial_stages=dto.execution.initial_stages,
        )
        v = find_variant(RewritingPipeline.get_variants(), variant)
        is_local = bool(
            getattr(dto.execution, "settings", None)
            and dto.execution.settings.is_local()
        )
        pipeline = RewritingPipeline(callback=callback, variant=v, local=is_local)
    except Exception as e:
        logger.error("Error preparing rewriting pipeline", exc_info=e)
        capture_exception(e)
        return

    try:
        pipeline(dto=dto)
    except Exception as e:
        logger.error("Error running rewriting pipeline", exc_info=e)
        callback.error("Fatal error.", exception=e)


@router.post(
    "/rewriting/run",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(TokenValidator())],
)
def run_rewriting_pipeline(dto: RewritingPipelineExecutionDTO):
    variant = validate_pipeline_variant(
        dto.execution.settings, RewritingPipeline
    ).lower()
    logger.info("Rewriting pipeline started | variant=%s", variant)
    request_id = get_request_id()
    thread = Thread(
        target=run_rewriting_pipeline_worker,
        args=(dto, variant, request_id),
    )
    thread.start()


def run_inconsistency_check_pipeline_worker(
    dto: InconsistencyCheckPipelineExecutionDTO, _variant: str, request_id: str
):  # pylint: disable=invalid-name
    set_request_id(request_id)
    try:
        callback = InconsistencyCheckCallback(
            run_id=dto.execution.settings.authentication_token,
            base_url=dto.execution.settings.artemis_base_url,
            initial_stages=dto.execution.initial_stages,
        )
        variant = find_variant(InconsistencyCheckPipeline.get_variants(), _variant)
        is_local = bool(
            getattr(dto.execution, "settings", None)
            and dto.execution.settings.is_local()
        )
        pipeline = InconsistencyCheckPipeline(
            callback=callback, variant=variant, local=is_local
        )
    except Exception as e:
        logger.error("Error preparing inconsistency check pipeline", exc_info=e)
        capture_exception(e)
        return

    try:
        pipeline(dto=dto)
    except Exception as e:
        logger.error("Error running inconsistency check pipeline", exc_info=e)
        callback.error("Fatal error.", exception=e)


@router.post(
    "/inconsistency-check/run",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(TokenValidator())],
)
def run_inconsistency_check_pipeline(dto: InconsistencyCheckPipelineExecutionDTO):
    variant = validate_pipeline_variant(
        dto.execution.settings, InconsistencyCheckPipeline
    )
    request_id = get_request_id()
    thread = Thread(
        target=run_inconsistency_check_pipeline_worker,
        args=(dto, variant, request_id),
    )
    thread.start()


def run_communication_tutor_suggestions_pipeline_worker(
    dto: CommunicationTutorSuggestionPipelineExecutionDTO, variant_id, request_id: str
):  # pylint: disable=invalid-name
    set_request_id(request_id)
    logger.info("Communication tutor suggestions pipeline started")
    try:
        callback = TutorSuggestionCallback(
            run_id=dto.settings.authentication_token,
            base_url=dto.settings.artemis_base_url,
            initial_stages=dto.initial_stages,
        )
        variant = find_variant(TutorSuggestionPipeline.get_variants(), variant_id)
        pipeline = TutorSuggestionPipeline()
    except Exception as e:
        logger.error(
            "Error preparing communication tutor suggestions pipeline", exc_info=e
        )
        capture_exception(e)
        return

    try:
        pipeline(dto=dto, callback=callback, variant=variant)
    except Exception as e:
        logger.error(
            "Error running communication tutor suggestions pipeline", exc_info=e
        )
        callback.error("Fatal error.", exception=e)


@router.post(
    "/tutor-suggestion/run",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(TokenValidator())],
)
def run_communication_tutor_suggestions_pipeline(
    dto: CommunicationTutorSuggestionPipelineExecutionDTO,
):
    variant = validate_pipeline_variant(dto.settings, TutorSuggestionPipeline)
    request_id = get_request_id()
    thread = Thread(
        target=run_communication_tutor_suggestions_pipeline_worker,
        args=(dto, variant, request_id),
    )
    thread.start()


def run_autonomous_tutor_pipeline_worker(
    dto: AutonomousTutorPipelineExecutionDTO, variant_id: str, request_id: str
):
    set_request_id(request_id)
    logger.info("Autonomous tutor pipeline started")
    try:
        callback = AutonomousTutorCallback(
            run_id=dto.settings.authentication_token,
            base_url=dto.settings.artemis_base_url,
            initial_stages=dto.initial_stages,
        )
        variant = find_variant(AutonomousTutorPipeline.get_variants(), variant_id)
        pipeline = AutonomousTutorPipeline()
    except Exception as e:
        logger.error("Error preparing autonomous tutor pipeline", exc_info=e)
        capture_exception(e)
        return

    try:
        pipeline(dto=dto, variant=variant, callback=callback)
    except Exception as e:
        logger.error("Error running autonomous tutor pipeline", exc_info=e)
        callback.error("Fatal error.", exception=e)


@router.post(
    "/autonomous-tutor/run",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(TokenValidator())],
)
def run_autonomous_tutor_pipeline(dto: AutonomousTutorPipelineExecutionDTO):
    variant = validate_pipeline_variant(dto.settings, AutonomousTutorPipeline)
    request_id = get_request_id()
    thread = Thread(
        target=run_autonomous_tutor_pipeline_worker,
        args=(dto, variant, request_id),
    )
    thread.start()


@router.get("/{feature}/variants")
def get_pipeline(feature: str) -> list[FeatureDTO]:
    """
    Get the pipeline variants for the given feature.
    """
    # Get available LLMs from LlmManager
    llm_manager = LlmManager()
    available_llms = llm_manager.entries

    def safe_get_variants(get_variants_fn):
        try:
            return get_variants_fn()
        except LlmConfigurationError as e:
            logger.warning("LLM configuration incomplete for %s: %s", feature, e)
            return []

    match feature:
        case "CHAT":
            return get_available_variants(
                safe_get_variants(ExerciseChatAgentPipeline.get_variants),
                available_llms,
            )
        case "PROGRAMMING_EXERCISE_CHAT":
            return get_available_variants(
                safe_get_variants(ExerciseChatAgentPipeline.get_variants),
                available_llms,
            )
        case "TEXT_EXERCISE_CHAT":
            return get_available_variants(
                safe_get_variants(TextExerciseChatPipeline.get_variants), available_llms
            )
        case "COURSE_CHAT":
            return get_available_variants(
                safe_get_variants(CourseChatPipeline.get_variants), available_llms
            )
        case "COMPETENCY_GENERATION":
            return get_available_variants(
                safe_get_variants(CompetencyExtractionPipeline.get_variants),
                available_llms,
            )
        case "LECTURE_CHAT":
            return get_available_variants(
                safe_get_variants(LectureChatPipeline.get_variants), available_llms
            )
        case "INCONSISTENCY_CHECK":
            return get_available_variants(
                safe_get_variants(InconsistencyCheckPipeline.get_variants),
                available_llms,
            )
        case "REWRITING":
            return get_available_variants(
                safe_get_variants(RewritingPipeline.get_variants), available_llms
            )
        case "LECTURE_INGESTION":
            return get_available_variants(
                safe_get_variants(LectureIngestionUpdatePipeline.get_variants),
                available_llms,
            )
        case "FAQ_INGESTION":
            return get_available_variants(
                safe_get_variants(FaqIngestionPipeline.get_variants), available_llms
            )
        case "TUTOR_SUGGESTION":
            return get_available_variants(
                safe_get_variants(TutorSuggestionPipeline.get_variants), available_llms
            )
        case "AUTONOMOUS_TUTOR":
            return get_available_variants(
                safe_get_variants(AutonomousTutorPipeline.get_variants),
                available_llms,
            )
        case _:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown feature: {feature}",
            )


def get_available_variants(
    all_variants: List[AbstractVariant], available_llms: List[LanguageModel]
) -> List[FeatureDTO]:
    """
    Returns available variants for this pipeline based on available LLMs.

    :param all_variants: List of all variants for the pipeline
    :param available_llms: List of available language models

    :return: List of FeatureDTO objects for supported variants
    """
    available_ids = {llm.id for llm in available_llms}
    return [
        variant.feature_dto()
        for variant in all_variants
        if not missing_llm_requirements(
            variant.required_models(),
            available_ids=available_ids,
        )
    ]
