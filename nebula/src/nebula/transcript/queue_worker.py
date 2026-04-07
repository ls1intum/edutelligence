# nebula/transcript/queue_worker.py
import asyncio
import logging
import os
import shutil
import uuid
from typing import Tuple

from nebula.tracing import get_current_context, trace_job, trace_span
from nebula.transcript.align_utils import align_slides_with_segments
from nebula.transcript.dto import TranscribeRequestDTO, TranscriptionSegmentDTO
from nebula.transcript.jobs import cleanup_finished_jobs, fail_job, save_job_result
from nebula.transcript.slide_turn_detector import detect_slide_timestamps
from nebula.transcript.transcriber_config import VIDEO_STORAGE_PATH
from nebula.transcript.video_utils import download_video, extract_audio
from nebula.transcript.whisper_utils import transcribe_with_whisper

# FIFO queue of (job_id, request)
_job_queue: "asyncio.Queue[Tuple[str, TranscribeRequestDTO]]" = asyncio.Queue()
_worker_task: asyncio.Task | None = None
_cleanup_task: asyncio.Task | None = None


async def enqueue_job(job_id: str, req: TranscribeRequestDTO) -> None:
    # Put new jobs at the tail -> strict FIFO consumption
    await _job_queue.put((job_id, req))
    logging.info("[Job %s] Enqueued for heavy pipeline", job_id)


async def _heavy_pipeline(job_id: str, req: TranscribeRequestDTO) -> dict:
    """
    Run the serialized/heavy part (download -> extract -> whisper) in strict FIFO order.
    Return the Whisper transcription dict on success.
    """
    logging.info("[Job %s] Starting heavy pipeline", job_id)

    # Update context phase
    ctx = get_current_context()
    if ctx:
        ctx.current_phase = "heavy"

    # Unique temp paths
    uid = str(uuid.uuid4())
    video_path = os.path.join(VIDEO_STORAGE_PATH, f"{uid}.mp4")
    audio_path = os.path.join(VIDEO_STORAGE_PATH, f"{uid}.mp3")

    try:
        # Run blocking work in threads so the event loop stays responsive
        logging.debug("[Job %s] Downloading video...", job_id)
        await asyncio.to_thread(download_video, req.videoUrl, video_path)

        logging.debug("[Job %s] Extracting audio...", job_id)
        await asyncio.to_thread(extract_audio, video_path, audio_path)

        logging.debug("[Job %s] Transcribing with Whisper...", job_id)
        transcription = await asyncio.to_thread(transcribe_with_whisper, audio_path)

        return {
            "transcription": transcription,
            "video_path": video_path,
            "audio_path": audio_path,
            "uid": uid,
        }

    except Exception as e:
        logging.error("[Job %s] Heavy pipeline failed: %s", job_id, e, exc_info=True)
        raise


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
    # Update context phase (context is inherited from caller)
    ctx = get_current_context()
    if ctx:
        ctx.current_phase = "light"

    try:
        with trace_span("Light Pipeline") as light_span:
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
            await asyncio.sleep(0)

            logging.debug("[Job %s] Aligning slides with transcript...", job_id)
            aligned_segments = align_slides_with_segments(
                transcription["segments"], slide_timestamps
            )

            segments = [
                TranscriptionSegmentDTO(**s).model_dump() for s in aligned_segments
            ]
            await save_job_result(
                job_id,
                {
                    "lectureUnitId": req.lectureUnitId,
                    "language": transcription.get("language", "en"),
                    "segments": segments,
                },
            )
            logging.info("[Job %s] Finished (saved result)", job_id)
            light_span.set_output(
                {"slide_changes": len(slide_timestamps), "segments": len(segments)}
            )

    except Exception as e:
        logging.error("[Job %s] Light phase failed: %s", job_id, e, exc_info=True)
        await fail_job(job_id, str(e))
    finally:
        # Cleanup temp files and chunk dirs
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


async def _worker_loop():
    while True:
        job_id, req = await _job_queue.get()  # strict FIFO
        logging.info("[Job %s] Dequeued - starting processing", job_id)

        # Create parent trace for entire job
        with trace_job(
            job_id,
            name="Transcription Job",
            video_url=req.videoUrl,
            lecture_unit_id=req.lectureUnitId,
        ):
            try:
                # Heavy pipeline as a child span
                with trace_span("Heavy Pipeline") as heavy_span:
                    bundle = await _heavy_pipeline(job_id, req)
                    heavy_span.set_output(
                        {"segments": len(bundle["transcription"].get("segments", []))}
                    )

                # Run light phase within trace context for proper nesting
                await _light_phase(
                    job_id,
                    req,
                    bundle["transcription"],
                    bundle["video_path"],
                    bundle["audio_path"],
                    bundle["uid"],
                )

            except Exception as e:
                await fail_job(job_id, str(e))

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
