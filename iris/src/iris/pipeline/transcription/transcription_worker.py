"""Worker for running video transcription in a separate process."""

import os
import signal
from multiprocessing import Semaphore as ProcessSemaphore
from multiprocessing import Value

from sentry_sdk import capture_exception

from iris.common.logging_config import get_logger, setup_logging
from iris.config import settings
from iris.domain.transcription.video_transcription_execution_dto import (
    VideoTranscriptionPipelineExecutionDto,
)
from iris.pipeline.transcription.video_transcription_pipeline import (
    VideoTranscriptionPipeline,
)

logger = get_logger(__name__)

MAX_SLOTS = settings.transcription.max_concurrent_jobs


class TranscriptionWorker:
    """
    Runs the video transcription pipeline in a separate process.

    Manages semaphore slot acquisition, SIGTERM handling, and cleanup
    to limit concurrent Whisper jobs (CPU/memory intensive).
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

    def run(self):
        setup_logging()
        os.setpgrp()  # own process group so ffmpeg children can be killed together
        signal.signal(signal.SIGTERM, self._on_sigterm)

        logger.info(
            "[Job %s, Lecture %d] Worker spawned - waiting for semaphore slot",
            self.job_id,
            self.dto.lecture_unit_id,
        )
        self._acquire_slot()

        self._slot_acquired = True
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
            self._pipeline = VideoTranscriptionPipeline(self.dto)
            self._pipeline()
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

    def _on_sigterm(self, signum, frame):  # pylint: disable=unused-argument
        logger.warning(
            "[Job %s, Lecture %d] SIGTERM received - cleaning up",
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
