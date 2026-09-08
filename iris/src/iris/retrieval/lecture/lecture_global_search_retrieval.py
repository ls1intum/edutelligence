from dataclasses import dataclass
from datetime import datetime
from typing import Any

from weaviate import WeaviateClient
from weaviate.classes.query import Filter, MetadataQuery

from iris.common.logging_config import get_logger
from iris.domain.search.global_search_dto import (
    AccessContext,
    CourseInfo,
    LectureInfo,
    LectureSearchResultDTO,
    LectureUnitInfo,
)
from iris.llm import LlmRequestHandler
from iris.llm.llm_configuration import resolve_model
from iris.retrieval.lecture.lecture_visibility import (
    is_segment_visible,
    is_transcription_visible,
    is_unit_released,
)
from iris.tracing import TracedThreadPoolExecutor
from iris.vector_database.lecture_transcription_schema import (
    LectureTranscriptionSchema,
    init_lecture_transcription_schema,
)
from iris.vector_database.lecture_unit_page_chunk_schema import (
    LectureUnitPageChunkSchema,
    init_lecture_unit_page_chunk_schema,
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


@dataclass(frozen=True)
class _VisibilityPolicy:
    """Per-search visibility decision derived from the Artemis access context.

    Mirrors Artemis lecture-unit visibility: admins (``unrestricted``) and staff of a
    course see units regardless of release date; everyone else is gated on the unit's
    release date evaluated at ``now`` (the Artemis request time, not the Pyris clock).
    Slide-level ``hidden_until`` is enforced for all roles and is never bypassed here.
    """

    now: datetime | None
    unrestricted: bool
    staff_course_ids: frozenset[int]

    @classmethod
    def from_context(cls, ctx: AccessContext | None) -> "_VisibilityPolicy":
        if ctx is None:
            return cls(now=None, unrestricted=False, staff_course_ids=frozenset())
        return cls(
            now=ctx.effective_now_dt(),
            unrestricted=ctx.unrestricted,
            staff_course_ids=frozenset(ctx.staff_course_ids),
        )

    def release_bypassed(self, course_id: Any) -> bool:
        """Whether the unit-level release-date gate is waived for this course."""
        return self.unrestricted or (
            course_id is not None and course_id in self.staff_course_ids
        )


def resolve_effective_course_ids(
    course_ids: list[int] | None, ctx: AccessContext | None
) -> list[int] | None:
    """Intersect the user's course filter with the courses the access context permits.

    Returns None (no course ceiling) when there is no access context or the context is
    unrestricted (admin). An empty list means the user has no accessible courses.
    """
    if ctx is None or ctx.unrestricted:
        return course_ids
    if course_ids is None:
        return ctx.course_ids
    allowed = set(ctx.course_ids)
    return [course_id for course_id in course_ids if course_id in allowed]


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
        self.page_chunk_collection = init_lecture_unit_page_chunk_schema(client)
        self.transcription_collection = init_lecture_transcription_schema(client)

    def search(
        self,
        query: str,
        limit: int,
        alpha: float = 0.5,
        course_ids: list[int] | None = None,
        access_context: AccessContext | None = None,
    ) -> list[LectureSearchResultDTO]:
        """
        Search for lecture content based on a query.

        :param query: The search query.
        :param limit: The maximum number of results to return.
        :param alpha: Hybrid search weight (1.0 = pure semantic, 0.0 = pure keyword).
        :param course_ids: Optional list of course IDs to restrict the search scope.
                           When None, searches all ingested courses (global search).
        :param access_context: Optional permissions filter resolved by Artemis. Intersected
                               with course_ids; an empty accessible scope skips the search.
        :return: Segments sorted by relevance.
        """
        effective_course_ids = resolve_effective_course_ids(course_ids, access_context)
        if effective_course_ids is not None and not effective_course_ids:
            logger.debug(
                "Access context yields no accessible courses; skipping search."
            )
            return []
        query_embedding = self.llm_embedding.embed(query)
        return self._run_hybrid_search(
            query=query,
            vector=query_embedding,
            alpha=alpha,
            limit=limit,
            course_ids=effective_course_ids,
            policy=_VisibilityPolicy.from_context(access_context),
        )

    def search_with_vector_override(
        self,
        query: str,
        vector_text: str,
        alpha: float,
        limit: int,
        course_ids: list[int] | None = None,
        access_context: AccessContext | None = None,
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
        :param access_context: Optional permissions filter resolved by Artemis. Intersected
                               with course_ids; an empty accessible scope skips the search.
        :return: Segments sorted by relevance.
        """
        effective_course_ids = resolve_effective_course_ids(course_ids, access_context)
        if effective_course_ids is not None and not effective_course_ids:
            logger.debug(
                "Access context yields no accessible courses; skipping search."
            )
            return []
        vector = self.llm_embedding.embed(vector_text)
        return self._run_hybrid_search(
            query=query,
            vector=vector,
            alpha=alpha,
            limit=limit,
            course_ids=effective_course_ids,
            policy=_VisibilityPolicy.from_context(access_context),
        )

    def _run_hybrid_search(
        self,
        query: str,
        vector: list[float],
        alpha: float,
        limit: int,
        course_ids: list[int] | None = None,
        policy: "_VisibilityPolicy | None" = None,
    ) -> list[LectureSearchResultDTO]:
        """Run hybrid searches, expanding candidates until visible results are filled."""
        if policy is None:
            policy = _VisibilityPolicy.from_context(None)
        candidate_limit = max(limit, 1)
        while True:
            with TracedThreadPoolExecutor(max_workers=2) as executor:
                seg_future = executor.submit(
                    self._search_segments,
                    query,
                    vector,
                    alpha,
                    candidate_limit,
                    course_ids,
                )
                trans_future = executor.submit(
                    self._search_video_transcriptions,
                    query,
                    vector,
                    alpha,
                    candidate_limit,
                    course_ids,
                )
            seg_objects = seg_future.result()
            trans_objects = trans_future.result()
            logger.debug(
                "Segment hits: %d | Transcription hits: %d",
                len(seg_objects),
                len(trans_objects),
            )
            scored = self._map_search_objects(seg_objects, trans_objects, policy)
            segment_scored = [
                item
                for item in scored
                if item[1].lecture_unit.source_type != "lecture_unit_video"
            ]
            transcription_scored = [
                item
                for item in scored
                if item[1].lecture_unit.source_type == "lecture_unit_video"
            ]
            segment_complete = (
                len(segment_scored) >= limit or len(seg_objects) < candidate_limit
            )
            transcription_complete = (
                len(transcription_scored) >= limit
                or len(trans_objects) < candidate_limit
            )
            if (
                segment_complete and transcription_complete
            ) or candidate_limit >= 10_000:
                scored.sort(key=lambda item: item[0], reverse=True)
                return [dto for _, dto in scored[:limit]]
            candidate_limit = min(candidate_limit * 2, 10_000)

    def _map_search_objects(
        self,
        seg_objects: list[Any],
        trans_objects: list[Any],
        policy: "_VisibilityPolicy",
    ) -> list[tuple[float, LectureSearchResultDTO]]:
        """Map one candidate window and discard unreleased or hidden objects."""

        # Single pass over seg_objects: collect unit_ids and page_pairs together
        seg_unit_ids: set[int] = set()
        unit_page_pairs: list[tuple[str, int, int]] = []
        for obj in seg_objects:
            uid = obj.properties.get(LectureUnitSegmentSchema.LECTURE_UNIT_ID.value)
            page = obj.properties.get(LectureUnitSegmentSchema.PAGE_NUMBER.value)
            base_url = obj.properties.get(LectureUnitSegmentSchema.BASE_URL.value)
            if (
                uid is not None
                and page is not None
                and page >= 0
                and base_url is not None
            ):
                seg_unit_ids.add(uid)
                unit_page_pairs.append((base_url, uid, page))

        trans_unit_ids = {
            obj.properties.get(LectureTranscriptionSchema.LECTURE_UNIT_ID.value)
            for obj in trans_objects
            if obj.properties.get(LectureTranscriptionSchema.LECTURE_UNIT_ID.value)
            is not None
        }
        all_unit_ids = list(seg_unit_ids | trans_unit_ids)

        # Phase 2: lecture unit metadata + transcription timestamps in parallel
        with TracedThreadPoolExecutor(max_workers=3) as executor:
            lecture_unit_future = executor.submit(
                self._fetch_lecture_units, all_unit_ids
            )
            ts_future = executor.submit(
                self._fetch_transcription_start_times, unit_page_pairs
            )
            slide_future = executor.submit(
                self._fetch_slides_by_display_page, list(trans_unit_ids)
            )
        lecture_unit_by_id = lecture_unit_future.result()
        transcription_start_times = ts_future.result()
        slide_by_display_page = slide_future.result()
        logger.debug("unit_page_pairs: %s", unit_page_pairs)
        logger.debug("transcription_start_times: %s", transcription_start_times)

        scored: list[tuple[float, LectureSearchResultDTO]] = []

        for obj in seg_objects:
            dto = self._segment_to_dto(
                obj.properties, lecture_unit_by_id, transcription_start_times, policy
            )
            if dto is not None:
                score = (
                    obj.metadata.score
                    if obj.metadata and obj.metadata.score is not None
                    else 0.0
                )
                scored.append((score, dto))

        for obj in trans_objects:
            dto = self._transcription_to_dto(
                obj.properties, lecture_unit_by_id, slide_by_display_page, policy
            )
            if dto is not None:
                score = (
                    obj.metadata.score
                    if obj.metadata and obj.metadata.score is not None
                    else 0.0
                )
                scored.append((score, dto))

        return scored

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
        self, unit_page_pairs: list[tuple[str, int, int]]
    ) -> dict[tuple[str, int, int], float]:
        """Batch-fetch min start time per Artemis instance, unit, and page."""
        if not unit_page_pairs:
            return {}
        unit_ids = list({uid for _, uid, _ in unit_page_pairs})
        transcriptions = self.transcription_collection.query.fetch_objects(
            filters=Filter.by_property(
                LectureTranscriptionSchema.LECTURE_UNIT_ID.value
            ).contains_any(unit_ids),
            limit=10_000,
            return_properties=[
                LectureTranscriptionSchema.LECTURE_UNIT_ID.value,
                LectureTranscriptionSchema.PAGE_NUMBER.value,
                LectureTranscriptionSchema.BASE_URL.value,
                LectureTranscriptionSchema.SEGMENT_START_TIME.value,
            ],
        ).objects
        result: dict[tuple[str, int, int], float] = {}
        for t in transcriptions:
            props = t.properties
            uid = props.get(LectureTranscriptionSchema.LECTURE_UNIT_ID.value)
            page = props.get(LectureTranscriptionSchema.PAGE_NUMBER.value)
            base_url = props.get(LectureTranscriptionSchema.BASE_URL.value)
            start = props.get(LectureTranscriptionSchema.SEGMENT_START_TIME.value)
            if (
                uid is None
                or page is None
                or base_url is None
                or start is None
                or page == -1
            ):
                continue
            key = (str(base_url), int(uid), int(page))
            if key not in result or start < result[key]:
                result[key] = float(start)
        return result

    def _fetch_lecture_units(
        self, unit_ids: list[int]
    ) -> dict[tuple[str | None, int], Any]:
        """Fetch lecture unit metadata for the given IDs in a single Weaviate query."""
        if not unit_ids:
            return {}
        lecture_units = self.lecture_unit_collection.query.fetch_objects(
            filters=Filter.by_property(
                LectureUnitSchema.LECTURE_UNIT_ID.value
            ).contains_any(unit_ids),
            limit=10_000,
        ).objects
        return {
            (
                lecture_unit.properties.get(LectureUnitSchema.BASE_URL.value),
                lecture_unit.properties[LectureUnitSchema.LECTURE_UNIT_ID.value],
            ): lecture_unit.properties
            for lecture_unit in lecture_units
        }

    def _fetch_slides_by_display_page(
        self, unit_ids: list[int]
    ) -> dict[tuple[str | None, int, int], list[Any]]:
        if not unit_ids:
            return {}
        chunks = self.page_chunk_collection.query.fetch_objects(
            filters=Filter.by_property(
                LectureUnitPageChunkSchema.LECTURE_UNIT_ID.value
            ).contains_any(unit_ids),
            limit=10_000,
            return_properties=[
                LectureUnitPageChunkSchema.LECTURE_UNIT_ID.value,
                LectureUnitPageChunkSchema.BASE_URL.value,
                LectureUnitPageChunkSchema.PAGE_NUMBER.value,
                LectureUnitPageChunkSchema.DISPLAY_PAGE_NUMBER.value,
                LectureUnitPageChunkSchema.HIDDEN_UNTIL.value,
            ],
        ).objects
        result_by_physical_page: dict[tuple[str | None, int, int], dict[int, Any]] = {}
        for chunk in chunks:
            properties = chunk.properties
            unit_id = properties.get(LectureUnitPageChunkSchema.LECTURE_UNIT_ID.value)
            display_page = properties.get(
                LectureUnitPageChunkSchema.DISPLAY_PAGE_NUMBER.value,
                properties.get(LectureUnitPageChunkSchema.PAGE_NUMBER.value),
            )
            physical_page = properties.get(LectureUnitPageChunkSchema.PAGE_NUMBER.value)
            if unit_id is None or display_page is None or physical_page is None:
                continue
            key = (
                properties.get(LectureUnitPageChunkSchema.BASE_URL.value),
                int(unit_id),
                int(display_page),
            )
            result_by_physical_page.setdefault(key, {})[int(physical_page)] = properties
        return {
            key: list(slides_by_physical_page.values())
            for key, slides_by_physical_page in result_by_physical_page.items()
        }

    @staticmethod
    def _segment_to_dto(
        props: dict[str, Any],
        lecture_unit_by_id: dict[tuple[str | None, int], Any],
        transcription_start_times: dict[tuple[str, int, int], float],
        policy: "_VisibilityPolicy | None" = None,
    ) -> LectureSearchResultDTO | None:
        if policy is None:
            policy = _VisibilityPolicy.from_context(None)
        if not is_segment_visible(props, policy.now):
            return None

        snippet = props.get(LectureUnitSegmentSchema.SEGMENT_SUMMARY.value)
        if not snippet or snippet.startswith(_EMPTY_SEGMENT_PREFIX):
            return None

        unit_id = props.get(LectureUnitSegmentSchema.LECTURE_UNIT_ID.value)
        base_url = props.get(LectureUnitSegmentSchema.BASE_URL.value)
        course_id = props.get(LectureUnitSegmentSchema.COURSE_ID.value)
        lecture_unit = (
            lecture_unit_by_id.get((base_url, unit_id)) if unit_id is not None else None
        )
        if lecture_unit is None or (
            not policy.release_bypassed(course_id)
            and not is_unit_released(lecture_unit, policy.now)
        ):
            return None

        lecture_id = props.get(LectureUnitSegmentSchema.LECTURE_ID.value)
        page_number = props.get(LectureUnitSegmentSchema.PAGE_NUMBER.value)
        if (
            course_id is None
            or lecture_id is None
            or page_number is None
            or page_number < 0
        ):
            return None

        start_time = transcription_start_times.get(
            (str(base_url), int(unit_id), int(page_number))
        )
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
        lecture_unit_by_id: dict[tuple[str | None, int], Any],
        slide_by_display_page: (
            dict[tuple[str | None, int, int], list[Any]] | None
        ) = None,
        policy: "_VisibilityPolicy | None" = None,
    ) -> LectureSearchResultDTO | None:
        if policy is None:
            policy = _VisibilityPolicy.from_context(None)
        snippet = props.get(
            LectureTranscriptionSchema.SEGMENT_SUMMARY.value
        ) or props.get(LectureTranscriptionSchema.SEGMENT_TEXT.value)
        if not snippet:
            return None

        unit_id = props.get(LectureTranscriptionSchema.LECTURE_UNIT_ID.value)
        base_url = props.get(LectureTranscriptionSchema.BASE_URL.value)
        lecture_unit = (
            lecture_unit_by_id.get((base_url, unit_id)) if unit_id is not None else None
        )
        page_number = props.get(LectureTranscriptionSchema.PAGE_NUMBER.value)
        course_id = props.get(LectureTranscriptionSchema.COURSE_ID.value)
        associated_slide = None
        if slide_by_display_page is not None and page_number is not None:
            try:
                associated_slide = slide_by_display_page.get(
                    (base_url, int(unit_id), int(page_number))
                )
            except (TypeError, ValueError):
                return None
        if lecture_unit is None or not is_transcription_visible(
            props,
            lecture_unit,
            associated_slide,
            now=policy.now,
            bypass_release=policy.release_bypassed(course_id),
        ):
            return None

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
