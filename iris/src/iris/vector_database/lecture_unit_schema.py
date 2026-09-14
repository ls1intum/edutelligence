from enum import Enum

from weaviate import WeaviateClient
from weaviate.classes.config import Property
from weaviate.collections import Collection
from weaviate.collections.classes.config import (
    Configure,
    DataType,
    VectorDistances,
)
from weaviate.exceptions import UnexpectedStatusCodeError, WeaviateInvalidInputError


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
    RELEASE_DATE = "release_date"
    SLIDE_VISIBILITY = "slide_visibility"
    CONTENT_FINGERPRINT = "content_fingerprint"
    INGESTION_RUN_ID = "ingestion_run_id"
    EXPECTED_CHUNK_COUNTS = "expected_chunk_counts"
    PIPELINE_VERSION = "ingestion_pipeline_version"
    QUALITY_SCORE = "quality_score"
    QUALITY_FLAGS = "quality_flags"


def _ledger_properties() -> list[Property]:
    """Properties of the per-unit ingestion ledger stamped by the write path."""
    return [
        Property(
            name=LectureUnitSchema.CONTENT_FINGERPRINT.value,
            description="Fingerprint of the ingested source content, stamped verbatim as sent by Artemis",
            data_type=DataType.TEXT,
            index_searchable=False,
        ),
        Property(
            name=LectureUnitSchema.INGESTION_RUN_ID.value,
            description=(
                "Id of the ingestion run that wrote this row; rows of "
                "other runs are swept after a successful write"
            ),
            data_type=DataType.TEXT,
            index_searchable=False,
        ),
        Property(
            name=LectureUnitSchema.EXPECTED_CHUNK_COUNTS.value,
            description=(
                "JSON map of page number to prepared chunk count, so "
                "completeness is verifiable below page granularity"
            ),
            data_type=DataType.TEXT,
            index_searchable=False,
        ),
        Property(
            name=LectureUnitSchema.PIPELINE_VERSION.value,
            description="Ingestion pipeline version that produced this unit's content",
            data_type=DataType.INT,
            index_searchable=False,
        ),
        Property(
            name=LectureUnitSchema.QUALITY_SCORE.value,
            description="Deterministic quality score of the ingested content (0..1)",
            data_type=DataType.NUMBER,
            index_searchable=False,
        ),
        Property(
            name=LectureUnitSchema.QUALITY_FLAGS.value,
            description="JSON list of deterministic quality findings for this unit",
            data_type=DataType.TEXT,
            index_searchable=False,
        ),
    ]


def _add_property_if_missing(collection: Collection, new_property: Property) -> None:
    def property_exists() -> bool:
        return any(
            schema_property.name == new_property.name
            for schema_property in collection.config.get(simple=True).properties
        )

    if property_exists():
        return
    try:
        collection.config.add_property(new_property)
    except (UnexpectedStatusCodeError, WeaviateInvalidInputError):
        # Another concurrent initializer may have added the property after our check.
        if not property_exists():
            raise


def init_lecture_unit_schema(client: WeaviateClient) -> Collection:
    if client.collections.exists(LectureUnitSchema.COLLECTION_NAME.value):
        collection = client.collections.get(LectureUnitSchema.COLLECTION_NAME.value)
        _add_property_if_missing(
            collection,
            Property(
                name=LectureUnitSchema.RELEASE_DATE.value,
                description="UTC release timestamp for student-level retrieval; null means released",
                data_type=DataType.DATE,
                index_searchable=False,
            ),
        )
        _add_property_if_missing(
            collection,
            Property(
                name=LectureUnitSchema.SLIDE_VISIBILITY.value,
                description="Latest serialized slide visibility snapshot from Artemis",
                data_type=DataType.TEXT,
                index_searchable=False,
            ),
        )
        _add_property_if_missing(
            collection,
            Property(
                name=LectureUnitSchema.COURSE_LANGUAGE.value,
                description="The language of the course",
                data_type=DataType.TEXT,
                index_searchable=False,
            ),
        )
        for ledger_property in _ledger_properties():
            _add_property_if_missing(collection, ledger_property)
        return collection
    return client.collections.create(
        name=LectureUnitSchema.COLLECTION_NAME.value,
        vector_config=Configure.Vectors.self_provided(
            vector_index_config=Configure.VectorIndex.hnsw(
                distance_metric=VectorDistances.COSINE
            ),
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
            Property(
                name=LectureUnitSchema.RELEASE_DATE.value,
                description="UTC release timestamp for student-level retrieval; null means released",
                data_type=DataType.DATE,
                index_searchable=False,
            ),
            Property(
                name=LectureUnitSchema.SLIDE_VISIBILITY.value,
                description="Latest serialized slide visibility snapshot from Artemis",
                data_type=DataType.TEXT,
                index_searchable=False,
            ),
            *_ledger_properties(),
        ],
    )
