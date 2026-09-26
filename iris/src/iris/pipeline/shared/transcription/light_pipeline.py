"""Light transcription pipeline: slide detection and transcript alignment.

This phase is API-bound (GPT Vision calls) rather than CPU-intensive.
It takes the raw transcript from the heavy phase and enriches each segment
with a slide number by analysing video frames.
"""

from threading import Event
from typing import Any, Dict, List, Optional

from iris.common.cancellation import raise_if_cancelled
from iris.common.logging_config import get_logger
from iris.llm.llm_configuration import resolve_model
from iris.llm.request_handler.llm_request_handler import LlmRequestHandler
from iris.pipeline.shared.transcription.alignment import align_slides_with_segments
from iris.pipeline.shared.transcription.slide_turn_detector import (
    detect_slide_timestamps,
)
from iris.tracing import observe
from iris.web.status.status_update import StatusCallback

logger = get_logger(__name__)


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
        local: bool = False,
        cancel_event: Optional[Event] = None,
    ):
        self.callback = callback
        self.video_path = video_path
        self.cancel_event = cancel_event
        # Vision model for slide-number detection. Resolved through the
        # standard llm_configuration so it can be swapped per deployment
        # without touching code.
        model_id = resolve_model(
            "transcription_ingestion_pipeline",
            "default",
            "vision_chat",
            local=local,
        )
        self.request_handler = LlmRequestHandler(model_id=model_id)

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

        raise_if_cancelled(self.cancel_event, lecture_unit_id, "before slide detection")
        if self.video_path is None:
            logger.info("%s No video file available, skipping slide detection", prefix)
            self.callback.update()
            self.callback.update()
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
        self.callback.update()

        def on_slide_detection_progress(labeled: int, total: int) -> None:
            del labeled, total
            raise_if_cancelled(
                self.cancel_event, lecture_unit_id, "during slide detection"
            )
            self.callback.update()

        slide_timestamps = detect_slide_timestamps(
            video_path=self.video_path,
            segments=segments,
            request_handler=self.request_handler,
            anchor_stride=50,
            min_stride=1,
            job_id=str(lecture_unit_id),
            on_progress=on_slide_detection_progress,
            cancel_event=self.cancel_event,
        )
        self.callback.update()
        logger.info(
            "%s Slide detection complete: %d changes",
            prefix,
            len(slide_timestamps),
        )

        # Stage: Align segments with slides
        # Note: the orchestrator sends a checkpoint update for this stage so it can
        # attach the checkpoint data atomically in the same HTTP call.
        raise_if_cancelled(self.cancel_event, lecture_unit_id, "before alignment")
        self.callback.update()
        aligned_segments = align_slides_with_segments(
            segments,
            slide_timestamps,
            lecture_unit_id=lecture_unit_id,
            cancel_event=self.cancel_event,
        )
        logger.info(
            "%s Alignment complete: %d segments with slide numbers",
            prefix,
            len(aligned_segments),
        )

        return aligned_segments
