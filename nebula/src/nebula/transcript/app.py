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
    print("[DEBUG] ▶ Received request", flush=True)

    video_url = req.videoUrl
    if not video_url:
        raise HTTPException(status_code=400, detail="Missing videoUrl")

    uid = str(uuid.uuid4())
    video_path = os.path.join(Config.VIDEO_STORAGE_PATH, f"{uid}.mp4")
    audio_path = os.path.join(Config.VIDEO_STORAGE_PATH, f"{uid}.wav")

    print(f"[DEBUG] ▶ Video URL: {video_url}", flush=True)
    print(
        f"[DEBUG] ▶ Temp paths -> video: {video_path}, audio: {audio_path}", flush=True
    )

    try:
        print("[DEBUG] ▶ Downloading video...", flush=True)
        download_video(video_url, video_path)
        print("[DEBUG] ✅ Video downloaded.", flush=True)

        print("[DEBUG] ▶ Extracting audio...", flush=True)
        extract_audio(video_path, audio_path)
        print("[DEBUG] ✅ Audio extracted.", flush=True)

        print("[DEBUG] ▶ Starting transcription...", flush=True)
        transcription = transcribe_with_azure_whisper(audio_path)
        print(
            f"[DEBUG] ✅ Transcription complete. Segments: {len(transcription['segments'])}",
            flush=True,
        )

        timestamps = [s["start"] for s in transcription["segments"]]
        print(f"[DEBUG] ▶ Extracting {len(timestamps)} frames...", flush=True)
        frames = extract_frames_at_timestamps(video_path, timestamps)
        print(f"[DEBUG] ✅ Extracted {len(frames)} frames.", flush=True)

        slide_timestamps = []
        for idx, (ts, img_b64) in enumerate(frames):
            print(
                f"[DEBUG] ▶ Asking GPT for slide {idx + 1}/{len(frames)} at {ts:.2f}s...",
                flush=True,
            )
            slide_number = ask_gpt_for_slide_number(img_b64)
            print(f"[DEBUG] → GPT returned slide number: {slide_number}", flush=True)
            if slide_number is not None:
                slide_timestamps.append((ts, slide_number))
            time.sleep(2)

        print("[DEBUG] ▶ Aligning slide numbers with transcript...", flush=True)
        aligned_segments = align_slides_with_segments(
            transcription["segments"], slide_timestamps
        )
        print(
            f"[DEBUG] ✅ Alignment complete: {len(aligned_segments)} segments.",
            flush=True,
        )

        segments = [TranscriptionSegmentDTO(**s) for s in aligned_segments]

        print("[DEBUG] ✅ Sending final response.", flush=True)
        return TranscriptionResponseDTO(
            lectureUnitId=req.lectureUnitId,
            language=transcription.get("language", "en"),
            segments=segments,
        )

    except Exception as e:
        traceback.print_exc()
        print(f"[ERROR] ❌ Transcription failed: {e}", flush=True)
        logging.error("Transcription failed", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e

    finally:
        try:
            os.remove(video_path)
            os.remove(audio_path)
            print("[DEBUG] 🧹 Temp files removed.", flush=True)
        except Exception as cleanup_err:
            print(f"[WARNING] ⚠️ Cleanup failed: {cleanup_err}", flush=True)
            logging.warning("Cleanup failed: %s", cleanup_err)
