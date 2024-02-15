import weaviate.classes as wvc
from weaviate import WeaviateClient
from weaviate.collections import Collection


COLLECTION_NAME = "StudentRepository"


class RepositoryChunk:
    CONTENT = "content"  # The only property which will be embedded
    COURSE_ID = "course_id"
    EXERCISE_ID = "exercise_id"
    REPOSITORY_ID = "repository_id"
    FILEPATH = "filepath"


def init_schema(client: WeaviateClient) -> Collection:
    if client.collections.exists(COLLECTION_NAME):
        return client.collections.get(COLLECTION_NAME)
    return client.collections.create(
        name=COLLECTION_NAME,
        vectorizer_config=wvc.config.Configure.Vectorizer.none(),  # We do not want to vectorize the text automatically
        # HNSW is preferred over FLAT for large amounts of data, which is the case here
        vector_index_config=wvc.config.Configure.VectorIndex.hnsw(
            distance_metric=wvc.config.VectorDistances.COSINE  # select preferred distance metric
        ),
        # The properties are like the columns of a table in a relational database
        properties=[
            wvc.config.Property(
                name=RepositoryChunk.CONTENT,
                description="The content of this chunk of code",
                data_type=wvc.config.DataType.TEXT,
            ),
            wvc.config.Property(
                name=RepositoryChunk.COURSE_ID,
                description="The ID of the course",
                data_type=wvc.config.DataType.INT,
            ),
            wvc.config.Property(
                name=RepositoryChunk.EXERCISE_ID,
                description="The ID of the exercise",
                data_type=wvc.config.DataType.INT,
            ),
            wvc.config.Property(
                name=RepositoryChunk.REPOSITORY_ID,
                description="The ID of the repository",
                data_type=wvc.config.DataType.INT,
            ),
            wvc.config.Property(
                name=RepositoryChunk.FILEPATH,
                description="The filepath of the code",
                data_type=wvc.config.DataType.TEXT,
            ),
        ],
    )
