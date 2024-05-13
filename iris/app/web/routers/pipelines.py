import logging
import traceback
from threading import Thread
from urllib.request import Request

from fastapi import APIRouter, status, Response, Depends, FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse

from app.domain import (
    TutorChatPipelineExecutionDTO, CourseChatPipelineExecutionDTO,
)
from app.pipeline.chat.course_chat_pipeline import CourseChatPipeline
from app.pipeline.chat.tutor_chat_pipeline import TutorChatPipeline
from app.web.status.status_update import TutorChatStatusCallback, CourseChatStatusCallback
from app.dependencies import TokenValidator

router = APIRouter(prefix="/api/v1/pipelines", tags=["pipelines"])
logger = logging.getLogger(__name__)


def run_tutor_chat_pipeline_worker(dto: TutorChatPipelineExecutionDTO):
    try:
        callback = TutorChatStatusCallback(
            run_id=dto.base.settings.authentication_token,
            base_url=dto.base.settings.artemis_base_url,
            initial_stages=dto.base.initial_stages,
        )
        pipeline = TutorChatPipeline(callback=callback)
    except Exception as e:
        logger.error(f"Error preparing tutor chat pipeline: {e}")
        logger.error(traceback.format_exc())
        return

    try:
        pipeline(dto=dto)
    except Exception as e:
        logger.error(f"Error running tutor chat pipeline: {e}")
        logger.error(traceback.format_exc())
        callback.error('Fatal error.')


@router.post(
    "/tutor-chat/{variant}/run",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(TokenValidator())],
)
def run_tutor_chat_pipeline(variant: str, dto: TutorChatPipelineExecutionDTO):
    thread = Thread(target=run_tutor_chat_pipeline_worker, args=(dto,))
    thread.start()


def run_course_chat_pipeline_worker(dto):
    try:
        callback = CourseChatStatusCallback(
            run_id=dto.base.settings.authentication_token,
            base_url=dto.base.settings.artemis_base_url,
            initial_stages=dto.base.initial_stages,
        )
        pipeline = CourseChatPipeline(callback=callback)
    except Exception as e:
        logger.error(f"Error preparing tutor chat pipeline: {e}")
        logger.error(traceback.format_exc())
        return

    try:
        pipeline(dto=dto)
    except Exception as e:
        logger.error(f"Error running tutor chat pipeline: {e}")
        logger.error(traceback.format_exc())
        callback.error('Fatal error.')



@router.post(
    "/course-chat/{variant}/run",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(TokenValidator())],
)
def run_course_chat_pipeline(variant: str, dto: CourseChatPipelineExecutionDTO):
    thread = Thread(target=run_course_chat_pipeline_worker, args=(dto,))
    thread.start()


@router.get("/{feature}")
def get_pipeline(feature: str):
    return Response(status_code=status.HTTP_501_NOT_IMPLEMENTED)
