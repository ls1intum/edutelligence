from typing import Any

from weaviate import WeaviateClient
from weaviate.classes.query import Filter, MetadataQuery

from iris.common.logging_config import get_logger
from iris.domain.search.lecture_search_dto import (
    CourseInfo,
    LectureInfo,
    LectureSearchResultDTO,
    LectureUnitInfo,
)
from iris.llm import LlmRequestHandler
from iris.llm.llm_configuration import resolve_model
from iris.tracing import TracedThreadPoolExecutor
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
    """Retrieves lecture content from Weaviate using hybrid search across two collections:
    LectureUnitSegments (slide-based) and LectureTranscriptions (video-only segments with
    no associated slide). Both searches run in parallel and results are merged by score.
    """

    def __init__(self, client: WeaviateClient, local: bool = False):
        embedding_model = resolve_model(
            "global_search_pipeline", "default", "embedding", local=local
        )
        self.llm_embedding = LlmRequestHandler(model_id=embedding_model)
        self.collection = init_lecture_unit_segment_schema(client)
        self.lecture_unit_collection = init_lecture_unit_schema(client)
        self.transcription_collection = init_lecture_transcription_schema(client)

    def search(
        self,
        query: str,
        limit: int,
        alpha: float = 0.5,
        course_ids: list[int] | None = None,
    ) -> list[LectureSearchResultDTO]:
        """
        Search for lecture content based on a query.

        :param query: The search query.
        :param limit: The maximum number of results to return.
        :param alpha: Hybrid search weight (1.0 = pure semantic, 0.0 = pure keyword).
        :param course_ids: Optional list of course IDs to restrict the search scope.
                           When None, searches all ingested courses (global search).
        :return: Segments sorted by relevance.
        """
        query_embedding = self.llm_embedding.embed(query)
        return self._run_hybrid_search(
            query=query,
            vector=query_embedding,
            alpha=alpha,
            limit=limit,
            course_ids=course_ids,
        )

    def search_with_vector_override(
        self,
        query: str,
        vector_text: str,
        alpha: float,
        limit: int,
        course_ids: list[int] | None = None,
    ) -> list[LectureSearchResultDTO]:
        """
        Search using a custom text to generate the search vector, while keeping the
        original query for BM25 keyword matching. Used by HyDE: pass the hypothetical
        answer as ``vector_text`` so the semantic search operates in answer-space.

        :param query: The original query used for BM25 keyword matching.
        :param vector_text: The text to embed and use as the semantic search vector.
        :param alpha: Hybrid search weight (1.0 = pure semantic, 0.0 = pure keyword).
        :param limit: The maximum number of results to return.
        :param course_ids: Optional list of course IDs to restrict the search scope.
        :return: Segments sorted by relevance.
        """
        vector = self.llm_embedding.embed(vector_text)
        return self._run_hybrid_search(
            query=query, vector=vector, alpha=alpha, limit=limit, course_ids=course_ids
        )

    def _run_hybrid_search(
        self,
        query: str,
        vector: list[float],
        alpha: float,
        limit: int,
        course_ids: list[int] | None = None,
    ) -> list[LectureSearchResultDTO]:
        """Run a hybrid search and map results to DTOs."""
        # Phase 1: both hybrid searches in parallel
        with TracedThreadPoolExecutor(max_workers=2) as executor:
            seg_future = executor.submit(
                self._search_segments, query, vector, alpha, limit, course_ids
            )
            trans_future = executor.submit(
                self._search_video_transcriptions,
                query,
                vector,
                alpha,
                limit,
                course_ids,
            )
        seg_objects = seg_future.result()
        trans_objects = trans_future.result()
        logger.debug(
            "Segment hits: %d | Transcription hits: %d",
            len(seg_objects),
            len(trans_objects),
        )

        # Single pass over seg_objects: collect unit_ids and page_pairs together
        seg_unit_ids: set[int] = set()
        unit_page_pairs: list[tuple[int, int]] = []
        for obj in seg_objects:
            uid = obj.properties.get(LectureUnitSegmentSchema.LECTURE_UNIT_ID.value)
            page = obj.properties.get(LectureUnitSegmentSchema.PAGE_NUMBER.value)
            if uid is not None and page is not None and page >= 0:
                seg_unit_ids.add(uid)
                unit_page_pairs.append((uid, page))

        trans_unit_ids = {
            obj.properties.get(LectureTranscriptionSchema.LECTURE_UNIT_ID.value)
            for obj in trans_objects
            if obj.properties.get(LectureTranscriptionSchema.LECTURE_UNIT_ID.value)
            is not None
        }
        all_unit_ids = list(seg_unit_ids | trans_unit_ids)

        # Phase 2: lecture unit metadata + transcription timestamps in parallel
        with TracedThreadPoolExecutor(max_workers=2) as executor:
            lecture_unit_future = executor.submit(
                self._fetch_lecture_units, all_unit_ids
            )
            ts_future = executor.submit(
                self._fetch_transcription_start_times, unit_page_pairs
            )
        lecture_unit_by_id = lecture_unit_future.result()
        transcription_start_times = ts_future.result()
        logger.debug("unit_page_pairs: %s", unit_page_pairs)
        logger.debug("transcription_start_times: %s", transcription_start_times)

        # Map to DTOs, attach scores, sort, take top limit
        scored: list[tuple[float, LectureSearchResultDTO]] = []

        for obj in seg_objects:
            dto = self._segment_to_dto(
                obj.properties, lecture_unit_by_id, transcription_start_times
            )
            if dto is not None:
                score = (
                    obj.metadata.score
                    if obj.metadata and obj.metadata.score is not None
                    else 0.0
                )
                scored.append((score, dto))

        for obj in trans_objects:
            dto = self._transcription_to_dto(obj.properties, lecture_unit_by_id)
            if dto is not None:
                score = (
                    obj.metadata.score
                    if obj.metadata and obj.metadata.score is not None
                    else 0.0
                )
                scored.append((score, dto))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [dto for _, dto in scored[:limit]]

    def _search_segments(
        self,
        query: str,
        vector: list[float],
        alpha: float,
        limit: int,
        course_ids: list[int] | None = None,
    ) -> list[Any]:
        filters = (
            Filter.by_property(LectureUnitSegmentSchema.COURSE_ID.value).contains_any(
                course_ids
            )
            if course_ids
            else None
        )
        return self.collection.query.hybrid(
            query=query,
            alpha=alpha,
            vector=vector,
            filters=filters,
            limit=limit,
            return_metadata=MetadataQuery(score=True),
        ).objects

    def _search_video_transcriptions(
        self,
        query: str,
        vector: list[float],
        alpha: float,
        limit: int,
        course_ids: list[int] | None = None,
    ) -> list[Any]:
        """Search LectureTranscriptions restricted to segments with no associated slide
        (page_number == -1). These are video-only moments not captured in any segment.
        """
        page_filter = Filter.by_property(
            LectureTranscriptionSchema.PAGE_NUMBER.value
        ).equal(-1)
        if course_ids:
            course_filter = Filter.by_property(
                LectureTranscriptionSchema.COURSE_ID.value
            ).contains_any(course_ids)
            filters = Filter.all_of([page_filter, course_filter])
        else:
            filters = page_filter
        return self.transcription_collection.query.hybrid(
            query=query,
            alpha=alpha,
            vector=vector,
            filters=filters,
            limit=limit,
            return_metadata=MetadataQuery(score=True),
        ).objects

    def _fetch_transcription_start_times(
        self, unit_page_pairs: list[tuple[int, int]]
    ) -> dict[tuple[int, int], float]:
        """Batch-fetch min start_time per (unit_id, page_number) for slide-sync detection."""
        if not unit_page_pairs:
            return {}
        unit_ids = list({uid for uid, _ in unit_page_pairs})
        transcriptions = self.transcription_collection.query.fetch_objects(
            filters=Filter.by_property(
                LectureTranscriptionSchema.LECTURE_UNIT_ID.value
            ).contains_any(unit_ids),
            limit=10_000,
        ).objects
        result: dict[tuple[int, int], float] = {}
        for t in transcriptions:
            props = t.properties
            uid = props.get(LectureTranscriptionSchema.LECTURE_UNIT_ID.value)
            page = props.get(LectureTranscriptionSchema.PAGE_NUMBER.value)
            start = props.get(LectureTranscriptionSchema.SEGMENT_START_TIME.value)
            if uid is None or page is None or start is None or page == -1:
                continue
            key = (int(uid), int(page))
            if key not in result or start < result[key]:
                result[key] = float(start)
        return result

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
            lecture_unit.properties[
                LectureUnitSchema.LECTURE_UNIT_ID.value
            ]: lecture_unit.properties
            for lecture_unit in lecture_units
        }

    @staticmethod
    def _segment_to_dto(
        props: dict[str, Any],
        lecture_unit_by_id: dict[int, Any],
        transcription_start_times: dict[tuple[int, int], float],
    ) -> LectureSearchResultDTO | None:
        snippet = props.get(LectureUnitSegmentSchema.SEGMENT_SUMMARY.value)
        if not snippet or snippet.startswith(_EMPTY_SEGMENT_PREFIX):
            return None

        unit_id = props.get(LectureUnitSegmentSchema.LECTURE_UNIT_ID.value)
        lecture_unit = lecture_unit_by_id.get(unit_id) if unit_id is not None else None
        if lecture_unit is None:
            return None

        course_id = props.get(LectureUnitSegmentSchema.COURSE_ID.value)
        lecture_id = props.get(LectureUnitSegmentSchema.LECTURE_ID.value)
        page_number = props.get(LectureUnitSegmentSchema.PAGE_NUMBER.value)
        if (
            course_id is None
            or lecture_id is None
            or page_number is None
            or page_number < 0
        ):
            return None

        start_time = transcription_start_times.get((int(unit_id), int(page_number)))
        if start_time is not None:
            source_type = "lecture_unit_slide_video"
            query_params: dict[str, str | int | float] = {
                "unit": unit_id,
                "page": page_number,
                "timestamp": start_time,
            }
            minutes = int(start_time // 60)
            seconds = int(start_time % 60)
            display_meta = f"p. {page_number} · {minutes}:{seconds:02d}"
        else:
            source_type = "lecture_unit_slide"
            query_params = {"unit": unit_id, "page": page_number}
            display_meta = f"p. {page_number}"

        return LectureSearchResultDTO(
            course=CourseInfo(
                id=course_id, name=lecture_unit[LectureUnitSchema.COURSE_NAME.value]
            ),
            lecture=LectureInfo(
                id=lecture_id, name=lecture_unit[LectureUnitSchema.LECTURE_NAME.value]
            ),
            lectureUnit=LectureUnitInfo(
                id=unit_id,
                name=lecture_unit[LectureUnitSchema.LECTURE_UNIT_NAME.value],
                link=f"/courses/{course_id}/lectures/{lecture_id}",
                pageNumber=page_number,
                sourceType=source_type,
                queryParams=query_params,
                displayMeta=display_meta,
            ),
            snippet=snippet,
        )

    @staticmethod
    def _transcription_to_dto(
        props: dict[str, Any],
        lecture_unit_by_id: dict[int, Any],
    ) -> LectureSearchResultDTO | None:
        snippet = props.get(
            LectureTranscriptionSchema.SEGMENT_SUMMARY.value
        ) or props.get(LectureTranscriptionSchema.SEGMENT_TEXT.value)
        if not snippet:
            return None

        unit_id = props.get(LectureTranscriptionSchema.LECTURE_UNIT_ID.value)
        lecture_unit = lecture_unit_by_id.get(unit_id) if unit_id is not None else None
        if lecture_unit is None:
            return None

        course_id = props.get(LectureTranscriptionSchema.COURSE_ID.value)
        lecture_id = props.get(LectureTranscriptionSchema.LECTURE_ID.value)
        start_time = props.get(LectureTranscriptionSchema.SEGMENT_START_TIME.value)
        if course_id is None or lecture_id is None or start_time is None:
            return None

        start_time = float(start_time)
        minutes = int(start_time // 60)
        seconds = int(start_time % 60)

        return LectureSearchResultDTO(
            course=CourseInfo(
                id=course_id, name=lecture_unit[LectureUnitSchema.COURSE_NAME.value]
            ),
            lecture=LectureInfo(
                id=lecture_id, name=lecture_unit[LectureUnitSchema.LECTURE_NAME.value]
            ),
            lectureUnit=LectureUnitInfo(
                id=unit_id,
                name=lecture_unit[LectureUnitSchema.LECTURE_UNIT_NAME.value],
                link=f"/courses/{course_id}/lectures/{lecture_id}",
                pageNumber=-1,
                sourceType="lecture_unit_video",
                queryParams={"unit": unit_id, "timestamp": start_time},
                displayMeta=f"{minutes}:{seconds:02d}",
            ),
            snippet=snippet,
        )
