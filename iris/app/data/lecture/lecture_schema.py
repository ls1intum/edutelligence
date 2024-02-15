import weaviate.classes as wvc
from weaviate import WeaviateClient
from weaviate.collections import Collection


COLLECTION_NAME = "LectureSlides"


# Potential improvement:
# Don't store the names of the courses, lectures, and units for every single chunk
# These can be looked up via the IDs when needed - query Artemis? or store locally?


class LectureSlideChunk:
    PAGE_CONTENT = "page_content"  # The only property which will be embedded
    COURSE_ID = "course_id"
    COURSE_NAME = "course_name"
    LECTURE_ID = "lecture_id"
    LECTURE_NAME = "lecture_name"
    LECTURE_UNIT_ID = "lecture_unit_id"  # The attachment unit ID in Artemis
    LECTURE_UNIT_NAME = "lecture_unit_name"
    FILENAME = "filename"
    PAGE_NUMBER = "page_number"


def init_schema(client: WeaviateClient) -> Collection:
    if client.collections.exists(COLLECTION_NAME):
        return client.collections.get(COLLECTION_NAME)
    return client.collections.create(
        name=COLLECTION_NAME,
        vectorizer_config=wvc.config.Configure.Vectorizer.none(),  # We do not want to vectorize the text automatically
        # HNSW is preferred over FLAT for large amounts of data, which is the case here
        vector_index_config=wvc.config.Configure.VectorIndex.hnsw(
            distance_metric=wvc.config.VectorDistances.COSINE  # select preferred distance metric
        ),
        # The properties are like the columns of a table in a relational database
        properties=[
            wvc.config.Property(
                name=LectureSlideChunk.PAGE_CONTENT,
                description="The original text content from the slide",
                data_type=wvc.config.DataType.TEXT,
            ),
            wvc.config.Property(
                name=LectureSlideChunk.COURSE_ID,
                description="The ID of the course",
                data_type=wvc.config.DataType.INT,
            ),
            wvc.config.Property(
                name=LectureSlideChunk.COURSE_NAME,
                description="The name of the course",
                data_type=wvc.config.DataType.TEXT,
            ),
            wvc.config.Property(
                name=LectureSlideChunk.LECTURE_ID,
                description="The ID of the lecture",
                data_type=wvc.config.DataType.INT,
            ),
            wvc.config.Property(
                name=LectureSlideChunk.LECTURE_NAME,
                description="The name of the lecture",
                data_type=wvc.config.DataType.TEXT,
            ),
            wvc.config.Property(
                name=LectureSlideChunk.LECTURE_UNIT_ID,
                description="The ID of the lecture unit",
                data_type=wvc.config.DataType.INT,
            ),
            wvc.config.Property(
                name=LectureSlideChunk.LECTURE_UNIT_NAME,
                description="The name of the lecture unit",
                data_type=wvc.config.DataType.TEXT,
            ),
            wvc.config.Property(
                name=LectureSlideChunk.FILENAME,
                description="The name of the file from which the slide was extracted",
                data_type=wvc.config.DataType.TEXT,
            ),
            wvc.config.Property(
                name=LectureSlideChunk.PAGE_NUMBER,
                description="The page number of the slide",
                data_type=wvc.config.DataType.INT,
            ),
        ],
    )
