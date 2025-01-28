from enum import Enum

from weaviate.classes.config import Property
from weaviate import WeaviateClient
from weaviate.collections import Collection
from weaviate.collections.classes.config import Configure, VectorDistances, DataType


class LectureTranscriptionSchema(Enum):
    """
    Schema for the lecture transcriptions
    """

    COLLECTION_NAME = "LectureTranscriptions"
    COURSE_ID = "course_id"
    COURSE_NAME = "course_name"
    LECTURE_ID = "lecture_id"
    LECTURE_NAME = "lecture_name"
    LANGUAGE = "language"
    SEGMENT_START = "segment_start"
    SEGMENT_END = "segment_end"
    SEGMENT_TEXT = "segment_text"
    SEGMENT_LECTURE_UNIT_SLIDES_ID = "segment_lecture_unit_slides_id"
    SEGMENT_LECTURE_UNIT_SLIDE_NUMBER = "segment_lecture_unit_slide_number"


def init_lecture_transcription_schema(client: WeaviateClient) -> Collection:
    if client.collections.exists(LectureTranscriptionSchema.COLLECTION_NAME.value):
        return client.collections.get(LectureTranscriptionSchema.COLLECTION_NAME.value)

    return client.collections.create(
        name=LectureTranscriptionSchema.COLLECTION_NAME.value,
        vectorizer_config=Configure.Vectorizer.none(),
        vector_index_config=Configure.VectorIndex.hnsw(
            distance_metric=VectorDistances.COSINE
        ),
        properties=[
            Property(
                name=LectureTranscriptionSchema.COURSE_ID.value,
                description="The ID of the course",
                data_type=DataType.INT,
                index_searable=False,
            ),
            Property(
                name=LectureTranscriptionSchema.COURSE_NAME.value,
                description="The name of the course",
                data_type=DataType.TEXT,
                index_searchable=False,
            ),
            Property(
                name=LectureTranscriptionSchema.LECTURE_ID.value,
                description="The ID of the lecture",
                data_type=DataType.INT,
                index_searchable=False,
            ),
            Property(
                name=LectureTranscriptionSchema.LECTURE_NAME.value,
                description="The name of the lecture",
                data_type=DataType.TEXT,
                index_searchable=False,
            ),
            Property(
                name=LectureTranscriptionSchema.LANGUAGE.value,
                description="The language of the text",
                data_type=DataType.TEXT,
                index_searchable=False,
            ),
            Property(
                name=LectureTranscriptionSchema.SEGMENT_START.value,
                description="The start of the segment",
                data_type=DataType.NUMBER,
                index_searchable=False,
            ),
            Property(
                name=LectureTranscriptionSchema.SEGMENT_END.value,
                description="The end of the segment",
                data_type=DataType.NUMBER,
                index_searchable=False,
            ),
            Property(
                name=LectureTranscriptionSchema.SEGMENT_TEXT.value,
                description="The transcription of the segment",
                data_type=DataType.TEXT,
                index_searchable=True,
            ),
            Property(
                name=LectureTranscriptionSchema.SEGMENT_LECTURE_UNIT_SLIDES_ID.value,
                description="The id of the lecture unit slides of the segment",
                data_type=DataType.INT,
                index_searchable=False,
            ),
            Property(
                name=LectureTranscriptionSchema.SEGMENT_LECTURE_UNIT_SLIDE_NUMBER.value,
                description="The slide number of the lecture unit of the segment",
                data_type=DataType.INT,
                index_searchable=False,
            ),
        ],
    )
