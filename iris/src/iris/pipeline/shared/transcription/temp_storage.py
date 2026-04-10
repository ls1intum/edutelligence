"""Temporary file storage for one video transcription job.

A single TranscriptionTempStorage context wraps the entire pipeline
(heavy phase + light phase + ingestion).  The video file downloaded
in the heavy phase stays on disk for the light phase's frame
extraction.  Everything is cleaned up in the finally block, whether
the pipeline succeeds or fails.
"""

import os
import shutil
import uuid

from iris.common.logging_config import get_logger

logger = get_logger(__name__)


class TranscriptionTempStorage:
    """Context manager that creates and cleans up a per-job temp directory.

    Usage::

        with TranscriptionTempStorage(base_dir, lecture_unit_id=42) as storage:
            download_video(url, storage.video_path, timeout=3600)
            extract_audio(storage.video_path, storage.audio_path, timeout=600)
            chunks = split_audio_ffmpeg(storage.audio_path, storage.chunks_dir, 900)
            # video file still on disk here for slide detection
            ...
        # everything cleaned up here

    Attributes:
        job_dir: Root directory for this job's temp files.
        video_path: Path where the downloaded video should be saved.
        audio_path: Path where the extracted audio should be saved.
        chunks_dir: Directory where audio chunks are written.
    """

    def __init__(self, base_dir: str, lecture_unit_id: int | None = None):
        """
        Args:
            base_dir: Base directory for temp files (from config.transcription.temp_dir).
            lecture_unit_id: Used to create a readable directory name.
        """
        suffix = (
            f"lecture-{lecture_unit_id}-{uuid.uuid4().hex[:8]}"
            if lecture_unit_id is not None
            else uuid.uuid4().hex[:8]
        )
        self.job_dir = os.path.join(base_dir, suffix)
        self.video_path = os.path.join(self.job_dir, "video.mp4")
        self.audio_path = os.path.join(self.job_dir, "audio.mp3")
        self.chunks_dir = os.path.join(self.job_dir, "chunks")

    def __enter__(self) -> "TranscriptionTempStorage":
        os.makedirs(self.job_dir, exist_ok=True)
        logger.info("Created temp directory: %s", self.job_dir)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        try:
            shutil.rmtree(self.job_dir, ignore_errors=True)
            logger.info("Cleaned up temp directory: %s", self.job_dir)
        except Exception as e:
            logger.warning("Failed to clean up %s: %s", self.job_dir, e)
        return None  # Do not suppress exceptions

    @property
    def video_exists(self) -> bool:
        """True if a video file has been downloaded (useful for retry skip logic)."""
        return os.path.isfile(self.video_path)

    @property
    def audio_exists(self) -> bool:
        """True if audio has been extracted."""
        return os.path.isfile(self.audio_path)
