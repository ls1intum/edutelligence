import logging
import os
import time
import traceback
import uuid

from fastapi import FastAPI, HTTPException

from nebula.health import router as health_router
from nebula.security import AuthMiddleware, add_security_schema_to_app
from nebula.transcript.align_utils import align_slides_with_segments
from nebula.transcript.config import Config
from nebula.transcript.dto import (TranscribeRequestDTO,
                                   TranscriptionResponseDTO,
                                   TranscriptionSegmentDTO)
from nebula.transcript.slide_utils import ask_gpt_for_slide_number
from nebula.transcript.video_utils import (download_video, extract_audio,
                                           extract_frames_at_timestamps)
from nebula.transcript.whisper_utils import transcribe_with_azure_whisper

# Get the API token from config
if not Config.API_KEYS:
    raise RuntimeError("No API keys configured!")
token = Config.API_KEYS[0]


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
app.include_router(health_router)

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
    logging.debug("▶ Received request")

    video_url = req.videoUrl
    if not video_url:
        raise HTTPException(status_code=400, detail="Missing videoUrl")

    uid = str(uuid.uuid4())
    video_path = os.path.join(Config.VIDEO_STORAGE_PATH, f"{uid}.mp4")
    audio_path = os.path.join(Config.VIDEO_STORAGE_PATH, f"{uid}.wav")

    logging.debug("▶ Video URL: %s", video_url)
    logging.debug("▶ Temp paths -> video: %s, audio: %s", video_path, audio_path)

    try:
        logging.debug("▶ Downloading video...")
        download_video(video_url, video_path)
        logging.debug("✅ Video downloaded.")

        logging.debug("▶ Extracting audio...")
        extract_audio(video_path, audio_path)
        logging.debug("✅ Audio extracted.")

        logging.debug("▶ Starting transcription...")
        transcription = transcribe_with_azure_whisper(audio_path)
        logging.debug(
            "✅ Transcription complete. Segments: %d", len(transcription["segments"])
        )

        timestamps = [s["start"] for s in transcription["segments"]]
        logging.debug("▶ Extracting %d frames...", len(timestamps))
        frames = extract_frames_at_timestamps(video_path, timestamps)
        logging.debug("✅ Extracted %d frames.", len(frames))

        slide_timestamps = []
        for idx, (ts, img_b64) in enumerate(frames):
            logging.debug(
                "▶ Asking GPT for slide %d/%d at %.2fs...", idx + 1, len(frames), ts
            )
            slide_number = ask_gpt_for_slide_number(img_b64)
            logging.debug("→ GPT returned slide number: %s", slide_number)
            if slide_number is not None:
                slide_timestamps.append((ts, slide_number))
            time.sleep(2)

        logging.debug("▶ Aligning slide numbers with transcript...")
        aligned_segments = align_slides_with_segments(
            transcription["segments"], slide_timestamps
        )
        logging.debug("✅ Alignment complete: %d segments.", len(aligned_segments))

        segments = [TranscriptionSegmentDTO(**s) for s in aligned_segments]

        logging.debug("✅ Sending final response.")
        return TranscriptionResponseDTO(
            lectureUnitId=req.lectureUnitId,
            language=transcription.get("language", "en"),
            segments=segments,
        )

    except Exception as e:
        traceback.print_exc()
        logging.error("❌ Transcription failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e

    finally:
        try:
            os.remove(video_path)
            os.remove(audio_path)
            logging.debug("🧹 Temp files removed.")
        except Exception as cleanup_err:
            logging.warning("⚠️ Cleanup failed: %s", cleanup_err)
