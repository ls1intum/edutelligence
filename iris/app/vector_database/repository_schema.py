from enum import Enum

import weaviate.classes as wvc
from weaviate import WeaviateClient
from weaviate.collections import Collection


class RepositorySchema(Enum):
    """
    Schema for the student repository
    """
    COLLECTION_NAME = "StudentRepository"
    CONTENT = "content"
    COURSE_ID = "course_id"
    EXERCISE_ID = "exercise_id"
    REPOSITORY_ID = "repository_id"
    FILEPATH = "filepath"


def init_repository_schema(client: WeaviateClient) -> Collection:
    """
    Initialize the schema for the student repository
    """
    if client.collections.exists(RepositorySchema.COLLECTION_NAME.value):
        return client.collections.get(RepositorySchema.COLLECTION_NAME.value)
    return client.collections.create(
        name=RepositorySchema.COLLECTION_NAME.value,
        vectorizer_config=wvc.config.Configure.Vectorizer.none(),
        vector_index_config=wvc.config.Configure.VectorIndex.hnsw(
            distance_metric=wvc.config.VectorDistances.COSINE
        ),
        properties=[
            wvc.config.Property(
                name=RepositorySchema.CONTENT.value,
                description="The content of this chunk of code",
                data_type=wvc.config.DataType.TEXT,
            ),
            wvc.config.Property(
                name=RepositorySchema.COURSE_ID.value,
                description="The ID of the course",
                data_type=wvc.config.DataType.INT,
            ),
            wvc.config.Property(
                name=RepositorySchema.EXERCISE_ID.value,
                description="The ID of the exercise",
                data_type=wvc.config.DataType.INT,
            ),
            wvc.config.Property(
                name=RepositorySchema.REPOSITORY_ID.value,
                description="The ID of the repository",
                data_type=wvc.config.DataType.INT,
            ),
            wvc.config.Property(
                name=RepositorySchema.FILEPATH.value,
                description="The filepath of the code",
                data_type=wvc.config.DataType.TEXT,
            ),
        ],
    )
