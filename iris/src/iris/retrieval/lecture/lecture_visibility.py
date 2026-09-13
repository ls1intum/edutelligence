import json
from datetime import datetime, timezone
from typing import Any, Mapping

from iris.vector_database.lecture_transcription_schema import (
    LectureTranscriptionSchema,
)
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


def is_transcription_visible(
    transcription_properties: Mapping[str, Any],
    lecture_unit_properties: Mapping[str, Any],
    associated_slide_properties: (
        Mapping[str, Any] | list[Mapping[str, Any]] | None
    ) = None,
    now: datetime | None = None,
    *,
    bypass_release: bool = False,
) -> bool:
    """Return whether a transcription and its associated slide are visible.

    ``bypass_release`` skips only the unit-level release-date gate (for staff/admins,
    mirroring Artemis ``isAllowedToSeeLectureUnit``). Slide-level ``hidden_until`` is
    still enforced for everyone.
    """
    if not bypass_release and not is_unit_released(lecture_unit_properties, now):
        return False

    page_number = transcription_properties.get(
        LectureTranscriptionSchema.PAGE_NUMBER.value
    )
    try:
        page_number = int(page_number)
    except (TypeError, ValueError):
        return False
    if page_number <= 0:
        return True
    if associated_slide_properties is not None:
        associated_slides = (
            associated_slide_properties
            if isinstance(associated_slide_properties, list)
            else [associated_slide_properties]
        )
        return bool(associated_slides) and all(
            is_slide_visible(slide, now) for slide in associated_slides
        )

    serialized_snapshot = lecture_unit_properties.get(
        LectureUnitSchema.SLIDE_VISIBILITY.value
    )
    if serialized_snapshot is None:
        return True
    try:
        snapshot = (
            json.loads(serialized_snapshot)
            if isinstance(serialized_snapshot, str)
            else serialized_snapshot
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    if not isinstance(snapshot, Mapping):
        return False
    # Snapshot keys are physical PDF slide numbers, while transcription page numbers
    # are detected display numbers. Without the page-chunk mapping, only allow the
    # transcription when the snapshot proves every physical slide is visible.
    return all(_is_visible_at(hidden_until, now) for hidden_until in snapshot.values())
