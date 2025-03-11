from enum import Enum

from weaviate.classes.config import Property
from weaviate import WeaviateClient
from weaviate.collections import Collection
from weaviate.collections.classes.config import Configure, VectorDistances, DataType


class LectureUnitPageChunkSchema(Enum):
    """
    Schema for the lecture slides
    """

    COLLECTION_NAME = "Lectures"
    COURSE_ID = "course_id"
    COURSE_LANGUAGE = "course_language"
    LECTURE_ID = "lecture_id"
    LECTURE_UNIT_ID = "lecture_unit_id"
    PAGE_TEXT_CONTENT = "page_text_content"
    PAGE_NUMBER = "page_number"
    BASE_URL = "base_url"


def init_lecture_unit_page_chunk_schema(client: WeaviateClient) -> Collection:
    """
    Initialize the schema for the lecture unit page chunks
    """
    if client.collections.exists(LectureUnitPageChunkSchema.COLLECTION_NAME.value):
        collection = client.collections.get(
            LectureUnitPageChunkSchema.COLLECTION_NAME.value
        )
        properties = collection.config.get(simple=True).properties

        # Check and add 'course_language' property if missing
        if not any(
            property.name == LectureUnitPageChunkSchema.COURSE_LANGUAGE.value
            for property in properties
        ):
            collection.config.add_property(
                Property(
                    name=LectureUnitPageChunkSchema.COURSE_LANGUAGE.value,
                    description="The language of the COURSE",
                    data_type=DataType.TEXT,
                    index_searchable=False,
                )
            )

        return collection

    return client.collections.create(
        name=LectureUnitPageChunkSchema.COLLECTION_NAME.value,
        vectorizer_config=Configure.Vectorizer.none(),
        vector_index_config=Configure.VectorIndex.hnsw(
            distance_metric=VectorDistances.COSINE
        ),
        properties=[
            Property(
                name=LectureUnitPageChunkSchema.COURSE_ID.value,
                description="The ID of the course",
                data_type=DataType.INT,
                index_searchable=False,
            ),
            Property(
                name=LectureUnitPageChunkSchema.COURSE_LANGUAGE.value,
                description="The language of the COURSE",
                data_type=DataType.TEXT,
                index_searchable=False,
            ),
            Property(
                name=LectureUnitPageChunkSchema.LECTURE_ID.value,
                description="The ID of the lecture",
                data_type=DataType.INT,
                index_searchable=False,
            ),
            Property(
                name=LectureUnitPageChunkSchema.LECTURE_UNIT_ID.value,
                description="The ID of the lecture unit",
                data_type=DataType.INT,
                index_searchable=False,
            ),
            Property(
                name=LectureUnitPageChunkSchema.PAGE_TEXT_CONTENT.value,
                description="The content of the lecture slide",
                data_type=DataType.TEXT,
                index_searchable=True,
            ),
            Property(
                name=LectureUnitPageChunkSchema.PAGE_NUMBER.value,
                description="The page number of the slide",
                data_type=DataType.INT,
                index_searchable=False,
            ),
            Property(
                name=LectureUnitPageChunkSchema.BASE_URL.value,
                description="The base url of the website where the lecture unit is hosted",
                data_type=DataType.TEXT,
                index_searchable=False,
            ),
        ],
    )
