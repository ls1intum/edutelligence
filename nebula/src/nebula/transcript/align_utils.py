from typing import Dict, List, Tuple


def align_slides_with_segments(
    segments: List[Dict], slide_timestamps: List[Tuple[float, int]]
) -> List[Dict]:
    """Attach slide numbers to transcript segments based on timestamps."""
    result = []

    for segment in segments:
        slide_number = -1  # Default if no matching timestamp
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
