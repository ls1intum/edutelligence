from threading import Thread
from typing import List

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sentry_sdk import capture_exception

from iris.common.logging_config import get_logger, get_request_id, set_request_id
from iris.dependencies import TokenValidator
from iris.domain import (
    ChatPipelineExecutionDTO,
    CompetencyExtractionPipelineExecutionDTO,
    FeatureDTO,
    InconsistencyCheckPipelineExecutionDTO,
)
from iris.domain.communication.communication_tutor_suggestion_pipeline_execution_dto import (
    CommunicationTutorSuggestionPipelineExecutionDTO,
)
from iris.domain.rewriting_pipeline_execution_dto import (
    RewritingPipelineExecutionDTO,
)
from iris.domain.variant.abstract_variant import AbstractVariant
from iris.llm.external.model import LanguageModel
from iris.llm.llm_manager import LlmManager
from iris.pipeline.chat.chat_context import ChatContext
from iris.pipeline.chat.chat_pipeline import ChatPipeline
from iris.pipeline.competency_extraction_pipeline import (
    CompetencyExtractionPipeline,
)
from iris.pipeline.faq_ingestion_pipeline import FaqIngestionPipeline
from iris.pipeline.inconsistency_check_pipeline import (
    InconsistencyCheckPipeline,
)
from iris.pipeline.lecture_ingestion_pipeline import LectureUnitPageIngestionPipeline
from iris.pipeline.rewriting_pipeline import RewritingPipeline
from iris.pipeline.tutor_suggestion_pipeline import TutorSuggestionPipeline
from iris.web.status.status_update import (
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
    dto: ChatPipelineExecutionDTO,
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
        pipeline = ChatPipeline(context=ChatContext.EXERCISE)
    except Exception as e:
        logger.error("Error preparing exercise chat pipeline", exc_info=e)
        capture_exception(e)
        return

    try:
        for variant in ChatPipeline.get_variants(ChatContext.EXERCISE):
            if variant.id == variant_id:
                break
        else:
            raise ValueError(f"Unknown variant: {variant_id}")

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
    dto: ChatPipelineExecutionDTO = Body(
        description="Exercise Chat Pipeline Execution DTO"
    ),
):
    # variant = validate_pipeline_variant(dto.settings, ExerciseChatAgentPipeline)
    variant = validate_pipeline_variant(dto.settings, ChatPipeline)
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
        for variant in ChatPipeline.get_variants():
            if variant.id == variant_id:
                break
        else:
            raise ValueError(f"Unknown variant: {variant_id}")
        pipeline = ChatPipeline(context=ChatContext.COURSE, event=event)
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
    dto: ChatPipelineExecutionDTO = Body(
        description="Course Chat Pipeline Execution DTO"
    ),
):
    variant = validate_pipeline_variant(dto.settings, ChatPipeline)
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
        for variant in ChatPipeline.get_variants():
            if variant.id == variant_id:
                break
        else:
            raise ValueError(f"Unknown variant: {variant_id}")
        pipeline = ChatPipeline(context=ChatContext.TEXT_EXERCISE)
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
        callback = LectureChatCallback(
            run_id=dto.settings.authentication_token,
            base_url=dto.settings.artemis_base_url,
            initial_stages=dto.initial_stages,
        )
        for variant in ChatPipeline.get_variants():
            if variant.id == variant_id:
                break
        else:
            raise ValueError(f"Unknown variant: {variant_id}")
        pipeline = ChatPipeline(context=ChatContext.LECTURE)
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
def run_text_exercise_chat_pipeline(dto: ChatPipelineExecutionDTO):
    variant = validate_pipeline_variant(dto.settings, ChatPipeline)
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
def run_lecture_chat_pipeline(dto: ChatPipelineExecutionDTO):
    variant = validate_pipeline_variant(dto.settings, ChatPipeline)
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
        pipeline = CompetencyExtractionPipeline(callback=callback)
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
        match variant:
            case "faq" | "problem_statement":
                pipeline = RewritingPipeline(callback=callback, variant=variant)
            case _:
                raise ValueError(f"Unknown variant: {variant}")
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
        pipeline = InconsistencyCheckPipeline(callback=callback)
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
        for variant in TutorSuggestionPipeline.get_variants():
            if variant.id == variant_id:
                break
        else:
            raise ValueError(f"Unknown variant: {variant_id}")
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


@router.get("/{feature}/variants")
def get_pipeline(feature: str) -> list[FeatureDTO]:
    """
    Get the pipeline variants for the given feature.
    """
    # Get available LLMs from LlmManager
    llm_manager = LlmManager()
    available_llms = llm_manager.entries

    match feature:
        case "CHAT":
            # ExerciseChatAgentPipeline.get_variants(), available_llms
            return get_available_variants(
                ChatPipeline.get_variants(ChatContext.EXERCISE), available_llms
            )
        case "PROGRAMMING_EXERCISE_CHAT":
            # ExerciseChatAgentPipeline.get_variants(), available_llms
            return get_available_variants(
                ChatPipeline.get_variants(ChatContext.EXERCISE), available_llms
            )
        case "TEXT_EXERCISE_CHAT":
            return get_available_variants(ChatPipeline.get_variants(), available_llms)
        case "COURSE_CHAT":
            return get_available_variants(ChatPipeline.get_variants(), available_llms)
        case "COMPETENCY_GENERATION":
            return get_available_variants(
                CompetencyExtractionPipeline.get_variants(), available_llms
            )
        case "LECTURE_CHAT":
            return get_available_variants(ChatPipeline.get_variants(), available_llms)
        case "INCONSISTENCY_CHECK":
            return get_available_variants(
                InconsistencyCheckPipeline.get_variants(), available_llms
            )
        case "REWRITING":
            return get_available_variants(
                RewritingPipeline.get_variants(), available_llms
            )
        case "LECTURE_INGESTION":
            return get_available_variants(
                LectureUnitPageIngestionPipeline.get_variants(), available_llms
            )
        case "FAQ_INGESTION":
            return get_available_variants(
                FaqIngestionPipeline.get_variants(), available_llms
            )
        case "TUTOR_SUGGESTION":
            return get_available_variants(
                TutorSuggestionPipeline.get_variants(), available_llms
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
    return [
        variant.feature_dto()
        for variant in all_variants
        if set(variant.required_models()).issubset(
            {llm.model for llm in available_llms}
        )
    ]
