"""Worker for running video transcription in a separate process."""

import os
import signal
from multiprocessing import Semaphore as ProcessSemaphore
from multiprocessing import Value

from sentry_sdk import capture_exception

from iris import sentry
from iris.common.logging_config import get_logger, setup_logging
from iris.config import settings
from iris.domain.transcription.video_transcription_execution_dto import (
    VideoTranscriptionPipelineExecutionDto,
)
from iris.pipeline.transcription.video_transcription_pipeline import (
    VideoTranscriptionPipeline,
)
from iris.web.status.video_transcription_callback import VideoTranscriptionCallback

logger = get_logger(__name__)

MAX_SLOTS = settings.transcription.max_concurrent_jobs


class TranscriptionWorker:
    """
    Runs the video transcription pipeline in a separate process.

    Manages semaphore slot acquisition, SIGTERM handling, and cleanup
    to limit concurrent Whisper jobs (CPU/memory intensive).

    The callback is created early (before semaphore acquisition) so that
    every failure path — SIGTERM, pipeline __init__ error, or a pipeline
    execution error — can notify Artemis and trigger its retry scheduler.
    """

    def __init__(
        self,
        dto: VideoTranscriptionPipelineExecutionDto,
        semaphore: ProcessSemaphore,
        active_count: Value,
    ):
        self.dto = dto
        self.semaphore = semaphore
        self.active_count = active_count
        self.job_id = (
            dto.settings.authentication_token.rsplit("-", 1)[-1]
            if dto.settings
            else "?"
        )
        self._slot_acquired = False
        self._pipeline = None
        self._callback = None
        self._pipeline_completed = False

    def run(self):
        setup_logging()
        # Subprocess needs its own Sentry init: on spawn-based platforms (macOS,
        # Windows) the child does not inherit the parent's SDK client, so
        # capture_exception would otherwise be a silent no-op.
        sentry.init()
        os.setpgrp()  # own process group so ffmpeg children can be killed together
        signal.signal(signal.SIGTERM, self._on_sigterm)

        # Create the callback before acquiring the semaphore so SIGTERM can
        # always notify Artemis regardless of when termination is received.
        if self.dto.settings is not None:
            self._callback = VideoTranscriptionCallback(
                run_id=self.dto.settings.authentication_token,
                base_url=self.dto.settings.artemis_base_url,
                initial_stages=self.dto.initial_stages,
                lecture_unit_id=self.dto.lecture_unit_id,
            )

        logger.info(
            "[Job %s, Lecture %d] Worker spawned - waiting for semaphore slot",
            self.job_id,
            self.dto.lecture_unit_id,
        )
        self._acquire_slot()
        try:
            self._run_pipeline()
        finally:
            if self._slot_acquired:
                self._slot_acquired = False
                self._release_slot()

    def _acquire_slot(self):
        # Try non-blocking first so we can log "at capacity" without waiting
        if not self.semaphore.acquire(block=False):
            with self.active_count.get_lock():
                current = self.active_count.value
            logger.warning(
                "[Job %s, Lecture %d] Semaphore at capacity (%d/%d active) - queuing until a slot frees up",
                self.job_id,
                self.dto.lecture_unit_id,
                current,
                MAX_SLOTS,
            )
            self.semaphore.acquire(block=True)
        # Set the flag here so SIGTERM always sees it regardless of which acquire path was taken
        self._slot_acquired = True

    def _release_slot(self):
        with self.active_count.get_lock():
            self.active_count.value -= 1
            current = self.active_count.value
        self.semaphore.release()
        logger.info(
            "[Job %s, Lecture %d] Semaphore slot released (%d/%d active, %d free)",
            self.job_id,
            self.dto.lecture_unit_id,
            current,
            MAX_SLOTS,
            MAX_SLOTS - current,
        )

    def _run_pipeline(self):
        with self.active_count.get_lock():
            self.active_count.value += 1
            current = self.active_count.value
        logger.info(
            "[Job %s, Lecture %d] Semaphore slot acquired (%d/%d active, %d free) - starting pipeline",
            self.job_id,
            self.dto.lecture_unit_id,
            current,
            MAX_SLOTS,
            MAX_SLOTS - current,
        )
        try:
            # Pass the pre-created callback so the pipeline reuses the same
            # instance; if __init__ raises before __call__ is reached, the
            # except block below can still report the failure to Artemis.
            self._pipeline = VideoTranscriptionPipeline(
                self.dto, callback=self._callback
            )
            self._pipeline()
            self._pipeline_completed = True
            logger.info(
                "[Job %s, Lecture %d] Video transcription completed successfully",
                self.job_id,
                self.dto.lecture_unit_id,
            )
        except Exception as e:
            logger.error(
                "[Job %s, Lecture %d] Transcription pipeline failed: %s",
                self.job_id,
                self.dto.lecture_unit_id,
                str(e),
                exc_info=True,
            )
            capture_exception(e)
            # VideoTranscriptionPipeline.__call__() already sends callback.error()
            # and re-raises for normal execution failures (self._pipeline is set).
            # Only send error here when __init__ raised before __call__ was reached.
            if self._pipeline is None and self._callback is not None:
                try:
                    self._callback.error(str(e))
                except Exception:
                    logger.warning(
                        "[Job %s, Lecture %d] Failed to send error callback after init failure",
                        self.job_id,
                        self.dto.lecture_unit_id,
                    )

    def _on_sigterm(self, signum, frame):  # pylint: disable=unused-argument
        logger.warning(
            "[Job %s, Lecture %d] SIGTERM received - cleaning up",
            self.job_id,
            self.dto.lecture_unit_id,
        )
        # Notify Artemis so it can schedule a retry immediately instead of
        # waiting for the 2-hour stuck-state timeout.
        # Only send if the pipeline did not already complete successfully
        # (avoids overwriting a DONE callback with a spurious ERROR).
        if not self._pipeline_completed and self._callback is not None:
            try:
                self._callback.error("Transcription job was terminated (SIGTERM)")
            except Exception:
                logger.warning(
                    "[Job %s, Lecture %d] Failed to send error callback on SIGTERM",
                    self.job_id,
                    self.dto.lecture_unit_id,
                )
        if self._pipeline is not None:
            self._pipeline.cleanup()
        if self._slot_acquired:
            self._slot_acquired = False
            self._release_slot()
        os.killpg(os.getpgrp(), signal.SIGKILL)  # kill ffmpeg and exit immediately


def run_video_transcription_worker(
    dto: VideoTranscriptionPipelineExecutionDto,
    semaphore: ProcessSemaphore,
    active_count: Value,
):
    TranscriptionWorker(dto, semaphore, active_count).run()
