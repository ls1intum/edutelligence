from enum import Enum

from weaviate import WeaviateClient
from weaviate.classes.config import Property
from weaviate.collections import Collection
from weaviate.collections.classes.config import (
    Configure,
    DataType,
    VectorDistances,
)


class LectureUnitSchema(Enum):
    """
    Schema for the lectures
    """

    COLLECTION_NAME = "LectureUnits"
    COURSE_ID = "course_id"
    COURSE_NAME = "course_name"
    COURSE_DESCRIPTION = "course_description"
    COURSE_LANGUAGE = "course_language"
    LECTURE_ID = "lecture_id"
    LECTURE_NAME = "lecture_name"
    LECTURE_UNIT_ID = "lecture_unit_id"
    LECTURE_UNIT_NAME = "lecture_unit_name"
    LECTURE_UNIT_LINK = "lecture_unit_link"
    BASE_URL = "base_url"
    LECTURE_UNIT_SUMMARY = "lecture_unit_summary"
    VIDEO_LINK = "video_link"


def init_lecture_unit_schema(client: WeaviateClient) -> Collection:
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
            Property(
                name=LectureUnitSchema.COURSE_DESCRIPTION.value,
                description="The description of the course",
                data_type=DataType.TEXT,
                index_searchable=False,
            ),
            Property(
                name=LectureUnitSchema.COURSE_LANGUAGE.value,
                description="The language of the course",
                data_type=DataType.TEXT,
                index_searchable=False,
            ),
            Property(
                name=LectureUnitSchema.LECTURE_ID.value,
                description="The ID of the lecture",
                data_type=DataType.INT,
                index_searchable=False,
            ),
            Property(
                name=LectureUnitSchema.LECTURE_NAME.value,
                description="The name of the lecture",
                data_type=DataType.TEXT,
                index_searchable=False,
            ),
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
                name=LectureUnitSchema.VIDEO_LINK.value,
                description="The link to the video of the lecture unit",
                data_type=DataType.TEXT,
                index_searchable=False,
            ),
            Property(
                name=LectureUnitSchema.BASE_URL.value,
                description="The base url of the website where the lecture unit is hosted",
                data_type=DataType.TEXT,
                index_searchable=False,
            ),
            Property(
                name=LectureUnitSchema.LECTURE_UNIT_SUMMARY.value,
                description="The summary of the lecture unit",
                data_type=DataType.TEXT,
                index_searchable=True,
            ),
        ],
    )
