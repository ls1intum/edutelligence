import traceback
from asyncio.log import logger
from threading import Thread

from ...domain.data.lecture_unit_dto import LectureUnitDTO

from fastapi import APIRouter, status, Response, Depends

from app.dependencies import TokenValidator
from ...pipeline.lecture_ingestion_pipeline import LectureIngestionPipeline
from ...vector_database.db import VectorDatabase

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


def run_lecture_update_pipeline_worker(dto):
    try:
        pipeline = LectureIngestionPipeline(VectorDatabase().client)
        pipeline(dto=dto)
    except Exception as e:
        logger.error(f"Error running tutor chat pipeline: {e}")
        logger.error(traceback.format_exc())


@router.post("/lecture-units",
             status_code=status.HTTP_202_ACCEPTED,
             dependencies=[Depends(TokenValidator())]
             )
def lecture_webhook(dto: LectureUnitDTO):
    thread = Thread(target=run_lecture_update_pipeline_worker, args=(dto,))
    thread.start()


@router.post("/assignment")
def assignment_webhook():
    return Response(status_code=status.HTTP_501_NOT_IMPLEMENTED)
