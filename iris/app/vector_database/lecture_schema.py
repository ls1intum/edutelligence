from enum import Enum

from weaviate.classes.config import Property, ReferenceProperty
from weaviate import WeaviateClient
from weaviate.collections import Collection
from weaviate.collections.classes.config import Configure, VectorDistances, DataType

from app.vector_database.lecture_slide_schema import LectureUnitPageChunkSchema
from app.vector_database.lecture_transcription_schema import LectureTranscriptionSchema


class LectureUnitSegmentSchema(Enum):
    """
    Schema for the lectures
    """
    COLLECTION_NAME = "Lecture_unit_segments"
    COURSE_ID = "course_id"
    LECTURE_ID = "lecture_id"
    LECTURE_UNIT_ID = "lecture_unit_id"
    CONTENT = "content"
    SLIDE_NUMBER = "slide_number"
    TRANSCRIPTIONS = "transcriptions"
    SLIDES = "slides"

def init_lecture_schema(client: WeaviateClient) -> Collection:
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
                name=LectureUnitSegmentSchema.CONTENT.value,
                description="The content of the lecture slide",
                data_type=DataType.TEXT,
                index_searchable=True,
            ),
            Property(
                name=LectureUnitSegmentSchema.SLIDE_NUMBER.value,
                description="The slide number of the summary",
                data_type=DataType.INT,
                index_searchable=False,
            )
        ],
        references=[
            ReferenceProperty(
                name=LectureUnitSegmentSchema.TRANSCRIPTIONS.value,
                target_collection=LectureTranscriptionSchema.COLLECTION_NAME.value,
            ),
            ReferenceProperty(
                name=LectureUnitSegmentSchema.SLIDES.value,
                target_collection=LectureUnitPageChunkSchema.COLLECTION_NAME.value,
            )
        ]
    )