import logging
import traceback
from threading import Thread
from typing import List

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sentry_sdk import capture_exception

from iris.dependencies import TokenValidator
from iris.domain import (
    CompetencyExtractionPipelineExecutionDTO,
    CourseChatPipelineExecutionDTO,
    ExerciseChatPipelineExecutionDTO,
    FeatureDTO,
    InconsistencyCheckPipelineExecutionDTO,
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
from iris.domain.variant.abstract_variant import AbstractVariant
from iris.llm.external.model import LanguageModel
from iris.llm.llm_manager import LlmManager
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
logger = logging.getLogger(__name__)


def run_exercise_chat_pipeline_worker(
    dto: ExerciseChatPipelineExecutionDTO,
    variant_id: str,
    event: str | None = None,
):
    try:
        callback = ExerciseChatStatusCallback(
            run_id=dto.settings.authentication_token,
            base_url=dto.settings.artemis_base_url,
            initial_stages=dto.initial_stages,
        )
        pipeline = ExerciseChatAgentPipeline(local=dto.settings.is_local())
    except Exception as e:
        logger.error("Error preparing exercise chat pipeline: %s", e)
        logger.error(traceback.format_exc())
        capture_exception(e)
        return

    try:
        for variant in ExerciseChatAgentPipeline.get_variants():
            if variant.id == variant_id:
                break
        else:
            raise ValueError(f"Unknown variant: {variant_id}")

        pipeline(dto=dto, variant=variant, callback=callback, event=event)
    except Exception as e:
        logger.error("Error running exercise chat pipeline: %s", e)
        logger.error(traceback.format_exc())
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
    thread = Thread(
        target=run_exercise_chat_pipeline_worker,
        args=(dto, variant, event),
    )
    thread.start()


def run_course_chat_pipeline_worker(dto, variant_id, event):
    try:
        callback = CourseChatStatusCallback(
            run_id=dto.settings.authentication_token,
            base_url=dto.settings.artemis_base_url,
            initial_stages=dto.initial_stages,
        )
        for variant in CourseChatPipeline.get_variants():
            if variant.id == variant_id:
                break
        else:
            raise ValueError(f"Unknown variant: {variant_id}")
        pipeline = CourseChatPipeline(event=event, local=dto.settings.is_local())
    except Exception as e:
        logger.error("Error preparing exercise chat pipeline: %s", e)
        logger.error(traceback.format_exc())
        capture_exception(e)
        return

    try:
        pipeline(dto=dto, callback=callback, variant=variant)
    except Exception as e:
        logger.error("Error running exercise chat pipeline: %s", e)
        logger.error(traceback.format_exc())
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

    thread = Thread(target=run_course_chat_pipeline_worker, args=(dto, variant, event))
    thread.start()


def run_text_exercise_chat_pipeline_worker(dto, variant_id):
    try:
        callback = TextExerciseChatCallback(
            run_id=dto.settings.authentication_token,
            base_url=dto.settings.artemis_base_url,
            initial_stages=dto.initial_stages,
        )
        for variant in TextExerciseChatPipeline.get_variants():
            if variant.id == variant_id:
                break
        else:
            raise ValueError(f"Unknown variant: {variant_id}")
        pipeline = TextExerciseChatPipeline(local=dto.settings.is_local())
    except Exception as e:
        logger.error("Error preparing text exercise chat pipeline: %s", e)
        logger.error(traceback.format_exc())
        capture_exception(e)
        return

    try:
        pipeline(dto=dto, variant=variant, callback=callback)
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
        pipeline = LectureChatPipeline(callback=callback, dto=dto, variant=variant)
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
    "/text-exercise-chat/run",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(TokenValidator())],
)
def run_text_exercise_chat_pipeline(dto: TextExerciseChatPipelineExecutionDTO):
    variant = validate_pipeline_variant(dto.settings, TextExerciseChatPipeline)

    thread = Thread(target=run_text_exercise_chat_pipeline_worker, args=(dto, variant))
    thread.start()


@router.post(
    "/lecture-chat/run",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(TokenValidator())],
)
def run_lecture_chat_pipeline(dto: LectureChatPipelineExecutionDTO):
    variant = validate_pipeline_variant(dto.settings, LectureChatPipeline)

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
        pipeline = CompetencyExtractionPipeline(
            callback=callback, local=dto.execution.settings.is_local()
        )
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
    "/competency-extraction/run",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(TokenValidator())],
)
def run_competency_extraction_pipeline(dto: CompetencyExtractionPipelineExecutionDTO):
    variant = validate_pipeline_variant(
        dto.execution.settings, CompetencyExtractionPipeline
    )

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
                is_local = bool(
                    dto.execution.settings and dto.execution.settings.is_local()
                )
                pipeline = RewritingPipeline(
                    callback=callback, variant=variant, local=is_local
                )
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
    "/rewriting/run",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(TokenValidator())],
)
def run_rewriting_pipeline(dto: RewritingPipelineExecutionDTO):
    variant = validate_pipeline_variant(
        dto.execution.settings, RewritingPipeline
    ).lower()
    logger.info("Rewriting pipeline started with variant: %s and dlo: %s", variant, dto)

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
        pipeline = InconsistencyCheckPipeline(
            callback=callback, local=dto.execution.settings.is_local()
        )
    except Exception as e:
        logger.error("Error preparing inconsistency check pipeline: %s", e)

    try:
        pipeline(dto=dto)
    except Exception as e:
        logger.error("Error running inconsistency check pipeline: %s", e)
        logger.error(traceback.format_exc())
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

    thread = Thread(target=run_inconsistency_check_pipeline_worker, args=(dto, variant))
    thread.start()


def run_communication_tutor_suggestions_pipeline_worker(
    dto: CommunicationTutorSuggestionPipelineExecutionDTO, variant_id
):  # pylint: disable=invalid-name
    logger.info("Communication tutor suggestions pipeline started with dlo: %s", dto)
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
        logger.error("Error preparing communication tutor suggestions pipeline: %s", e)
        logger.error(traceback.format_exc())
        capture_exception(e)
        return

    try:
        pipeline(dto=dto, callback=callback, variant=variant)
    except Exception as e:
        logger.error("Error running communication tutor suggestions pipeline: %s", e)
        logger.error(traceback.format_exc())
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

    thread = Thread(
        target=run_communication_tutor_suggestions_pipeline_worker, args=(dto, variant)
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
            return get_available_variants(
                ExerciseChatAgentPipeline.get_variants(), available_llms
            )
        case "PROGRAMMING_EXERCISE_CHAT":
            return get_available_variants(
                ExerciseChatAgentPipeline.get_variants(), available_llms
            )
        case "TEXT_EXERCISE_CHAT":
            return get_available_variants(
                TextExerciseChatPipeline.get_variants(), available_llms
            )
        case "COURSE_CHAT":
            return get_available_variants(
                CourseChatPipeline.get_variants(), available_llms
            )
        case "COMPETENCY_GENERATION":
            return get_available_variants(
                CompetencyExtractionPipeline.get_variants(), available_llms
            )
        case "LECTURE_CHAT":
            return get_available_variants(
                LectureChatPipeline.get_variants(), available_llms
            )
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
