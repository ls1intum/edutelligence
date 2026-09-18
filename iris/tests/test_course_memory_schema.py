from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from weaviate.collections.classes.config import DataType

from iris.vector_database import course_memory_schema as schema_module
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


def test_missing_properties_are_added_and_backfilled():
    """A collection created before version/deleted existed is migrated in place.

    Objects written back then carry null for the new properties, and an equality
    filter does not match null — a `deleted == False` filter would silently hide
    every legacy entry. The backfill is what keeps them retrievable without a
    collection reset.
    """
    client = MagicMock()
    legacy_names = [
        name
        for name in _all_property_names()
        if name
        not in (CourseMemorySchema.VERSION.value, CourseMemorySchema.DELETED.value)
    ]
    legacy_object = SimpleNamespace(uuid="u-legacy", properties={})
    collection = _existing_collection(client, legacy_names, [legacy_object])

    init_course_memory_schema(client)

    added = [
        call.args[0].name for call in collection.config.add_property.call_args_list
    ]
    assert sorted(added) == sorted(
        [CourseMemorySchema.VERSION.value, CourseMemorySchema.DELETED.value]
    )
    collection.data.update.assert_called_once_with(
        uuid="u-legacy",
        properties={
            CourseMemorySchema.VERSION.value: 0,
            CourseMemorySchema.DELETED.value: False,
        },
    )


def test_backfill_leaves_objects_that_already_carry_the_property_alone():
    client = MagicMock()
    legacy_names = [
        name
        for name in _all_property_names()
        if name != CourseMemorySchema.DELETED.value
    ]
    already_set = SimpleNamespace(
        uuid="u-set", properties={CourseMemorySchema.DELETED.value: False}
    )
    collection = _existing_collection(client, legacy_names, [already_set])

    init_course_memory_schema(client)

    collection.data.update.assert_not_called()


def test_migration_runs_once_per_process():
    client = MagicMock()
    collection = _existing_collection(client, _all_property_names())

    init_course_memory_schema(client)
    init_course_memory_schema(client)

    # The schema round-trip is paid once, not on every pipeline construction.
    collection.config.get.assert_called_once()


def test_migration_failure_does_not_break_initialisation():
    client = MagicMock()
    collection = _existing_collection(client, [])
    collection.config.add_property.side_effect = RuntimeError("schema locked")

    result = init_course_memory_schema(client)

    assert result is collection
