import logging
import os
import shutil
import time
import uuid

from fastapi import BackgroundTasks, FastAPI, HTTPException

from nebula.health import router as health_router
from nebula.transcript.align_utils import align_slides_with_segments
from nebula.transcript.config import Config
from nebula.transcript.dto import (
    TranscribeRequestDTO,
    TranscriptionSegmentDTO,
)
from nebula.transcript.jobs import (
    create_job,
    fail_job,
    get_job_status,
    save_job_result,
)
from nebula.transcript.slide_utils import ask_gpt_for_slide_number
from nebula.transcript.video_utils import (
    download_video,
    extract_audio,
    extract_frames_at_timestamps,
)
from nebula.transcript.whisper_utils import transcribe_with_azure_whisper

# ─────────────────────────────
# ✅ Initialize FastAPI
# ─────────────────────────────
app = FastAPI(title="Nebula Transcription Service")
app.include_router(health_router)

logging.basicConfig(level=getattr(logging, Config.get_log_level()))
Config.ensure_dirs()


# ─────────────────────────────
# 🧠 Transcription Worker
# ─────────────────────────────
def run_transcription(req: TranscribeRequestDTO, job_id: str):
    uid = str(uuid.uuid4())
    video_path = os.path.join(Config.VIDEO_STORAGE_PATH, f"{uid}.mp4")
    audio_path = os.path.join(Config.VIDEO_STORAGE_PATH, f"{uid}.wav")

    try:
        logging.debug("▶ Downloading video...")
        download_video(req.videoUrl, video_path)

        logging.debug("▶ Extracting audio...")
        extract_audio(video_path, audio_path)

        logging.debug("▶ Transcribing with Whisper...")
        transcription = transcribe_with_azure_whisper(audio_path)

        logging.debug("▶ Extracting frames for GPT...")
        timestamps = [s["start"] for s in transcription["segments"]]
        frames = extract_frames_at_timestamps(video_path, timestamps)

        slide_timestamps = []
        for ts, img_b64 in frames:
            slide_number = ask_gpt_for_slide_number(img_b64)
            if slide_number is not None:
                slide_timestamps.append((ts, slide_number))
            time.sleep(2)

        logging.debug("▶ Aligning slides with transcript...")
        aligned_segments = align_slides_with_segments(
            transcription["segments"], slide_timestamps
        )

        segments = [TranscriptionSegmentDTO(**s).dict() for s in aligned_segments]

        save_job_result(
            job_id,
            {
                "lectureUnitId": req.lectureUnitId,
                "language": transcription.get("language", "en"),
                "segments": segments,
            },
        )

        logging.info("✅ Job %s finished successfully", job_id)

    except Exception as e:
        logging.error("❌ Job %s failed: %s", job_id, e, exc_info=True)
        fail_job(job_id, str(e))

    finally:
        for path in [video_path, audio_path]:
            try:
                if os.path.exists(path):
                    os.remove(path)
                    logging.debug("🧹 Removed temp file: %s", path)
            except Exception as cleanup_err:
                logging.warning(
                    "⚠️ Failed to remove temp file %s: %s", path, cleanup_err
                )

        chunk_dir_prefix = f"chunks_{uid}"
        temp_dir = Config.VIDEO_STORAGE_PATH

        try:
            for entry in os.listdir(temp_dir):
                full_path = os.path.join(temp_dir, entry)
                if entry.startswith(chunk_dir_prefix) and os.path.isdir(full_path):
                    shutil.rmtree(full_path)
                    logging.debug("🧹 Removed chunk directory: %s", full_path)
        except Exception as cleanup_err:
            logging.warning("⚠️ Failed to remove chunk directories: %s", cleanup_err)


# ─────────────────────────────
# 🚀 Internal Transcription Endpoint (called by Gateway)
# ─────────────────────────────
@app.post("/start-transcribe", tags=["internal"])
async def start_transcribe(
    req: TranscribeRequestDTO, background_tasks: BackgroundTasks
):
    if not req.videoUrl:
        raise HTTPException(status_code=400, detail="Missing videoUrl")

    job_id = create_job()
    background_tasks.add_task(run_transcription, req, job_id)
    logging.info("🟡 Started transcription job: %s", job_id)
    return {"status": "processing", "transcriptionId": job_id}


# ─────────────────────────────
# 🔁 Internal Status Endpoint (called by Gateway)
# ─────────────────────────────
@app.get("/status/{job_id}", tags=["internal"])
async def get_transcription_status(job_id: str):
    return get_job_status(job_id)


# ─────────────────────────────
# 👋 Health Check
# ─────────────────────────────
@app.get("/", include_in_schema=False)
async def home():
    return {"message": "FastAPI Nebula transcription service is running"}
