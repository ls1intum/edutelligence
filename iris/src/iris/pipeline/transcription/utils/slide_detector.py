"""
Slide detection utilities using GPT Vision.

Uses a sparse probing strategy with recursive refinement to minimize
GPT Vision API calls while accurately detecting slide changes:

1. Probe sparse "anchors" (every N segments) with GPT Vision
2. When adjacent anchors disagree, recursively probe the midpoint
3. Compress per-segment labels into (timestamp, slide_number) change points
"""

from __future__ import annotations

import base64
import re
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

import cv2

from iris.common.logging_config import get_logger
from iris.common.pyris_message import IrisMessageRole, PyrisMessage
from iris.domain.data.image_message_content_dto import ImageMessageContentDTO
from iris.domain.data.text_message_content_dto import TextMessageContentDTO
from iris.llm.completion_arguments import CompletionArguments
from iris.llm.request_handler.model_version_request_handler import (
    ModelVersionRequestHandler,
)
from iris.tracing import observe

logger = get_logger(__name__)


class _FrameCache:
    """LRU cache for base64-encoded cropped frames keyed by segment index."""

    def __init__(
        self,
        video_path: str,
        segments: List[Dict],
        capture_offset_ratio: float = 0.2,
        capacity: int = 16,
    ):
        self.video_path = video_path
        self.segments = segments
        self.capture_offset_ratio = capture_offset_ratio
        self.capacity = capacity
        self.cap = cv2.VideoCapture(video_path)
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 0.0
        self._cache: OrderedDict[int, Optional[str]] = OrderedDict()

    def close(self) -> None:
        """Release the video capture resource."""
        self.cap.release()

    def get(self, idx: int) -> Optional[str]:
        """
        Get the cropped frame at segment index as base64 JPEG string.

        Returns None if the frame cannot be read.
        """
        if idx in self._cache:
            self._cache.move_to_end(idx)
            return self._cache[idx]

        if self.fps <= 0:
            logger.warning(
                "Video FPS unavailable; cannot extract frame for idx=%d", idx
            )
            self._cache[idx] = None
            return None

        ts = self._capture_timestamp(idx)
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, int(ts * self.fps))
        ret, frame = self.cap.read()

        if not ret:
            self._cache[idx] = None
            return None

        # Crop bottom half to focus on slide area (typical placement)
        height = frame.shape[0]
        cropped = frame[int(height * 0.5) :, :]  # noqa: E203
        success, buffer = cv2.imencode(".jpg", cropped)

        if not success:
            self._cache[idx] = None
            return None

        img_b64 = base64.b64encode(buffer).decode("utf-8")
        self._cache[idx] = img_b64

        # Enforce LRU capacity
        if len(self._cache) > self.capacity:
            self._cache.popitem(last=False)

        return img_b64

    def _capture_timestamp(self, idx: int) -> float:
        """Get timestamp 20% into the segment to avoid transition frames."""
        try:
            start = float(self.segments[idx]["start"])
        except (KeyError, TypeError, ValueError):
            return 0.0

        if idx + 1 < len(self.segments):
            try:
                next_start = float(self.segments[idx + 1]["start"])
            except (KeyError, TypeError, ValueError):
                next_start = start
        else:
            try:
                next_start = float(self.segments[idx].get("end", start))
            except (TypeError, ValueError):
                next_start = start

        duration = max(0.0, next_start - start)
        return start + duration * self.capture_offset_ratio


class SlideTurnDetector:
    """
    Detect slide-number change points with minimal GPT Vision calls.

    Uses recursive midpoint refinement between disagreeing anchors.
    """

    def __init__(
        self,
        video_path: str,
        segments: List[Dict],
        request_handler: ModelVersionRequestHandler,
        anchor_stride: int = 50,
        min_stride: int = 1,
        cache_size: int = 16,
        job_id: Optional[str] = None,
        capture_offset_ratio: float = 0.2,
    ):
        """
        Initialize the detector.

        Args:
            video_path: Path to the video file.
            segments: Whisper transcript segments (must have "start" key).
            request_handler: LLM request handler for GPT Vision calls.
            anchor_stride: Probe every Nth segment initially.
            min_stride: Smallest interval to refine.
            cache_size: Max cached frames.
            job_id: Optional job ID for logging.
            capture_offset_ratio: Fraction into segment to capture frame.
        """
        self.video_path = video_path
        self.segments = segments
        self.request_handler = request_handler
        self.anchor_stride = max(1, anchor_stride)
        self.min_stride = max(1, min_stride)
        self.job_id = job_id
        self.labels: List[Optional[int]] = [None] * len(segments)
        self.frame_cache = _FrameCache(
            video_path,
            segments,
            capture_offset_ratio=capture_offset_ratio,
            capacity=cache_size,
        )
        self.gpt_calls = 0

    def __del__(self):
        frame_cache = getattr(self, "frame_cache", None)
        if frame_cache is not None:
            frame_cache.close()

    @observe(name="Slide Turn Detection")
    def detect(self) -> List[Tuple[float, int]]:
        """
        Run detection and return change points as (timestamp, slide_num).
        """
        try:
            if not self.segments:
                return []

            logger.info(
                "[Job %s] SlideTurnDetector start: segments=%d, anchor_stride=%d",
                self.job_id,
                len(self.segments),
                self.anchor_stride,
            )

            anchor_indices = self._build_anchor_indices()
            logger.debug("[Job %s] Anchors: %s", self.job_id, anchor_indices)

            for idx in anchor_indices:
                if self.labels[idx] is None:
                    self.labels[idx] = self._query_label(idx)

            for left, right in zip(anchor_indices, anchor_indices[1:]):
                self._resolve_interval(left, right)

            self._backfill_unknowns()
            change_points = self._to_change_points()

            logger.info(
                "[Job %s] SlideTurnDetector done: change_points=%d, gpt_calls=%d",
                self.job_id,
                len(change_points),
                self.gpt_calls,
            )

            return change_points
        finally:
            self.frame_cache.close()

    def _build_anchor_indices(self) -> List[int]:
        """Return sorted unique anchor indices including the last segment."""
        anchors = list(range(0, len(self.segments), self.anchor_stride))
        if anchors[-1] != len(self.segments) - 1:
            anchors.append(len(self.segments) - 1)
        return anchors

    def _query_label(self, idx: int) -> Optional[int]:
        """Query GPT Vision for the slide label at segment index."""
        frame_b64 = self.frame_cache.get(idx)
        if frame_b64 is None:
            return None

        logger.debug("[Job %s] GPT query for segment idx=%d", self.job_id, idx)
        slide_num = self._ask_gpt_for_slide_number(frame_b64)
        self.gpt_calls += 1
        return slide_num

    def _ask_gpt_for_slide_number(self, image_b64: str) -> Optional[int]:
        """Use GPT Vision to detect the slide number from a base64 image."""
        try:
            system_prompt = TextMessageContentDTO(
                text_content=(
                    "You are an AI that reads slide numbers from presentation "
                    "images. Respond only with the slide number as an integer, "
                    "or 'null' if no slide number is visible or if the image "
                    "does not look like a presentation slide."
                )
            )
            image_content = ImageMessageContentDTO(base64=image_b64)

            messages = [
                PyrisMessage(
                    sender=IrisMessageRole.SYSTEM,
                    contents=[system_prompt],
                ),
                PyrisMessage(
                    sender=IrisMessageRole.USER,
                    contents=[image_content],
                ),
            ]

            response = self.request_handler.chat(
                messages=messages,
                arguments=CompletionArguments(temperature=0, max_tokens=50),
                tools=None,
            )

            content = ""
            for item in response.contents:
                if hasattr(item, "text_content"):
                    content += item.text_content or ""

            content = content.strip().lower()

            if "null" in content or "unknown" in content:
                return -1

            match = re.search(r"\d+", content)
            return int(match.group(0)) if match else None

        except Exception as e:
            logger.warning("GPT Vision failed: %s", e)
            return None

    def _resolve_interval(self, idx_left: int, idx_right: int) -> None:
        """Recursively refine interval where endpoints disagree."""
        if idx_right - idx_left <= 1:
            return

        left_label = self.labels[idx_left]
        right_label = self.labels[idx_right]

        if (
            left_label is not None
            and right_label is not None
            and left_label == right_label
        ):
            # Stable span: fill interior with same label
            for i in range(idx_left + 1, idx_right):
                if self.labels[i] is None:
                    self.labels[i] = left_label
            return

        # Need refinement
        mid = (idx_left + idx_right) // 2
        if self.labels[mid] is None:
            self.labels[mid] = self._query_label(mid)

        if idx_right - idx_left <= self.min_stride:
            return

        self._resolve_interval(idx_left, mid)
        self._resolve_interval(mid, idx_right)

    def _backfill_unknowns(self) -> None:
        """Replace remaining None labels with last known or -1."""
        last_label: int = -1
        for i, label in enumerate(self.labels):
            if label is None:
                self.labels[i] = last_label
            else:
                last_label = label

    def _to_change_points(self) -> List[Tuple[float, int]]:
        """Compress per-segment labels into change points."""
        change_points: List[Tuple[float, int]] = []
        last_label: Optional[int] = None
        timestamps = [float(s["start"]) for s in self.segments]

        for ts, label in zip(timestamps, self.labels):
            label_val = -1 if label is None else label
            if last_label is None or label_val != last_label:
                change_points.append((ts, label_val))
                last_label = label_val

        return change_points


def detect_slide_timestamps(
    video_path: str,
    segments: List[Dict[str, Any]],
    request_handler: ModelVersionRequestHandler,
    anchor_stride: int = 50,
    min_stride: int = 1,
    job_id: Optional[str] = None,
) -> List[Tuple[float, int]]:
    """
    Detect slide change timestamps using minimal GPT Vision calls.

    Args:
        video_path: Path to the video file.
        segments: Whisper transcript segments (must have "start" key).
        request_handler: LLM request handler for GPT Vision.
        anchor_stride: Probe every Nth segment initially.
        min_stride: Smallest interval to refine.
        job_id: Optional job ID for logging.

    Returns:
        List of (timestamp, slide_number) change points.
    """
    detector = SlideTurnDetector(
        video_path=video_path,
        segments=segments,
        request_handler=request_handler,
        anchor_stride=anchor_stride,
        min_stride=min_stride,
        job_id=job_id,
    )
    return detector.detect()
