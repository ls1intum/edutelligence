from enum import Enum

from weaviate import WeaviateClient
from weaviate.classes.config import Property
from weaviate.collections import Collection
from weaviate.collections.classes.config import (
    Configure,
    DataType,
    VectorDistances,
)

from .schema_properties import add_property_if_missing


class FaqSchema(Enum):
    """
    Schema for the faqs
    """

    COLLECTION_NAME = "Faqs"
    COURSE_NAME = "course_name"
    COURSE_DESCRIPTION = "course_description"
    COURSE_LANGUAGE = "course_language"
    COURSE_ID = "course_id"
    FAQ_ID = "faq_id"
    QUESTION_TITLE = "question_title"
    QUESTION_ANSWER = "question_answer"
    BASE_URL = "base_url"
    CONTENT_FINGERPRINT = "content_fingerprint"


def _base_url_property() -> Property:
    return Property(
        name=FaqSchema.BASE_URL.value,
        description="The base URL of the Artemis instance the FAQ belongs to",
        data_type=DataType.TEXT,
        index_searchable=False,
    )


def _content_fingerprint_property() -> Property:
    return Property(
        name=FaqSchema.CONTENT_FINGERPRINT.value,
        description="Fingerprint of the FAQ content, computed by Artemis and reported back by the FAQ census",
        data_type=DataType.TEXT,
        index_searchable=False,
    )


def init_faq_schema(client: WeaviateClient) -> Collection:
    """
    Initialize the schema for the faqs
    """
    if client.collections.exists(FaqSchema.COLLECTION_NAME.value):
        collection = client.collections.get(FaqSchema.COLLECTION_NAME.value)
        add_property_if_missing(
            collection,
            Property(
                name=FaqSchema.COURSE_LANGUAGE.value,
                description="The language of the COURSE",
                data_type=DataType.TEXT,
                index_searchable=False,
            ),
        )
        add_property_if_missing(collection, _base_url_property())
        add_property_if_missing(collection, _content_fingerprint_property())
        return collection

    return client.collections.create(
        name=FaqSchema.COLLECTION_NAME.value,
        vector_config=Configure.Vectors.self_provided(
            vector_index_config=Configure.VectorIndex.hnsw(
                distance_metric=VectorDistances.COSINE
            ),
        ),
        properties=[
            Property(
                name=FaqSchema.COURSE_ID.value,
                description="The ID of the course",
                data_type=DataType.INT,
                index_searchable=False,
            ),
            Property(
                name=FaqSchema.COURSE_NAME.value,
                description="The name of the course",
                data_type=DataType.TEXT,
                index_searchable=False,
            ),
            Property(
                name=FaqSchema.COURSE_DESCRIPTION.value,
                description="The description of the COURSE",
                data_type=DataType.TEXT,
                index_searchable=False,
            ),
            Property(
                name=FaqSchema.COURSE_LANGUAGE.value,
                description="The language of the COURSE",
                data_type=DataType.TEXT,
                index_searchable=False,
            ),
            Property(
                name=FaqSchema.FAQ_ID.value,
                description="The ID of the Faq",
                data_type=DataType.INT,
                index_searchable=False,
            ),
            Property(
                name=FaqSchema.QUESTION_TITLE.value,
                description="The title of the faq",
                data_type=DataType.TEXT,
            ),
            Property(
                name=FaqSchema.QUESTION_ANSWER.value,
                description="The answer of the faq",
                data_type=DataType.TEXT,
            ),
            _base_url_property(),
            _content_fingerprint_property(),
        ],
    )
