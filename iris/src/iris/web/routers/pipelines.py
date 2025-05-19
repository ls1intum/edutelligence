import logging
import traceback
from threading import Thread

from fastapi import APIRouter, Body, Depends, Query, Response, status
from sentry_sdk import capture_exception

from iris.dependencies import TokenValidator
from iris.domain import (
    CompetencyExtractionPipelineExecutionDTO,
    CourseChatPipelineExecutionDTO,
    ExerciseChatPipelineExecutionDTO,
    InconsistencyCheckPipelineExecutionDTO,
)
from iris.domain.chat.lecture_chat.lecture_chat_pipeline_execution_dto import (
    LectureChatPipelineExecutionDTO,
)
from iris.domain.communication.communication_tutor_suggestion_pipeline_execution_dto import (
    CommunicationTutorSuggestionPipelineExecutionDTO,
)
from iris.domain.rewriting_pipeline_execution_dto import (
    RewritingPipelineExecutionDTO,
)
from iris.domain.text_exercise_chat_pipeline_execution_dto import (
    TextExerciseChatPipelineExecutionDTO,
)
from iris.llm.llm_manager import LlmManager
from iris.pipeline.chat.course_chat_pipeline import CourseChatPipeline
from iris.pipeline.chat.exercise_chat_agent_pipeline import (
    ExerciseChatAgentPipeline,
)
from iris.pipeline.chat.lecture_chat_pipeline import LectureChatPipeline
from iris.pipeline.chat_gpt_wrapper_pipeline import ChatGPTWrapperPipeline
from iris.pipeline.competency_extraction_pipeline import (
    CompetencyExtractionPipeline,
)
from iris.pipeline.faq_ingestion_pipeline import FaqIngestionPipeline
from iris.pipeline.inconsistency_check_pipeline import (
    InconsistencyCheckPipeline,
)
from iris.pipeline.lecture_ingestion_pipeline import LectureUnitPageIngestionPipeline
from iris.pipeline.rewriting_pipeline import RewritingPipeline
from iris.pipeline.text_exercise_chat_pipeline import TextExerciseChatPipeline
from iris.pipeline.tutor_suggestion_pipeline import TutorSuggestionPipeline
from iris.web.status.status_update import (
    ChatGPTWrapperStatusCallback,
    CompetencyExtractionCallback,
    CourseChatStatusCallback,
    ExerciseChatStatusCallback,
    InconsistencyCheckCallback,
    LectureChatCallback,
    RewritingCallback,
    TextExerciseChatCallback,
    TutorSuggestionCallback,
)

router = APIRouter(prefix="/api/v1/pipelines", tags=["pipelines"])
logger = logging.getLogger(__name__)


def run_exercise_chat_pipeline_worker(
    dto: ExerciseChatPipelineExecutionDTO,
    variant: str,
    event: str | None = None,
):
    try:
        callback = ExerciseChatStatusCallback(
            run_id=dto.settings.authentication_token,
            base_url=dto.settings.artemis_base_url,
            initial_stages=dto.initial_stages,
        )
        pipeline = ExerciseChatAgentPipeline(
            callback=callback, variant=variant, event=event
        )
    except Exception as e:
        logger.error("Error preparing exercise chat pipeline: %s", e)
        logger.error(traceback.format_exc())
        capture_exception(e)
        return

    try:
        pipeline(dto=dto)
    except Exception as e:
        logger.error("Error running exercise chat pipeline: %s", e)
        logger.error(traceback.format_exc())
        callback.error("Fatal error.", exception=e)


def run_chatgpt_wrapper_pipeline_worker(
    dto: ExerciseChatPipelineExecutionDTO, _variant: str
):  # pylint: disable=invalid-name
    try:
        callback = ChatGPTWrapperStatusCallback(
            run_id=dto.settings.authentication_token,
            base_url=dto.settings.artemis_base_url,
            initial_stages=dto.initial_stages,
        )
        pipeline = ChatGPTWrapperPipeline(callback=callback)
    except Exception as e:
        logger.error("Error preparing ChatGPT wrapper pipeline: %s", e)
        logger.error(traceback.format_exc())
        callback.error("Fatal error.", exception=e)
        capture_exception(e)
        return

    try:
        pipeline(dto=dto)
    except Exception as e:
        logger.error("Error running ChatGPT wrapper pipeline: %s", e)
        logger.error(traceback.format_exc())
        callback.error("Fatal error.", exception=e)


@router.post(
    "/tutor-chat/{variant}/run",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(TokenValidator())],
)
def run_exercise_chat_pipeline(
    variant: str,
    event: str | None = Query(None, description="Event query parameter"),
    dto: ExerciseChatPipelineExecutionDTO = Body(
        description="Exercise Chat Pipeline Execution DTO"
    ),
):
    if variant == "chat-gpt-wrapper":
        thread = Thread(target=run_chatgpt_wrapper_pipeline_worker, args=(dto, variant))
    else:
        thread = Thread(
            target=run_exercise_chat_pipeline_worker,
            args=(dto, variant, event),
        )
    thread.start()


def run_course_chat_pipeline_worker(dto, variant, event):
    try:
        callback = CourseChatStatusCallback(
            run_id=dto.settings.authentication_token,
            base_url=dto.settings.artemis_base_url,
            initial_stages=dto.initial_stages,
        )
        pipeline = CourseChatPipeline(callback=callback, variant=variant, event=event)
    except Exception as e:
        logger.error("Error preparing exercise chat pipeline: %s", e)
        logger.error(traceback.format_exc())
        capture_exception(e)
        return

    try:
        pipeline(dto=dto)
    except Exception as e:
        logger.error("Error running exercise chat pipeline: %s", e)
        logger.error(traceback.format_exc())
        callback.error("Fatal error.", exception=e)


@router.post(
    "/course-chat/{variant}/run",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(TokenValidator())],
)
def run_course_chat_pipeline(
    variant: str,
    event: str | None = Query(None, description="Event query parameter"),
    dto: CourseChatPipelineExecutionDTO = Body(
        description="Course Chat Pipeline Execution DTO"
    ),
):
    thread = Thread(target=run_course_chat_pipeline_worker, args=(dto, variant, event))
    thread.start()


def run_text_exercise_chat_pipeline_worker(dto, variant):
    try:
        callback = TextExerciseChatCallback(
            run_id=dto.execution.settings.authentication_token,
            base_url=dto.execution.settings.artemis_base_url,
            initial_stages=dto.execution.initial_stages,
        )
        match variant:
            case "default" | "text_exercise_chat_pipeline_reference_impl":
                pipeline = TextExerciseChatPipeline(callback=callback)
            case _:
                raise ValueError(f"Unknown variant: {variant}")
    except Exception as e:
        logger.error("Error preparing text exercise chat pipeline: %s", e)
        logger.error(traceback.format_exc())
        capture_exception(e)
        return

    try:
        pipeline(dto=dto)
    except Exception as e:
        logger.error("Error running text exercise chat pipeline: %s", e)
        logger.error(traceback.format_exc())
        callback.error("Fatal error.", exception=e)


def run_lecture_chat_pipeline_worker(dto, variant):
    try:
        callback = LectureChatCallback(
            run_id=dto.settings.authentication_token,
            base_url=dto.settings.artemis_base_url,
            initial_stages=dto.initial_stages,
        )
        match variant:
            case "default" | "lecture_chat_pipeline_reference_impl":
                pipeline = LectureChatPipeline(
                    callback=callback, dto=dto, variant=variant
                )
            case _:
                raise ValueError(f"Unknown variant: {variant}")
    except Exception as e:
        logger.error("Error preparing lecture chat pipeline: %s", e)
        logger.error(traceback.format_exc())
        capture_exception(e)
        return

    try:
        pipeline(dto=dto)
    except Exception as e:
        logger.error("Error running lecture chat pipeline: %s", e)
        logger.error(traceback.format_exc())
        callback.error("Fatal error.", exception=e)


@router.post(
    "/text-exercise-chat/{variant}/run",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(TokenValidator())],
)
def run_text_exercise_chat_pipeline(
    variant: str, dto: TextExerciseChatPipelineExecutionDTO
):
    thread = Thread(target=run_text_exercise_chat_pipeline_worker, args=(dto, variant))
    thread.start()


@router.post(
    "/lecture-chat/{variant}/run",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(TokenValidator())],
)
def run_lecture_chat_pipeline(variant: str, dto: LectureChatPipelineExecutionDTO):
    thread = Thread(target=run_lecture_chat_pipeline_worker, args=(dto, variant))
    thread.start()


def run_competency_extraction_pipeline_worker(
    dto: CompetencyExtractionPipelineExecutionDTO, _variant: str
):  # pylint: disable=invalid-name
    try:
        callback = CompetencyExtractionCallback(
            run_id=dto.execution.settings.authentication_token,
            base_url=dto.execution.settings.artemis_base_url,
            initial_stages=dto.execution.initial_stages,
        )
        pipeline = CompetencyExtractionPipeline(callback=callback)
    except Exception as e:
        logger.error("Error preparing competency extraction pipeline: %s", e)
        logger.error(traceback.format_exc())
        capture_exception(e)
        return

    try:
        pipeline(dto=dto)
    except Exception as e:
        logger.error("Error running competency extraction pipeline: %s", e)
        logger.error(traceback.format_exc())
        callback.error("Fatal error.", exception=e)


@router.post(
    "/competency-extraction/{variant}/run",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(TokenValidator())],
)
def run_competency_extraction_pipeline(
    variant: str, dto: CompetencyExtractionPipelineExecutionDTO
):
    thread = Thread(
        target=run_competency_extraction_pipeline_worker, args=(dto, variant)
    )
    thread.start()


def run_rewriting_pipeline_worker(dto: RewritingPipelineExecutionDTO, variant: str):
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
        logger.error("Error preparing rewriting pipeline: %s", e)
        logger.error(traceback.format_exc())
        capture_exception(e)
        return

    try:
        pipeline(dto=dto)
    except Exception as e:
        logger.error("Error running rewriting extraction pipeline: %s", e)
        logger.error(traceback.format_exc())
        callback.error("Fatal error.", exception=e)


@router.post(
    "/rewriting/{variant}/run",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(TokenValidator())],
)
def run_rewriting_pipeline(variant: str, dto: RewritingPipelineExecutionDTO):
    variant = variant.lower()
    logger.info("Rewriting pipeline started with variant: %s and dto: %s", variant, dto)
    thread = Thread(target=run_rewriting_pipeline_worker, args=(dto, variant))
    thread.start()


def run_inconsistency_check_pipeline_worker(
    dto: InconsistencyCheckPipelineExecutionDTO, _variant: str
):  # pylint: disable=invalid-name
    try:
        callback = InconsistencyCheckCallback(
            run_id=dto.execution.settings.authentication_token,
            base_url=dto.execution.settings.artemis_base_url,
            initial_stages=dto.execution.initial_stages,
        )
        pipeline = InconsistencyCheckPipeline(callback=callback)
    except Exception as e:
        logger.error("Error preparing inconsistency check pipeline: %s", e)

    try:
        pipeline(dto=dto)
    except Exception as e:
        logger.error("Error running inconsistency check pipeline: %s", e)
        logger.error(traceback.format_exc())
        callback.error("Fatal error.", exception=e)


@router.post(
    "/inconsistency-check/{variant}/run",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(TokenValidator())],
)
def run_inconsistency_check_pipeline(
    variant: str, dto: InconsistencyCheckPipelineExecutionDTO
):
    thread = Thread(target=run_inconsistency_check_pipeline_worker, args=(dto, variant))
    thread.start()


def run_communication_tutor_suggestions_pipeline_worker(
    dto: CommunicationTutorSuggestionPipelineExecutionDTO, _variant: str
):  # pylint: disable=invalid-name
    logger.info("Communication tutor suggestions pipeline started with dto: %s", dto)
    try:
        callback = TutorSuggestionCallback(
            run_id=dto.settings.authentication_token,
            base_url=dto.settings.artemis_base_url,
            initial_stages=dto.initial_stages,
        )
        pipeline = TutorSuggestionPipeline(callback=callback)
    except Exception as e:
        logger.error("Error preparing communication tutor suggestions pipeline: %s", e)

    try:
        pipeline(dto=dto)
    except Exception as e:
        logger.error("Error running communication tutor suggestions pipeline: %s", e)
        logger.error(traceback.format_exc())
        callback.error("Fatal error.", exception=e)


@router.post(
    "/tutor-suggestion/{variant}/run",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(TokenValidator())],
)
def run_communication_tutor_suggestions_pipeline(
    variant: str, dto: CommunicationTutorSuggestionPipelineExecutionDTO
):
    thread = Thread(
        target=run_communication_tutor_suggestions_pipeline_worker, args=(dto, variant)
    )
    thread.start()


@router.get("/{feature}/variants")
def get_pipeline(feature: str):
    """
    Get the pipeline variants for the given feature.
    """
    # Get available LLMs from LlmManager
    llm_manager = LlmManager()
    available_llms = llm_manager.entries

    match feature:
        case "CHAT":
            return ChatGPTWrapperPipeline.get_variants(available_llms)
        case "PROGRAMMING_EXERCISE_CHAT":
            return ExerciseChatAgentPipeline.get_variants(available_llms)
        case "TEXT_EXERCISE_CHAT":
            return TextExerciseChatPipeline.get_variants(available_llms)
        case "COURSE_CHAT":
            return CourseChatPipeline.get_variants(available_llms)
        case "COMPETENCY_GENERATION":
            return CompetencyExtractionPipeline.get_variants(available_llms)
        case "LECTURE_CHAT":
            return LectureChatPipeline.get_variants(available_llms)
        case "INCONSISTENCY_CHECK":
            return InconsistencyCheckPipeline.get_variants(available_llms)
        case "REWRITING":
            return RewritingPipeline.get_variants(available_llms)
        case "CHAT_GPT_WRAPPER":
            return ChatGPTWrapperPipeline.get_variants(available_llms)
        case "LECTURE_INGESTION":
            return LectureUnitPageIngestionPipeline.get_variants(available_llms)
        case "FAQ_INGESTION":
            return FaqIngestionPipeline.get_variants(available_llms)
        case "TUTOR_SUGGESTION":
            return [
                FeatureDTO(
                    id="default",
                    name="Default Variant",
                    description="Default tutor suggestion variant.",
                )
            ]
        case _:
            return Response(status_code=status.HTTP_400_BAD_REQUEST)
