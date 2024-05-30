from enum import Enum

from weaviate.classes.config import Property
from weaviate import WeaviateClient
from weaviate.collections import Collection
from weaviate.collections.classes.config import Configure, VectorDistances, DataType


class LectureSchema(Enum):
    """
    Schema for the lecture slides
    """

    COLLECTION_NAME = "LectureSlides"
    COURSE_NAME = "course_name"
    COURSE_DESCRIPTION = "course_description"
    COURSE_LANGUAGE = "course_language"
    COURSE_ID = "course_id"
    LECTURE_ID = "lecture_id"
    LECTURE_NAME = "lecture_name"
    LECTURE_UNIT_ID = "lecture_unit_id"
    LECTURE_UNIT_NAME = "lecture_unit_name"
    PAGE_TEXT_CONTENT = "page_text_content"
    PAGE_IMAGE_DESCRIPTION = "page_image_explanation"
    PAGE_BASE64 = "page_base64"
    PAGE_NUMBER = "page_number"
    BASE_URL = "base_url"


def init_lecture_schema(client: WeaviateClient) -> Collection:
    """
    Initialize the schema for the lecture slides
    """
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
            ),
            Property(
                name=LectureSchema.COURSE_NAME.value,
                description="The name of the course",
                data_type=DataType.TEXT,
            ),
            Property(
                name=LectureSchema.COURSE_DESCRIPTION.value,
                description="The description of the COURSE",
                data_type=DataType.TEXT,
            ),
            Property(
                name=LectureSchema.LECTURE_ID.value,
                description="The ID of the lecture",
                data_type=DataType.INT,
            ),
            Property(
                name=LectureSchema.LECTURE_NAME.value,
                description="The name of the lecture",
                data_type=DataType.TEXT,
            ),
            Property(
                name=LectureSchema.LECTURE_UNIT_ID.value,
                description="The ID of the lecture unit",
                data_type=DataType.INT,
            ),
            Property(
                name=LectureSchema.LECTURE_UNIT_NAME.value,
                description="The name of the lecture unit",
                data_type=DataType.TEXT,
            ),
            Property(
                name=LectureSchema.PAGE_TEXT_CONTENT.value,
                description="The original text content from the slide",
                data_type=DataType.TEXT,
            ),
            Property(
                name=LectureSchema.PAGE_IMAGE_DESCRIPTION.value,
                description="The description of the slide if the slide contains an image",
                data_type=DataType.TEXT,
            ),
            Property(
                name=LectureSchema.PAGE_BASE64.value,
                description="The base64 encoded image of the slide if the slide contains an image",
                data_type=DataType.TEXT,
            ),
            Property(
                name=LectureSchema.PAGE_NUMBER.value,
                description="The page number of the slide",
                data_type=DataType.INT,
            ),
            Property(
                name=LectureSchema.BASE_URL.value,
                description="The base url of the website where the lecture slides are hosted",
                data_type=DataType.TEXT,
            ),
        ],
    )
