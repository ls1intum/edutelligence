from enum import Enum
from weaviate.classes.config import Property
from weaviate import WeaviateClient
from weaviate.collections import Collection
from weaviate.collections.classes.config import Configure, VectorDistances, DataType


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
        vectorizer_config=Configure.Vectorizer.none(),
        vector_index_config=Configure.VectorIndex.hnsw(
            distance_metric=VectorDistances.COSINE
        ),
        properties=[
            Property(
                name=RepositorySchema.CONTENT.value,
                description="The content of this chunk of code",
                data_type=DataType.TEXT,
            ),
            Property(
                name=RepositorySchema.COURSE_ID.value,
                description="The ID of the course",
                data_type=DataType.INT,
            ),
            Property(
                name=RepositorySchema.EXERCISE_ID.value,
                description="The ID of the exercise",
                data_type=DataType.INT,
            ),
            Property(
                name=RepositorySchema.REPOSITORY_ID.value,
                description="The ID of the repository",
                data_type=DataType.INT,
            ),
            Property(
                name=RepositorySchema.FILEPATH.value,
                description="The filepath of the code",
                data_type=DataType.TEXT,
            ),
        ],
    )