import logging
import os
import time
import traceback
import uuid

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from align_utils import align_slides_with_segments
from config import Config
from fastapi.middleware import Middleware
from security import AuthMiddleware
from health  import router as health_router
from slide_utils import ask_gpt_for_slide_number
from video_utils import download_video, extract_audio, extract_frames_at_timestamps
from whisper_utils import transcribe_with_azure_whisper

token = Config.API_KEYS[0] if Config.API_KEYS else "fallback-token"

middleware = [
    Middleware(
        AuthMiddleware,
        api_key=token,
        exclude_paths=["/health", "/docs", "/openapi.json"],
        header_name="Authorization",
    )
]

app = FastAPI(middleware=middleware)
app.include_router(health_router)

# Setup logging
logging.basicConfig(level=getattr(logging, Config.LOG_LEVEL))

# Ensure temp directories exist
Config.ensure_dirs()


class TranscribeRequest(BaseModel):
    videoUrl: str


@app.get("/")
async def home():
    return {"message": "FastAPI server is running!"}


@app.post("/start-transcribe")
async def start_transcribe(req: TranscribeRequest):
    video_url = req.videoUrl
    if not video_url:
        raise HTTPException(status_code=400, detail="Missing videoUrl")

    uid = str(uuid.uuid4())
    video_path = os.path.join(Config.VIDEO_STORAGE_PATH, f"{uid}.mp4")
    audio_path = os.path.join(Config.VIDEO_STORAGE_PATH, f"{uid}.wav")

    try:
        download_video(video_url, video_path)
        extract_audio(video_path, audio_path)

        transcription = transcribe_with_azure_whisper(audio_path)
        timestamps = [s["start"] for s in transcription["segments"]]
        frames = extract_frames_at_timestamps(video_path, timestamps)

        slide_timestamps = []
        for ts, img_b64 in frames:
            slide_number = ask_gpt_for_slide_number(img_b64)
            if slide_number is not None:
                slide_timestamps.append((ts, slide_number))
            time.sleep(2)  # Respect GPT rate limit

        segments = align_slides_with_segments(transcription["segments"], slide_timestamps)
        result = {
            "language": transcription.get("language", "en"),
            "segments": segments,
        }

        return result

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
