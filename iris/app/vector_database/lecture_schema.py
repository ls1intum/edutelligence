from enum import Enum

import weaviate.classes as wvc
from weaviate import WeaviateClient
from weaviate.collections import Collection


class LectureSchema(Enum):
    """
    Schema for the lecture slides
    """

    COLLECTION_NAME = "LectureSlides"
    COURSE_NAME = "course_name"
    COURSE_DESCRIPTION = "course_description"
    COURSE_ID = "course_id"
    LECTURE_ID = "lecture_id"
    LECTURE_NAME = "lecture_name"
    LECTURE_UNIT_ID = "lecture_unit_id"  # The attachment unit ID in Artemis
    LECTURE_UNIT_NAME = "lecture_unit_name"
    PAGE_TEXT_CONTENT = "page_text_content"  # The only property which will be embedded
    PAGE_IMAGE_DESCRIPTION = "page_image_explanation"  # The description of the slide if the slide contains an image
    PAGE_BASE64 = "page_base64"  # The base64 encoded image of the slide if the slide contains an image
    PAGE_NUMBER = "page_number"


def init_lecture_schema(client: WeaviateClient) -> Collection:
    """
    Initialize the schema for the lecture slides
    """
    if client.collections.exists(LectureSchema.COLLECTION_NAME.value):
        return client.collections.get(LectureSchema.COLLECTION_NAME.value)
    return client.collections.create(
        name=LectureSchema.COLLECTION_NAME.value,
        vectorizer_config=wvc.config.Configure.Vectorizer.none(),
        # We do not want to vectorize the text automatically
        # HNSW is preferred over FLAT for large amounts of vector_database, which is the case here
        vector_index_config=wvc.config.Configure.VectorIndex.hnsw(
            distance_metric=wvc.config.VectorDistances.COSINE  # select preferred distance metric
        ),
        # The properties are like the columns of a table in a relational database
        properties=[
            wvc.config.Property(
                name=LectureSchema.COURSE_ID.value,
                description="The ID of the course",
                data_type=wvc.config.DataType.INT,
            ),
            wvc.config.Property(
                name=LectureSchema.COURSE_NAME.value,
                description="The name of the course",
                data_type=wvc.config.DataType.TEXT,
            ),
            wvc.config.Property(
                name=LectureSchema.COURSE_DESCRIPTION.value,
                description="The description of the COURSE",
                data_type=wvc.config.DataType.TEXT,
            ),
            wvc.config.Property(
                name=LectureSchema.LECTURE_ID.value,
                description="The ID of the lecture",
                data_type=wvc.config.DataType.INT,
            ),
            wvc.config.Property(
                name=LectureSchema.LECTURE_NAME.value,
                description="The name of the lecture",
                data_type=wvc.config.DataType.TEXT,
            ),
            wvc.config.Property(
                name=LectureSchema.LECTURE_UNIT_ID.value,
                description="The ID of the lecture unit",
                data_type=wvc.config.DataType.INT,
            ),
            wvc.config.Property(
                name=LectureSchema.LECTURE_UNIT_NAME.value,
                description="The name of the lecture unit",
                data_type=wvc.config.DataType.TEXT,
            ),
            wvc.config.Property(
                name=LectureSchema.PAGE_TEXT_CONTENT.value,
                description="The original text content from the slide",
                data_type=wvc.config.DataType.TEXT,
            ),
            wvc.config.Property(
                name=LectureSchema.PAGE_IMAGE_DESCRIPTION.value,
                description="The description of the slide if the slide contains an image",
                data_type=wvc.config.DataType.TEXT.value,
            ),
            wvc.config.Property(
                name=LectureSchema.PAGE_BASE64.value,
                description="The base64 encoded image of the slide if the slide contains an image",
                data_type=wvc.config.DataType.TEXT.value,
            ),
            wvc.config.Property(
                name=LectureSchema.PAGE_NUMBER.value,
                description="The page number of the slide",
                data_type=wvc.config.DataType.INT,
            ),
        ],
    )
