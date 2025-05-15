import logging
import os
import time
import traceback
import uuid

from fastapi import FastAPI, HTTPException

from nebula.security import AuthMiddleware, add_security_schema_to_app
from nebula.health import create_health_router
from nebula.transcript.config import Config
from nebula.transcript.align_utils import align_slides_with_segments
from nebula.transcript.slide_utils import ask_gpt_for_slide_number
from nebula.transcript.video_utils import (
    download_video,
    extract_audio,
    extract_frames_at_timestamps,
)
from nebula.transcript.whisper_utils import transcribe_with_azure_whisper
from nebula.transcript.dto import (
    TranscribeRequestDTO,
    TranscriptionSegmentDTO,
    TranscriptionResponseDTO,
)


# Get the API token from config
token = Config.API_KEYS[0] if Config.API_KEYS else "fallback-token"

# Initialize FastAPI app
app = FastAPI()

# Register authentication middleware
app.add_middleware(
    AuthMiddleware,
    api_key=token,
    exclude_paths=["/health", "/docs", "/openapi.json"],
    header_name="Authorization",
)

# Health check router
app.include_router(create_health_router(app_version="1.0.0"))

# Add security schema to OpenAPI
add_security_schema_to_app(
    app,
    header_name="Authorization",
    exclude_paths=["/health", "/docs", "/openapi.json"],
)

# Setup logging
logging.basicConfig(level=getattr(logging, Config.LOG_LEVEL))

# Ensure temp directory exists
Config.ensure_dirs()


@app.get("/")
async def home():
    return {"message": "FastAPI server is running!"}


@app.post("/start-transcribe", response_model=TranscriptionResponseDTO)
async def start_transcribe(req: TranscribeRequestDTO):
    video_url = req.videoUrl
    if not video_url:
        raise HTTPException(status_code=400, detail="Missing videoUrl")

    uid = str(uuid.uuid4())
    video_path = os.path.join(Config.VIDEO_STORAGE_PATH, f"{uid}.mp4")
    audio_path = os.path.join(Config.VIDEO_STORAGE_PATH, f"{uid}.wav")

    try:
        # Download and process media
        download_video(video_url, video_path)
        extract_audio(video_path, audio_path)

        # Transcribe
        transcription = transcribe_with_azure_whisper(audio_path)

        # Extract frames
        timestamps = [s["start"] for s in transcription["segments"]]
        frames = extract_frames_at_timestamps(video_path, timestamps)

        # Detect slide numbers
        slide_timestamps = []
        for ts, img_b64 in frames:
            slide_number = ask_gpt_for_slide_number(img_b64)
            if slide_number is not None:
                slide_timestamps.append((ts, slide_number))
            time.sleep(2)  # GPT rate limit

        # Align slide numbers to transcript segments
        aligned_segments = align_slides_with_segments(
            transcription["segments"], slide_timestamps
        )
        segments = [TranscriptionSegmentDTO(**s) for s in aligned_segments]

        # Return structured response
        return TranscriptionResponseDTO(
            lectureUnitId=req.lectureUnitId,
            language=transcription.get("language", "en"),
            segments=segments,
        )

    except Exception as e:
        traceback.print_exc()
        logging.error("Transcription failed", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        try:
            os.remove(video_path)
            os.remove(audio_path)
        except Exception as cleanup_err:
            logging.warning(f"Cleanup failed: {cleanup_err}")
