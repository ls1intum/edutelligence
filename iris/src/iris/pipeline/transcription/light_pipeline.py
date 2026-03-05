"""Light transcription pipeline: slide detection and alignment."""

from pathlib import Path
from typing import Any, Dict, List

from iris.common.logging_config import get_logger
from iris.domain.transcription.video_transcription_execution_dto import (
    VideoTranscriptionPipelineExecutionDto,
)
from iris.llm.request_handler.model_version_request_handler import (
    ModelVersionRequestHandler,
)
from iris.pipeline.transcription.utils.alignment import align_slides_with_segments
from iris.pipeline.transcription.utils.slide_detector import detect_slide_timestamps
from iris.tracing import observe
from iris.web.status.video_transcription_callback import VideoTranscriptionCallback

logger = get_logger(__name__)

# Model for GPT Vision slide detection
VISION_MODEL = "gpt-4.1-mini"


class LightTranscriptionPipeline:
    """
    Light transcription pipeline for slide detection and alignment.

    This pipeline handles:
    1. Detecting slide changes using GPT Vision
    2. Aligning transcript segments with detected slides

    These operations are API-bound (GPT Vision calls) rather than
    CPU-intensive, so they can run in parallel with other jobs.
    """

    def __init__(
        self,
        dto: VideoTranscriptionPipelineExecutionDto,
        callback: VideoTranscriptionCallback,
        transcription: Dict[str, Any],
        video_path: Path,
    ):
        """
        Initialize the light pipeline.

        Args:
            dto: Execution DTO with lecture information.
            callback: Status callback for progress updates.
            transcription: Dict with "segments" list from heavy pipeline.
            video_path: Path to video file for frame extraction.
        """
        self.dto = dto
        self.callback = callback
        self.transcription = transcription
        self.video_path = video_path
        self.request_handler = ModelVersionRequestHandler(VISION_MODEL)

    @observe(name="Light Transcription Pipeline")
    def __call__(self) -> List[Dict[str, Any]]:
        """
        Execute the light pipeline.

        Returns:
            List of aligned segments with slide numbers.
            Each segment has: startTime, endTime, text, slideNumber
        """
        segments = self.transcription.get("segments", [])
        job_id = str(self.dto.lecture_unit_id)

        logger.info(
            "[Lecture %d] Starting light pipeline: %d segments",
            self.dto.lecture_unit_id,
            len(segments),
        )

        # Stage 4: Detect slide changes
        self.callback.in_progress("Detecting slide changes with GPT Vision...")
        slide_timestamps = detect_slide_timestamps(
            video_path=str(self.video_path),
            segments=segments,
            request_handler=self.request_handler,
            anchor_stride=50,  # Probe every 50th segment
            min_stride=1,  # Refine to per-segment accuracy
            job_id=job_id,
        )
        self.callback.done(f"Detected {len(slide_timestamps)} slide changes")

        # Stage 5: Align segments with slides
        self.callback.in_progress("Aligning transcript with slides...")
        aligned_segments = align_slides_with_segments(segments, slide_timestamps)
        self.callback.done("Alignment complete")

        logger.info(
            "[Lecture %d] Light pipeline complete: %d slides, %d aligned segments",
            self.dto.lecture_unit_id,
            len(slide_timestamps),
            len(aligned_segments),
        )

        return aligned_segments
