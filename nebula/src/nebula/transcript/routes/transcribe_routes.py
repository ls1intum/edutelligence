import logging

from fastapi import APIRouter, HTTPException

from nebula.transcript.dto import TranscribeRequestDTO
from nebula.transcript.jobs import create_job, get_job_status
from nebula.transcript.queue_worker import cancel_job_processing, enqueue_job

router = APIRouter()


@router.post("/start", tags=["internal"])
async def start_transcribe(req: TranscribeRequestDTO):
    if not req.videoUrl:
        raise HTTPException(status_code=400, detail="Missing videoUrl")
    job_id = await create_job()
    # Put the job into the FIFO queue and return immediately
    await enqueue_job(job_id, req)  # NEW
    logging.info("[Job %s] Accepted and queued", job_id)
    return {"status": "processing", "transcriptionId": job_id}


@router.get("/status/{job_id}", tags=["internal"])
async def get_transcription_status(job_id: str):
    return await get_job_status(job_id)


@router.post("/cancel/{job_id}", tags=["internal"])
async def cancel_transcription(job_id: str):
    """
    Cancel a transcription job by job_id.
    - If the job is queued but not started, it will be removed from the queue.
    - If the job is currently processing, it will be stopped and temp files cleaned up.
    - The next job in the queue will automatically start processing.
    """
    result = await cancel_job_processing(job_id)
    logging.info("[Job %s] Cancellation result: %s", job_id, result)
    return result


@router.get("/test")
async def test():
    return {"message": "Transcription service is up"}
