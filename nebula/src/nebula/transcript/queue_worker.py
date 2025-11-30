# nebula/transcript/queue_worker.py
import asyncio
import logging
import os
import shutil
import uuid
from typing import Tuple

from nebula.transcript.align_utils import align_slides_with_segments
from nebula.transcript.dto import TranscribeRequestDTO, TranscriptionSegmentDTO
from nebula.transcript.jobs import (
    cancel_job,
    cleanup_finished_jobs,
    fail_job,
    is_job_cancelled,
    remove_from_cancelled,
    save_job_result,
)
from nebula.transcript.slide_turn_detector import detect_slide_timestamps
from nebula.transcript.transcriber_config import VIDEO_STORAGE_PATH
from nebula.transcript.video_utils import download_video, extract_audio
from nebula.transcript.whisper_utils import transcribe_with_whisper

# FIFO queue of (job_id, request)
_job_queue: "asyncio.Queue[Tuple[str, TranscribeRequestDTO]]" = asyncio.Queue()
_worker_task: asyncio.Task | None = None
_cleanup_task: asyncio.Task | None = None

# Track currently processing jobs and their temp files
_processing_jobs: dict[str, dict] = {}
_processing_lock = asyncio.Lock()


async def enqueue_job(job_id: str, req: TranscribeRequestDTO) -> None:
    # Put new jobs at the tail -> strict FIFO consumption
    await _job_queue.put((job_id, req))
    logging.info("[Job %s] Enqueued for heavy pipeline", job_id)


async def remove_job_from_queue(job_id: str) -> bool:
    """
    Remove a job from the queue if it hasn't started yet.
    Returns True if job was found and removed, False otherwise.
    """
    # Create a temporary list to hold jobs
    temp_jobs = []
    found = False

    # Drain the queue
    while not _job_queue.empty():
        try:
            current_job = _job_queue.get_nowait()
            if current_job[0] == job_id:
                found = True
                logging.info("[Job %s] Removed from queue", job_id)
            else:
                temp_jobs.append(current_job)
            # Mark this queue entry as processed
            _job_queue.task_done()
        except asyncio.QueueEmpty:
            break

    # Put back the jobs that weren't removed (creates fresh queue entries)
    for job in temp_jobs:
        await _job_queue.put(job)

    return found


async def cancel_job_processing(job_id: str) -> dict:
    """
    Cancel a job - either remove it from queue or stop it if processing.
    Returns status dict with information about cancellation.
    """
    # First mark the job as cancelled
    await cancel_job(job_id)

    # Check if job is currently processing
    async with _processing_lock:
        if job_id in _processing_jobs:
            logging.info("[Job %s] Marked for cancellation while processing", job_id)
            return {
                "status": "cancelled",
                "message": "Job is processing and will be stopped at next checkpoint",
            }

    # Try to remove from queue
    removed = await remove_job_from_queue(job_id)
    if removed:
        logging.info("[Job %s] Cancelled while in queue", job_id)
        return {
            "status": "cancelled",
            "message": "Job was in queue and has been removed",
        }

    # Job might have already completed or doesn't exist
    logging.info(
        "[Job %s] Cancellation requested but job not found in queue or processing",
        job_id,
    )
    return {
        "status": "cancelled",
        "message": "Job cancellation requested (job may have already completed or not exist)",
    }


def _cleanup_temp_files(
    video_path: str | None, audio_path: str | None, uid: str | None
):
    """Clean up temporary files for a job."""
    try:
        for path in (video_path, audio_path):
            if path and os.path.exists(path):
                os.remove(path)
                logging.debug("Removed temp file: %s", path)

        # Remove chunk directories
        if uid:
            chunk_dir_prefix = f"chunks_{uid}"
            for entry in os.listdir(VIDEO_STORAGE_PATH):
                full = os.path.join(VIDEO_STORAGE_PATH, entry)
                if entry.startswith(chunk_dir_prefix) and os.path.isdir(full):
                    shutil.rmtree(full)
                    logging.debug("Removed chunk directory: %s", full)
    except Exception as ce:
        logging.warning("Cleanup issue: %s", ce)


async def _heavy_pipeline(job_id: str, req: TranscribeRequestDTO) -> dict:
    """
    Run the serialized/heavy part (download -> extract -> whisper) in strict FIFO order.
    Return the Whisper transcription dict on success.
    """
    logging.info("[Job %s] Starting heavy pipeline", job_id)

    # Unique temp paths
    uid = str(uuid.uuid4())
    video_path = os.path.join(VIDEO_STORAGE_PATH, f"{uid}.mp4")
    audio_path = os.path.join(VIDEO_STORAGE_PATH, f"{uid}.mp3")

    # Track this job as processing
    async with _processing_lock:
        _processing_jobs[job_id] = {
            "video_path": video_path,
            "audio_path": audio_path,
            "uid": uid,
        }

    try:
        # Check for cancellation before starting
        if await is_job_cancelled(job_id):
            logging.info("[Job %s] Job cancelled before pipeline start", job_id)
            raise asyncio.CancelledError("Job was cancelled")

        # Run blocking work in threads so the event loop stays responsive
        logging.debug("[Job %s] Downloading video...", job_id)
        await asyncio.to_thread(download_video, req.videoUrl, video_path)

        # Check for cancellation after download
        if await is_job_cancelled(job_id):
            logging.info("[Job %s] Job cancelled after download", job_id)
            raise asyncio.CancelledError("Job was cancelled")

        logging.debug("[Job %s] Extracting audio...", job_id)
        await asyncio.to_thread(extract_audio, video_path, audio_path)

        # Check for cancellation after audio extraction
        if await is_job_cancelled(job_id):
            logging.info("[Job %s] Job cancelled after audio extraction", job_id)
            raise asyncio.CancelledError("Job was cancelled")

        logging.debug(" [Job %s] Transcribing with Whisper...", job_id)
        transcription = await asyncio.to_thread(
            transcribe_with_whisper, audio_path
        )  # requests loop, blocking

        # Check for cancellation after transcription
        if await is_job_cancelled(job_id):
            logging.info("[Job %s] Job cancelled after transcription", job_id)
            raise asyncio.CancelledError("Job was cancelled")

        return {
            "transcription": transcription,
            "video_path": video_path,
            "audio_path": audio_path,
            "uid": uid,
        }

    except asyncio.CancelledError:
        # Clean up temp files on cancellation
        logging.info("[Job %s] Cleaning up temp files after cancellation", job_id)
        _cleanup_temp_files(video_path, audio_path, uid)
        raise
    except Exception as e:
        logging.error("[Job %s] Heavy pipeline failed: %s", job_id, e, exc_info=True)
        # Clean up temp files on failure
        _cleanup_temp_files(video_path, audio_path, uid)
        raise
    finally:
        # Remove from processing tracking
        async with _processing_lock:
            _processing_jobs.pop(job_id, None)


async def _light_phase(
    job_id: str,
    req: TranscribeRequestDTO,
    transcription: dict,
    video_path: str,
    audio_path: str,
    uid: str,
):
    """
    Run the parallelizable part per job:
    frames -> GPT-Vision -> align -> save -> cleanup.
    """
    try:
        # Check for cancellation at the start of light phase
        if await is_job_cancelled(job_id):
            logging.info("[Job %s] Job cancelled at light phase start", job_id)
            return

        logging.debug("[Job %s] Detecting slide change points...", job_id)
        # Offload GPT-backed slide detection so the event loop stays responsive.
        slide_timestamps = await asyncio.to_thread(
            detect_slide_timestamps,
            video_path,
            transcription["segments"],
            50,
            1,
            job_id,
        )
        logging.info(
            "[Job %s] Slide detection complete: change_points=%d",
            job_id,
            len(slide_timestamps),
        )

        # Check for cancellation after slide detection
        if await is_job_cancelled(job_id):
            logging.info("[Job %s] Job cancelled after slide detection", job_id)
            return

        logging.debug("[Job %s] Aligning slides with transcript...", job_id)
        aligned_segments = align_slides_with_segments(
            transcription["segments"], slide_timestamps
        )

        segments = [TranscriptionSegmentDTO(**s).model_dump() for s in aligned_segments]
        await save_job_result(
            job_id,
            {
                "lectureUnitId": req.lectureUnitId,
                "language": transcription.get("language", "en"),
                "segments": segments,
            },
        )
        logging.info("[Job %s] Finished (saved result)", job_id)

    except Exception as e:
        logging.error("[Job %s] Light phase failed: %s", job_id, e, exc_info=True)
        await fail_job(job_id, str(e))
    finally:
        # Cleanup temp files and chunk dirs (same logic as your current cleanup)
        try:
            for path in (video_path, audio_path):
                if path and os.path.exists(path):
                    os.remove(path)
                    logging.debug("[Job %s] Removed temp file: %s", job_id, path)
            # remove chunk dirs
            chunk_dir_prefix = f"chunks_{uid}"
            for entry in os.listdir(VIDEO_STORAGE_PATH):
                full = os.path.join(VIDEO_STORAGE_PATH, entry)
                if entry.startswith(chunk_dir_prefix) and os.path.isdir(full):
                    shutil.rmtree(full)
                    logging.debug("[Job %s] Removed chunk directory: %s", job_id, full)
        except Exception as ce:
            logging.warning("[Job %s] Cleanup issue: %s", job_id, ce)
        # Remove from cancelled set if it was there
        await remove_from_cancelled(job_id)


async def _worker_loop():
    while True:
        job_id, req = await _job_queue.get()  # strict FIFO
        logging.info("[Job %s] Dequeued — starting heavy pipeline", job_id)

        try:
            bundle = await _heavy_pipeline(job_id, req)
        except asyncio.CancelledError:
            # Job was cancelled during heavy pipeline
            # Temp files are already cleaned up by _heavy_pipeline
            logging.info("[Job %s] Cancelled during heavy pipeline", job_id)
            await remove_from_cancelled(job_id)
            _job_queue.task_done()
            continue
        except Exception as e:
            # Temp files are already cleaned up by _heavy_pipeline
            await fail_job(job_id, str(e))
            _job_queue.task_done()
            continue

        # Schedule light phase in parallel (don't block the worker)
        asyncio.create_task(
            _light_phase(
                job_id,
                req,
                bundle["transcription"],
                bundle["video_path"],
                bundle["audio_path"],
                bundle["uid"],
            )
        )
        _job_queue.task_done()


async def _cleanup_loop():
    """Periodically clean up old finished jobs to prevent memory leaks."""
    while True:
        try:
            await asyncio.sleep(3600)  # Run every hour
            logging.debug("Running periodic job cleanup...")
            await cleanup_finished_jobs(ttl_minutes=60)
            logging.debug("Job cleanup completed")
        except asyncio.CancelledError:
            logging.info("Cleanup task cancelled")
            break
        except Exception as e:
            logging.error("Error during job cleanup: %s", e, exc_info=True)


def start_worker():
    global _worker_task, _cleanup_task
    if _worker_task is None or _worker_task.done():
        _worker_task = asyncio.create_task(_worker_loop())
        logging.info("FIFO worker started")
    if _cleanup_task is None or _cleanup_task.done():
        _cleanup_task = asyncio.create_task(_cleanup_loop())
        logging.info("Periodic cleanup task started")


async def stop_worker():
    global _worker_task, _cleanup_task
    if _worker_task:
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
        _worker_task = None
    if _cleanup_task:
        _cleanup_task.cancel()
        try:
            await _cleanup_task
        except asyncio.CancelledError:
            pass
        _cleanup_task = None
