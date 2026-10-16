"""Fill ``base_url_exact`` on lecture rows written before it existed, then switch the filters to it.

At schema setup, :func:`prepare_exact_filters` checks each lecture collection: the exact property must use
field tokenization (auto-schema could have created it with word tokenization from a write that raced the
setup), and a collection whose description carries the marker switches to exact filters right away. Then
:func:`start_backfill` runs one pass in the background on every startup, so rows written by an older Pyris
in between (after a rollback, or by another Pyris sharing the Weaviate) get the value too. The pass copies
``base_url`` into ``base_url_exact`` with partial updates, which keep the vector. When a pass finishes
without errors and no two stored spellings differ only in case or a trailing slash, the collection gets the
marker and its filters switch to the exact property. Run only one Pyris against a shared Weaviate during the
upgrade; the pass itself is idempotent.
"""

import threading
from collections import Counter

from weaviate import WeaviateClient
from weaviate.classes.config import Tokenization
from weaviate.exceptions import UnexpectedStatusCodeError

from iris.common.logging_config import get_logger

from .instance_filter import mark_exact
from .lecture_transcription_schema import LectureTranscriptionSchema
from .lecture_unit_page_chunk_schema import LectureUnitPageChunkSchema
from .lecture_unit_schema import LectureUnitSchema
from .lecture_unit_segment_schema import LectureUnitSegmentSchema
from .schema_properties import BASE_URL_EXACT, BASE_URL_EXACT_MARKER

logger = get_logger(__name__)

LECTURE_SCHEMAS = (
    LectureUnitPageChunkSchema,
    LectureTranscriptionSchema,
    LectureUnitSegmentSchema,
    LectureUnitSchema,
)

_started = False
_start_lock = threading.Lock()


def prepare_exact_filters(client: WeaviateClient) -> list:
    """Check every lecture collection and switch the ones already marked to exact filters.

    :return: the schemas whose exact property uses field tokenization, which the backfill may fill
    """
    return prepare_exact_filters_for(client, LECTURE_SCHEMAS)


def prepare_exact_filters_for(client: WeaviateClient, schemas) -> list:
    """:func:`prepare_exact_filters` for the given lecture collection schemas."""
    eligible = []
    for schema in schemas:
        name = schema.COLLECTION_NAME.value
        config = client.collections.get(name).config.get()
        exact_property = next(
            (prop for prop in config.properties if prop.name == BASE_URL_EXACT), None
        )
        if exact_property is None or exact_property.tokenization != Tokenization.FIELD:
            logger.error(
                "%s.%s is missing or not field-tokenized (%s); its base URL filters stay on the word-tokenized "
                "base_url, which can match another Artemis instance whose URL contains the same words",
                name,
                BASE_URL_EXACT,
                exact_property.tokenization if exact_property else "missing",
            )
            continue
        if config.description == BASE_URL_EXACT_MARKER:
            mark_exact(name)
        eligible.append(schema)
    return eligible


def start_backfill(client: WeaviateClient, schemas: list) -> None:
    """Run one backfill pass over the given collections in a daemon thread, once per process."""
    global _started  # pylint: disable=global-statement
    with _start_lock:
        if _started or not schemas:
            return
        _started = True
    threading.Thread(
        target=backfill_all,
        args=(client, schemas),
        name="base-url-exact-backfill",
        daemon=True,
    ).start()


def backfill_all(client: WeaviateClient, schemas: list) -> None:
    """Backfill each collection, isolating failures so one collection never stops the others."""
    for schema in schemas:
        try:
            backfill_collection(client, schema)
        except Exception:
            logger.warning(
                "Backfill of %s failed; its base URL filters stay as they are until the next start",
                schema.COLLECTION_NAME.value,
                exc_info=True,
            )


def backfill_collection(client: WeaviateClient, schema) -> bool:
    """Copy base_url into base_url_exact for every row that lacks it, then mark the collection if it is safe.

    :return: whether the collection's filters use the exact property afterwards
    """
    name = schema.COLLECTION_NAME.value
    collection = client.collections.get(name)
    base_url_property = schema.BASE_URL.value
    spellings: Counter = Counter()
    updated = 0
    failed = 0
    for row in collection.iterator(
        return_properties=[base_url_property, BASE_URL_EXACT]
    ):
        base_url = row.properties.get(base_url_property)
        if not base_url:
            continue
        spellings[base_url] += 1
        if row.properties.get(BASE_URL_EXACT) == base_url:
            continue
        try:
            collection.data.update(uuid=row.uuid, properties={BASE_URL_EXACT: base_url})
            updated += 1
        except UnexpectedStatusCodeError as error:
            if error.status_code != 404:
                failed += 1
                logger.warning(
                    "Could not backfill row %s of %s: %s", row.uuid, name, error
                )
            # 404: the row was deleted meanwhile; nothing to fill
    logger.info(
        "Backfilled %s on %d row(s) of %s; base URLs found: %s",
        BASE_URL_EXACT,
        updated,
        name,
        dict(spellings),
    )
    if failed:
        logger.warning(
            "%d row(s) of %s could not be backfilled; trying again at the next start",
            failed,
            name,
        )
        return False
    collapsed = _collapsed_spellings(spellings)
    if collapsed:
        logger.warning(
            "%s holds base URLs that differ only in case or a trailing slash: %s. Exact filters would no longer "
            "match the rows of the other spelling, so its filters stay on the word-tokenized base_url",
            name,
            collapsed,
        )
        return False
    if collection.config.get().description != BASE_URL_EXACT_MARKER:
        collection.config.update(description=BASE_URL_EXACT_MARKER)
    mark_exact(name)
    return True


def _collapsed_spellings(spellings: Counter) -> dict:
    """Groups of stored base URLs (with row counts) that become one value when lowercased without a trailing slash."""
    groups: dict[str, dict[str, int]] = {}
    for base_url, count in spellings.items():
        groups.setdefault(base_url.lower().rstrip("/"), {})[base_url] = count
    return {key: values for key, values in groups.items() if len(values) > 1}
