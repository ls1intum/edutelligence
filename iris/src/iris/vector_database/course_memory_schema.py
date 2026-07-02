from enum import Enum

from weaviate import WeaviateClient
from weaviate.classes.config import Property
from weaviate.collections import Collection
from weaviate.collections.classes.config import (
    Configure,
    DataType,
    VectorDistances,
)


class CourseMemorySchema(Enum):
    """
    Schema for the course memory.

    Stores verified Q/A pairs mined from Artemis public communication channels.
    Only ``question`` is searchable (BM25) and carries the dense vector supplied at
    insert time; all other properties are payload/metadata used for the answer,
    course scoping, deduplication and backlinking.
    """

    COLLECTION_NAME = "CourseMemory"
    QUESTION = "question"
    ANSWER = "answer"
    COURSE_ID = "course_id"
    MESSAGE_ID = "message_id"
    CONVERSATION_ID = "conversation_id"
    SOURCE = "source"
    VERIFIED_AT = "verified_at"
    VERIFIED_BY = "verified_by"


def init_course_memory_schema(client: WeaviateClient) -> Collection:
    """
    Initialize the schema for the course memory.
    """
    if client.collections.exists(CourseMemorySchema.COLLECTION_NAME.value):
        return client.collections.get(CourseMemorySchema.COLLECTION_NAME.value)

    return client.collections.create(
        name=CourseMemorySchema.COLLECTION_NAME.value,
        vector_config=Configure.Vectors.self_provided(
            vector_index_config=Configure.VectorIndex.hnsw(
                distance_metric=VectorDistances.COSINE
            ),
        ),
        properties=[
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
                index_searchable=False,
            ),
            Property(
                name=CourseMemorySchema.MESSAGE_ID.value,
                description="The answer message's ID; used for upsert/dedup and backlinking",
                data_type=DataType.TEXT,
                index_searchable=False,
            ),
            Property(
                name=CourseMemorySchema.CONVERSATION_ID.value,
                description="The originating thread's ID; used for backlinking",
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
        ],
    )
