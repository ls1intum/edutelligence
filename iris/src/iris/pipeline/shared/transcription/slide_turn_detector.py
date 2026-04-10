"""
Detect slide-number change points from a video with minimal GPT Vision calls.

Strategy:
- Probe sparse "anchors" (every ``anchor_stride`` segments) with GPT Vision.
- When adjacent anchors disagree (or either is unknown), recursively probe the
  midpoint until the interval either stabilises or shrinks to ``min_stride``.
- Compress the per-segment labels into ``(timestamp, slide_num)`` change points
  for the alignment step.
"""

from __future__ import annotations

import base64
import re
from collections import OrderedDict
from typing import Callable, Dict, List, Optional, Tuple

import cv2

from iris.common.logging_config import get_logger
from iris.common.pyris_message import IrisMessageRole, PyrisMessage
from iris.domain.data.image_message_content_dto import ImageMessageContentDTO
from iris.domain.data.text_message_content_dto import TextMessageContentDTO
from iris.llm.completion_arguments import CompletionArguments
from iris.llm.request_handler.llm_request_handler import LlmRequestHandler

logger = get_logger(__name__)

_SYSTEM_PROMPT = (
    "You are an AI that reads slide numbers from images of presentation slides. "
    "Respond only with the slide number as an integer, or 'null' if no slide "
    "number is visible. If the image does not look like a presentation slide, "
    "respond with 'null'."
)


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
        self.cap.release()

    def get(self, idx: int) -> Optional[str]:
        """Return cropped frame at segment index as base64 JPEG. None if unreadable."""
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

        # Crop bottom half — slides are typically in the lower portion of the frame.
        height = frame.shape[0]
        cropped = frame[int(height * 0.5) :, :]  # noqa: E203
        success, buffer = cv2.imencode(".jpg", cropped)

        if not success:
            self._cache[idx] = None
            return None

        img_b64 = base64.b64encode(buffer).decode("utf-8")
        self._cache[idx] = img_b64

        if len(self._cache) > self.capacity:
            self._cache.popitem(last=False)

        return img_b64

    def _capture_timestamp(self, idx: int) -> float:
        """Choose a timestamp 20% into the segment span to avoid transition frames."""
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
    Detect slide-number change points using recursive midpoint refinement.

    Minimises GPT Vision calls by only probing anchors and refining intervals
    where adjacent anchors disagree.
    """

    def __init__(
        self,
        video_path: str,
        segments: List[Dict],
        request_handler: LlmRequestHandler,
        anchor_stride: int = 50,
        min_stride: int = 1,
        cache_size: int = 16,
        job_id: Optional[str] = None,
        capture_offset_ratio: float = 0.2,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ):
        """
        Args:
            video_path: Path to the downloaded video file.
            segments: Whisper transcript segments (must have "start" key).
            request_handler: Configured GPT Vision handler from LlmManager.
            anchor_stride: Probe every Nth segment initially.
            min_stride: Smallest interval to refine (1 = per-segment correctness).
            cache_size: Max frames to keep in the LRU cache.
            job_id: Optional job ID for log correlation.
            capture_offset_ratio: Fraction into the segment span to capture the frame.
        """
        self.video_path = video_path
        self.segments = segments
        self.request_handler = request_handler
        self.anchor_stride = max(1, anchor_stride)
        self.min_stride = max(1, min_stride)
        self.job_id = job_id
        self.on_progress = on_progress
        self.labels: List[Optional[int]] = [None] * len(segments)
        self.frame_cache = _FrameCache(
            video_path,
            segments,
            capture_offset_ratio=capture_offset_ratio,
            capacity=cache_size,
        )
        self.gpt_calls = 0

    def __del__(self) -> None:
        frame_cache = getattr(self, "frame_cache", None)
        if frame_cache is not None:
            frame_cache.close()

    def detect(self) -> List[Tuple[float, int]]:
        """Run detection and return change points as (timestamp, slide_num)."""
        try:
            if not self.segments:
                return []

            logger.info(
                "[Lecture %s] SlideTurnDetector start: segments=%d, anchor_stride=%d, min_stride=%d",
                self.job_id,
                len(self.segments),
                self.anchor_stride,
                self.min_stride,
            )

            anchor_indices = self._build_anchor_indices()
            logger.debug("[Lecture %s] Anchors: %s", self.job_id, anchor_indices)

            for idx in anchor_indices:
                if self.labels[idx] is None:
                    self.labels[idx] = self._query_label(idx)

            for left, right in zip(anchor_indices, anchor_indices[1:]):
                self._resolve_interval(left, right)

            self._backfill_unknowns()
            change_points = self._to_change_points()

            logger.info(
                "[Lecture %s] SlideTurnDetector done: change_points=%d, gpt_calls=%d",
                self.job_id,
                len(change_points),
                self.gpt_calls,
            )

            return change_points
        finally:
            self.frame_cache.close()

    def _build_anchor_indices(self) -> List[int]:
        anchors = list(range(0, len(self.segments), self.anchor_stride))
        if anchors[-1] != len(self.segments) - 1:
            anchors.append(len(self.segments) - 1)
        return anchors

    def _query_label(self, idx: int) -> Optional[int]:
        frame_b64 = self.frame_cache.get(idx)
        if frame_b64 is None:
            return None
        logger.debug(
            "[Lecture %s] GPT Vision query for segment idx=%d", self.job_id, idx
        )
        slide_num = self._ask_gpt_for_slide_number(frame_b64)
        self.gpt_calls += 1
        self._log_progress(f"label resolved for idx={idx}")
        return slide_num

    def _ask_gpt_for_slide_number(self, image_b64: str) -> Optional[int]:
        """Send one video frame to GPT Vision and parse the slide number response."""
        try:
            messages = [
                PyrisMessage(
                    sender=IrisMessageRole.SYSTEM,
                    contents=[TextMessageContentDTO(text_content=_SYSTEM_PROMPT)],
                ),
                PyrisMessage(
                    sender=IrisMessageRole.USER,
                    contents=[ImageMessageContentDTO(base64=image_b64)],
                ),
            ]

            response = self.request_handler.chat(
                messages=messages,
                arguments=CompletionArguments(temperature=0),
                tools=None,
            )

            raw = ""
            for item in response.contents:
                if isinstance(item, TextMessageContentDTO):
                    raw += item.text_content or ""

            content = raw.strip().lower()

            if "null" in content or "unknown" in content:
                return -1  # Frame visible but no slide number shown

            match = re.search(r"\d+", content)
            return int(match.group(0)) if match else None

        except Exception as e:
            logger.warning("[Lecture %s] GPT Vision failed: %s", self.job_id, e)
            return None

    def _resolve_interval(self, idx_left: int, idx_right: int) -> None:
        """Recursively refine an interval where endpoints disagree or are unknown."""
        if idx_right - idx_left <= 1:
            return

        left_label = self.labels[idx_left]
        right_label = self.labels[idx_right]

        if (
            left_label is not None
            and right_label is not None
            and left_label >= 0
            and right_label >= 0
            and left_label == right_label
        ):
            # Stable span — fill interior without more GPT calls.
            # Note: -1 means "unknown slide number", not a stable label.
            # Two unknown endpoints must still be probed at the midpoint.
            for i in range(idx_left + 1, idx_right):
                if self.labels[i] is None:
                    self.labels[i] = left_label
            self._log_progress(f"filled stable span [{idx_left}, {idx_right}]")
            return

        mid = (idx_left + idx_right) // 2
        if self.labels[mid] is None:
            self.labels[mid] = self._query_label(mid)

        if idx_right - idx_left <= self.min_stride:
            return

        self._resolve_interval(idx_left, mid)
        self._resolve_interval(mid, idx_right)

    def _backfill_unknowns(self) -> None:
        """Replace remaining None labels with last known label, or -1 if none seen."""
        last_label: int = -1
        for i, label in enumerate(self.labels):
            if label is None:
                self.labels[i] = last_label
            else:
                last_label = label

    def _to_change_points(self) -> List[Tuple[float, int]]:
        """Compress per-segment labels into (timestamp, slide_num) change points."""
        change_points: List[Tuple[float, int]] = []
        last_label: Optional[int] = None
        timestamps = [float(s["start"]) for s in self.segments]

        for ts, label in zip(timestamps, self.labels):
            label_val = -1 if label is None else label
            if last_label is None or label_val != last_label:
                change_points.append((ts, label_val))
                last_label = label_val

        return change_points

    def _log_progress(self, context: str) -> None:
        total = len(self.labels)
        filled = sum(1 for lbl in self.labels if lbl is not None)
        percent = (filled / total * 100) if total else 100.0
        logger.debug(
            "[Lecture %s] %s | labeled %d/%d (%.1f%%)",
            self.job_id,
            context,
            filled,
            total,
            percent,
        )
        if self.on_progress is not None:
            self.on_progress(filled, total)


def detect_slide_timestamps(
    video_path: str,
    segments: List[Dict],
    request_handler: LlmRequestHandler,
    anchor_stride: int = 50,
    min_stride: int = 1,
    job_id: Optional[str] = None,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> List[Tuple[float, int]]:
    """Detect slide change timestamps using minimal GPT Vision calls.

    Args:
        video_path: Path to the downloaded video file.
        segments: Whisper transcript segments (must have "start" key).
        request_handler: Configured GPT Vision handler from LlmManager.
        anchor_stride: Probe every Nth segment initially.
        min_stride: Smallest interval to refine (1 = per-segment correctness).
        job_id: Optional job ID for log correlation.

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
        on_progress=on_progress,
    )
    return detector.detect()
