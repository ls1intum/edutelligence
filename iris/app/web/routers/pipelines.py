import logging
import traceback
from threading import Thread

from fastapi import APIRouter, status, Response, Depends
from app.domain import (
    TutorChatPipelineExecutionDTO,
    LectureChatPipelineExecutionDTO,
)
from app.pipeline.chat.lecture_chat_pipeline import LectureChatPipeline
from app.pipeline.chat.tutor_chat_pipeline import TutorChatPipeline
from app.web.status.tutor_chat_status_callback import TutorChatStatusCallback
from app.dependencies import TokenValidator

router = APIRouter(prefix="/api/v1/pipelines", tags=["pipelines"])
logger = logging.getLogger(__name__)


def run_tutor_chat_pipeline_worker(dto):
    """
    Run the tutor chat pipeline with the given DTO.
    """
    try:
        callback = TutorChatStatusCallback(
            run_id=dto.settings.authentication_token,
            base_url=dto.settings.artemis_base_url,
            initial_stages=dto.initial_stages,
        )
        pipeline = TutorChatPipeline(callback=callback)
        pipeline(dto=dto)
    except Exception as e:
        logger.error(f"Error running tutor chat pipeline: {e}")
        logger.error(traceback.format_exc())


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
def run_tutor_chat_pipeline(variant: str, dto: TutorChatPipelineExecutionDTO):
    """
    Run the tutor chat pipeline with the given DTO.
    """
    thread = Thread(target=run_tutor_chat_pipeline_worker, args=(dto,))
    thread.start()


@router.post(
    "/lecture-chat/{variant}/run",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(TokenValidator())],
)
def run_lecture_chat_pipeline(variant: str, dto: LectureChatPipelineExecutionDTO):
    """
    Run the lecture chat pipeline with the given DTO.
    """
    thread = Thread(target=run_lecture_chat_pipeline_worker, args=(dto,))
    thread.start()


@router.get("/{feature}")
def get_pipeline(feature: str):
    """
    Get the pipeline for the given feature.
    """
    return Response(status_code=status.HTTP_501_NOT_IMPLEMENTED)
