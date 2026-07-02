from unittest.mock import MagicMock

from weaviate.collections.classes.config import DataType

from iris.vector_database.course_memory_schema import (
    CourseMemorySchema,
    init_course_memory_schema,
)


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
        CourseMemorySchema.MESSAGE_ID.value,
        CourseMemorySchema.CONVERSATION_ID.value,
        CourseMemorySchema.SOURCE.value,
        CourseMemorySchema.VERIFIED_AT.value,
        CourseMemorySchema.VERIFIED_BY.value,
    ):
        assert props[name].indexSearchable is False

    assert props[CourseMemorySchema.COURSE_ID.value].dataType == DataType.INT


def test_init_is_idempotent_when_collection_exists():
    client = MagicMock()
    client.collections.exists.return_value = True

    init_course_memory_schema(client)

    client.collections.create.assert_not_called()
    client.collections.get.assert_called_once_with(
        CourseMemorySchema.COLLECTION_NAME.value
    )
