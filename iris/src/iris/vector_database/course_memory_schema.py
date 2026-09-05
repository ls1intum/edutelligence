from enum import Enum
from typing import List

from weaviate import WeaviateClient
from weaviate.classes.config import Property
from weaviate.collections import Collection
from weaviate.collections.classes.config import (
    Configure,
    DataType,
    VectorDistances,
)

from iris.common.logging_config import get_logger

logger = get_logger(__name__)


class CourseMemorySchema(Enum):
    """
    Schema for the course memory.

    Stores verified Q/A pairs mined from Artemis public communication channels.
    Only ``question`` is searchable (BM25) and carries the dense vector supplied at
    insert time; all other properties are payload/metadata used for the answer,
    course scoping, deduplication, backlinking and operation ordering.
    """

    COLLECTION_NAME = "CourseMemory"
    QUESTION = "question"
    ANSWER = "answer"
    COURSE_ID = "course_id"
    POST_ID = "post_id"
    MESSAGE_ID = "message_id"
    CONVERSATION_ID = "conversation_id"
    SOURCE = "source"
    VERIFIED_AT = "verified_at"
    VERIFIED_BY = "verified_by"
    # Monotonic Artemis operation version of the write that produced the object. An
    # ingestion or retraction carrying an older version than the stored one is stale
    # and ignored, so out-of-order webhooks cannot resurrect or overwrite newer state.
    VERSION = "version"
    # Tombstone flag. A retracted thread keeps its object with deleted=True and its
    # version, so a stale ingestion finds it and gives up; retrieval filters them out.
    DELETED = "deleted"


# Defaults written to objects that predate a property, so a filter on that property
# still sees them. A legacy entry counts as version 0 (anything Artemis sends is newer)
# and as live.
_BACKFILL_DEFAULTS = {
    CourseMemorySchema.VERSION.value: 0,
    CourseMemorySchema.DELETED.value: False,
}

# Collections already checked for missing properties in this process. The check costs a
# schema round-trip, and every pipeline and retriever constructor calls init, so it is
# done once per process rather than once per request.
_MIGRATION_CHECKED: set = set()


def _property_definitions() -> List[Property]:
    """The collection's properties, shared by creation and by the migration of an
    existing collection so both cannot drift apart."""
    return [
        Property(
            name=CourseMemorySchema.QUESTION.value,
            description="The student question; embedded as the search vector and BM25-indexed",
            data_type=DataType.TEXT,
        ),
        Property(
            name=CourseMemorySchema.ANSWER.value,
            description="The verified answer; retrieved payload, not searched",
            data_type=DataType.TEXT,
            index_searchable=False,
        ),
        Property(
            name=CourseMemorySchema.COURSE_ID.value,
            description="The ID of the course; scopes all searches",
            data_type=DataType.INT,
            # index_searchable applies only to text/text[]; INT uses the
            # default filterable index (course_id is a filter, not searched).
        ),
        Property(
            name=CourseMemorySchema.POST_ID.value,
            description="The originating thread's root post ID; the upsert/dedup key and the backlink target",
            data_type=DataType.TEXT,
            index_searchable=False,
        ),
        Property(
            name=CourseMemorySchema.MESSAGE_ID.value,
            description="The answer message that most recently updated this entry; provenance only",
            data_type=DataType.TEXT,
            index_searchable=False,
        ),
        Property(
            name=CourseMemorySchema.CONVERSATION_ID.value,
            description="The channel the thread lives in; used for backlinking",
            data_type=DataType.TEXT,
            index_searchable=False,
        ),
        Property(
            name=CourseMemorySchema.SOURCE.value,
            description="Origin of the entry: IRIS_AUTO, TUTOR_WRITTEN, IRIS_CORRECTED, THREAD_RESOLVED",
            data_type=DataType.TEXT,
            index_searchable=False,
        ),
        Property(
            name=CourseMemorySchema.VERIFIED_AT.value,
            description="Timestamp of verification",
            data_type=DataType.TEXT,
            index_searchable=False,
        ),
        Property(
            name=CourseMemorySchema.VERIFIED_BY.value,
            description="Identifier of the tutor who verified the entry",
            data_type=DataType.TEXT,
            index_searchable=False,
        ),
        Property(
            name=CourseMemorySchema.VERSION.value,
            description="Monotonic Artemis operation version; older operations on the same thread are ignored",
            data_type=DataType.INT,
        ),
        Property(
            name=CourseMemorySchema.DELETED.value,
            description="Tombstone flag: the thread's entry was retracted and only its version is kept",
            data_type=DataType.BOOL,
        ),
    ]


def init_course_memory_schema(client: WeaviateClient) -> Collection:
    """
    Initialize the schema for the course memory.

    An existing collection is brought up to date in place: properties added since it
    was created are appended and backfilled, so an instance that stored entries before
    ``version``/``deleted`` existed keeps them retrievable without a collection reset.
    """
    name = CourseMemorySchema.COLLECTION_NAME.value
    if client.collections.exists(name):
        collection = client.collections.get(name)
        if name not in _MIGRATION_CHECKED:
            _add_missing_properties(collection)
            _MIGRATION_CHECKED.add(name)
        return collection

    return client.collections.create(
        name=name,
        vector_config=Configure.Vectors.self_provided(
            vector_index_config=Configure.VectorIndex.hnsw(
                distance_metric=VectorDistances.COSINE
            ),
        ),
        properties=_property_definitions(),
    )


def _add_missing_properties(collection: Collection) -> None:
    """Append properties the collection was created without, then backfill them.

    Weaviate allows adding properties to a collection but not altering existing ones,
    so this is the whole of the supported in-place migration. Objects written before
    a property existed carry ``null`` for it, which an equality filter does not match —
    a ``deleted == False`` filter would silently hide every legacy entry — hence the
    backfill. Failures are logged rather than raised: a migration hiccup must not take
    ingestion and retrieval down with it, and the check runs again on the next start.
    """
    try:
        existing = {prop.name for prop in collection.config.get().properties}
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not read the CourseMemory schema for migration: %s", e)
        return
    missing = [prop for prop in _property_definitions() if prop.name not in existing]
    if not missing:
        return
    try:
        for prop in missing:
            collection.config.add_property(prop)
        logger.info(
            "Added missing CourseMemory properties: %s",
            ", ".join(prop.name for prop in missing),
        )
        _backfill(collection, [prop.name for prop in missing])
    except Exception as e:  # noqa: BLE001
        logger.error("CourseMemory schema migration failed: %s", e, exc_info=True)


def _backfill(collection: Collection, property_names: List[str]) -> None:
    """Write the default for each newly added property onto every object lacking it."""
    updates = {
        name: _BACKFILL_DEFAULTS[name]
        for name in property_names
        if name in _BACKFILL_DEFAULTS
    }
    if not updates:
        return
    backfilled = 0
    for obj in collection.iterator(return_properties=list(updates)):
        patch = {
            name: value
            for name, value in updates.items()
            if obj.properties.get(name) is None
        }
        if not patch:
            continue
        collection.data.update(uuid=obj.uuid, properties=patch)
        backfilled += 1
    logger.info("Backfilled %s CourseMemory objects with %s", backfilled, updates)
