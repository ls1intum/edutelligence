from typing import Any

from weaviate import WeaviateClient
from weaviate.classes.query import Filter

from iris.common.logging_config import get_logger
from iris.domain.search.lecture_search_dto import (
    CourseInfo,
    LectureInfo,
    LectureSearchResultDTO,
    LectureUnitInfo,
)
from iris.llm import LlmRequestHandler
from iris.llm.llm_configuration import resolve_model
from iris.vector_database.lecture_transcription_schema import (
    LectureTranscriptionSchema,
    init_lecture_transcription_schema,
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

# Segments whose summary starts with this prefix are placeholders written during ingestion
# when a slide had no extractable content. They must be excluded from search results.
_EMPTY_SEGMENT_PREFIX = "There is no content"


class LectureGlobalSearchRetrieval:
    """Retrieves lecture unit segments from Weaviate using hybrid search and maps them to search result DTOs."""

    def __init__(self, client: WeaviateClient):
        embedding_model = resolve_model(
            "lecture_search_answer_pipeline", "default", "embedding", local=False
        )
        self.llm_embedding = LlmRequestHandler(model_id=embedding_model)
        self.collection = init_lecture_unit_segment_schema(client)
        self.lecture_unit_collection = init_lecture_unit_schema(client)
        self.transcription_collection = init_lecture_transcription_schema(client)

    def search(self, query: str, limit: int) -> list[LectureSearchResultDTO]:
        """
        Search for lecture content based on a query.

        :param query: The search query.
        :param limit: The maximum number of results to return.
        :return: Segments sorted by relevance.
        """
        query_embedding = self.llm_embedding.embed(query)
        return self._run_hybrid_search(
            query=query, vector=query_embedding, alpha=0.9, limit=limit
        )

    def search_with_vector_override(
        self, query: str, vector_text: str, alpha: float, limit: int
    ) -> list[LectureSearchResultDTO]:
        """
        Search using a custom text to generate the search vector, while keeping the
        original query for BM25 keyword matching. Used by HyDE: pass the hypothetical
        answer as ``vector_text`` so the semantic search operates in answer-space.

        :param query: The original query used for BM25 keyword matching.
        :param vector_text: The text to embed and use as the semantic search vector.
        :param alpha: Hybrid search weight (1.0 = pure semantic, 0.0 = pure keyword).
        :param limit: The maximum number of results to return.
        :return: Segments sorted by relevance.
        """
        vector = self.llm_embedding.embed(vector_text)
        return self._run_hybrid_search(
            query=query, vector=vector, alpha=alpha, limit=limit
        )

    def _run_hybrid_search(
        self, query: str, vector: list[float], alpha: float, limit: int
    ) -> list[LectureSearchResultDTO]:
        """Run a hybrid search and map results to DTOs."""
        results = self.collection.query.hybrid(
            query=query,
            alpha=alpha,
            vector=vector,
            limit=limit,
        ).objects

        # Collect unique lecture_unit_ids and fetch all metadata in one batch query
        unit_ids = list(
            {
                obj.properties.get(LectureUnitSegmentSchema.LECTURE_UNIT_ID.value)
                for obj in results
                if obj.properties.get(LectureUnitSegmentSchema.LECTURE_UNIT_ID.value)
                is not None
            }
        )
        lu_by_id = self._fetch_lecture_units(unit_ids)

        unit_page_pairs = [
            (
                obj.properties[LectureUnitSegmentSchema.LECTURE_UNIT_ID.value],
                obj.properties[LectureUnitSegmentSchema.PAGE_NUMBER.value],
            )
            for obj in results
            if obj.properties.get(LectureUnitSegmentSchema.LECTURE_UNIT_ID.value)
            is not None
            and obj.properties.get(LectureUnitSegmentSchema.PAGE_NUMBER.value)
            is not None
        ]
        start_times = self._fetch_transcription_start_times(unit_page_pairs)

        search_results = []
        for obj in results:
            result = self._to_search_result_dto(obj.properties, lu_by_id, start_times)
            if result is not None:
                search_results.append(result)
        return search_results

    def _fetch_transcription_start_times(
        self, unit_page_pairs: list[tuple[int, int]]
    ) -> dict[tuple[int, int], int]:
        """Fetch the earliest start_time (seconds) from LectureTranscriptions for each (unit_id, page_number) pair."""
        if not unit_page_pairs:
            return {}
        requested = set(unit_page_pairs)
        unit_ids = list({uid for uid, _ in unit_page_pairs})
        transcriptions = self.transcription_collection.query.fetch_objects(
            filters=Filter.by_property(
                LectureTranscriptionSchema.LECTURE_UNIT_ID.value
            ).contains_any(unit_ids),
            limit=500,
        ).objects
        times: dict[tuple[int, int], int] = {}
        for t in transcriptions:
            props = t.properties
            uid = props.get(LectureTranscriptionSchema.LECTURE_UNIT_ID.value)
            page = props.get(LectureTranscriptionSchema.PAGE_NUMBER.value)
            start = props.get(LectureTranscriptionSchema.SEGMENT_START_TIME.value)
            if uid is None or page is None or start is None:
                continue
            key = (uid, page)
            if key not in requested:
                continue
            if key not in times or start < times[key]:
                times[key] = int(start)
        return times

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
        segment_props: dict[str, Any],
        lu_by_id: dict[int, Any],
        start_times: dict[tuple[int, int], int],
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
        page_number = segment_props[LectureUnitSegmentSchema.PAGE_NUMBER.value]
        start_time = start_times.get((unit_id, page_number))

        return LectureSearchResultDTO(
            course=CourseInfo(
                id=course_id,
                name=lu[LectureUnitSchema.COURSE_NAME.value],
            ),
            lecture=LectureInfo(
                id=lecture_id,
                name=lu[LectureUnitSchema.LECTURE_NAME.value],
            ),
            lectureUnit=LectureUnitInfo(
                id=unit_id,
                name=lu[LectureUnitSchema.LECTURE_UNIT_NAME.value],
                link=f"/courses/{course_id}/lectures/{lecture_id}",
                pageNumber=page_number,
                startTime=start_time,
            ),
            snippet=snippet,
        )
