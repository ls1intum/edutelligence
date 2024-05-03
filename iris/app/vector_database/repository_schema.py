import weaviate.classes as wvc
from weaviate import WeaviateClient
from weaviate.collections import Collection

COLLECTION_NAME = "StudentRepository"


class RepositorySchema:
    """
    Schema for the student repository
    """

    CONTENT = "content"  # The only property which will be embedded
    COURSE_ID = "course_id"
    EXERCISE_ID = "exercise_id"
    REPOSITORY_ID = "repository_id"
    FILEPATH = "filepath"


def init_repository_schema(client: WeaviateClient) -> Collection:
    """
    Initialize the schema for the student repository
    """
    if client.collections.exists(COLLECTION_NAME):
        return client.collections.get(COLLECTION_NAME)
    return client.collections.create(
        name=COLLECTION_NAME,
        vectorizer_config=wvc.config.Configure.Vectorizer.none(),
        vector_index_config=wvc.config.Configure.VectorIndex.hnsw(
            distance_metric=wvc.config.VectorDistances.COSINE
        ),
        properties=[
            wvc.config.Property(
                name=RepositorySchema.CONTENT,
                description="The content of this chunk of code",
                data_type=wvc.config.DataType.TEXT,
            ),
            wvc.config.Property(
                name=RepositorySchema.COURSE_ID,
                description="The ID of the course",
                data_type=wvc.config.DataType.INT,
            ),
            wvc.config.Property(
                name=RepositorySchema.EXERCISE_ID,
                description="The ID of the exercise",
                data_type=wvc.config.DataType.INT,
            ),
            wvc.config.Property(
                name=RepositorySchema.REPOSITORY_ID,
                description="The ID of the repository",
                data_type=wvc.config.DataType.INT,
            ),
            wvc.config.Property(
                name=RepositorySchema.FILEPATH,
                description="The filepath of the code",
                data_type=wvc.config.DataType.TEXT,
            ),
        ],
    )
