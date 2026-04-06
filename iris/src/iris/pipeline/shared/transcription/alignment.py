"""Utilities for aligning transcript segments with detected slide changes."""

from typing import Dict, List, Tuple


def align_slides_with_segments(
    segments: List[Dict], slide_timestamps: List[Tuple[float, int]]
) -> List[Dict]:
    """Attach slide numbers to transcript segments based on timestamps.

    For each segment, finds the most recent slide change that occurred
    before or at the segment's start time.

    Args:
        segments: Whisper transcript segments with "start", "end", "text" keys.
        slide_timestamps: (timestamp, slide_number) tuples sorted ascending.
            Sorted defensively to guarantee correctness.

    Returns:
        List of aligned segments with "startTime", "endTime", "text",
        and "slideNumber" keys.
    """
    slide_timestamps = sorted(slide_timestamps, key=lambda x: x[0])
    result = []

    for segment in segments:
        slide_number = -1

        for ts, num in reversed(slide_timestamps):
            if ts <= segment["start"]:
                slide_number = num
                break

        result.append(
            {
                "startTime": segment["start"],
                "endTime": segment["end"],
                "text": segment["text"].strip(),
                "slideNumber": slide_number,
            }
        )

    return result
