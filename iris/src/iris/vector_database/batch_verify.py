"""Verification of Weaviate batch and delete-many results.

The Weaviate batch context collects per-object insert errors instead of
raising them, and ``delete_many`` reports failures on its return value. A
pipeline that does not read those results can drop objects silently and still
report success. Every ingestion write path must call these helpers directly
after the write so a partial write becomes a failed run instead of a partial
unit.
"""

from typing import Optional

from weaviate.classes.query import Filter, MetadataQuery

from iris.common.ingestion_errors import (
    STALE_CONTENT_DELETE_FAILED,
    VECTOR_STORE_WRITE_FAILED,
    IngestionStageError,
)
from iris.common.logging_config import get_logger
from iris.vector_database.write_retry import (
    WeaviateWriteRetry,
    is_transient_message,
)

logger = get_logger(__name__)

_SWEEP_FETCH_LIMIT = 10_000
_SWEEP_DELETE_BATCH = 500


def _failed_object_payloads(failed) -> Optional[list]:
    """Reconstruct the (properties, vector) of each dropped object.

    Returns ``None`` when the client did not carry the object back, in which case
    a safe re-submit is impossible and the run must fail instead of retrying.
    """
    payloads = []
    for error_object in failed:
        carried = getattr(error_object, "object_", None)
        if carried is None:
            return None
        payloads.append(
            (getattr(carried, "properties", None), getattr(carried, "vector", None))
        )
    return payloads


def _rate_limited_batch(collection):
    return collection.batch.rate_limit(requests_per_minute=600)


def _creation_time(row):
    """Return a row's Weaviate-assigned creation time, or ``None`` when unavailable."""
    metadata = getattr(row, "metadata", None)
    return getattr(metadata, "creation_time", None) if metadata is not None else None


def stale_generation_ids(rows, is_own) -> list:
    """Ids of rows to sweep: every not-own row older than this run's own oldest row.

    The concurrency fence — never delete a row at or newer than the current run's own oldest row —
    is what keeps two concurrent writers from wiping each other's freshly written generation; they
    degrade to last-writer-wins instead of a mutual wipe. ``is_own(row)`` identifies this run's own
    rows (by run id for the chunk/transcript/segment sweeps, by uuid for the single unit row). The
    fence engages only when Weaviate reports creation times (always in production); when the own rows
    carry none it falls back to sweeping every not-own row, exactly as an un-fenced sweep would.

    A legacy row without a timestamp predates any fenced generation and is swept; a row at or after
    the fence belongs to a concurrent later writer and is left alone. Exact-timestamp ties therefore
    survive on both sides and are cleaned up by the next generation's sweep (brief duplication, never
    a wipe).
    """
    own_creation_times = [
        creation_time
        for row in rows
        if is_own(row)
        for creation_time in (_creation_time(row),)
        if creation_time is not None
    ]
    fence = min(own_creation_times) if own_creation_times else None
    return [
        row.uuid
        for row in rows
        if not is_own(row)
        and (
            fence is None or _creation_time(row) is None or _creation_time(row) < fence
        )
    ]


def write_batch_with_retry(
    collection,
    prepared,
    context: str,
    *,
    retry: Optional[WeaviateWriteRetry] = None,
    open_batch=_rate_limited_batch,
) -> None:
    """Insert ``(properties, vector)`` pairs, retrying only what a transient drop lost.

    The expensive work (vision, embeddings, summaries) is already done by the time
    a batch is written, so a transient store condition (read-only under resource
    pressure, a rate limit, a momentary overload) is recovered by re-submitting just
    the dropped objects within the shared retry budget — never by re-running the
    pipeline. A non-transient drop, or one that outlasts the budget, fails the run
    with ``VECTOR_STORE_WRITE_FAILED``, exactly as an un-retried write would.

    ``open_batch`` selects the batching mode (rate-limited by default; callers with
    their own strategy, e.g. dynamic batching, pass their own).
    """
    retry = retry or WeaviateWriteRetry.for_request()
    pending = list(prepared)
    attempt = 0
    while True:
        attempt += 1
        with open_batch(collection) as batch:
            for properties, vector in pending:
                batch.add_object(properties=properties, vector=vector)
        failed = collection.batch.failed_objects
        if not failed:
            return
        first_message = getattr(failed[0], "message", str(failed[0]))
        retriable = _failed_object_payloads(failed)
        if (
            is_transient_message(first_message)
            and retriable is not None
            and retry.backoff(attempt, context)
        ):
            logger.warning(
                "Retrying %d dropped object(s) while writing %s (transient): %s",
                len(failed),
                context,
                first_message,
            )
            pending = retriable
            continue
        logger.error(
            "Weaviate batch dropped %d object(s) while writing %s | first error: %s",
            len(failed),
            context,
            first_message,
        )
        raise IngestionStageError(
            VECTOR_STORE_WRITE_FAILED,
            f"Weaviate batch dropped {len(failed)} object(s) while writing "
            f"{context}: {first_message}",
        )


def delete_many_with_retry(
    collection, where, context: str, *, retry: Optional[WeaviateWriteRetry] = None
):
    """Delete matching rows, retrying a transient failure.

    ``delete_many`` is idempotent — deleting already-gone rows is a no-op — so a
    retry is always safe. A transient exception is retried within the shared
    budget; a returned failure count is definitive and fails the run at once via
    :func:`raise_on_failed_delete`.
    """
    retry = retry or WeaviateWriteRetry.for_request()
    result = retry.run(
        lambda: collection.data.delete_many(where=where),
        description=f"delete {context}",
    )
    raise_on_failed_delete(result, context)
    return result


def fetch_with_retry(fetch, *, retry: Optional[WeaviateWriteRetry] = None):
    """Run a read (``fetch_objects``/aggregate) with transient-failure retry.

    A transient read blip must not spuriously fail a run or a verification audit,
    so reads share the same bounded, transient-only retry as writes.
    """
    retry = retry or WeaviateWriteRetry.for_request()
    return retry.run(fetch, description="Weaviate read")


def sweep_other_generations(
    collection,
    unit_filter,
    run_id_property: str,
    current_run_id: str,
    context: str,
    *,
    retry: Optional[WeaviateWriteRetry] = None,
) -> int:
    """Delete every row of the unit that was not written by the current run.

    This is the second half of the write-new-then-sweep pattern: the new
    generation is inserted and verified first, then everything else — the
    previous generation, legacy rows without a run id, and half-written rows
    from crashed runs — is removed. Sweeping by fetched ids rather than a
    property inequality filter is what catches rows that carry no run id at
    all. A crash before the sweep leaves the old rows in place (briefly
    duplicated, never missing), and the next run's sweep removes them.

    The read and the deletes retry transient failures within the shared budget,
    so a momentary store condition during the sweep does not fail the run.
    Returns the number of swept rows; raises when the fetch hit its cap
    (silent truncation would leave stale rows undetected) or the delete
    failed for good.

    Concurrency fence: the sweep never deletes a row newer than this run's own
    oldest row. The process-local write locks serialize same-unit runs within one
    process, but two runs in different processes (multiple workers or replicas)
    could otherwise each delete the other's freshly written generation and leave
    the unit empty. Comparing against this run's earliest creation time means a
    concurrent later writer keeps its generation (the sweep degrades to
    last-writer-wins) instead of a mutual wipe. The fence only engages when
    Weaviate reports creation times, which it always does in production; without
    them (e.g. a unit test that does not stub metadata) it falls back to the plain
    "everything that is not mine" sweep.
    """
    retry = retry or WeaviateWriteRetry.for_request()
    rows = fetch_with_retry(
        lambda: collection.query.fetch_objects(
            filters=unit_filter,
            limit=_SWEEP_FETCH_LIMIT,
            return_properties=[run_id_property],
            return_metadata=MetadataQuery(creation_time=True),
        ),
        retry=retry,
    ).objects
    if len(rows) >= _SWEEP_FETCH_LIMIT:
        raise IngestionStageError(
            STALE_CONTENT_DELETE_FAILED,
            f"Generation sweep of {context} hit the fetch cap of "
            f"{_SWEEP_FETCH_LIMIT} rows; refusing to certify a possibly "
            f"partial sweep",
        )

    stale_ids = stale_generation_ids(
        rows, lambda row: row.properties.get(run_id_property) == current_run_id
    )
    for start in range(0, len(stale_ids), _SWEEP_DELETE_BATCH):
        end = start + _SWEEP_DELETE_BATCH
        batch_ids = stale_ids[start:end]
        delete_many_with_retry(
            collection, Filter.by_id().contains_any(batch_ids), context, retry=retry
        )
    if stale_ids:
        logger.info(
            "Swept %d stale row(s) of other generations while writing %s",
            len(stale_ids),
            context,
        )
    return len(stale_ids)


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
