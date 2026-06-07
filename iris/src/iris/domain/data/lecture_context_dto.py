import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class IrisLectureContextDTO:
    """Context about user's current position in lecture content.

    This is parsed from [context:...] blocks in user messages.
    Internal data structure, not sent from Artemis.
    """

    lecture_unit_id: int
    page: Optional[int] = None
    timestamp: Optional[float] = None


# Pattern to match: [context:lectureUnitId:page:timestamp]
CONTEXT_PATTERN = re.compile(r"\[context:(\d+):(\d*):([0-9.]*)\]")


def parse_lecture_context(text: str) -> Optional[IrisLectureContextDTO]:
    """
    Extract context information from message text.

    Format: [context:lectureUnitId:page:timestamp]

    Args:
        text: The message text potentially containing a context block

    Returns:
        Parsed context information, or None if no valid context block found
    """
    if not text:
        return None

    match = CONTEXT_PATTERN.search(text)
    if not match:
        return None

    try:
        lecture_unit_id = int(match.group(1))
        page = int(match.group(2)) if match.group(2) else None
        timestamp = float(match.group(3)) if match.group(3) else None

        return IrisLectureContextDTO(
            lecture_unit_id=lecture_unit_id, page=page, timestamp=timestamp
        )
    except (ValueError, IndexError):
        return None


def remove_context_block(text: str) -> str:
    """
    Remove the context block from message text for clean LLM processing.

    Args:
        text: The message text potentially containing a context block

    Returns:
        The message text with context block removed
    """
    if not text:
        return text
    return CONTEXT_PATTERN.sub("", text).strip()
