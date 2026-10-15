"""FAQ census, write and delete against a real Weaviate.

Runs only when ``IRIS_TEST_WEAVIATE_URL`` names a disposable Weaviate (``http://host:http_port``
with the gRPC port in
``IRIS_TEST_WEAVIATE_GRPC_PORT``, default 50051); CI has none, so it is skipped there. It checks
what the mocked tests cannot: the
identity-minus-ids delete filter, the schema on a missing and on a legacy collection, and the census
on stored rows.
"""

import os
from unittest.mock import MagicMock, patch
from urllib.parse import urlparse

import pytest

from iris.domain.data.faq_dto import FaqDTO
from iris.pipeline.faq_ingestion_pipeline import FaqIngestionPipeline
from iris.vector_database.faq_schema import FaqSchema, init_faq_schema
from iris.web.routers import faq_census

WEAVIATE_URL = os.environ.get("IRIS_TEST_WEAVIATE_URL")

pytestmark = pytest.mark.skipif(
    not WEAVIATE_URL, reason="needs a disposable Weaviate in IRIS_TEST_WEAVIATE_URL"
)

OWN = "https://artemis.example"
OTHER = "https://other.example"


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


def _pipeline(collection):
    pipeline = FaqIngestionPipeline.__new__(FaqIngestionPipeline)
    pipeline.collection = collection
    pipeline.llm_embedding = MagicMock()
    pipeline.llm_embedding.embed.return_value = [0.1, 0.2, 0.3]
    pipeline.tokens = []
    return pipeline


def _census(collection, base_url=OWN):
    with patch.object(faq_census, "VectorDatabase") as database:
        database.return_value.faqs = collection
        database.return_value.client.collections.exists.return_value = True
        return {
            (entry.course_id, entry.faq_id): entry
            for entry in faq_census.get_faq_census(base_url=base_url).faqs
        }


def test_empty_weaviate_refill_and_census(client):
    # The collection does not exist, as after replacing Weaviate with an empty one
    with patch.object(faq_census, "VectorDatabase") as database:
        database.return_value.client = client
        assert not faq_census.get_faq_census(base_url=OWN).faqs
    collection = init_faq_schema(client)
    pipeline = _pipeline(collection)
    assert _census(collection) == {}

    for faq_id in range(1, 26):
        pipeline.delete_faq(faq_id, 7, OWN)
        pipeline.insert_faq(
            FaqDTO(
                faqId=faq_id,
                courseId=7,
                questionTitle=f"Q{faq_id}",
                contentFingerprint=f"v1:{faq_id}",
            ),
            OWN,
        )

    census = _census(collection)
    assert len(census) == 25
    assert all(
        entry.owned_row_count == 1 and entry.legacy_row_count == 0
        for entry in census.values()
    )
    assert census[(7, 3)].owned_fingerprint == "v1:3"


def test_delete_keeps_other_instances_and_push_replaces_legacy_rows(client):
    collection = init_faq_schema(client)
    pipeline = _pipeline(collection)
    # A legacy row (no base URL) and another instance's row for the same FAQ ids
    collection.data.insert(
        properties={
            FaqSchema.FAQ_ID.value: 1,
            FaqSchema.COURSE_ID.value: 7,
            FaqSchema.QUESTION_TITLE.value: "legacy",
        },
        vector=[0.1, 0.2, 0.3],
    )
    collection.data.insert(
        properties={
            FaqSchema.FAQ_ID.value: 1,
            FaqSchema.COURSE_ID.value: 7,
            FaqSchema.QUESTION_TITLE.value: "other",
            FaqSchema.BASE_URL.value: OTHER,
        },
        vector=[0.1, 0.2, 0.3],
    )
    assert _census(collection)[(7, 1)].legacy_row_count == 1
    assert _census(collection)[(7, 1)].owned_row_count == 0

    # The push deletes this instance's and the legacy row, then writes one owned row
    pipeline.delete_faq(1, 7, OWN)
    pipeline.insert_faq(
        FaqDTO(faqId=1, courseId=7, questionTitle="Q1", contentFingerprint="v1:1"), OWN
    )

    own = _census(collection)[(7, 1)]
    assert (own.owned_row_count, own.legacy_row_count, own.owned_fingerprint) == (
        1,
        0,
        "v1:1",
    )
    other = _census(collection, OTHER)[(7, 1)]
    assert (other.owned_row_count, other.legacy_row_count) == (1, 0)

    # Deleting the FAQ for this instance leaves the other instance's row
    pipeline.delete_faq(1, 7, OWN)
    assert (7, 1) not in _census(collection)
    assert _census(collection, OTHER)[(7, 1)].owned_row_count == 1


def test_legacy_collection_gets_the_new_properties(client):
    from weaviate.classes.config import (  # pylint: disable=import-outside-toplevel
        Configure,
        DataType,
        Property,
    )

    client.collections.create(
        name=FaqSchema.COLLECTION_NAME.value,
        vector_config=Configure.Vectors.self_provided(),
        properties=[
            Property(name=FaqSchema.FAQ_ID.value, data_type=DataType.INT),
            Property(name=FaqSchema.COURSE_ID.value, data_type=DataType.INT),
        ],
    )

    collection = init_faq_schema(client)

    names = {prop.name for prop in collection.config.get().properties}
    assert {
        FaqSchema.BASE_URL.value,
        FaqSchema.CONTENT_FINGERPRINT.value,
        FaqSchema.COURSE_LANGUAGE.value,
    } <= names


def test_delete_does_not_reach_an_instance_whose_url_contains_all_words_of_ours(
    client,
):
    # "https://artemis.example" splits into words that "https://artemis-test.artemis.example" also contains
    collection = init_faq_schema(client)
    pipeline = _pipeline(collection)
    longer = "https://artemis-test.artemis.example"
    pipeline.insert_faq(FaqDTO(faqId=1, courseId=7, questionTitle="mine"), OWN)
    pipeline.insert_faq(FaqDTO(faqId=1, courseId=7, questionTitle="theirs"), longer)

    pipeline.delete_faq(1, 7, OWN)

    assert (7, 1) not in _census(collection)
    assert _census(collection, longer)[(7, 1)].owned_row_count == 1
