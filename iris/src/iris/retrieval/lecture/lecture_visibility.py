from datetime import datetime, timezone
from typing import Any, Mapping

from iris.vector_database.lecture_unit_page_chunk_schema import (
    LectureUnitPageChunkSchema,
)
from iris.vector_database.lecture_unit_schema import LectureUnitSchema
from iris.vector_database.lecture_unit_segment_schema import LectureUnitSegmentSchema


def _as_datetime(value: Any) -> datetime | None:
    """Normalize Weaviate DATE values for visibility comparisons."""
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime):
        raise TypeError(f"Expected a datetime-compatible value, got {type(value)!r}")
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


def _is_visible_at(value: Any, now: datetime | None = None) -> bool:
    try:
        visible_at = _as_datetime(value)
    except (TypeError, ValueError):
        return False
    if visible_at is None:
        return True
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    return visible_at <= current_time


def is_slide_visible(
    properties: Mapping[str, Any], now: datetime | None = None
) -> bool:
    """Return whether a page chunk is visible at ``now``."""
    return _is_visible_at(
        properties.get(LectureUnitPageChunkSchema.HIDDEN_UNTIL.value), now
    )


def is_segment_visible(
    properties: Mapping[str, Any], now: datetime | None = None
) -> bool:
    """Return whether a slide-backed aggregate segment is visible at ``now``."""
    return _is_visible_at(
        properties.get(LectureUnitSegmentSchema.HIDDEN_UNTIL.value), now
    )


def is_unit_released(
    properties: Mapping[str, Any], now: datetime | None = None
) -> bool:
    """Return whether a lecture unit has reached its release date."""
    return _is_visible_at(properties.get(LectureUnitSchema.RELEASE_DATE.value), now)
