from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import NAMESPACE_URL, uuid5

import pytest
from weaviate.collections.classes.config import DataType

from iris.vector_database import course_memory_schema as schema_module
from iris.vector_database import database as database_module
from iris.vector_database.course_memory_schema import (
    CourseMemorySchema,
    init_course_memory_schema,
)

# The migration memo and the property list are module internals; exercising them is the point.
# pylint: disable=protected-access


@pytest.fixture(autouse=True)
def _fresh_migration_state(monkeypatch):
    # The migration check is memoised per process; each test starts unchecked.
    monkeypatch.setattr(schema_module, "_MIGRATION_CHECKED", set())


def _props_by_name(create_kwargs):
    return {p.name: p for p in create_kwargs["properties"]}


def test_init_creates_collection_with_correct_index_flags():
    client = MagicMock()
    client.collections.exists.return_value = False

    init_course_memory_schema(client)

    client.collections.create.assert_called_once()
    kwargs = client.collections.create.call_args.kwargs
    assert kwargs["name"] == CourseMemorySchema.COLLECTION_NAME.value

    props = _props_by_name(kwargs)

    # Only `question` is BM25-searchable (indexSearchable defaults to True).
    question = props[CourseMemorySchema.QUESTION.value]
    assert question.dataType == DataType.TEXT
    assert question.indexSearchable is not False

    # All other properties are non-searchable payload/metadata.
    for name in (
        CourseMemorySchema.ANSWER.value,
        CourseMemorySchema.POST_ID.value,
        CourseMemorySchema.MESSAGE_ID.value,
        CourseMemorySchema.CONVERSATION_ID.value,
        CourseMemorySchema.SOURCE.value,
        CourseMemorySchema.VERIFIED_AT.value,
        CourseMemorySchema.VERIFIED_BY.value,
    ):
        assert props[name].indexSearchable is False

    assert props[CourseMemorySchema.COURSE_ID.value].dataType == DataType.INT


def test_schema_carries_the_ordering_properties():
    # version orders every write of a thread; deleted marks a retracted thread's
    # tombstone. Both are filtered/compared, never searched.
    client = MagicMock()
    client.collections.exists.return_value = False

    init_course_memory_schema(client)

    props = _props_by_name(client.collections.create.call_args.kwargs)
    assert props[CourseMemorySchema.VERSION.value].dataType == DataType.INT
    assert props[CourseMemorySchema.DELETED.value].dataType == DataType.BOOL


def _existing_collection(client, property_names, objects=()):
    client.collections.exists.return_value = True
    collection = client.collections.get.return_value
    collection.config.get.return_value = SimpleNamespace(
        properties=[SimpleNamespace(name=name) for name in property_names]
    )
    collection.iterator.return_value = list(objects)
    return collection


def _all_property_names():
    return [prop.name for prop in schema_module._property_definitions()]


def test_init_is_idempotent_when_collection_exists():
    client = MagicMock()
    _existing_collection(client, _all_property_names())

    init_course_memory_schema(client)

    client.collections.create.assert_not_called()
    client.collections.get.assert_called_once_with(
        CourseMemorySchema.COLLECTION_NAME.value
    )


def test_up_to_date_collection_is_not_migrated():
    client = MagicMock()
    collection = _existing_collection(client, _all_property_names())

    init_course_memory_schema(client)

    collection.config.add_property.assert_not_called()
    collection.data.update.assert_not_called()


def _uuid(key):
    # Real UUIDs: the deletion filter is built with Filter.by_id().contains_any.
    return str(uuid5(NAMESPACE_URL, key))


def _with_deletable_objects(collection, objects):
    """Let the collection's cursor see ``objects`` and delete_many remove them."""
    store = list(objects)

    def iterator(return_properties=None):
        del return_properties
        return iter(list(store))

    def delete_many(where):
        del where
        # The production code deletes the batch it collected: at most one batch of
        # objects without an instance per call.
        removed = [obj for obj in store if not obj.properties.get("base_url")][
            : schema_module._LEGACY_DELETE_BATCH
        ]
        for obj in removed:
            store.remove(obj)
        return SimpleNamespace(failed=0, successful=len(removed))

    collection.iterator.side_effect = iterator
    collection.data.delete_many.side_effect = delete_many
    return store


def test_missing_properties_are_added():
    client = MagicMock()
    names_before_isolation = [
        name
        for name in _all_property_names()
        if name
        not in (CourseMemorySchema.BASE_URL.value, CourseMemorySchema.WRITTEN_AT.value)
    ]
    collection = _existing_collection(client, names_before_isolation)

    init_course_memory_schema(client)

    added = [
        call.args[0].name for call in collection.config.add_property.call_args_list
    ]
    assert sorted(added) == sorted(
        [CourseMemorySchema.BASE_URL.value, CourseMemorySchema.WRITTEN_AT.value]
    )


def test_objects_without_an_instance_are_deleted_and_isolated_ones_kept():
    """Objects written before instance isolation belong to no known Artemis: no filter
    can serve them and no retraction can address them. They are removed; objects
    that carry their instance are left alone."""
    client = MagicMock()
    collection = _existing_collection(client, _all_property_names())
    legacy = [
        SimpleNamespace(uuid=_uuid(f"legacy-{i}"), properties={}) for i in range(2500)
    ]
    kept = SimpleNamespace(
        uuid=_uuid("kept"), properties={"base_url": "https://a.example"}
    )
    store = _with_deletable_objects(collection, legacy + [kept])

    init_course_memory_schema(client)

    assert store == [kept]
    # More than one pass: the deletion is bounded per call.
    assert collection.data.delete_many.call_count >= 3


def test_failed_cleanup_raises_and_is_retried_by_the_next_init():
    client = MagicMock()
    collection = _existing_collection(client, _all_property_names())
    store = _with_deletable_objects(
        collection, [SimpleNamespace(uuid=_uuid("legacy"), properties={})]
    )
    collection.data.delete_many.side_effect = [SimpleNamespace(failed=1)]

    with pytest.raises(RuntimeError):
        init_course_memory_schema(client)

    # Not recorded as done: the next initialisation tries again and succeeds.
    _with_deletable_objects(collection, store)
    init_course_memory_schema(client)
    assert collection.config.get.call_count == 2


def test_new_collection_scopes_the_instance_exactly():
    client = MagicMock()
    client.collections.exists.return_value = False

    init_course_memory_schema(client)

    props = _props_by_name(client.collections.create.call_args.kwargs)
    base_url = props[CourseMemorySchema.BASE_URL.value]
    assert base_url.tokenization.value == "field"
    assert props[CourseMemorySchema.WRITTEN_AT.value].dataType == DataType.DATE


def test_migration_runs_once_per_process():
    client = MagicMock()
    collection = _existing_collection(client, _all_property_names())

    init_course_memory_schema(client)
    init_course_memory_schema(client)

    # The schema round-trip is paid once, not on every pipeline construction.
    collection.config.get.assert_called_once()


def test_vector_database_retries_after_a_failed_initialisation(monkeypatch):
    """A failed schema init must not leave a client without collections behind.

    The client is published only after every schema initialised; otherwise every
    later construction would skip initialisation and fail on missing collections.
    """
    clients = []

    def connect(**_kwargs):
        client = MagicMock()
        clients.append(client)
        return client

    calls = {"count": 0}

    def flaky_course_memory_init(client):
        del client
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("weaviate busy")
        return MagicMock(name="course_memory")

    monkeypatch.setattr(database_module.weaviate, "connect_to_custom", connect)
    monkeypatch.setattr(
        database_module, "init_course_memory_schema", flaky_course_memory_init
    )
    for name in (
        "init_lecture_unit_page_chunk_schema",
        "init_lecture_transcription_schema",
        "init_lecture_unit_segment_schema",
        "init_lecture_unit_schema",
        "init_faq_schema",
    ):
        monkeypatch.setattr(database_module, name, lambda client: MagicMock())
    monkeypatch.setattr(database_module.VectorDatabase, "static_client_instance", None)
    monkeypatch.setattr(database_module.VectorDatabase, "_static_collections", {})

    with pytest.raises(RuntimeError):
        database_module.VectorDatabase()
    assert database_module.VectorDatabase.static_client_instance is None
    clients[0].close.assert_called_once()

    db = database_module.VectorDatabase()
    assert db.client is clients[1]
    assert db.course_memory is not None
