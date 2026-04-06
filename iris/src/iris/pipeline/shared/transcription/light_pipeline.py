"""Light transcription pipeline: slide detection and transcript alignment.

This phase is API-bound (GPT Vision calls) rather than CPU-intensive.
It takes the raw transcript from the heavy phase and enriches each segment
with a slide number by analysing video frames.
"""

from typing import Any, Dict, List, Optional

from iris.common.logging_config import get_logger
from iris.llm.request_handler.model_version_request_handler import (
    ModelVersionRequestHandler,
)
from iris.pipeline.shared.transcription.alignment import align_slides_with_segments
from iris.pipeline.shared.transcription.slide_turn_detector import (
    detect_slide_timestamps,
)
from iris.tracing import observe
from iris.web.status.status_update import StatusCallback

logger = get_logger(__name__)

# Model used for GPT Vision slide detection
VISION_MODEL = "gpt-4.1-mini"


class LightTranscriptionPipeline:
    """Detect slide changes and align them with transcript segments.

    Steps:
    1. Probe video frames with GPT Vision to find slide change points.
    2. Align each transcript segment with the most recent slide change.

    Requires the video file to still be on disk (from the heavy phase
    or re-downloaded on retry).
    """

    def __init__(
        self,
        callback: StatusCallback,
        video_path: Optional[str],
    ):
        self.callback = callback
        self.video_path = video_path
        self.request_handler = ModelVersionRequestHandler(VISION_MODEL)

    @observe(name="Light Transcription Pipeline")
    def __call__(
        self,
        transcription: Dict[str, Any],
        lecture_unit_id: int,
    ) -> List[Dict[str, Any]]:
        """Run the light pipeline.

        Args:
            transcription: Dict with "segments" list from heavy pipeline.
            lecture_unit_id: For logging.

        Returns:
            List of aligned segment dicts with keys:
            startTime, endTime, text, slideNumber.
        """
        segments = transcription.get("segments", [])
        prefix = f"[Lecture {lecture_unit_id}]"

        logger.info("%s Starting light pipeline: %d segments", prefix, len(segments))

        if self.video_path is None:
            logger.info("%s No video file available, skipping slide detection", prefix)
            self.callback.skip("Skipped (no video file)")
            self.callback.skip("Skipped (no video file)")
            return [
                {
                    "startTime": seg["start"],
                    "endTime": seg["end"],
                    "text": seg["text"].strip(),
                    "slideNumber": -1,
                }
                for seg in segments
            ]

        # Stage: Detect slide changes
        self.callback.in_progress("Detecting slide changes with GPT Vision...")
        slide_timestamps = detect_slide_timestamps(
            video_path=self.video_path,
            segments=segments,
            request_handler=self.request_handler,
            anchor_stride=50,
            min_stride=1,
            job_id=str(lecture_unit_id),
        )
        self.callback.done(f"Detected {len(slide_timestamps)} slide changes")
        logger.info(
            "%s Slide detection complete: %d changes",
            prefix,
            len(slide_timestamps),
        )

        # Stage: Align segments with slides
        # Note: the orchestrator calls done() for this stage so it can
        # attach the checkpoint data atomically in the same HTTP call.
        self.callback.in_progress("Aligning transcript with slides...")
        aligned_segments = align_slides_with_segments(segments, slide_timestamps)
        logger.info(
            "%s Alignment complete: %d segments with slide numbers",
            prefix,
            len(aligned_segments),
        )

        return aligned_segments
