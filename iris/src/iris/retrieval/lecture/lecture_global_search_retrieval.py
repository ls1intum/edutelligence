from datetime import timezone
from typing import Any

from weaviate import WeaviateClient
from weaviate.classes.query import Filter, MetadataQuery

from iris.common.logging_config import get_logger
from iris.domain.search.lecture_search_dto import (
    AccessContext,
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
        course_ids: list[int] | None = None,
        access_context: AccessContext | None = None,
    ) -> list[tuple[float, LectureSearchResultDTO]]:
        ctx = access_context
        effective_course_ids = course_ids if ctx is None else ctx.course_ids
        logger.info("[LectureSearch] course_ids filter=%s", effective_course_ids)
        if effective_course_ids is not None and len(effective_course_ids) == 0:
            logger.info(
                "[LectureSearch] user has no accessible courses — returning nothing"
            )
            return []
        query_embedding = self.llm_embedding.embed(query)
        return self._run_hybrid_search(
            query=query,
            vector=query_embedding,
            alpha=0.5,
            limit=limit,
            course_ids=effective_course_ids,
            access_context=ctx,
        )

    def search_with_vector_override(
        self,
        query: str,
        vector_text: str,
        alpha: float,
        limit: int,
        course_ids: list[int] | None = None,
        access_context: AccessContext | None = None,
    ) -> list[tuple[float, LectureSearchResultDTO]]:
        """Used by HyDE: embed ``vector_text`` for semantic search while keeping
        ``query`` for BM25 keyword matching."""
        ctx = access_context
        effective_course_ids = course_ids if ctx is None else ctx.course_ids
        logger.info("[LectureSearch/HyDE] course_ids filter=%s", effective_course_ids)
        if effective_course_ids is not None and len(effective_course_ids) == 0:
            logger.info(
                "[LectureSearch/HyDE] user has no accessible courses — returning nothing"
            )
            return []
        vector = self.llm_embedding.embed(vector_text)
        return self._run_hybrid_search(
            query=query,
            vector=vector,
            alpha=alpha,
            limit=limit,
            course_ids=effective_course_ids,
            access_context=ctx,
        )

    def _run_hybrid_search(
        self,
        query: str,
        vector: list[float],
        alpha: float,
        limit: int,
        course_ids: list[int] | None = None,
        access_context: AccessContext | None = None,
    ) -> list[tuple[float, LectureSearchResultDTO]]:
        course_filter = (
            Filter.by_property(LectureUnitSegmentSchema.COURSE_ID.value).contains_any(
                course_ids
            )
            if course_ids
            else None
        )

        # Phase 1: both hybrid searches in parallel
        with TracedThreadPoolExecutor(max_workers=2) as executor:
            seg_future = executor.submit(
                self._search_segments, query, vector, alpha, limit, course_filter
            )
            trans_future = executor.submit(
                self._search_video_transcriptions,
                query,
                vector,
                alpha,
                limit,
                course_filter,
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

        # SYNC[global-search-access-filters]: mirrors GlobalSearchResource.buildLectureUnitDisjunct
        # update when lecture unit visibility rules change
        if access_context is not None and access_context.student_course_ids:
            student_set = set(access_context.student_course_ids)
            now_str = access_context.effective_now()
            to_remove = set()
            for unit_id, props in lecture_unit_by_id.items():
                course_id = props.get(LectureUnitSchema.COURSE_ID.value)
                if course_id not in student_set:
                    continue
                release_date = props.get(LectureUnitSchema.RELEASE_DATE.value)
                if release_date is None:
                    continue
                if hasattr(release_date, "isoformat"):
                    rd = (
                        release_date
                        if release_date.tzinfo
                        else release_date.replace(tzinfo=timezone.utc)
                    )
                    if rd.isoformat() > now_str:
                        to_remove.add(unit_id)
            for uid in to_remove:
                del lecture_unit_by_id[uid]
            if to_remove:
                logger.info(
                    "[LectureSearch] filtered %d unreleased unit(s)", len(to_remove)
                )

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
        top = scored[:limit]
        final_with_scores: list[tuple[float, LectureSearchResultDTO]] = top
        logger.info(
            "[LectureSearch] hits=%d  results=%s",
            len(top),
            [
                f"{dto.course.name}/{dto.lecture.name}/{dto.lecture_unit.name}"
                f"(p.{dto.lecture_unit.page_number},score={score:.3f})"
                for score, dto in top
            ],
        )
        return final_with_scores

    def _search_segments(
        self,
        query: str,
        vector: list[float],
        alpha: float,
        limit: int,
        course_filter: Filter | None = None,
    ) -> list[Any]:
        return self.collection.query.hybrid(
            query=query,
            alpha=alpha,
            vector=vector,
            limit=limit,
            filters=course_filter,
            return_metadata=MetadataQuery(score=True),
        ).objects

    def _search_video_transcriptions(
        self,
        query: str,
        vector: list[float],
        alpha: float,
        limit: int,
        course_filter: Filter | None = None,
    ) -> list[Any]:
        """Search LectureTranscriptions restricted to segments with no associated slide
        (page_number == -1). These are video-only moments not captured in any segment.
        """
        page_filter = Filter.by_property(
            LectureTranscriptionSchema.PAGE_NUMBER.value
        ).equal(-1)
        combined_filter = (
            (page_filter & course_filter) if course_filter else page_filter
        )
        return self.transcription_collection.query.hybrid(
            query=query,
            alpha=alpha,
            vector=vector,
            filters=combined_filter,
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
                id=course_id,
                name="",  # enriched with current Artemis title after the final RRF merge
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
                id=course_id,
                name="",  # enriched with current Artemis title after the final RRF merge
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
