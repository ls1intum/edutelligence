"""Heavy transcription pipeline: download, extract audio, transcribe."""

import uuid
from pathlib import Path
from typing import Any, Dict

from iris.common.logging_config import get_logger
from iris.config import settings
from iris.domain.transcription.video_transcription_execution_dto import (
    VideoTranscriptionPipelineExecutionDto,
)
from iris.pipeline.transcription.utils.video_utils import download_video, extract_audio
from iris.pipeline.transcription.utils.whisper_client import WhisperClient
from iris.tracing import observe
from iris.web.status.video_transcription_callback import VideoTranscriptionCallback

logger = get_logger(__name__)


class HeavyTranscriptionPipeline:
    """
    Heavy transcription pipeline for CPU-intensive operations.

    This pipeline handles:
    1. Downloading video from URL
    2. Extracting audio from video
    3. Transcribing audio with Whisper

    These operations are sequential and resource-intensive, so they
    run one at a time in the job queue.
    """

    def __init__(
        self,
        dto: VideoTranscriptionPipelineExecutionDto,
        callback: VideoTranscriptionCallback,
        temp_dir: Path,
    ):
        """
        Initialize the heavy pipeline.

        Args:
            dto: Execution DTO with video URL and settings.
            callback: Status callback for progress updates.
            temp_dir: Directory for temporary files.
        """
        self.dto = dto
        self.callback = callback
        self.temp_dir = temp_dir

        self.whisper_client = WhisperClient(
            model=settings.transcription.whisper_model,
            chunk_duration=settings.transcription.chunk_duration_seconds,
            max_workers=settings.transcription.whisper_max_workers,
        )

    @observe(name="Heavy Transcription Pipeline")
    def __call__(self) -> Dict[str, Any]:
        """
        Execute the heavy pipeline.

        Returns:
            Dict containing:
            - transcription: Dict with "segments" list
            - video_path: Path to downloaded video (for slide detection)
            - audio_path: Path to extracted audio
            - uid: Unique identifier for this job's temp files
        """
        self.uid = str(uuid.uuid4())
        uid = self.uid
        video_path = self.temp_dir / f"{uid}.mp4"
        audio_path = self.temp_dir / f"{uid}.mp3"

        # Strip JWT query param so the token is never written to logs
        video_url_clean = self.dto.video_url.split("?")[0]

        logger.info(
            "[Lecture %d] Starting heavy pipeline for %s",
            self.dto.lecture_unit_id,
            video_url_clean,
        )

        # Stage 1: Download video
        self.callback.in_progress("Downloading video...")
        logger.info(
            "[Lecture %d] Stage 1/3: Downloading video -> %s",
            self.dto.lecture_unit_id,
            video_path,
        )
        download_video(
            self.dto.video_url,
            str(video_path),
            lecture_unit_id=self.dto.lecture_unit_id,
        )
        self.callback.done("Video downloaded")
        logger.info(
            "[Lecture %d] Stage 1/3: Video downloaded successfully (%d MB)",
            self.dto.lecture_unit_id,
            video_path.stat().st_size // (1024 * 1024) if video_path.exists() else 0,
        )

        # Stage 2: Extract audio
        self.callback.in_progress("Extracting audio from video...")
        logger.info(
            "[Lecture %d] Stage 2/3: Extracting audio to %s",
            self.dto.lecture_unit_id,
            audio_path,
        )
        extract_audio(
            str(video_path), str(audio_path), lecture_unit_id=self.dto.lecture_unit_id
        )
        self.callback.done("Audio extracted")
        logger.info(
            "[Lecture %d] Stage 2/3: Audio extracted successfully (%d MB)",
            self.dto.lecture_unit_id,
            audio_path.stat().st_size // (1024 * 1024) if audio_path.exists() else 0,
        )

        # Stage 3: Transcribe
        self.callback.in_progress("Transcribing audio with Whisper...")
        logger.info(
            "[Lecture %d] Stage 3/3: Starting transcription with %s (chunk duration: %ds)",
            self.dto.lecture_unit_id,
            self.whisper_client.provider_name,
            self.whisper_client.chunk_duration,
        )
        transcription = self.whisper_client.transcribe(
            str(audio_path), lecture_unit_id=self.dto.lecture_unit_id
        )
        segment_count = len(transcription.get("segments", []))
        self.callback.done(f"Transcribed {segment_count} segments")

        logger.info(
            "[Lecture %d] Stage 3/3: Transcription complete - %d segments, language: %s",
            self.dto.lecture_unit_id,
            segment_count,
            transcription.get("language", "unknown"),
        )

        logger.info(
            "[Lecture %d] Heavy pipeline complete: %d segments",
            self.dto.lecture_unit_id,
            segment_count,
        )

        return {
            "transcription": transcription,
            "video_path": video_path,
            "audio_path": audio_path,
            "uid": uid,
        }
