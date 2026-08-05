"""Cancellation helpers for the lecture ingestion pipelines."""

import threading
from typing import Optional

from iris.common.custom_exceptions import IngestionCancelledException
from iris.common.logging_config import get_logger

logger = get_logger(__name__)


def raise_if_cancelled(
    cancel_event: Optional[threading.Event],
    lecture_unit_id: Optional[int] = None,
    stage: Optional[str] = None,
) -> None:
    """Stop the current ingestion job if a newer request superseded it.

    Belongs at the boundary of expensive work — between slides, between
    embeddings — and immediately before every Weaviate mutation, but never
    inside a delete/insert pair that would leave the unit half-written.

    Raises:
        IngestionCancelledException: If ``cancel_event`` is set.
    """
    if cancel_event is None or not cancel_event.is_set():
        return

    logger.info("[Lecture %s] Cancellation detected at %s", lecture_unit_id, stage)
    raise IngestionCancelledException(
        lecture_unit_id,
        f"Cancelled during {stage}" if stage else "Superseded by a newer request",
    )
