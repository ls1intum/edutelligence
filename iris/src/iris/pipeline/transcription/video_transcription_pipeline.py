"""Main video transcription pipeline orchestrator."""

import json
import shutil
from pathlib import Path
from typing import Optional

from iris.common.logging_config import get_logger
from iris.config import settings
from iris.domain.transcription.video_transcription_execution_dto import (
    VideoTranscriptionPipelineExecutionDto,
)
from iris.pipeline.transcription.heavy_pipeline import HeavyTranscriptionPipeline
from iris.pipeline.transcription.light_pipeline import LightTranscriptionPipeline
from iris.tracing import observe
from iris.web.status.video_transcription_callback import VideoTranscriptionCallback

logger = get_logger(__name__)


class VideoTranscriptionPipeline:
    """
    Main orchestrator for video transcription.

    Coordinates the heavy and light sub-pipelines and handles:
    - Status callbacks to Artemis
    - Temporary file cleanup
    - Error handling and reporting

    The pipeline produces a JSON result with:
    - lectureUnitId: ID of the lecture unit
    - language: Detected language (from Whisper)
    - segments: List of transcript segments with slide numbers
    """

    implementation_id = "video_transcription_pipeline"

    def __init__(self, dto: VideoTranscriptionPipelineExecutionDto):
        """
        Initialize the transcription pipeline.

        Args:
            dto: Execution DTO with video URL, lecture info, and settings.

        Raises:
            ValueError: If transcription is not enabled in settings.
        """
        self.dto = dto

        if not settings.transcription.enabled:
            raise ValueError("Transcription is not enabled in settings")

        self.temp_dir = Path(settings.transcription.temp_dir)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        self._heavy_result: Optional[dict] = None

    @observe(name="Video Transcription Pipeline")
    def __call__(self) -> None:
        """Execute the full transcription pipeline."""
        callback = VideoTranscriptionCallback(
            run_id=self.dto.settings.authentication_token,
            base_url=self.dto.settings.artemis_base_url,
            initial_stages=self.dto.initial_stages,
            lecture_unit_id=self.dto.lecture_unit_id,
        )

        logger.info(
            "[Lecture %d] Starting transcription pipeline for course '%s', lecture '%s'",
            self.dto.lecture_unit_id,
            self.dto.course_name,
            self.dto.lecture_name,
        )

        try:
            # Phase 1: Heavy pipeline (download, extract, transcribe)
            heavy = HeavyTranscriptionPipeline(
                dto=self.dto,
                callback=callback,
                temp_dir=self.temp_dir,
            )
            self._heavy_result = heavy()

            # Phase 2: Light pipeline (slide detection, alignment)
            light = LightTranscriptionPipeline(
                dto=self.dto,
                callback=callback,
                transcription=self._heavy_result["transcription"],
                video_path=self._heavy_result["video_path"],
            )
            aligned_segments = light()

            # Stage 6: Finalize and send result
            callback.in_progress("Finalizing transcription...")

            result = {
                "lectureUnitId": self.dto.lecture_unit_id,
                "language": self._heavy_result["transcription"].get("language", "en"),
                "segments": aligned_segments,
            }

            callback.done(
                message="Transcription complete",
                final_result=json.dumps(result),
            )

            logger.info(
                "[Lecture %d] Transcription pipeline complete: %d segments",
                self.dto.lecture_unit_id,
                len(aligned_segments),
            )

        except Exception as e:
            logger.error(
                "[Lecture %d] Transcription pipeline failed: %s",
                self.dto.lecture_unit_id,
                str(e),
                exc_info=True,
            )
            callback.error(str(e), exception=e)
            raise

        finally:
            self._cleanup()

    def _cleanup(self) -> None:
        """Clean up temporary files created during processing."""
        if self._heavy_result is None:
            return

        uid = self._heavy_result.get("uid")
        if not uid:
            return

        # Clean up video, audio, and chunks
        files_to_remove = [
            self.temp_dir / f"{uid}.mp4",
            self.temp_dir / f"{uid}.mp3",
        ]
        dirs_to_remove = [
            self.temp_dir / f"chunks_{uid}",
        ]

        for file_path in files_to_remove:
            try:
                if file_path.exists():
                    file_path.unlink()
                    logger.debug("Cleaned up: %s", file_path)
            except OSError as e:
                logger.warning("Failed to clean up %s: %s", file_path, e)

        for dir_path in dirs_to_remove:
            try:
                if dir_path.exists():
                    shutil.rmtree(dir_path)
                    logger.debug("Cleaned up: %s", dir_path)
            except OSError as e:
                logger.warning("Failed to clean up %s: %s", dir_path, e)
