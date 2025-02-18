from enum import Enum

from weaviate.classes.config import Property
from weaviate import WeaviateClient
from weaviate.collections import Collection
from weaviate.collections.classes.config import Configure, VectorDistances, DataType

class LectureSchema(Enum):
    """
    Schema for the lectures
    """
    COLLECTION_NAME = "Lectures"
    COURSE_ID = "course_id"
    COURSE_NAME = "course_name"
    COURSE_DESCRIPTION = "course_description"
    COURSE_LANGUAGE = "course_language"
    LECTURE_ID = "lecture_id"
    LECTURE_NAME = "lecture_name"
    LECTURE_UNIT_ID = "lecture_unit_id"
    CONTENT = "content"
    SLIDE_NUMBER = "slide_number"

def init_lecture_schema(client: WeaviateClient) -> Collection:
    if client.collections.exists(LectureSchema.COLLECTION_NAME.value):
        return client.collections.get(LectureSchema.COLLECTION_NAME.value)

    return client.collections.create(
        name=LectureSchema.COLLECTION_NAME.value,
        vectorizer_config=Configure.Vectorizer.none(),
        vector_index_config=Configure.VectorIndex.hnsw(
            distance_metric=VectorDistances.COSINE
        ),
        properties=[
            Property(
                name=LectureSchema.COURSE_ID.value,
                description="The ID of the course",
                data_type=DataType.INT,
                index_searchable=False,
            ),
            Property(
                name=LectureSchema.COURSE_NAME.value,
                description="The name of the course",
                data_type=DataType.TEXT,
                index_searchable=False,
            ),
            Property(
                name=LectureSchema.COURSE_DESCRIPTION.value,
                description="The description of the course",
                data_type=DataType.TEXT,
                index_searchable=False,
            ),
            Property(
                name=LectureSchema.COURSE_LANGUAGE.value,
                description="The language of the course",
                data_type=DataType.TEXT,
                index_searchable=False,
            ),
            Property(
                name=LectureSchema.LECTURE_ID.value,
                description="The ID of the lecture",
                data_type=DataType.INT,
                index_searchable=False,
            ),
            Property(
                name=LectureSchema.LECTURE_NAME.value,
                description="The name of the lecture",
                data_type=DataType.TEXT,
                index_searchable=False,
            ),
            Property(
                name=LectureSchema.LECTURE_UNIT_ID.value,
                description="The id of the lecture unit",
                data_type=DataType.INT,
                index_searchable=False,
            ),
            Property(
                name=LectureSchema.CONTENT.value,
                description="The content of the lecture slide",
                data_type=DataType.TEXT,
                index_searchable=True,
            ),
            Property(
                name=LectureSchema.SLIDE_NUMBER.value,
                description="The slide number of the summary",
                data_type=DataType.INT,
                index_searchable=False,
            )
        ],
    )