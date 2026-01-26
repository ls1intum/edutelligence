"""
Utilities for detecting slide number change points with minimal GPT calls.

The core idea:
- Probe sparse "anchors" (every ``anchor_stride`` transcript segments) with GPT to
  read the slide number.
- Whenever adjacent anchors disagree (or any is unknown), recursively probe the
  midpoint until either the interval endpoints agree (and we can fill the range)
  or the interval shrinks to ``min_stride``.
- Finally, compress the per-segment labels into a list of ``(timestamp, label)``
  change points for downstream alignment.

Assumptions:
- ``ask_gpt_for_slide_number`` returns a correct integer label (``-1`` is a valid
  non-slide label) or ``None`` if unreadable.
- Setting ``min_stride=1`` ensures every differing interval is refined down to
  adjacent segments, which gives per-segment correctness when GPT labels are
  correct.
"""

from __future__ import annotations

import base64
import logging
from collections import OrderedDict
from typing import Dict, List, Optional, Tuple

import cv2

from nebula.tracing import trace_span
from nebula.transcript.slide_utils import ask_gpt_for_slide_number


class _FrameCache:
    """Simple LRU cache for base64-encoded cropped frames keyed by segment index."""

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
        """
        Return cropped frame at segment index as base64 jpeg string.
        Returns None if frame cannot be read.
        """
        if idx in self._cache:
            # move to end as most recently used
            self._cache.move_to_end(idx)
            return self._cache[idx]

        if self.fps <= 0:
            logging.warning(
                "Video FPS unavailable; cannot extract frame for idx=%s", idx
            )
            self._cache[idx] = None
            return None

        ts = self._capture_timestamp(idx)

        self.cap.set(cv2.CAP_PROP_POS_FRAMES, int(ts * self.fps))
        ret, frame = self.cap.read()
        if not ret:
            self._cache[idx] = None
            return None

        # Match existing behavior: crop bottom half to focus on slides.
        height = frame.shape[0]
        cropped = frame[int(height * 0.5) :, :]
        success, buffer = cv2.imencode(".jpg", cropped)
        if not success:
            self._cache[idx] = None
            return None

        img_b64 = base64.b64encode(buffer).decode("utf-8")
        self._cache[idx] = img_b64

        # Enforce LRU capacity.
        if len(self._cache) > self.capacity:
            self._cache.popitem(last=False)

        return img_b64

    def _capture_timestamp(self, idx: int) -> float:
        """
        Choose a timestamp 20% into the current segment span to avoid transition frames.
        """
        try:
            start = float(self.segments[idx]["start"])
        except (KeyError, TypeError, ValueError):
            return 0.0

        # Use next segment start if available; fallback to current end or start.
        next_start: float
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
    Detect slide-number change points with minimal GPT calls using recursive
    midpoint refinement between disagreeing anchors.
    """

    def __init__(
        self,
        video_path: str,
        segments: List[Dict],
        anchor_stride: int = 50,
        min_stride: int = 1,
        cache_size: int = 16,
        job_id: Optional[str] = None,
        capture_offset_ratio: float = 0.2,
    ):
        """
        :param video_path: Path to the downloaded video.
        :param segments: Whisper transcript segments (expects ``start`` keys).
        :param anchor_stride: Probe every Nth segment initially.
        :param min_stride: Smallest interval to refine before stopping. Use 1 for per-segment correctness.
        :param cache_size: Max cached frames.
        :param job_id: Optional job id for logging context.
        :param capture_offset_ratio: Fraction into a segment to capture the frame (e.g., 0.2 -> 20% into the span).
        """
        self.video_path = video_path
        self.segments = segments
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
        # Ensure capture is released even if caller forgets.
        frame_cache = getattr(self, "frame_cache", None)
        if frame_cache is not None:
            frame_cache.close()

    def detect(self) -> List[Tuple[float, int]]:
        """
        Run detection and return change points as ``(timestamp, slide_num)``.
        """
        try:
            if not self.segments:
                return []

            with trace_span(
                "Slide Turn Detection",
                input_data={
                    "segments": len(self.segments),
                    "anchor_stride": self.anchor_stride,
                },
            ) as span:
                logging.info(
                    "[Job %s] SlideTurnDetector start: segments=%d, anchor_stride=%d, min_stride=%d",
                    self.job_id,
                    len(self.segments),
                    self.anchor_stride,
                    self.min_stride,
                )

                anchor_indices = self._build_anchor_indices()
                logging.info(
                    "[Job %s] SlideTurnDetector anchors=%s",
                    self.job_id,
                    anchor_indices,
                )
                for idx in anchor_indices:
                    if self.labels[idx] is None:
                        self.labels[idx] = self._query_label(idx)

                for left, right in zip(anchor_indices, anchor_indices[1:]):
                    self._resolve_interval(left, right)

                # Fill any remaining None labels by carrying last known (or -1 default).
                self._backfill_unknowns()

                change_points = self._to_change_points()
                logging.info(
                    "[Job %s] SlideTurnDetector done: change_points=%d, gpt_calls=%d",
                    self.job_id,
                    len(change_points),
                    self.gpt_calls,
                )

                span.set_output(
                    {
                        "change_points": len(change_points),
                        "gpt_calls": self.gpt_calls,
                    }
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
        """Load frame for segment index and ask GPT for the slide label."""
        frame_b64 = self.frame_cache.get(idx)
        if frame_b64 is None:
            return None
        logging.info("[Job %s] GPT query for segment idx=%d", self.job_id, idx)
        slide_num = ask_gpt_for_slide_number(frame_b64, job_id=self.job_id)
        self.gpt_calls += 1
        self._log_progress(f"Label resolved for idx={idx}")
        return slide_num

    def _resolve_interval(self, idx_left: int, idx_right: int) -> None:
        """
        Recursively refine interval where endpoints disagree or include unknowns.
        """
        if idx_right - idx_left <= 1:
            return

        left_label = self.labels[idx_left]
        right_label = self.labels[idx_right]

        if (
            left_label is not None
            and right_label is not None
            and left_label == right_label
        ):
            # Stable span: fill interior.
            logging.info(
                "[Job %s] Stable span [%d, %d] with label=%s",
                self.job_id,
                idx_left,
                idx_right,
                left_label,
            )
            for i in range(idx_left + 1, idx_right):
                if self.labels[i] is None:
                    self.labels[i] = left_label
            self._log_progress(f"Filled stable span [{idx_left}, {idx_right}]")
            return

        # Need further refinement.
        mid = (idx_left + idx_right) // 2
        if self.labels[mid] is None:
            logging.info(
                "[Job %s] New midpoint idx=%d for interval [%d, %d]",
                self.job_id,
                mid,
                idx_left,
                idx_right,
            )
            self.labels[mid] = self._query_label(mid)
        logging.info(
            "[Job %s] Split interval [%d, %d] -> [%d, %d] and [%d, %d]",
            self.job_id,
            idx_left,
            idx_right,
            idx_left,
            mid,
            mid,
            idx_right,
        )

        if idx_right - idx_left <= self.min_stride:
            return

        self._resolve_interval(idx_left, mid)
        self._resolve_interval(mid, idx_right)

    def _log_progress(self, context: str) -> None:
        """Emit a progress log showing percent of segments with assigned labels."""
        total = len(self.labels)
        filled = sum(1 for lbl in self.labels if lbl is not None)
        percent = (filled / total * 100) if total else 100.0
        logging.info(
            "[Job %s] %s | labeled %d/%d (%.1f%%)",
            self.job_id,
            context,
            filled,
            total,
            percent,
        )

    def _backfill_unknowns(self) -> None:
        """
        Replace any remaining None with last seen label or -1 if none seen yet.
        """
        last_label: int = -1
        for i, label in enumerate(self.labels):
            if label is None:
                self.labels[i] = last_label
            else:
                last_label = label

    def _to_change_points(self) -> List[Tuple[float, int]]:
        """
        Compress per-segment labels into change points for aligner consumption.
        """
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
    segments: List[Dict],
    anchor_stride: int = 50,
    min_stride: int = 1,
    job_id: Optional[str] = None,
) -> List[Tuple[float, int]]:
    """
    Public wrapper to detect slide change timestamps using minimal GPT calls.

    :param video_path: Path to the downloaded video.
    :param segments: Whisper transcript segments (expects ``start`` keys).
    :param anchor_stride: Probe every Nth segment initially.
    :param min_stride: Smallest interval to refine before stopping. Use 1 to refine to adjacent segments.
    :param job_id: Optional job id for logging context.
    :return: List of ``(timestamp, slide_num)`` change points.
    """
    detector = SlideTurnDetector(
        video_path=video_path,
        segments=segments,
        anchor_stride=anchor_stride,
        min_stride=min_stride,
        job_id=job_id,
    )
    return detector.detect()
