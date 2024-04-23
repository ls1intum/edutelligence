import traceback
from asyncio.log import logger
from threading import Thread


from fastapi import APIRouter, status, Depends
from app.dependencies import TokenValidator
from ...domain.ingestion_pipeline_execution_dto import IngestionPipelineExecutionDto
from ...pipeline.lecture_ingestion_pipeline import LectureIngestionPipeline
from ...vector_database.database import VectorDatabase

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


def run_lecture_update_pipeline_worker(dto: IngestionPipelineExecutionDto):
    """
    Run the tutor chat pipeline in a separate thread"""
    try:
        db = VectorDatabase()
        client = db.get_client()
        pipeline = LectureIngestionPipeline(client, dto=dto)
        pipeline()
    except Exception as e:
        logger.error(f"Error Ingestion pipeline: {e}")
        logger.error(traceback.format_exc())


@router.post(
    "/lectures",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(TokenValidator())],
)
def lecture_webhook(dto: IngestionPipelineExecutionDto):
    """
    Webhook endpoint to trigger the tutor chat pipeline
    """
    thread = Thread(target=run_lecture_update_pipeline_worker, args=(dto,))
    thread.start()
