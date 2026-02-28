from typing import Any

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

        # Collect unique lecture_unit_ids and fetch all metadata in one batch query
        unit_ids = list(
            {
                obj.properties[LectureUnitSegmentSchema.LECTURE_UNIT_ID.value]
                for obj in results
            }
        )
        lu_by_id = self._fetch_lecture_units(unit_ids)

        search_results = []
        for obj in results:
            result = self._to_search_result_dto(obj.properties, lu_by_id)
            if result is not None:
                search_results.append(result)
        return search_results

    def _fetch_lecture_units(self, unit_ids: list[int]) -> dict[int, Any]:
        """Fetch lecture unit metadata for the given IDs in a single Weaviate query."""
        if not unit_ids:
            return {}
        lecture_units = self.lecture_unit_collection.query.fetch_objects(
            filters=Filter.by_property(
                LectureUnitSchema.LECTURE_UNIT_ID.value
            ).contains_any(unit_ids),
            limit=len(unit_ids),
        ).objects
        return {
            lu.properties[LectureUnitSchema.LECTURE_UNIT_ID.value]: lu.properties
            for lu in lecture_units
        }

    @staticmethod
    def _to_search_result_dto(
        segment_props, lu_by_id: dict[int, Any]
    ) -> LectureSearchResultDTO | None:
        """Map segment properties to a result DTO using pre-fetched lecture unit metadata."""
        snippet = segment_props[LectureUnitSegmentSchema.SEGMENT_SUMMARY.value]
        if not snippet or snippet.startswith(_EMPTY_SEGMENT_PREFIX):
            return None

        unit_id = segment_props[LectureUnitSegmentSchema.LECTURE_UNIT_ID.value]
        lu = lu_by_id.get(unit_id)
        if lu is None:
            return None

        course_id = segment_props[LectureUnitSegmentSchema.COURSE_ID.value]
        lecture_id = segment_props[LectureUnitSegmentSchema.LECTURE_ID.value]

        return LectureSearchResultDTO(
            lecture_unit_id=unit_id,
            lecture_unit_name=lu[LectureUnitSchema.LECTURE_UNIT_NAME.value],
            lecture_unit_link=f"/courses/{course_id}/lectures/{lecture_id}",
            lecture_id=lecture_id,
            lecture_name=lu[LectureUnitSchema.LECTURE_NAME.value],
            course_id=course_id,
            course_name=lu[LectureUnitSchema.COURSE_NAME.value],
            page_number=segment_props[LectureUnitSegmentSchema.PAGE_NUMBER.value],
            snippet=snippet,
        )
