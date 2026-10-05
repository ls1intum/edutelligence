import threading
from enum import Enum
from typing import List

from weaviate import WeaviateClient
from weaviate.classes.config import Property, Tokenization
from weaviate.classes.query import Filter
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
    # No longer written or read: Course Memory stores no user identity. Weaviate cannot
    # drop a property, so collections created earlier keep the (empty) definition.
    VERIFIED_BY = "verified_by"
    # Monotonic Artemis operation version of the write that produced the object. An
    # ingestion or retraction carrying an older version than the stored one is stale
    # and ignored, so out-of-order webhooks cannot resurrect or overwrite newer state.
    VERSION = "version"
    # Tombstone flag. A retracted thread keeps its object with deleted=True and its
    # version, so a stale ingestion finds it and gives up; retrieval filters them out.
    DELETED = "deleted"
    # Canonical URL of the Artemis instance the entry belongs to (see
    # ``canonical_artemis_base_url``). Several instances may share this collection and
    # their course and post ids overlap, so every read, write and deletion is scoped by it.
    BASE_URL = "base_url"
    # When Iris wrote the object. The nightly sync skips objects written after the
    # snapshot Artemis based its list on, so it never retracts a thread that was
    # resolved for the first time while the sync was running.
    WRITTEN_AT = "written_at"


# Collections already migrated in this process. The check costs a schema round-trip and
# every pipeline and retriever constructor calls init, so it is done once per process.
# Only recorded after the migration succeeded, so a failure is retried on the next init.
_MIGRATION_CHECKED: set = set()

# Serialises initialisation, so two threads cannot both run the migration.
_migration_lock = threading.Lock()

# Objects fetched per pass when removing objects that predate instance isolation.
_LEGACY_DELETE_BATCH = 1000


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
        Property(
            name=CourseMemorySchema.BASE_URL.value,
            description="Canonical base URL of the Artemis instance; scopes every read, write and deletion",
            data_type=DataType.TEXT,
            # Whole-string equality: word tokenization would let two URLs that share
            # tokens match each other.
            tokenization=Tokenization.FIELD,
            index_searchable=False,
        ),
        Property(
            name=CourseMemorySchema.WRITTEN_AT.value,
            description="When Iris wrote the object; the nightly sync skips objects newer than its snapshot",
            data_type=DataType.DATE,
        ),
    ]


def init_course_memory_schema(client: WeaviateClient) -> Collection:
    """
    Initialize the schema for the course memory.

    An existing collection is migrated in place (see :func:`_migrate`). A failed
    migration raises: serving entries that cannot be scoped to an Artemis instance would
    be worse than not serving Course Memory, and because nothing is recorded as done,
    the next initialisation retries it.
    """
    name = CourseMemorySchema.COLLECTION_NAME.value
    with _migration_lock:
        if client.collections.exists(name):
            collection = client.collections.get(name)
            if name not in _MIGRATION_CHECKED:
                _migrate(collection)
                _MIGRATION_CHECKED.add(name)
            return collection

        collection = client.collections.create(
            name=name,
            vector_config=Configure.Vectors.self_provided(
                vector_index_config=Configure.VectorIndex.hnsw(
                    distance_metric=VectorDistances.COSINE
                ),
            ),
            properties=_property_definitions(),
        )
        _MIGRATION_CHECKED.add(name)
        return collection


def _migrate(collection: Collection) -> None:
    """Bring an existing collection up to the current schema.

    Weaviate allows adding properties but not altering existing ones, so the migration
    appends what is missing. Objects written before ``base_url`` existed belong to no
    known Artemis instance: no filter can ever serve them and no retraction can address
    them, so they are deleted. Only test deployments ever held such objects, since Course
    Memory was not released before instance isolation.
    """
    existing = {prop.name for prop in collection.config.get().properties}
    for prop in _property_definitions():
        if prop.name not in existing:
            collection.config.add_property(prop)
            logger.info("Added missing CourseMemory property: %s", prop.name)
    _delete_objects_without_instance(collection)


def _delete_objects_without_instance(collection: Collection) -> None:
    """Delete every object without a ``base_url``, until a full pass finds none.

    Deletes by id in bounded batches rather than with one filtered ``delete_many``:
    Weaviate caps the objects one deletion query removes, and an unindexed null cannot
    be filtered on. Any failed deletion raises, so the migration is retried later
    instead of being recorded as done.
    """
    removed = 0
    while True:
        batch = []
        for obj in collection.iterator(
            return_properties=[CourseMemorySchema.BASE_URL.value]
        ):
            if not obj.properties.get(CourseMemorySchema.BASE_URL.value):
                batch.append(obj.uuid)
                if len(batch) >= _LEGACY_DELETE_BATCH:
                    break
        if not batch:
            break
        result = collection.data.delete_many(where=Filter.by_id().contains_any(batch))
        failed = getattr(result, "failed", 0) or 0
        if failed:
            raise RuntimeError(
                f"Could not delete {failed} CourseMemory objects without base_url"
            )
        removed += len(batch)
    if removed:
        logger.info(
            "Deleted %s CourseMemory objects that predate instance isolation", removed
        )
