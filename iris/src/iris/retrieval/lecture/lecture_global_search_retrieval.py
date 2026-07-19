import re
import time
from collections import Counter
from typing import Any

from weaviate import WeaviateClient
from weaviate.classes.query import Filter, MetadataQuery

from iris.common.logging_config import get_logger
from iris.config import settings
from iris.domain.search.lecture_search_dto import (
    CourseInfo,
    LectureInfo,
    LectureSearchResultDTO,
    LectureUnitInfo,
)
from iris.llm import LlmRequestHandler
from iris.llm.llm_configuration import LlmConfigurationError, resolve_model
from iris.llm.llm_manager import LlmManager
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

# Qwen3-Embedding is instruction-tuned for ASYMMETRIC retrieval: the query is
# embedded with this instruction prefix while documents stay raw (ingestion must
# never use it — both sides shifting cancels the benefit). The wording keeps the
# scaffold the model was trained on ("Given a ... query, retrieve ... passages
# that answer the query") with the domain injected: student queries against
# lecture materials, covering both question-type queries ("answer") and
# navigational/topic queries ("cover").
QWEN3_RETRIEVAL_INSTRUCTION = (
    "Instruct: Given a search query from a university student, retrieve relevant "
    "passages from lecture materials that answer or cover the query\nQuery: "
)

# Default hybrid weight: the instruct-prefixed vector separates relevant content
# far better than BM25 on this substrate (census A/B), so lean semantic.
_DEFAULT_ALPHA = 0.75

# Content-quality filter applied to every hit's snippet at query time, regardless
# of collection: placeholder summaries written during ingestion ("There is no
# content...", "no spoken content") and micro-content carry no information for
# either the results list or the answer context.
_LOW_INFO_MIN_CHARS = 25
_LOW_INFO_PATTERNS = re.compile(
    r"^there is no content"  # ingestion placeholder (empty slide)
    r"|no spoken content"  # transcription placeholder (silent/music video)
    r"|solely of repeated"  # music-only / repeated-symbol transcriptions
    r"|single (word|phrase|character|letter)",  # one-word junk slides
    re.IGNORECASE,
)

# Weaviate autocut groups for the generation path: cut each sub-search at its
# natural score cliffs so the answer LLM's context is not padded with
# below-cliff distractors. Not applied to the UI results list.
_AUTOCUT_GROUPS = 2

# Near-duplicate slides (the same deck ingested by several courses) are collapsed
# by comparing this many leading snippet characters.
_DEDUP_KEY_CHARS = 100

# --- Two-stage retrieval (recall lanes -> shared reranker) ------------------ #
# Per-lane candidate depth. Weaviate search cost is flat (~5-10ms) at this depth
# and the fused order only selects CANDIDATES now — the reranker does the final
# ordering on one calibrated scale, so recall depth is nearly free quality.
_LANE_DEPTH = 25
# Upper bound on candidates sent to the reranker (one search unit covers 100).
_RERANK_MAX_CANDIDATES = 60
# Hard wall-clock bound on the rerank call: on timeout the search falls back to
# the fused ordering instead of blocking the request.
_RERANK_TIMEOUT_S = 4.0
# Reranker roles tried in order: a global-search-specific role first, then the
# lecture-chat reranker that existing deployments already configure.
_RERANKER_ROLES = [
    ("global_search_pipeline", "reranker"),
    ("lecture_retrieval_pipeline", "reranker"),
]


def _is_low_information(snippet: str) -> bool:
    stripped = snippet.strip()
    if len(stripped) < _LOW_INFO_MIN_CHARS:
        return True
    return bool(_LOW_INFO_PATTERNS.search(stripped))


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
        self.reranker_model_id = self._resolve_reranker(local)

    @staticmethod
    def _resolve_reranker(local: bool) -> str | None:
        """Resolve the reranker model id, or None to run without reranking."""
        for pipeline_id, role in _RERANKER_ROLES:
            try:
                return resolve_model(pipeline_id, "default", role, local=local)
            except LlmConfigurationError:
                continue
        logger.info("[LectureSearch] no reranker configured — using fused ordering")
        return None

    def embed_retrieval_query(self, query: str) -> list[float]:
        """Embed a USER QUERY with the Qwen3 retrieval instruction prefix.

        Query-side only (asymmetric retrieval): documents are ingested raw and
        must stay raw. Do not use this for document- or answer-like text — the
        HyDE hypothetical answer is document-shaped and is embedded raw.
        """
        return self.llm_embedding.embed(QWEN3_RETRIEVAL_INSTRUCTION + query)

    def search(
        self,
        query: str,
        limit: int,
        alpha: float = _DEFAULT_ALPHA,
        course_ids: list[int] | None = None,
        auto_cut: bool = False,
    ) -> list[LectureSearchResultDTO]:
        """
        Search for lecture content based on a query.

        :param query: The search query (embedded with the retrieval instruction).
        :param limit: The maximum number of results to return.
        :param alpha: Hybrid search weight (1.0 = pure semantic, 0.0 = pure keyword).
        :param course_ids: Optional list of course IDs to restrict the search scope.
                           When None, searches all ingested courses (global search).
        :param auto_cut: Cut each sub-search at its natural score cliff (use for
                         generation contexts, not for the UI results list).
        :return: Segments sorted by relevance.
        """
        query_embedding = self.embed_retrieval_query(query)
        return self._run_hybrid_search(
            query=query,
            vectors=[query_embedding],
            alpha=alpha,
            limit=limit,
            course_ids=course_ids,
            auto_cut=auto_cut,
        )

    def search_with_vector_override(
        self,
        query: str,
        vector_text: str,
        alpha: float,
        limit: int,
        course_ids: list[int] | None = None,
        auto_cut: bool = False,
    ) -> list[LectureSearchResultDTO]:
        """
        Search using a custom text to generate the search vector, while keeping the
        original query for BM25 keyword matching. Used by HyDE: pass the hypothetical
        answer as ``vector_text`` so the semantic search operates in answer-space.
        The vector text is embedded RAW (no retrieval instruction) — it is
        document-shaped, and stored documents are raw.

        :param query: The original query used for BM25 keyword matching.
        :param vector_text: The text to embed and use as the semantic search vector.
        :param alpha: Hybrid search weight (1.0 = pure semantic, 0.0 = pure keyword).
        :param limit: The maximum number of results to return.
        :param course_ids: Optional list of course IDs to restrict the search scope.
        :param auto_cut: Cut each sub-search at its natural score cliff.
        :return: Segments sorted by relevance.
        """
        vector = self.llm_embedding.embed(vector_text)
        return self._run_hybrid_search(
            query=query,
            vectors=[vector],
            alpha=alpha,
            limit=limit,
            course_ids=course_ids,
            auto_cut=auto_cut,
        )

    def search_dual(
        self,
        query: str,
        hyde_text: str | None,
        alpha: float,
        limit: int,
        course_ids: list[int] | None = None,
        auto_cut: bool = False,
    ) -> list[LectureSearchResultDTO]:
        """Dual-vector candidate retrieval for the AI answer path.

        Runs the recall lanes with BOTH the instruct-prefixed query embedding
        (deterministic baseline) and, when available, the raw-embedded HyDE
        hypothetical answer, then unions the candidates. A drifted or off-topic
        HyDE output can therefore never make retrieval worse than the
        deterministic baseline — the reranker arbitrates the union.
        The two embedding calls run in parallel: each costs ~400ms against the
        gateway, and sequential execution would put both on the critical path.
        """
        if hyde_text and hyde_text.strip():
            with TracedThreadPoolExecutor(max_workers=2) as executor:
                query_future = executor.submit(self.embed_retrieval_query, query)
                hyde_future = executor.submit(self.llm_embedding.embed, hyde_text)
            vectors = [query_future.result(), hyde_future.result()]
        else:
            vectors = [self.embed_retrieval_query(query)]
        return self._run_hybrid_search(
            query=query,
            vectors=vectors,
            alpha=alpha,
            limit=limit,
            course_ids=course_ids,
            auto_cut=auto_cut,
        )

    def _run_hybrid_search(
        self,
        query: str,
        vectors: list[list[float]],
        alpha: float,
        limit: int,
        course_ids: list[int] | None = None,
        auto_cut: bool = False,
    ) -> list[LectureSearchResultDTO]:
        """Run the recall lanes for every vector, union, and map results to DTOs."""
        # Phase 1: all lane searches in parallel (2 collections x N vectors).
        # Lanes fetch CANDIDATES at _LANE_DEPTH; the final ordering is decided by
        # the reranker (or the fused scores when no reranker is available).
        auto_limit = _AUTOCUT_GROUPS if auto_cut else None
        lane_depth = max(limit, _LANE_DEPTH)
        t_search = time.perf_counter()
        with TracedThreadPoolExecutor(max_workers=2 * len(vectors)) as executor:
            seg_futures = [
                executor.submit(
                    self._search_segments,
                    query,
                    vec,
                    alpha,
                    lane_depth,
                    course_ids,
                    auto_limit,
                )
                for vec in vectors
            ]
            trans_futures = [
                executor.submit(
                    self._search_video_transcriptions,
                    query,
                    vec,
                    alpha,
                    lane_depth,
                    course_ids,
                    auto_limit,
                )
                for vec in vectors
            ]
        seg_objects = self._union_by_uuid([f.result() for f in seg_futures])
        trans_objects = self._union_by_uuid([f.result() for f in trans_futures])
        search_ms = (time.perf_counter() - t_search) * 1000
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
        t_meta = time.perf_counter()
        with TracedThreadPoolExecutor(max_workers=2) as executor:
            lecture_unit_future = executor.submit(
                self._fetch_lecture_units, all_unit_ids
            )
            ts_future = executor.submit(
                self._fetch_transcription_start_times, unit_page_pairs
            )
        lecture_unit_by_id = lecture_unit_future.result()
        transcription_start_times = ts_future.result()
        meta_ms = (time.perf_counter() - t_meta) * 1000
        logger.debug("unit_page_pairs: %s", unit_page_pairs)
        logger.debug("transcription_start_times: %s", transcription_start_times)

        # Map to DTOs, attach scores, sort, take top limit. Hits that cannot be
        # mapped are counted per reason: silent drops here directly shrink the
        # result list the user sees, so they must be visible in the logs.
        scored: list[tuple[float, LectureSearchResultDTO]] = []
        drop_counts: Counter = Counter()
        drop_details: list[str] = []

        def _record_drop(kind: str, reason: str | None, props: dict[str, Any]) -> None:
            drop_counts[f"{kind}_{reason}"] += 1
            if len(drop_details) < 10:
                course = props.get("course_id")
                unit = props.get("lecture_unit_id")
                base_url = props.get("base_url")
                drop_details.append(
                    f"{kind}:{reason} course={course} unit={unit} base_url={base_url}"
                )

        for obj in seg_objects:
            dto, drop_reason = self._segment_to_dto(
                obj.properties, lecture_unit_by_id, transcription_start_times
            )
            if dto is None:
                _record_drop("seg", drop_reason, obj.properties)
                continue
            score = (
                obj.metadata.score
                if obj.metadata and obj.metadata.score is not None
                else 0.0
            )
            scored.append((score, dto))

        for obj in trans_objects:
            dto, drop_reason = self._transcription_to_dto(
                obj.properties, lecture_unit_by_id
            )
            if dto is None:
                _record_drop("trans", drop_reason, obj.properties)
                continue
            score = (
                obj.metadata.score
                if obj.metadata and obj.metadata.score is not None
                else 0.0
            )
            scored.append((score, dto))

        scored.sort(key=lambda x: x[0], reverse=True)

        # Collapse near-identical slides (same deck ingested by several courses):
        # keep the highest-scoring copy so the list carries distinct evidence.
        deduped: list[tuple[float, LectureSearchResultDTO]] = []
        seen_keys: set[str] = set()
        for score, dto in scored:
            key = (dto.snippet or "")[:_DEDUP_KEY_CHARS].casefold().strip()
            if key in seen_keys:
                drop_counts["duplicate_snippet"] += 1
                continue
            seen_keys.add(key)
            deduped.append((score, dto))

        # Stage 2: shared reranker over the candidate union. Fused scores are
        # per-collection-normalized and mutually incomparable; the cross-encoder
        # rescores every candidate against the query on ONE calibrated scale.
        # On any failure the search falls back to the fused ordering. Generation
        # contexts (auto_cut=True) are always reranked; the instant results list
        # only when configured — it trades the reranker's latency for mid-list
        # ranking quality.
        candidates = deduped[:_RERANK_MAX_CANDIDATES]
        use_rerank = auto_cut or settings.global_search_rerank_results_list
        rerank_scores = (
            self._safe_rerank(query, [dto for _, dto in candidates])
            if use_rerank
            else None
        )
        rerank_ms: float | None = None
        if rerank_scores is not None:
            rerank_ms, relevance = rerank_scores
            reranked = sorted(
                zip(relevance, (dto for _, dto in candidates)),
                key=lambda x: x[0],
                reverse=True,
            )
            threshold = settings.global_search_rerank_threshold
            kept = [(rel, dto) for rel, dto in reranked if rel >= threshold]
            below = len(reranked) - len(kept)
            if below:
                drop_counts["below_rerank_threshold"] += below
            top = kept[:limit]
        else:
            top = deduped[:limit]

        logger.info(
            "[LectureSearch] query=%r course_ids=%s alpha=%.2f auto_cut=%s "
            "raw_hits=%d+%d mapped=%d dropped=%s reranked=%s rerank_ms=%s hits=%d "
            "search_ms=%.0f meta_ms=%.0f",
            query,
            course_ids,
            alpha,
            auto_cut,
            len(seg_objects),
            len(trans_objects),
            len(scored),
            dict(drop_counts) or "none",
            rerank_scores is not None,
            f"{rerank_ms:.0f}" if rerank_ms is not None else "n/a",
            len(top),
            search_ms,
            meta_ms,
        )
        for detail in drop_details:
            logger.info("[LectureSearch]   dropped %s", detail)
        score_label = "rerank" if rerank_scores is not None else "fused"
        for rank, (score, dto) in enumerate(top, start=1):
            logger.info(
                "[LectureSearch]   #%d %s=%.4f source=%s course=%r unit=%r "
                "page=%s snippet=%r",
                rank,
                score_label,
                score,
                dto.lecture_unit.source_type,
                dto.course.name,
                dto.lecture_unit.name,
                dto.lecture_unit.page_number,
                (dto.snippet or "")[:120],
            )
        return [dto for _, dto in top]

    @staticmethod
    def _union_by_uuid(result_lists: list[list[Any]]) -> list[Any]:
        """Union Weaviate hit lists from multiple vector runs, first-seen wins.

        Lists are consumed in order, so hits from the first vector's run keep
        their position; later runs only contribute unseen objects. Ordering is
        only a fallback concern — the reranker rescores the union anyway.
        """
        seen: set[Any] = set()
        union: list[Any] = []
        for objects in result_lists:
            for obj in objects:
                if obj.uuid in seen:
                    continue
                seen.add(obj.uuid)
                union.append(obj)
        return union

    def _safe_rerank(
        self, query: str, candidates: list[LectureSearchResultDTO]
    ) -> tuple[float, list[float]] | None:
        """Rerank candidate snippets; return (duration_ms, per-candidate relevance).

        Returns None when no reranker is configured, on any API failure, or on
        timeout — the caller then falls back to the fused ordering, so the search
        can never degrade below pre-reranker behavior. Deliberately does NOT
        disable itself process-wide on failure (unlike RerankRequestHandler).
        """
        if self.reranker_model_id is None or len(candidates) < 2:
            return None
        documents = [
            (dto.snippet or dto.lecture_unit.name or "")[:2000] for dto in candidates
        ]
        t0 = time.perf_counter()
        try:
            client = LlmManager().get_llm_by_id(self.reranker_model_id)
            if client is None:
                return None
            # No `with` block: __exit__ would join the worker thread and a hung
            # rerank call would then block past the timeout. shutdown(wait=False)
            # lets the request move on while the stray call finishes in background.
            executor = TracedThreadPoolExecutor(max_workers=1)
            try:
                future = executor.submit(
                    client.rerank,
                    query=query,
                    documents=documents,
                    top_n=len(documents),
                )
                response = future.result(timeout=_RERANK_TIMEOUT_S)
            finally:
                executor.shutdown(wait=False)
            results = list(getattr(response, "results", None) or [])
            if not results:
                return None
            relevance = [0.0] * len(documents)
            for item in results:
                relevance[item.index] = float(item.relevance_score)
            return (time.perf_counter() - t0) * 1000, relevance
        except Exception as e:  # noqa: BLE001 - rerank is best-effort by design
            logger.warning(
                "[LectureSearch] rerank_failed model=%s after_ms=%.0f error=%s "
                "— falling back to fused ordering",
                self.reranker_model_id,
                (time.perf_counter() - t0) * 1000,
                str(e)[:200],
            )
            return None

    def _search_segments(
        self,
        query: str,
        vector: list[float],
        alpha: float,
        limit: int,
        course_ids: list[int] | None = None,
        auto_limit: int | None = None,
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
            auto_limit=auto_limit,
            return_metadata=MetadataQuery(score=True),
        ).objects

    def _search_video_transcriptions(
        self,
        query: str,
        vector: list[float],
        alpha: float,
        limit: int,
        course_ids: list[int] | None = None,
        auto_limit: int | None = None,
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
            auto_limit=auto_limit,
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
        """Fetch lecture unit metadata for the given IDs in a single Weaviate query.

        The limit is deliberately larger than ``len(unit_ids)``: multiple Artemis
        instances can share one Weaviate, their numeric unit ids collide, and one
        id may map to several LectureUnits rows. With ``limit=len(unit_ids)``
        those duplicates crowd out other requested ids, which then look like
        missing metadata and get their hits silently dropped.
        """
        if not unit_ids:
            return {}
        lecture_units = self.lecture_unit_collection.query.fetch_objects(
            filters=Filter.by_property(
                LectureUnitSchema.LECTURE_UNIT_ID.value
            ).contains_any(unit_ids),
            limit=max(100, len(unit_ids) * 10),
        ).objects
        result = {
            lecture_unit.properties[
                LectureUnitSchema.LECTURE_UNIT_ID.value
            ]: lecture_unit.properties
            for lecture_unit in lecture_units
        }
        missing = set(unit_ids) - set(result)
        if len(lecture_units) > len(result) or missing:
            logger.info(
                "[LectureSearch] lecture_units_fetch requested=%d rows=%d "
                "distinct=%d duplicate_rows=%d missing_ids=%s",
                len(unit_ids),
                len(lecture_units),
                len(result),
                len(lecture_units) - len(result),
                sorted(missing) or "none",
            )
        return result

    @staticmethod
    def _segment_to_dto(
        props: dict[str, Any],
        lecture_unit_by_id: dict[int, Any],
        transcription_start_times: dict[tuple[int, int], float],
    ) -> tuple[LectureSearchResultDTO | None, str | None]:
        """Map a segment hit to a DTO; on failure return (None, drop_reason)."""
        snippet = props.get(LectureUnitSegmentSchema.SEGMENT_SUMMARY.value)
        if not snippet:
            return None, "no_snippet"
        if _is_low_information(snippet):
            return None, "low_information"

        unit_id = props.get(LectureUnitSegmentSchema.LECTURE_UNIT_ID.value)
        lecture_unit = lecture_unit_by_id.get(unit_id) if unit_id is not None else None
        if lecture_unit is None:
            return None, "missing_unit_metadata"

        course_id = props.get(LectureUnitSegmentSchema.COURSE_ID.value)
        lecture_id = props.get(LectureUnitSegmentSchema.LECTURE_ID.value)
        page_number = props.get(LectureUnitSegmentSchema.PAGE_NUMBER.value)
        if (
            course_id is None
            or lecture_id is None
            or page_number is None
            or page_number < 0
        ):
            return None, "bad_page_or_ids"

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

        return (
            LectureSearchResultDTO(
                course=CourseInfo(
                    id=course_id, name=lecture_unit[LectureUnitSchema.COURSE_NAME.value]
                ),
                lecture=LectureInfo(
                    id=lecture_id,
                    name=lecture_unit[LectureUnitSchema.LECTURE_NAME.value],
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
            ),
            None,
        )

    @staticmethod
    def _transcription_to_dto(
        props: dict[str, Any],
        lecture_unit_by_id: dict[int, Any],
    ) -> tuple[LectureSearchResultDTO | None, str | None]:
        """Map a transcription hit to a DTO; on failure return (None, drop_reason)."""
        snippet = props.get(
            LectureTranscriptionSchema.SEGMENT_SUMMARY.value
        ) or props.get(LectureTranscriptionSchema.SEGMENT_TEXT.value)
        if not snippet:
            return None, "no_snippet"
        if _is_low_information(snippet):
            return None, "low_information"

        unit_id = props.get(LectureTranscriptionSchema.LECTURE_UNIT_ID.value)
        lecture_unit = lecture_unit_by_id.get(unit_id) if unit_id is not None else None
        if lecture_unit is None:
            return None, "missing_unit_metadata"

        course_id = props.get(LectureTranscriptionSchema.COURSE_ID.value)
        lecture_id = props.get(LectureTranscriptionSchema.LECTURE_ID.value)
        start_time = props.get(LectureTranscriptionSchema.SEGMENT_START_TIME.value)
        if course_id is None or lecture_id is None or start_time is None:
            return None, "missing_fields"

        start_time = float(start_time)
        minutes = int(start_time // 60)
        seconds = int(start_time % 60)

        return (
            LectureSearchResultDTO(
                course=CourseInfo(
                    id=course_id, name=lecture_unit[LectureUnitSchema.COURSE_NAME.value]
                ),
                lecture=LectureInfo(
                    id=lecture_id,
                    name=lecture_unit[LectureUnitSchema.LECTURE_NAME.value],
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
            ),
            None,
        )
