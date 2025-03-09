from enum import Enum

from weaviate.classes.config import Property
from weaviate import WeaviateClient
from weaviate.collections import Collection
from weaviate.collections.classes.config import (
    Configure,
    VectorDistances,
    DataType,
    ReferenceProperty,
)

from app.vector_database.lecture_transcription_schema import LectureTranscriptionSchema
from app.vector_database.lecture_unit_page_chunk_schema import (
    LectureUnitPageChunkSchema,
)


class LectureUnitSegmentSchema(Enum):
    """
    Schema for the lecture unit segments
    """

    COLLECTION_NAME = "LectureUnitSegments"
    COURSE_ID = "course_id"
    LECTURE_ID = "lecture_id"
    LECTURE_UNIT_ID = "lecture_unit_id"
    PAGE_NUMBER = "page_number"
    SEGMENT_SUMMARY = "segment_summary"
    TRANSCRIPTIONS = "transcriptions"
    SLIDES = "slides"
    BASE_URL = "base_url"


def init_lecture_unit_segment_schema(client: WeaviateClient) -> Collection:
    if client.collections.exists(LectureUnitSegmentSchema.COLLECTION_NAME.value):
        return client.collections.get(LectureUnitSegmentSchema.COLLECTION_NAME.value)

    return client.collections.create(
        name=LectureUnitSegmentSchema.COLLECTION_NAME.value,
        vectorizer_config=Configure.Vectorizer.none(),
        vector_index_config=Configure.VectorIndex.hnsw(
            distance_metric=VectorDistances.COSINE
        ),
        properties=[
            Property(
                name=LectureUnitSegmentSchema.COURSE_ID.value,
                description="The ID of the course",
                data_type=DataType.INT,
                index_searchable=False,
            ),
            Property(
                name=LectureUnitSegmentSchema.LECTURE_ID.value,
                description="The ID of the lecture",
                data_type=DataType.INT,
                index_searchable=False,
            ),
            Property(
                name=LectureUnitSegmentSchema.LECTURE_UNIT_ID.value,
                description="The id of the lecture unit",
                data_type=DataType.INT,
                index_searchable=False,
            ),
            Property(
                name=LectureUnitSegmentSchema.PAGE_NUMBER.value,
                description="The page number of the lecture unit",
                data_type=DataType.INT,
                index_searchable=False,
            ),
            Property(
                name=LectureUnitSegmentSchema.SEGMENT_SUMMARY.value,
                description="The summary of the transcription and the lecture content of the segment",
                data_type=DataType.TEXT,
                index_searchable=True,
            ),
            Property(
                name=LectureUnitSegmentSchema.BASE_URL.value,
                description="The base url of the website where the lecture unit is hosted",
                data_type=DataType.TEXT,
                index_searchable=False,
            ),
        ],
        references=[
            ReferenceProperty(
                name=LectureUnitSegmentSchema.TRANSCRIPTIONS.value,
                target_collection=LectureTranscriptionSchema.COLLECTION_NAME.value,
            ),
            ReferenceProperty(
                name=LectureUnitSegmentSchema.SLIDES.value,
                target_collection=LectureUnitPageChunkSchema.COLLECTION_NAME.value,
            ),
        ],
    )
