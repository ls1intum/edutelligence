import logging
import os
import shutil
import time
import traceback
import uuid

from fastapi import FastAPI, HTTPException

from nebula.health import router as health_router
from nebula.security import AuthMiddleware, add_security_schema_to_app
from nebula.transcript.align_utils import align_slides_with_segments
from nebula.transcript.config import Config
from nebula.transcript.dto import (
    TranscribeRequestDTO,
    TranscriptionResponseDTO,
    TranscriptionSegmentDTO,
)
from nebula.transcript.slide_utils import ask_gpt_for_slide_number
from nebula.transcript.video_utils import (
    download_video,
    extract_audio,
    extract_frames_at_timestamps,
)
from nebula.transcript.whisper_utils import transcribe_with_azure_whisper

# Setup logging
logging.basicConfig(level=logging.DEBUG)

# Get the API token from config
api_keys = Config.get_api_keys()
if not api_keys:
    raise RuntimeError("No API keys configured!")
token = api_keys[0]


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


# Ensure temp directory exists
Config.ensure_dirs()


@app.get("/")
async def home():
    return {"message": "FastAPI server is running!"}


@app.post("/start-transcribe", response_model=TranscriptionResponseDTO)
async def start_transcribe(req: TranscribeRequestDTO):
    logging.debug("Received transcription request.")

    video_url = req.videoUrl
    if not video_url:
        raise HTTPException(status_code=400, detail="Missing videoUrl")

    uid = str(uuid.uuid4())
    video_path = os.path.join(Config.VIDEO_STORAGE_PATH, f"{uid}.mp4")
    audio_path = os.path.join(Config.VIDEO_STORAGE_PATH, f"{uid}.wav")

    try:
        logging.debug("Downloading video...")
        download_video(video_url, video_path)

        logging.debug("Extracting audio...")
        extract_audio(video_path, audio_path)

        logging.debug("Transcribing with Azure Whisper...")
        transcription = transcribe_with_azure_whisper(audio_path)
        logging.debug(
            "Transcription complete. Segments: %d", len(transcription["segments"])
        )

        timestamps = [s["start"] for s in transcription["segments"]]
        frames = extract_frames_at_timestamps(video_path, timestamps)

        slide_timestamps = []
        for ts, img_b64 in frames:
            slide_number = ask_gpt_for_slide_number(img_b64)
            if slide_number is not None:
                slide_timestamps.append((ts, slide_number))
            time.sleep(2)  # to avoid rate limits

        aligned_segments = align_slides_with_segments(
            transcription["segments"], slide_timestamps
        )
        logging.debug("Slide alignment complete: %d segments.", len(aligned_segments))

        segments = [TranscriptionSegmentDTO(**s) for s in aligned_segments]
        return TranscriptionResponseDTO(
            lectureUnitId=req.lectureUnitId,
            language=transcription.get("language", "en"),
            segments=segments,
        )

    except Exception as e:
        traceback.print_exc()
        logging.error("Transcription failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e

    finally:
        # Clean video/audio temp files
        for path in [video_path, audio_path]:
            try:
                if os.path.exists(path):
                    os.remove(path)
                    logging.debug("Removed temp file: %s", path)
            except Exception as cleanup_err:
                logging.warning("Failed to remove temp file %s: %s", path, cleanup_err)

        # Clean chunk directories
        chunk_dir_prefix = f"chunks_{uid}"
        temp_dir = Config.VIDEO_STORAGE_PATH
        try:
            for entry in os.listdir(temp_dir):
                full_path = os.path.join(temp_dir, entry)
                if entry.startswith(chunk_dir_prefix) and os.path.isdir(full_path):

                    shutil.rmtree(full_path)
                    logging.debug("Removed chunk directory: %s", full_path)
        except Exception as cleanup_err:
            logging.warning("Failed to remove chunk directories: %s", cleanup_err)
