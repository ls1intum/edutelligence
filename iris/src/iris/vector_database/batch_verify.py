"""Verification of Weaviate batch and delete-many results.

The Weaviate batch context collects per-object insert errors instead of
raising them, and ``delete_many`` reports failures on its return value. A
pipeline that does not read those results can drop objects silently and still
report success. Every ingestion write path must call these helpers directly
after the write so a partial write becomes a failed run instead of a partial
unit.
"""

from iris.common.ingestion_errors import (
    STALE_CONTENT_DELETE_FAILED,
    VECTOR_STORE_WRITE_FAILED,
    IngestionStageError,
)
from iris.common.logging_config import get_logger

logger = get_logger(__name__)


def raise_on_failed_batch_objects(collection, context: str) -> None:
    """Fail the run when the last batch on ``collection`` dropped any object."""
    failed = collection.batch.failed_objects
    if not failed:
        return
    first_message = getattr(failed[0], "message", str(failed[0]))
    logger.error(
        "Weaviate batch dropped %d object(s) while writing %s | first error: %s",
        len(failed),
        context,
        first_message,
    )
    raise IngestionStageError(
        VECTOR_STORE_WRITE_FAILED,
        f"Weaviate batch dropped {len(failed)} object(s) while writing {context}: "
        f"{first_message}",
    )


def raise_on_failed_delete(delete_result, context: str) -> None:
    """Fail the run when a ``delete_many`` left matched objects undeleted."""
    if delete_result.failed == 0:
        return
    logger.error(
        "Weaviate delete_many failed for %d of %d matched object(s) while "
        "removing %s",
        delete_result.failed,
        delete_result.matches,
        context,
    )
    raise IngestionStageError(
        STALE_CONTENT_DELETE_FAILED,
        f"Weaviate failed to delete {delete_result.failed} of "
        f"{delete_result.matches} matched object(s) while removing {context}",
    )
