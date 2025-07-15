import logging
import os

import httpx
from fastapi import APIRouter, HTTPException, Request

router = APIRouter()
logger = logging.getLogger("nebula.gateway.transcribe")

TRANSCRIBE_BASE_URL = os.getenv("TRANSCRIBE_SERVICE_URL", "http://transcript:5000")


@router.post("/start")
async def proxy_start_transcription(request: Request):
    logger.info("Proxying /transcribe/start -> /start")

    try:
        body = await request.json()
    except Exception as exc:
        logger.warning("Invalid JSON body in start request.")
        raise HTTPException(status_code=400, detail="Invalid JSON body.") from exc

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(f"{TRANSCRIBE_BASE_URL}/transcribe/start", json=body)

        response.raise_for_status()
        logger.info("Transcription started successfully.")
        return response.json()

    except httpx.RequestError as exc:
        logger.error("Could not reach transcript service: %s", exc)
        raise HTTPException(
            status_code=502, detail=f"Transcription service unreachable: {exc}"
        ) from exc

    except httpx.HTTPStatusError as exc:
        logger.error("Transcript service error: %s", exc.response.text)
        raise HTTPException(
            status_code=exc.response.status_code, detail=exc.response.text
        ) from exc


@router.get("/status/{job_id}")
async def proxy_transcription_status(job_id: str):
    logger.info("Checking status for job: %s", job_id)

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{TRANSCRIBE_BASE_URL}/transcribe/status/{job_id}"
            )
            response.raise_for_status()  # Move inside this block

        logger.info("Status fetched successfully.")
        return response.json()

    except httpx.RequestError as exc:
        logger.error("Could not reach transcript service: %s", exc)
        raise HTTPException(
            status_code=502, detail=f"Transcription service unreachable: {exc}"
        ) from exc

    except httpx.HTTPStatusError as exc:
        logger.error("Transcript service error: %s", exc.response.text)
        raise HTTPException(
            status_code=exc.response.status_code, detail=exc.response.text
        ) from exc
