from weaviate import WeaviateClient
from weaviate.classes.query import Filter

from iris.common.logging_config import get_logger
from iris.domain.search.lecture_search_dto import LectureSearchResultDTO
from iris.llm.request_handler.model_version_request_handler import (
    ModelVersionRequestHandler,
)
from iris.vector_database.lecture_unit_schema import (
    LectureUnitSchema,
    init_lecture_unit_schema,
)
from iris.vector_database.lecture_unit_segment_schema import (
    LectureUnitSegmentSchema,
    init_lecture_unit_segment_schema,
)

logger = get_logger(__name__)

_EMPTY_SEGMENT_PREFIX = "There is no content"


class LectureGlobalSearchRetrieval:
    """Retrieves lecture unit segments from Weaviate using hybrid search and maps them to search result DTOs."""

    def __init__(self, client: WeaviateClient):
        self.llm_embedding = ModelVersionRequestHandler("text-embedding-3-small")
        self.collection = init_lecture_unit_segment_schema(client)
        self.lecture_unit_collection = init_lecture_unit_schema(client)

    def search(self, query: str, limit: int) -> list[LectureSearchResultDTO]:
        """
        Search for lecture content based on a query.

        :param query: The search query.
        :param limit: The maximum number of results to return.
        :return: Segments sorted by relevance.
        """
        query_embedding = self.llm_embedding.embed(query)

        results = self.collection.query.hybrid(
            query=query,
            alpha=0.9,
            vector=query_embedding,
            limit=limit,
        ).objects

        search_results = []
        for obj in results:
            result = self._to_search_result_dto(obj.properties)
            if result is not None:
                search_results.append(result)
        return search_results

    def _to_search_result_dto(self, segment_props) -> LectureSearchResultDTO | None:
        """Fetch lecture unit metadata and map segment properties to a result DTO."""
        snippet = segment_props[LectureUnitSegmentSchema.SEGMENT_SUMMARY.value]
        if not snippet or snippet.startswith(_EMPTY_SEGMENT_PREFIX):
            return None

        lecture_unit_filter = (
            Filter.by_property(LectureUnitSchema.COURSE_ID.value).equal(
                segment_props[LectureUnitSegmentSchema.COURSE_ID.value]
            )
            & Filter.by_property(LectureUnitSchema.LECTURE_ID.value).equal(
                segment_props[LectureUnitSegmentSchema.LECTURE_ID.value]
            )
            & Filter.by_property(LectureUnitSchema.LECTURE_UNIT_ID.value).equal(
                segment_props[LectureUnitSegmentSchema.LECTURE_UNIT_ID.value]
            )
        )
        lecture_units = self.lecture_unit_collection.query.fetch_objects(
            filters=lecture_unit_filter
        ).objects
        if not lecture_units:
            return None

        lu = lecture_units[0].properties
        base_url = segment_props[LectureUnitSegmentSchema.BASE_URL.value]
        course_id = segment_props[LectureUnitSegmentSchema.COURSE_ID.value]
        lecture_id = segment_props[LectureUnitSegmentSchema.LECTURE_ID.value]

        return LectureSearchResultDTO(
            lecture_unit_id=segment_props[
                LectureUnitSegmentSchema.LECTURE_UNIT_ID.value
            ],
            lecture_unit_name=lu[LectureUnitSchema.LECTURE_UNIT_NAME.value],
            lecture_unit_link=f"{base_url}/courses/{course_id}/lectures/{lecture_id}",
            lecture_id=lecture_id,
            lecture_name=lu[LectureUnitSchema.LECTURE_NAME.value],
            course_id=course_id,
            course_name=lu[LectureUnitSchema.COURSE_NAME.value],
            base_url=base_url,
            page_number=segment_props[LectureUnitSegmentSchema.PAGE_NUMBER.value],
            snippet=snippet,
        )
