"""Exact base URL filters and their backfill against a real Weaviate.

Runs only when ``IRIS_TEST_WEAVIATE_URL`` names a disposable Weaviate (``http://host:http_port``, gRPC port in
``IRIS_TEST_WEAVIATE_GRPC_PORT``, default 50051); CI has none, so it is skipped there.
"""

import os
import uuid
from urllib.parse import urlparse

import pytest
from weaviate.classes.config import Configure, DataType, Property, Tokenization
from weaviate.classes.query import Filter

from iris.vector_database import base_url_exact_backfill as backfill
from iris.vector_database import instance_filter
from iris.vector_database.lecture_unit_page_chunk_schema import (
    LectureUnitPageChunkSchema,
    init_lecture_unit_page_chunk_schema,
)
from iris.vector_database.schema_properties import BASE_URL_EXACT_MARKER

WEAVIATE_URL = os.environ.get("IRIS_TEST_WEAVIATE_URL")

pytestmark = pytest.mark.skipif(
    not WEAVIATE_URL, reason="needs a disposable Weaviate in IRIS_TEST_WEAVIATE_URL"
)

SHORT = "https://artemis.example"
LONG = "https://artemis-test.artemis.example"
NAME = LectureUnitPageChunkSchema.COLLECTION_NAME.value


@pytest.fixture
def client(monkeypatch):
    import weaviate  # pylint: disable=import-outside-toplevel

    monkeypatch.setattr(instance_filter, "_exact_collections", set())
    url = urlparse(WEAVIATE_URL)
    weaviate_client = weaviate.connect_to_local(
        host=url.hostname,
        port=url.port,
        grpc_port=int(os.environ.get("IRIS_TEST_WEAVIATE_GRPC_PORT", "50051")),
    )
    weaviate_client.collections.delete(NAME)
    yield weaviate_client
    weaviate_client.collections.delete(NAME)
    weaviate_client.close()


def _old_collection(client):
    """A page chunk collection as an older Pyris created it: word-tokenized base_url, no exact property."""
    return client.collections.create(
        name=NAME,
        vector_config=Configure.Vectors.self_provided(),
        properties=[
            Property(name="course_id", data_type=DataType.INT),
            Property(name="lecture_unit_id", data_type=DataType.INT),
            Property(name="base_url", data_type=DataType.TEXT, index_searchable=False),
            Property(name="hidden_until", data_type=DataType.DATE),
        ],
    )


def _matches(collection, base_url):
    return len(
        collection.query.fetch_objects(
            filters=instance_filter.artemis_instance_filter(
                LectureUnitPageChunkSchema, base_url
            )
            & Filter.by_property("course_id").equal(7)
        ).objects
    )


def test_old_collection_is_backfilled_and_then_filtered_exactly(client):
    old = _old_collection(client)
    ids = {}
    for index, base_url in enumerate([SHORT, LONG]):
        ids[base_url] = uuid.uuid4()
        old.data.insert(
            properties={
                "course_id": 7,
                "lecture_unit_id": 1,
                "base_url": base_url,
                "hidden_until": None,
            },
            vector=[0.1 * (index + 1), 0.2, 0.3],
            uuid=ids[base_url],
        )

    collection = init_lecture_unit_page_chunk_schema(client)
    eligible = backfill.prepare_exact_filters_for(client, [LectureUnitPageChunkSchema])
    assert eligible == [LectureUnitPageChunkSchema]
    # Until the backfill has finished, the filter stays as loose as before
    assert _matches(collection, SHORT) == 2

    assert backfill.backfill_collection(client, LectureUnitPageChunkSchema)

    assert collection.config.get().description == BASE_URL_EXACT_MARKER
    assert _matches(collection, SHORT) == 1
    assert _matches(collection, LONG) == 1
    stored = collection.query.fetch_object_by_id(ids[LONG], include_vector=True)
    assert stored.properties["base_url"] == LONG
    assert stored.vector["default"][0] == pytest.approx(0.2)

    # A restart switches the marked collection to exact filters right away
    instance_filter._exact_collections.clear()  # pylint: disable=protected-access
    backfill.prepare_exact_filters_for(client, [LectureUnitPageChunkSchema])
    assert instance_filter.is_exact(NAME)


def test_a_row_written_by_an_older_pyris_after_the_marker_is_filled_by_the_next_pass(
    client,
):
    collection = init_lecture_unit_page_chunk_schema(client)
    # A fresh collection is created with the marker, since every row it gets carries the exact value
    assert collection.config.get().description == BASE_URL_EXACT_MARKER
    late = uuid.uuid4()
    collection.data.insert(
        properties={"course_id": 7, "lecture_unit_id": 1, "base_url": SHORT},
        vector=[0.1, 0.2, 0.3],
        uuid=late,
    )
    backfill.prepare_exact_filters_for(client, [LectureUnitPageChunkSchema])
    assert _matches(collection, SHORT) == 0

    backfill.backfill_collection(client, LectureUnitPageChunkSchema)

    assert _matches(collection, SHORT) == 1


def test_an_exact_property_created_with_word_tokenization_is_never_used(client):
    old = _old_collection(client)
    old.config.add_property(
        Property(
            name="base_url_exact",
            data_type=DataType.TEXT,
            tokenization=Tokenization.WORD,
        )
    )
    init_lecture_unit_page_chunk_schema(client)

    assert not backfill.prepare_exact_filters_for(client, [LectureUnitPageChunkSchema])
    assert not instance_filter.is_exact(NAME)


def test_updating_a_deleted_row_raises_a_404(client):
    collection = init_lecture_unit_page_chunk_schema(client)
    with pytest.raises(Exception) as error:
        collection.data.update(uuid=uuid.uuid4(), properties={"base_url_exact": SHORT})
    assert getattr(error.value, "status_code", None) == 404, repr(error.value)
