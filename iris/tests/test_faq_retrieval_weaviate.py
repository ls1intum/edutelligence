"""FAQ retrieval and the FAQ tool gate against a real Weaviate, per Artemis instance.

Runs only when ``IRIS_TEST_WEAVIATE_URL`` names a disposable Weaviate (``http://host:http_port``
with the gRPC port in ``IRIS_TEST_WEAVIATE_GRPC_PORT``, default 50051); CI has none, so it is
skipped there. It checks what the mocked tests cannot: the instance filter on a field-tokenized and
on a word-tokenized base_url, and paging with offset in hybrid and plain queries.
"""

import os
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock
from urllib.parse import urlparse

import pytest

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.retrieval.faq_retrieval import FaqRetrieval  # noqa: E402
from iris.retrieval.faq_retrieval_utils import (
    faq_instance_filter,
    fetch_owned_faqs,
    should_allow_faq_tool,
)
from iris.vector_database.faq_schema import FaqSchema, init_faq_schema

WEAVIATE_URL = os.environ.get("IRIS_TEST_WEAVIATE_URL")

pytestmark = pytest.mark.skipif(
    not WEAVIATE_URL, reason="needs a disposable Weaviate in IRIS_TEST_WEAVIATE_URL"
)

OWN = "https://artemis.example"
# Contains every word of OWN, so a word-tokenized equality filter on OWN matches it too
LONGER = "https://artemis-test.artemis.example"
QUERY_VECTOR = [1.0, 0.0, 0.0]


@pytest.fixture
def client():
    import weaviate  # pylint: disable=import-outside-toplevel

    url = urlparse(WEAVIATE_URL)
    weaviate_client = weaviate.connect_to_local(
        host=url.hostname,
        port=url.port,
        grpc_port=int(os.environ.get("IRIS_TEST_WEAVIATE_GRPC_PORT", "50051")),
    )
    weaviate_client.collections.delete(FaqSchema.COLLECTION_NAME.value)
    yield weaviate_client
    weaviate_client.collections.delete(FaqSchema.COLLECTION_NAME.value)
    weaviate_client.close()


def _word_tokenized_collection(client):
    """A collection whose base_url auto-schema created with word tokenization."""
    from weaviate.classes.config import (  # pylint: disable=import-outside-toplevel
        Configure,
        DataType,
        Property,
        Tokenization,
    )

    client.collections.create(
        name=FaqSchema.COLLECTION_NAME.value,
        vector_config=Configure.Vectors.self_provided(),
        properties=[
            Property(name=FaqSchema.FAQ_ID.value, data_type=DataType.INT),
            Property(name=FaqSchema.COURSE_ID.value, data_type=DataType.INT),
            Property(name=FaqSchema.QUESTION_TITLE.value, data_type=DataType.TEXT),
            Property(name=FaqSchema.QUESTION_ANSWER.value, data_type=DataType.TEXT),
            Property(
                name=FaqSchema.BASE_URL.value,
                data_type=DataType.TEXT,
                tokenization=Tokenization.WORD,
            ),
        ],
    )
    collection = init_faq_schema(client)
    base_url = next(
        prop
        for prop in collection.config.get().properties
        if prop.name == FaqSchema.BASE_URL.value
    )
    assert base_url.tokenization == Tokenization.WORD
    return collection


def _insert(collection, number, base_url, title, vector, course_id=7):
    properties = {
        FaqSchema.FAQ_ID.value: number,
        FaqSchema.COURSE_ID.value: course_id,
        FaqSchema.QUESTION_TITLE.value: title,
        FaqSchema.QUESTION_ANSWER.value: "answer",
    }
    if base_url is not None:
        properties[FaqSchema.BASE_URL.value] = base_url
    # Ascending ids, so a plain fetch returns the rows in insertion order
    collection.data.insert(
        properties=properties, vector=vector, uuid=uuid.UUID(int=number)
    )


def _retrieval(collection):
    retrieval = FaqRetrieval.__new__(FaqRetrieval)
    retrieval.collection = collection
    retrieval.llm_embedding = MagicMock()
    retrieval.llm_embedding.embed.return_value = QUERY_VECTOR
    retrieval.tokens = []
    return retrieval


def _faq_ids(rows):
    return sorted(row["faq_id"] for row in rows)


def _db_ids(rows):
    return sorted(row["properties"]["faq_id"] for row in rows)


@pytest.mark.parametrize("word_tokenized", [False, True])
def test_only_this_instances_faqs_are_returned(client, word_tokenized):
    collection = (
        _word_tokenized_collection(client)
        if word_tokenized
        else init_faq_schema(client)
    )
    _insert(collection, 1, OWN, "exam date", QUERY_VECTOR)
    _insert(collection, 2, LONGER, "exam date", QUERY_VECTOR)
    _insert(collection, 3, "https://other.example", "exam date", QUERY_VECTOR)
    _insert(collection, 4, None, "exam date", QUERY_VECTOR)  # legacy row
    _insert(collection, 5, OWN, "exam date", QUERY_VECTOR, course_id=8)
    retrieval = _retrieval(collection)
    db = SimpleNamespace(faqs=collection)

    assert _faq_ids(retrieval("exam date", 7, OWN)) == [1]
    assert _db_ids(retrieval.get_faqs_from_db(7, OWN, search_text="exam date")) == [1]
    assert _db_ids(retrieval.get_faqs_from_db(7, OWN)) == [1]
    assert _faq_ids(retrieval("exam date", 7, LONGER)) == [2]
    assert retrieval("exam date", 7, None) == []
    assert retrieval.get_faqs_from_db(7, "") == []
    assert should_allow_faq_tool(db, 7, OWN) is True
    assert should_allow_faq_tool(db, 9, OWN) is False
    assert should_allow_faq_tool(db, 7, "https://none.example") is False
    assert should_allow_faq_tool(db, 7, None) is False


def test_colliding_rows_ranked_first_do_not_hide_owned_faqs(client):
    collection = _word_tokenized_collection(client)
    for number in range(1, 13):
        _insert(collection, number, LONGER, "exam date", QUERY_VECTOR)
    _insert(collection, 100, OWN, "room", [0.0, 1.0, 0.0])
    retrieval = _retrieval(collection)
    # Precondition: the first page of the plain filtered search holds only the other instance's rows
    first_page = collection.query.hybrid(
        query="exam date",
        vector=QUERY_VECTOR,
        alpha=0.9,
        limit=10,
        filters=faq_instance_filter(7, OWN),
        return_properties=[FaqSchema.BASE_URL.value],
    ).objects
    assert len(first_page) == 10
    assert {row.properties[FaqSchema.BASE_URL.value] for row in first_page} == {LONGER}

    assert _faq_ids(retrieval("exam date", 7, OWN, result_limit=10)) == [100]
    assert _db_ids(
        retrieval.get_faqs_from_db(7, OWN, search_text="exam date", result_limit=10)
    ) == [100]
    assert _db_ids(retrieval.get_faqs_from_db(7, OWN, result_limit=10)) == [100]


def test_the_gate_reads_past_colliding_rows_and_stays_open_at_its_budget(client):
    collection = _word_tokenized_collection(client)
    db = SimpleNamespace(faqs=collection)
    for number in range(1, 5):
        _insert(collection, number, LONGER, "exam", QUERY_VECTOR)
    _insert(collection, 50, OWN, "exam", QUERY_VECTOR)
    assert should_allow_faq_tool(db, 7, OWN) is True

    # Only colliding rows, fewer than the budget: the gate is closed
    collection.data.delete_by_id(uuid.UUID(int=50))
    assert should_allow_faq_tool(db, 7, OWN) is False

    # Five colliding rows spend the budget before the owned row is read: the gate stays open
    _insert(collection, 5, LONGER, "exam", QUERY_VECTOR)
    _insert(collection, 50, OWN, "exam", QUERY_VECTOR)
    owned, budget_spent = fetch_owned_faqs(
        lambda offset, limit: collection.query.fetch_objects(
            filters=faq_instance_filter(7, OWN),
            limit=limit,
            offset=offset,
            return_properties=[FaqSchema.BASE_URL.value],
        ).objects,
        OWN,
        1,
    )
    assert (owned, budget_spent) == ([], True)
    assert should_allow_faq_tool(db, 7, OWN) is True
