"""Heavy transcription pipeline: download, extract audio, transcribe."""

import uuid
from pathlib import Path
from typing import Any, Dict

from iris.common.logging_config import get_logger
from iris.config import settings
from iris.domain.transcription.video_transcription_execution_dto import (
    VideoSourceType,
    VideoTranscriptionPipelineExecutionDto,
)
from iris.pipeline.transcription.utils.video_utils import download_video, extract_audio
from iris.pipeline.transcription.utils.youtube_utils import download_youtube_audio
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
            request_timeout=settings.transcription.whisper_request_timeout_seconds,
            no_speech_threshold=settings.transcription.no_speech_filter_threshold,
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

        is_youtube = self.dto.video_source_type == VideoSourceType.YOUTUBE
        total_stages = 2 if is_youtube else 3

        if is_youtube:
            # YouTube: download audio directly (no video download needed)
            self.callback.in_progress("Downloading audio from YouTube...")
            logger.info(
                "[Lecture %d] Stage 1/%d: Downloading YouTube audio -> %s",
                self.dto.lecture_unit_id,
                total_stages,
                audio_path,
            )
            download_youtube_audio(
                self.dto.video_url,
                str(audio_path),
                lecture_unit_id=self.dto.lecture_unit_id,
                timeout=settings.transcription.download_timeout_seconds,
            )
            self.callback.done("YouTube audio downloaded")
            # Skip "Extracting audio" callback stage — not needed for YouTube
            self.callback.skip("Skipped (YouTube source)")
            video_path = None  # No video file for slide detection

        else:
            # TUM-Live (default): download HLS video, then extract audio
            # Stage 1: Download video
            self.callback.in_progress("Downloading video...")
            logger.info(
                "[Lecture %d] Stage 1/%d: Downloading video -> %s",
                self.dto.lecture_unit_id,
                total_stages,
                video_path,
            )
            download_video(
                self.dto.video_url,
                str(video_path),
                lecture_unit_id=self.dto.lecture_unit_id,
                timeout=settings.transcription.download_timeout_seconds,
            )
            self.callback.done("Video downloaded")
            logger.info(
                "[Lecture %d] Stage 1/%d: Video downloaded successfully (%d MB)",
                self.dto.lecture_unit_id,
                total_stages,
                video_path.stat().st_size // (1024 * 1024)
                if video_path.exists()
                else 0,
            )

            # Stage 2: Extract audio
            self.callback.in_progress("Extracting audio from video...")
            logger.info(
                "[Lecture %d] Stage 2/%d: Extracting audio to %s",
                self.dto.lecture_unit_id,
                total_stages,
                audio_path,
            )
            extract_audio(
                str(video_path),
                str(audio_path),
                lecture_unit_id=self.dto.lecture_unit_id,
                timeout=settings.transcription.extract_audio_timeout_seconds,
            )
            self.callback.done("Audio extracted")
            logger.info(
                "[Lecture %d] Stage 2/%d: Audio extracted successfully (%d MB)",
                self.dto.lecture_unit_id,
                total_stages,
                audio_path.stat().st_size // (1024 * 1024)
                if audio_path.exists()
                else 0,
            )

        # Final stage (both paths): Transcribe
        self.callback.in_progress("Transcribing audio with Whisper...")
        logger.info(
            "[Lecture %d] Stage %d/%d: Starting transcription with %s (chunk duration: %ds)",
            self.dto.lecture_unit_id,
            total_stages,
            total_stages,
            self.whisper_client.provider_name,
            self.whisper_client.chunk_duration,
        )
        transcription = self.whisper_client.transcribe(
            str(audio_path), lecture_unit_id=self.dto.lecture_unit_id
        )
        segment_count = len(transcription.get("segments", []))
        self.callback.done(f"Transcribed {segment_count} segments")

        logger.info(
            "[Lecture %d] Stage %d/%d: Transcription complete - %d segments, language: %s",
            self.dto.lecture_unit_id,
            total_stages,
            total_stages,
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
