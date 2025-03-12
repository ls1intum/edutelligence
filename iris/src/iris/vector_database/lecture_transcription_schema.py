from enum import Enum

from weaviate import WeaviateClient
from weaviate.classes.config import Property
from weaviate.collections import Collection
from weaviate.collections.classes.config import Configure, DataType, VectorDistances


class LectureTranscriptionSchema(Enum):
    """
    Schema for the lecture transcriptions
    """

    COLLECTION_NAME = "LectureTranscriptions"
    COURSE_ID = "course_id"
    LECTURE_ID = "lecture_id"
    LECTURE_UNIT_ID = "lecture_unit_id"
    LANGUAGE = "language"
    SEGMENT_START_TIME = "segment_start_time"
    SEGMENT_END_TIME = "segment_end_time"
    PAGE_NUMBER = "page_number"
    SEGMENT_TEXT = "segment_text"
    SEGMENT_SUMMARY = "segment_summary"
    BASE_URL = "base_url"


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
                index_searchable=False,
            ),
            Property(
                name=LectureTranscriptionSchema.LECTURE_ID.value,
                description="The ID of the lecture",
                data_type=DataType.INT,
                index_searchable=False,
            ),
            Property(
                name=LectureTranscriptionSchema.LANGUAGE.value,
                description="The language of the text",
                data_type=DataType.TEXT,
                index_searchable=False,
            ),
            Property(
                name=LectureTranscriptionSchema.SEGMENT_START_TIME.value,
                description="The start time of the segment",
                data_type=DataType.NUMBER,
                index_searchable=False,
            ),
            Property(
                name=LectureTranscriptionSchema.SEGMENT_END_TIME.value,
                description="The end time of the segment",
                data_type=DataType.NUMBER,
                index_searchable=False,
            ),
            Property(
                name=LectureTranscriptionSchema.LECTURE_UNIT_ID.value,
                description="The id of the lecture unit of the transcription",
                data_type=DataType.INT,
                index_searchable=False,
            ),
            Property(
                name=LectureTranscriptionSchema.PAGE_NUMBER.value,
                description="The page number of the lecture unit of the segment",
                data_type=DataType.INT,
                index_searchable=False,
            ),
            Property(
                name=LectureTranscriptionSchema.SEGMENT_TEXT.value,
                description="The transcription of the segment",
                data_type=DataType.TEXT,
                index_searchable=True,
            ),
            Property(
                name=LectureTranscriptionSchema.SEGMENT_SUMMARY.value,
                description="The summary of the text of the segment",
                data_type=DataType.TEXT,
                index_searchable=True,
            ),
            Property(
                name=LectureTranscriptionSchema.BASE_URL.value,
                description="The base url of the website where the lecture unit is hosted",
                data_type=DataType.TEXT,
                index_searchable=False,
            ),
        ],
    )
