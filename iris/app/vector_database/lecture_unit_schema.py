from enum import Enum

from weaviate.classes.config import Property, ReferenceProperty
from weaviate import WeaviateClient
from weaviate.collections import Collection
from weaviate.collections.classes.config import Configure, VectorDistances, DataType

from app.vector_database.lecture_schema import LectureUnitSegmentSchema
from app.vector_database.lecture_slide_schema import LectureUnitPageChunkSchema
from app.vector_database.lecture_transcription_schema import LectureTranscriptionSchema


class LectureUnitSchema(Enum):
    """
    Schema for the lectures
    """
    COLLECTION_NAME = "Lecture_units"
    LECTURE_UNIT_ID = "lecture_unit_id"
    LECTURE_UNIT_NAME = "lecture_unit_name"
    LECTURE_UNIT_LINK = "lecture_unit_link"
    LECTURE_ID = "lecture_id"
    LECTURE_NAME = "lecture_name"
    COURSE_ID = "course_id"
    COURSE_NAME = "course_name"

def init_lecture_schema(client: WeaviateClient) -> Collection:
    if client.collections.exists(LectureUnitSchema.COLLECTION_NAME.value):
        return client.collections.get(LectureUnitSchema.COLLECTION_NAME.value)

    return client.collections.create(
        name=LectureUnitSchema.COLLECTION_NAME.value,
        vectorizer_config=Configure.Vectorizer.none(),
        vector_index_config=Configure.VectorIndex.hnsw(
            distance_metric=VectorDistances.COSINE
        ),
        properties=[
            Property(
                name=LectureUnitSchema.LECTURE_UNIT_ID.value,
                description="The id of the lecture unit",
                data_type=DataType.INT,
                index_searchable=False,
            ),
            Property(
                name=LectureUnitSchema.LECTURE_UNIT_NAME.value,
                description="The name of the lecture unit",
                data_type=DataType.TEXT,
                index_searchable=False,
            ),
            Property(
                name=LectureUnitSchema.LECTURE_UNIT_LINK.value,
                description="The link to the lecture unit",
                data_type=DataType.TEXT,
                index_searchable=False,
            ),
            Property(
                name=LectureUnitSchema.LECTURE_ID.value,
                description="The id of the lecture",
                data_type=DataType.INT,
                index_searchable=False,
            ),
            Property(
                name=LectureUnitSchema.LECTURE_NAME.value,
                description="The name of the lecture",
                data_type=DataType.INT,
                index_searchable=False,
            ),
            Property(
                name=LectureUnitSchema.COURSE_ID.value,
                description="The ID of the course",
                data_type=DataType.INT,
                index_searchable=False,
            ),
            Property(
                name=LectureUnitSchema.COURSE_NAME.value,
                description="The name of the course",
                data_type=DataType.TEXT,
                index_searchable=False,
            ),
        ],
    )