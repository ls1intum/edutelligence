"""Verification of Weaviate batch and delete-many results.

The Weaviate batch context collects per-object insert errors instead of
raising them, and ``delete_many`` reports failures on its return value. A
pipeline that does not read those results can drop objects silently and still
report success. Every ingestion write path must call these helpers directly
after the write so a partial write becomes a failed run instead of a partial
unit.
"""

import uuid as uuid_module
from typing import Optional

from weaviate.classes.query import Filter

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


def _failed_object_payloads(failed) -> Optional[list]:
    """Reconstruct the ``(uuid, properties, vector)`` of each dropped object.

    The uuid is carried so a retry re-submits the object under the *same* id this
    run assigned it, keeping the caller's set of written ids exact. Returns
    ``None`` when the client did not carry the object (or its id) back, in which
    case a safe re-submit is impossible and the run must fail instead of retrying.
    """
    payloads = []
    for error_object in failed:
        carried = getattr(error_object, "object_", None)
        if carried is None:
            return None
        carried_uuid = getattr(carried, "uuid", None)
        if carried_uuid is None:
            return None
        payloads.append(
            (
                str(carried_uuid),
                getattr(carried, "properties", None),
                getattr(carried, "vector", None),
            )
        )
    return payloads


def _rate_limited_batch(collection):
    return collection.batch.rate_limit(requests_per_minute=600)


def write_batch_with_retry(
    collection,
    prepared,
    context: str,
    *,
    retry: Optional[WeaviateWriteRetry] = None,
    open_batch=_rate_limited_batch,
) -> list[str]:
    """Insert ``(properties, vector)`` pairs, retrying only what a transient drop lost.

    Every object is written under a client-assigned uuid, and the full list of
    those uuids is returned so the caller knows exactly what this run wrote —
    without a re-read (whose secondary indexes may be corrupt). That id set is
    what :func:`purge_other_rows` keeps while it removes everything else in the
    unit, so convergence never depends on the run-id index.

    The expensive work (vision, embeddings, summaries) is already done by the time
    a batch is written, so a transient store condition (read-only under resource
    pressure, a rate limit, a momentary overload) is recovered by re-submitting just
    the dropped objects — under their original ids — within the shared retry budget,
    never by re-running the pipeline. A non-transient drop, or one that outlasts the
    budget, fails the run with ``VECTOR_STORE_WRITE_FAILED``, exactly as an
    un-retried write would.

    ``open_batch`` selects the batching mode (rate-limited by default; callers with
    their own strategy, e.g. dynamic batching, pass their own).
    """
    retry = retry or WeaviateWriteRetry.for_request()
    pending = [
        (str(uuid_module.uuid4()), properties, vector)
        for properties, vector in prepared
    ]
    written_ids = [object_uuid for object_uuid, _, _ in pending]
    attempt = 0
    while True:
        attempt += 1
        with open_batch(collection) as batch:
            for object_uuid, properties, vector in pending:
                batch.add_object(uuid=object_uuid, properties=properties, vector=vector)
        failed = collection.batch.failed_objects
        if not failed:
            return written_ids
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


def confirmed_generations(
    collection,
    unit_filter,
    run_id_property: str,
    *,
    limit: int,
    sample_per_generation: int = 3,
    return_properties: Optional[list[str]] = None,
    retry: Optional[WeaviateWriteRetry] = None,
) -> tuple[set, list]:
    """Distinct *real* ingestion generations for a unit, excluding store ghosts.

    A raw ``fetch_objects`` scan still returns "object-store-only ghost" rows —
    rows left by an interrupted write that survive in a scan segment but have no
    record in the object store, so ``fetch_object_by_id`` returns ``None`` for
    them and retrieval can never surface them. Counting generations off the raw
    scan therefore over-counts: a healed unit with one real generation plus a few
    ghost run ids looks perpetually "dirty", and re-ingesting cannot remove the
    ghosts (no id or index entry to match), so a reconciler keyed on the raw count
    loops forever and convergence raises a false failure.

    This scans the unit, groups the scanned rows by run id, then confirms each
    generation against the object store: a generation is *real* only if at least
    one of its sampled rows is found by ``fetch_object_by_id``. It returns the set
    of real run ids and the full scanned object list, so a caller can both count
    generations and derive a ghost-free row count or page coverage by keeping only
    the objects whose run id is real. Sampling a few ids per generation tolerates a
    single flickering row without a per-row confirmation of the whole unit.
    """
    retry = retry or WeaviateWriteRetry.for_request()
    properties = [run_id_property]
    if return_properties:
        properties = list(dict.fromkeys([run_id_property, *return_properties]))
    objects = fetch_with_retry(
        lambda: collection.query.fetch_objects(
            filters=unit_filter,
            limit=limit,
            return_properties=properties,
        ),
        retry=retry,
    ).objects
    sample_ids_by_generation: dict = {}
    for stored_object in objects:
        generation = stored_object.properties.get(run_id_property)
        sample = sample_ids_by_generation.setdefault(generation, [])
        if len(sample) < sample_per_generation:
            sample.append(stored_object.uuid)
    real_generations: set = set()
    for generation, sample_ids in sample_ids_by_generation.items():
        for object_uuid in sample_ids:
            found = fetch_with_retry(
                lambda uid=object_uuid: collection.query.fetch_object_by_id(uid),
                retry=retry,
            )
            if found is not None:
                real_generations.add(generation)
                break
    return real_generations, objects


def purge_other_rows(
    collection,
    unit_filter,
    keep_uuids,
    context: str,
    *,
    retry: Optional[WeaviateWriteRetry] = None,
) -> int:
    """Delete every row of the unit except the ids this run just wrote.

    This is the second half of the write-new-then-purge pattern: the new
    generation is inserted and verified first, then everything else — previous
    generations, legacy rows, half-written rows from crashed runs, and
    index-only ghost rows left by store corruption — is removed. The delete
    matches by *unit identity* (always indexed) minus the current run's ids, so
    unlike a delete keyed on the run-id property or on a list of the *other*
    rows' ids, it still reaches rows whose run-id index entry or object-store
    backing was lost: a delete-by-id no-ops on a ghost (no object at that id),
    and a delete-by-run-id no-ops on it too (missing from the run-id index), but
    the unit-identity match removes it. Writing first and purging second keeps
    the unit from ever being empty on a crash — at worst two generations coexist
    briefly, and the next run's purge converges it.

    Trade-off: keeping "everything except my ids" drops the old run-id
    concurrency fence, so two writers hitting the same unit at once could delete
    each other's rows. Artemis's claim locking (SKIP LOCKED + the INGESTING
    state) makes concurrent same-unit runs a non-event in normal operation; the
    fence was insurance against a case the queue already prevents.

    Returns the number of rows deleted; raises when the delete failed for good.
    """
    retry = retry or WeaviateWriteRetry.for_request()
    keep = [str(object_uuid) for object_uuid in keep_uuids]
    if not keep:
        # The run wrote nothing to preserve; refuse to mass-delete the unit.
        # Leaving any existing rows in place is the fail-safe choice (the next
        # run converges) versus wiping the unit on an unexpected empty write.
        logger.warning(
            "Skipping purge of %s: this run wrote no rows to preserve", context
        )
        return 0
    result = delete_many_with_retry(
        collection,
        unit_filter & ~Filter.by_id().contains_any(keep),
        context,
        retry=retry,
    )
    if result.successful:
        logger.info(
            "Purged %d stale/ghost row(s) while writing %s",
            result.successful,
            context,
        )
    return result.successful


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
