import logging
import traceback
from threading import Thread
from urllib.request import Request

from fastapi import APIRouter, status, Response, Depends, FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse

from app.domain import (
    ExerciseChatPipelineExecutionDTO, 
    CourseChatPipelineExecutionDTO,
    LectureChatPipelineExecutionDTO,
    ExerciseChatPipelineExecutionDTO, CourseChatPipelineExecutionDTO,
)
from app.pipeline.chat.lecture_chat_pipeline import LectureChatPipeline
from app.web.status.status_update import ExerciseChatStatusCallback, CourseChatStatusCallback
from app.pipeline.chat.course_chat_pipeline import CourseChatPipeline
from app.pipeline.chat.exercise_chat_pipeline import ExerciseChatPipeline
from app.web.status.status_update import ExerciseChatStatusCallback, CourseChatStatusCallback
from app.dependencies import TokenValidator

router = APIRouter(prefix="/api/v1/pipelines", tags=["pipelines"])
logger = logging.getLogger(__name__)


def run_exercise_chat_pipeline_worker(dto: ExerciseChatPipelineExecutionDTO):
    try:
        callback = ExerciseChatStatusCallback(
            run_id=dto.settings.authentication_token,
            base_url=dto.settings.artemis_base_url,
            initial_stages=dto.initial_stages,
        )
        pipeline = ExerciseChatPipeline(callback=callback)
    except Exception as e:
        logger.error(f"Error preparing exercise chat pipeline: {e}")
        logger.error(traceback.format_exc())
        return

    try:
        pipeline(dto=dto)
    except Exception as e:
        logger.error(f"Error running exercise chat pipeline: {e}")
        logger.error(traceback.format_exc())
        callback.error('Fatal error.')


def run_lecture_chat_pipeline_worker(dto: LectureChatPipelineExecutionDTO):
    """
    Run the lecture chat pipeline with the given DTO.
    """
    try:
        pipeline = LectureChatPipeline()
        pipeline(dto=dto)
    except Exception as e:
        logger.error(f"Error running tutor chat pipeline: {e}")
        logger.error(traceback.format_exc())


@router.post(
    "/tutor-chat/{variant}/run",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(TokenValidator())],
)
def run_exercise_chat_pipeline(variant: str, dto: ExerciseChatPipelineExecutionDTO):
    thread = Thread(target=run_exercise_chat_pipeline_worker, args=(dto,))
    thread.start()


def run_course_chat_pipeline_worker(dto, variant):
    try:
        callback = CourseChatStatusCallback(
            run_id=dto.settings.authentication_token,
            base_url=dto.settings.artemis_base_url,
            initial_stages=dto.initial_stages,
        )
        pipeline = CourseChatPipeline(callback=callback, variant=variant)
    except Exception as e:
        logger.error(f"Error preparing exercise chat pipeline: {e}")
        logger.error(traceback.format_exc())
        return

    try:
        pipeline(dto=dto)
    except Exception as e:
        logger.error(f"Error running exercise chat pipeline: {e}")
        logger.error(traceback.format_exc())
        callback.error('Fatal error.')



@router.post(
    "/course-chat/{variant}/run",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(TokenValidator())],
)
def run_course_chat_pipeline(variant: str, dto: CourseChatPipelineExecutionDTO):
    thread = Thread(target=run_course_chat_pipeline_worker, args=(dto, variant))
    thread.start()


@router.get("/{feature}")
def get_pipeline(feature: str):
    """
    Get the pipeline for the given feature.
    """
    return Response(status_code=status.HTTP_501_NOT_IMPLEMENTED)
