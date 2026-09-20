import re
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from weaviate import WeaviateClient
from weaviate.classes.query import Filter, MetadataQuery

from iris.common.logging_config import get_logger
from iris.config import settings
from iris.domain.search.global_search_dto import (
    AccessContext,
    CourseInfo,
    EntitySourceDTO,
    LectureInfo,
    LectureSearchResultDTO,
    LectureUnitInfo,
)
from iris.llm import LlmRequestHandler
from iris.llm.llm_configuration import LlmConfigurationError, resolve_model
from iris.llm.llm_manager import LlmManager
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

# Reference value for a Qwen3-Embedding deployment's retrieval_instruction config
# field (see OpenAIEmbeddingModel), not applied automatically here. Qwen3-Embedding
# is instruction-tuned for ASYMMETRIC retrieval: the query is embedded with this
# instruction prefix while documents stay raw (ingestion must never use it — both
# sides shifting cancels the benefit). The wording keeps the scaffold the model was
# trained on ("Given a ... query, retrieve ... passages that answer the query")
# with the domain injected: student queries against lecture materials, covering
# both question-type queries ("answer") and navigational/topic queries ("cover").
QWEN3_RETRIEVAL_INSTRUCTION = (
    "Instruct: Given a search query from a university student, retrieve relevant "
    "passages from lecture materials that answer or cover the query\nQuery: "
)

# Default hybrid weight: the instruct-prefixed vector separates relevant content
# far better than BM25 on this substrate (census A/B), so lean semantic.
_DEFAULT_ALPHA = 0.75

# Weaviate autocut groups for the generation path: cut each sub-search at its
# natural score cliffs so the answer LLM's context is not padded with
# below-cliff distractors. Not applied to the UI results list.
_AUTOCUT_GROUPS = 2

# Per-search cap on per-drop detail log lines.
_MAX_DROP_DETAILS = 10

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
# Entity candidates (pre-fetched by Artemis, rendered as cards) always enter
# the rerank slice: their pre-rerank scores are meaningless, so they cannot
# compete for slice slots on fused ordering.
_MAX_ENTITY_CANDIDATES = 25
# Post-floor representation guarantee: the best above-floor hits of each kind
# keep a context slot even when the other kind sweeps the top-K. Entity cards
# are 1-2 lines (cheap context) and entity titles are ambiguous across types
# (unit/exercise/channel share names), so they get two slots; content
# snippets are ~1000 chars and get one.
_ENTITY_REPRESENTATION_SLOTS = 2
_CONTENT_REPRESENTATION_SLOTS = 1
# Entity cards offered to the navigate prompt when the floored pool is empty.
_POINTER_TIER_CAP = 3
# Hard wall-clock bound on the ANSWER-PATH rerank call: on timeout the search
# falls back to the fused ordering instead of blocking the request. The results
# list uses the shorter settings.global_search_rerank_list_timeout_s budget.
_RERANK_TIMEOUT_S = 4.0
# Reranker roles tried in order: a global-search-specific role first, then the
# lecture-chat reranker that existing deployments already configure.
_RERANKER_ROLES = [
    ("global_search_pipeline", "reranker"),
    ("lecture_retrieval_pipeline", "reranker"),
]


def resolve_reranker_model(local: bool = False) -> str | None:
    """Resolve the shared global-search reranker model id, or None if unset.

    Shared with the startup census's entity rerank rehearsal so both probe the
    exact reranker production retrieval would use.
    """
    for pipeline_id, role in _RERANKER_ROLES:
        try:
            return resolve_model(pipeline_id, "default", role, local=local)
        except LlmConfigurationError:
            continue
    logger.info("[LectureSearch] no reranker configured — using fused ordering")
    return None


@dataclass
class _SearchTelemetry:
    """Counters and timings accumulated across the search phases, emitted as
    one [LectureSearch] summary line so every hit, drop, and stage cost of a
    production query is reconstructible from a single log paste."""

    drop_counts: Counter = field(default_factory=Counter)
    drop_details: list[str] = field(default_factory=list)
    seg_hits: int = 0
    trans_hits: int = 0
    mapped: int = 0
    search_ms: float = 0.0
    meta_ms: float = 0.0
    rerank_ms: float | None = None
    reranked: bool = False
    expand_ms: float | None = None
    expanded: int = 0
    entity_candidates: int = 0
    entity_kept: int = 0
    pointer_tier: bool = False

    def record_drop(self, kind: str, reason: str | None, props: dict[str, Any]) -> None:
        self.drop_counts[f"{kind}_{reason}"] += 1
        if len(self.drop_details) < _MAX_DROP_DETAILS:
            course = props.get("course_id")
            unit = props.get("lecture_unit_id")
            base_url = props.get("base_url")
            self.drop_details.append(
                f"{kind}:{reason} course={course} unit={unit} base_url={base_url}"
            )


@dataclass
class _Candidate:
    """A scored hit plus the structural key used for graph expansion.

    The key is (base_url, course_id, lecture_unit_id) rather than the unit id
    alone: several Artemis instances can share one Weaviate and their numeric
    unit ids collide, which is the same hazard the metadata fetch guards
    against. The DTO does not carry base_url, so it is kept alongside.
    """

    score: float
    dto: LectureSearchResultDTO
    unit_key: tuple[Any, Any, Any]


_SEMESTER_PAREN_RE = re.compile(
    r"\s*\((?:ws\s?\d{2}/\d{2}|ss\s?\d{2})\)\s*$", re.IGNORECASE
)
_DATED_QUERY_RE = re.compile(
    r"(?:\bws|\bss)\s?\d{2}|\b20\d{2}\b|semester", re.IGNORECASE
)


def _strip_semester(text: str) -> str:
    stripped = (text or "").strip()
    while True:
        shorter = _SEMESTER_PAREN_RE.sub("", stripped)
        if shorter == stripped:
            return shorter.lower()
        stripped = shorter


def _twin_key(source: EntitySourceDTO) -> tuple[str, str, str]:
    course_name = source.course.name if source.course else ""
    return (
        source.entity_type,
        _strip_semester(course_name),
        _strip_semester(source.title),
    )


def _prefers_instance(
    challenger: EntitySourceDTO, incumbent: EntitySourceDTO, now: datetime
) -> bool:
    a, b = challenger.reference_date, incumbent.reference_date
    if a is None or b is None:
        return a is not None  # a dated instance beats an undatable one
    a_released, b_released = a <= now, b <= now
    if a_released != b_released:
        return a_released  # already-visible material beats future material
    if a_released:
        return a > b  # among released twins, the most recent run
    return a < b  # among future twins, the soonest upcoming


def dedupe_semester_twins(
    entity_sources: list[EntitySourceDTO],
    query: str,
    now: datetime | None = None,
) -> list[EntitySourceDTO]:
    """Collapse semester twins of a repeated course to one instance.

    Twins (same type, same suffix-stripped course and title, DIFFERENT
    course.id) are relevance ties by construction, so which one wins a
    context slot would otherwise be arbitrary — and the answer LLM cannot
    prefer the current run of a course it never sees. Among twins the most
    recent already-visible instance survives (else the soonest upcoming). A
    query that names a semester or year is exempt: the student may be
    asking about an old run.

    A course only loses its entry to a same-key winner when it is
    unambiguously the winner's twin analog: exactly one entity under this
    key. Course names are the only signal available to link semester
    instances of "the same" course, so two courses can share a key by
    coincidence rather than lineage (a generic module name reused across
    unrelated programs); a course contributing more than one entity here is
    evidence of that, not a repeated offering, so its entities are never
    discarded as a group. The same holds a fortiori for two same-titled
    entities that share ONE course.id (e.g. two exercises both called
    "Quiz") — both survive intact.
    """
    if not entity_sources or _DATED_QUERY_RE.search(query):
        return entity_sources
    now = now or datetime.now(timezone.utc)
    groups: dict[tuple[str, str, str], dict[int | None, list[EntitySourceDTO]]] = {}
    order: list[tuple[str, str, str]] = []
    for source in entity_sources:
        key = _twin_key(source)
        course_id = source.course.id if source.course else None
        if key not in groups:
            groups[key] = {}
            order.append(key)
        groups[key].setdefault(course_id, []).append(source)

    result: list[EntitySourceDTO] = []
    for key in order:
        by_course = groups[key]
        if len(by_course) == 1:
            # Every same-titled candidate shares one course (or none carry
            # course info) — nothing to pick between, keep them all.
            result.extend(next(iter(by_course.values())))
            continue
        # Multiple courses share this title: find the best-represented course
        # (comparing each course's own best instance) to prefer as the
        # current semester instance. A losing course is only dropped when it
        # has exactly one entity under this key — the unambiguous twin analog
        # of the winner. A losing course with more than one entity holds
        # entities that cannot all be "the same slot" as the winner's single
        # entry, so they are kept rather than discarded as a group.
        best_course_id, best_representative = None, None
        for course_id, items in by_course.items():
            representative = items[0]
            for other in items[1:]:
                if _prefers_instance(other, representative, now):
                    representative = other
            if best_representative is None or _prefers_instance(
                representative, best_representative, now
            ):
                best_course_id, best_representative = course_id, representative
        for course_id, items in by_course.items():
            if course_id == best_course_id or len(items) > 1:
                result.extend(items)
    return result


def _is_entity(candidate: "_Candidate") -> bool:
    return isinstance(candidate.dto, EntitySourceDTO)


def _fused_score(obj: Any) -> float:
    return (
        obj.metadata.score if obj.metadata and obj.metadata.score is not None else 0.0
    )


def _unit_key(props: dict[str, Any]) -> tuple[Any, Any, Any]:
    """Structural identity of the lecture unit a hit belongs to."""
    return (props.get("base_url"), props.get("course_id"), props.get("lecture_unit_id"))


def _course_scope_filter(
    course_id_property: str,
    course_ids: list[int] | None,
    exclude_course_ids: list[int] | None,
) -> Filter | None:
    """Build the course-scope filter for a Weaviate lane query.

    ``course_ids`` and ``exclude_course_ids`` are independent, additive
    constraints rather than alternatives: Artemis sends exclusions on their
    own precisely for the caller with no course_ids ceiling to narrow
    locally (an unrestricted caller), so both may be present, either alone,
    or neither.
    """
    clauses = []
    if course_ids:
        clauses.append(Filter.by_property(course_id_property).contains_any(course_ids))
    if exclude_course_ids:
        clauses.append(
            Filter.by_property(course_id_property).contains_none(exclude_course_ids)
        )
    if not clauses:
        return None
    return clauses[0] if len(clauses) == 1 else Filter.all_of(clauses)


def _snippet_key(dto: "LectureSearchResultDTO") -> str:
    return (dto.snippet or "")[:_DEDUP_KEY_CHARS].casefold().strip()


def _dedupe_by_snippet(
    scored: list[_Candidate],
    telemetry: _SearchTelemetry,
) -> list[_Candidate]:
    """Collapse near-identical slides (the same deck ingested by several
    courses): keep the highest-scoring copy so the list carries distinct
    evidence."""
    deduped: list[_Candidate] = []
    seen_keys: set[str] = set()
    for candidate in scored:
        key = _snippet_key(candidate.dto)
        if key in seen_keys:
            telemetry.drop_counts["duplicate_snippet"] += 1
            continue
        seen_keys.add(key)
        deduped.append(candidate)
    return deduped


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
        # Only a deployment actually serving an instruction-tuned embedding model
        # (e.g. Qwen3-Embedding) configures retrieval_instruction on that model
        # entry; every other provider (the oai-embedding-small default included)
        # leaves it unset and embeds the raw query. See OpenAIEmbeddingModel.
        self._retrieval_instruction = getattr(
            LlmManager().get_llm_by_id(embedding_model), "retrieval_instruction", None
        )
        self.collection = init_lecture_unit_segment_schema(client)
        self.lecture_unit_collection = init_lecture_unit_schema(client)
        self.page_chunk_collection = init_lecture_unit_page_chunk_schema(client)
        self.transcription_collection = init_lecture_transcription_schema(client)
        self.reranker_model_id = resolve_reranker_model(local)

    def embed_retrieval_query(self, query: str) -> list[float]:
        """Embed a USER QUERY, folding in the configured model's retrieval
        instruction if it has one (see __init__).

        Query-side only (asymmetric retrieval): documents are ingested raw and
        must stay raw — both sides carrying the instruction cancels the
        benefit. Never apply this to document-shaped text.
        """
        # getattr, not self._retrieval_instruction: many unit tests construct this
        # class via __new__ (bypassing __init__) and only stub the attributes their
        # scenario needs, so an instance without this one must still embed raw.
        instruction = getattr(self, "_retrieval_instruction", None)
        text = f"{instruction}{query}" if instruction else query
        return self.llm_embedding.embed(text)

    def search(
        self,
        query: str,
        limit: int,
        alpha: float = _DEFAULT_ALPHA,
        course_ids: list[int] | None = None,
        exclude_course_ids: list[int] | None = None,
        auto_cut: bool = False,
        access_context: AccessContext | None = None,
        entity_sources: list[EntitySourceDTO] | None = None,
    ) -> list[LectureSearchResultDTO | EntitySourceDTO]:
        """
        Search for lecture content based on a query.

        :param query: The search query (embedded with the retrieval instruction).
        :param limit: The maximum number of results to return.
        :param alpha: Hybrid search weight (1.0 = pure semantic, 0.0 = pure keyword).
        :param course_ids: Optional list of course IDs to restrict the search scope.
                           When None, searches all ingested courses (global search).
        :param exclude_course_ids: Courses to hide regardless of course_ids/access
                                   context — only needed for an unrestricted caller
                                   with no course ceiling for Artemis to narrow itself.
        :param auto_cut: Cut each sub-search at its natural score cliff (use for
                         generation contexts, not for the UI results list).
        :param access_context: Optional permissions filter resolved by Artemis. Intersected
                               with course_ids; an empty accessible scope skips the search.
        :return: Segments sorted by relevance.
        """
        effective_course_ids = resolve_effective_course_ids(course_ids, access_context)
        no_accessible_courses = (
            effective_course_ids is not None and not effective_course_ids
        )
        if no_accessible_courses:
            logger.debug(
                "Access context yields no accessible courses; skipping lecture content search."
            )
            if not entity_sources:
                return []
        if entity_sources:
            entity_sources = dedupe_semester_twins(entity_sources, query)
        # No accessible courses means no lecture content to embed a query against —
        # the embedding is skipped, but entity_sources (already authorized by
        # Artemis, independent of this course scope) still reach the rerank/gate.
        query_embedding = (
            self.embed_retrieval_query(query) if not no_accessible_courses else []
        )
        return self._run_hybrid_search(
            query=query,
            vector=query_embedding,
            alpha=alpha,
            limit=limit,
            course_ids=effective_course_ids,
            exclude_course_ids=exclude_course_ids,
            auto_cut=auto_cut,
            policy=_VisibilityPolicy.from_context(access_context),
            entity_sources=entity_sources,
            skip_content_lanes=no_accessible_courses,
        )

    def _run_hybrid_search(
        self,
        query: str,
        vector: list[float],
        alpha: float,
        limit: int,
        course_ids: list[int] | None = None,
        exclude_course_ids: list[int] | None = None,
        auto_cut: bool = False,
        policy: "_VisibilityPolicy | None" = None,
        entity_sources: list[EntitySourceDTO] | None = None,
        skip_content_lanes: bool = False,
    ) -> list["LectureSearchResultDTO | EntitySourceDTO"]:
        """Run the recall lanes, rerank the candidate pool, map to DTOs.

        ``entity_sources`` are pre-fetched, pre-authorized entity cards from
        Artemis; they join the shared rerank pool so one cross-encoder scores
        entities and content on the same calibrated scale. Their visibility
        was already decided by Artemis and is not re-checked here — so
        ``skip_content_lanes`` (no accessible courses for lecture content)
        still lets them reach the rerank/gate pipeline below.
        """
        if policy is None:
            policy = _VisibilityPolicy.from_context(None)
        telemetry = _SearchTelemetry()
        deduped = (
            []
            if skip_content_lanes
            else self._search_lanes_until_visible(
                query,
                vector,
                alpha,
                limit,
                course_ids,
                exclude_course_ids,
                auto_cut,
                policy,
                telemetry,
            )
        )
        entity_pool = [
            _Candidate(0.0, dto, (None, None, None))
            for dto in (entity_sources or [])[:_MAX_ENTITY_CANDIDATES]
        ]
        telemetry.entity_candidates = len(entity_pool)
        top = self._rerank_and_gate(
            query, deduped, limit, auto_cut, telemetry, entity_pool
        )
        # Expansion is for generation contexts only: the instant results list is
        # a ranked list by contract, and its latency budget is ~400ms.
        if auto_cut and settings.global_search_expand_units:
            top = self._expand_by_unit(top, telemetry, policy)
        self._log_results(query, course_ids, alpha, auto_cut, telemetry, top)
        return [c.dto for c in top]

    def _search_lanes_until_visible(
        self,
        query: str,
        vector: list[float],
        alpha: float,
        limit: int,
        course_ids: list[int] | None,
        exclude_course_ids: list[int] | None,
        auto_cut: bool,
        policy: "_VisibilityPolicy",
        telemetry: "_SearchTelemetry",
    ) -> list["_Candidate"]:
        """Fetch lanes and map+filter to visible candidates, expanding the lane
        depth on retry until there are enough or the lanes are exhausted.

        Release-date and slide-visibility filtering happens AFTER retrieval
        (in _segment_to_dto/_transcription_to_dto), so a fixed-depth fetch can
        be entirely consumed by unreleased or hidden rows while a visible,
        relevant result sits just beyond that depth. Each retry re-fetches
        from scratch at a doubled depth rather than incrementally, so only
        the final attempt's drop accounting is kept in telemetry — an earlier
        attempt's drops describe rows the wider, final fetch re-examines
        anyway.
        """
        lane_depth = max(limit, _LANE_DEPTH)
        depth_cap = settings.global_search_lane_depth_max
        while True:
            seg_objects, trans_objects = self._search_lanes(
                query,
                vector,
                alpha,
                lane_depth,
                course_ids,
                exclude_course_ids,
                auto_cut,
                telemetry,
            )
            exhausted = (
                len(seg_objects) < lane_depth and len(trans_objects) < lane_depth
            )
            telemetry.drop_counts = Counter()
            telemetry.drop_details = []
            units_by_id, start_times, slides_by_display_page = self._fetch_metadata(
                seg_objects, trans_objects, telemetry
            )
            scored = self._map_candidates(
                seg_objects,
                trans_objects,
                units_by_id,
                start_times,
                slides_by_display_page,
                telemetry,
                policy,
            )
            deduped = _dedupe_by_snippet(scored, telemetry)
            if len(deduped) >= limit or exhausted or lane_depth >= depth_cap:
                return deduped
            lane_depth = min(lane_depth * 2, depth_cap)

    def _search_lanes(
        self,
        query: str,
        vector: list[float],
        alpha: float,
        lane_depth: int,
        course_ids: list[int] | None,
        exclude_course_ids: list[int] | None,
        auto_cut: bool,
        telemetry: "_SearchTelemetry",
    ) -> tuple[list[Any], list[Any]]:
        """Query both collection lanes in parallel at the given candidate depth.

        The final ordering is decided by the reranker (or the fused scores
        when no reranker is available).
        """
        auto_limit = _AUTOCUT_GROUPS if auto_cut else None
        t_search = time.perf_counter()
        with TracedThreadPoolExecutor(max_workers=2) as executor:
            seg_future = executor.submit(
                self._search_segments,
                query,
                vector,
                alpha,
                lane_depth,
                course_ids,
                exclude_course_ids,
                auto_limit,
            )
            trans_future = executor.submit(
                self._search_video_transcriptions,
                query,
                vector,
                alpha,
                lane_depth,
                course_ids,
                exclude_course_ids,
                auto_limit,
            )
        seg_objects = seg_future.result()
        trans_objects = trans_future.result()
        telemetry.search_ms = (time.perf_counter() - t_search) * 1000
        telemetry.seg_hits = len(seg_objects)
        telemetry.trans_hits = len(trans_objects)
        return seg_objects, trans_objects

    def _fetch_metadata(
        self,
        seg_objects: list[Any],
        trans_objects: list[Any],
        telemetry: "_SearchTelemetry",
    ) -> tuple[
        dict[tuple[str, int], Any],
        dict[tuple[str, int, int], float],
        dict[tuple[str, int, int], list[Any]],
    ]:
        """Fetch unit metadata, slide-sync timestamps and slide visibility."""
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

        t_meta = time.perf_counter()
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
        units_by_id = lecture_unit_future.result()
        start_times = ts_future.result()
        slides_by_display_page = slide_future.result()
        telemetry.meta_ms = (time.perf_counter() - t_meta) * 1000
        return units_by_id, start_times, slides_by_display_page

    def _map_candidates(
        self,
        seg_objects: list[Any],
        trans_objects: list[Any],
        units_by_id: dict[tuple[str, int], Any],
        start_times: dict[tuple[str, int, int], float],
        slides_by_display_page: dict[tuple[str, int, int], list[Any]],
        telemetry: "_SearchTelemetry",
        policy: "_VisibilityPolicy",
    ) -> list[_Candidate]:
        """Map raw hits to scored DTOs, recording every drop with its reason.

        Silent drops here directly shrink the result list the user sees, so
        each one must be visible in the logs (this accounting is how the
        original vanishing-answer bug was found).
        """
        scored: list[_Candidate] = []
        for obj in seg_objects:
            dto, drop_reason = self._segment_to_dto(
                obj.properties, units_by_id, start_times, policy
            )
            if dto is None:
                telemetry.record_drop("seg", drop_reason, obj.properties)
                continue
            scored.append(_Candidate(_fused_score(obj), dto, _unit_key(obj.properties)))
        for obj in trans_objects:
            dto, drop_reason = self._transcription_to_dto(
                obj.properties, units_by_id, slides_by_display_page, policy
            )
            if dto is None:
                telemetry.record_drop("trans", drop_reason, obj.properties)
                continue
            scored.append(_Candidate(_fused_score(obj), dto, _unit_key(obj.properties)))
        scored.sort(key=lambda c: c.score, reverse=True)
        telemetry.mapped = len(scored)
        return scored

    def _rerank_and_gate(
        self,
        query: str,
        deduped: list[_Candidate],
        limit: int,
        auto_cut: bool,
        telemetry: "_SearchTelemetry",
        entity_pool: list[_Candidate] | None = None,
    ) -> list[_Candidate]:
        """Stage 2: shared reranker over the candidate pool, then the junk floor.

        Fused scores are per-collection-normalized and mutually incomparable;
        the cross-encoder rescores every candidate against the query on ONE
        calibrated scale. The floor then removes GARBAGE, not weak answers:
        it is calibrated against what irrelevant candidates score, so the
        surviving set is "everything plausibly worth showing", and relevance
        among survivors is decided by the ordering plus the answer LLM rather
        than by a cutoff. An all-below pool is the honest "no content exists"
        state. Deliberately NOT tuned to admit only strong matches - a cutoff
        placed inside the relevant band both deletes real answers and lands
        within the reranker's run-to-run noise, so identical requests would
        return different results. On any rerank
        failure the search falls back to the fused ordering. Generation
        contexts (auto_cut=True) are always reranked; the instant results list
        only when configured. The list also gets a tighter rerank budget: a
        slow call there delays a ~1s response (and can trip the caller's own
        timeout), while the answer path hides the same wait behind the LLM.

        Entity cards always enter the rerank slice (their pre-rerank scores
        are meaningless). After the floor, a representation pass guarantees
        the best above-floor hits of each kind a slot, and when NOTHING
        clears the floor, entity pointers from the calibrated band below it
        are admitted as navigational evidence. Without a reranker there is no
        shared scale to admit entities on, so the fused fallback returns
        content only.
        """
        entity_pool = entity_pool or []
        candidates = deduped[: _RERANK_MAX_CANDIDATES - len(entity_pool)] + entity_pool
        use_rerank = auto_cut or settings.global_search_rerank_results_list
        timeout_s = (
            _RERANK_TIMEOUT_S
            if auto_cut
            else settings.global_search_rerank_list_timeout_s
        )
        rerank_result = (
            self._safe_rerank(query, [c.dto for c in candidates], timeout_s)
            if use_rerank
            else None
        )
        if rerank_result is None:
            # Keep the ladder alive without rerank scores: entities join the
            # context in prefetch order (capped) and the answer model judges
            # them, instead of the whole entity world vanishing on a timeout.
            fallback_entities = entity_pool[:_POINTER_TIER_CAP]
            if fallback_entities:
                telemetry.entity_kept = len(fallback_entities)
            return deduped[:limit] + fallback_entities

        telemetry.rerank_ms, relevance = rerank_result
        telemetry.reranked = True
        reranked = sorted(
            (
                _Candidate(rel, c.dto, c.unit_key)
                for rel, c in zip(relevance, candidates)
            ),
            key=lambda c: c.score,
            reverse=True,
        )
        floor = settings.global_search_rerank_floor
        above = [c for c in reranked if c.score >= floor]
        below = len(reranked) - len(above)
        if below:
            telemetry.drop_counts["below_rerank_floor"] += below
        kept = above[:limit]

        # Representation pass: ranking decides ORDER, but whether a proven
        # (above-floor) candidate reaches the answer LLM at all is a
        # structural decision — for "is there an exercise about X?" twelve
        # relevant content passages must not push the one relevant exercise
        # card out of the context (same philosophy as _expand_by_unit).
        if above:
            slots = {
                True: _ENTITY_REPRESENTATION_SLOTS,
                False: _CONTENT_REPRESENTATION_SLOTS,
            }
            counts = {True: 0, False: 0}
            for candidate in kept:
                counts[_is_entity(candidate)] += 1
            for candidate in above[limit:]:
                kind = _is_entity(candidate)
                if counts[kind] < slots[kind]:
                    kept.append(candidate)
                    counts[kind] += 1
                if all(counts[k] >= slot_limit for k, slot_limit in slots.items()):
                    break
            telemetry.entity_kept = sum(1 for c in kept if _is_entity(c))

        # Pointer tier: when no entity card clears the floor, the best-ranked
        # cards are admitted from below it anyway. The floor is calibrated for
        # "does this text ANSWER the question", which correctly rejects a card
        # that merely NAMES material for a definition question (a sorting
        # exercise scores 0.03 for "what is a sorting algorithm") — but
        # whether material is ABOUT the topic is a different judgment, and it
        # belongs to the answer LLM, not a score cutoff. With an otherwise
        # empty pool the cards go alone to the navigate prompt; alongside
        # surviving content the grounded prompt (and its null-to-navigate
        # fallback) decides between answering, pointing, and declining. The
        # LLM is the junk gate for the below-floor entity world, and that
        # discrimination is measured by the negative suite in the gate.
        if entity_pool and not any(_is_entity(c) for c in kept):
            pointers = [c for c in reranked if _is_entity(c)][:_POINTER_TIER_CAP]
            if pointers:
                telemetry.pointer_tier = True
                telemetry.entity_kept = len(pointers)
                for candidate in pointers:
                    candidate.dto.via_pointer_tier = True
                kept = kept + pointers
        return kept

    def _expand_by_unit(
        self,
        kept: list[_Candidate],
        telemetry: "_SearchTelemetry",
        policy: "_VisibilityPolicy",
    ) -> list[_Candidate]:
        """Graph expansion: pull the rest of each surviving unit's material.

        Ranking is a competition, so every additional passage of an already
        identified unit has to win a slot it does not need to win - the answer
        is known to live in that unit. Measured on the scattered-scenario
        harness: at least one relevant item is returned for 93% of queries,
        but ALL of the collections holding relevant material are represented
        for only 16%, because the rest lose the ranking contest.

        So once an anchor survives the floor, its siblings are FETCHED by the
        structural key rather than ranked: a join has 100% recall by
        construction, which turns a multi-collection conjunction into the
        single question of whether the anchor was right.

        Expanded items are appended after the ranked anchors and carry their
        anchor's score, so ordering is unchanged for everything that earned
        its place.
        """
        if not kept:
            return kept
        unit_keys: list[tuple[Any, Any, Any]] = []
        for candidate in kept:
            if candidate.unit_key not in unit_keys and all(
                part is not None for part in candidate.unit_key
            ):
                unit_keys.append(candidate.unit_key)
        unit_keys = unit_keys[: settings.global_search_expand_max_units]
        if not unit_keys:
            return kept

        unit_ids = list({key[2] for key in unit_keys})
        t_expand = time.perf_counter()
        with TracedThreadPoolExecutor(max_workers=2) as executor:
            seg_future = executor.submit(
                self._fetch_unit_objects,
                self.collection,
                LectureUnitSegmentSchema,
                unit_ids,
            )
            trans_future = executor.submit(
                self._fetch_unit_objects,
                self.transcription_collection,
                LectureTranscriptionSchema,
                unit_ids,
                # A page-numbered transcription row is already represented by that
                # page's slide segment (see _search_video_transcriptions); without
                # this, the join pulls it in a second time as a duplicate
                # "video-only" moment and spends the per-unit expansion budget on it.
                Filter.by_property(LectureTranscriptionSchema.PAGE_NUMBER.value).equal(
                    -1
                ),
            )
        # Only objects whose FULL key matches an anchor: a bare unit-id match can
        # belong to a different Artemis instance sharing this Weaviate.
        wanted = set(unit_keys)
        seg_objects = [
            o for o in seg_future.result() if _unit_key(o.properties) in wanted
        ]
        trans_objects = [
            o for o in trans_future.result() if _unit_key(o.properties) in wanted
        ]
        if not seg_objects and not trans_objects:
            telemetry.expand_ms = (time.perf_counter() - t_expand) * 1000
            return kept

        units_by_id, start_times, slides_by_display_page = self._fetch_metadata(
            seg_objects, trans_objects, telemetry
        )
        siblings = self._map_candidates(
            seg_objects,
            trans_objects,
            units_by_id,
            start_times,
            slides_by_display_page,
            telemetry,
            policy,
        )

        seen = {_snippet_key(c.dto) for c in kept}
        anchor_score = {key: 0.0 for key in unit_keys}
        for candidate in kept:
            anchor_score[candidate.unit_key] = max(
                anchor_score.get(candidate.unit_key, 0.0), candidate.score
            )
        per_unit: Counter = Counter()
        added: list[_Candidate] = []
        for candidate in siblings:
            key = _snippet_key(candidate.dto)
            if key in seen or candidate.unit_key not in wanted:
                continue
            if per_unit[candidate.unit_key] >= settings.global_search_expand_per_unit:
                continue
            seen.add(key)
            per_unit[candidate.unit_key] += 1
            added.append(
                _Candidate(
                    anchor_score.get(candidate.unit_key, 0.0),
                    candidate.dto,
                    candidate.unit_key,
                )
            )
        telemetry.expand_ms = (time.perf_counter() - t_expand) * 1000
        telemetry.expanded = len(added)
        return kept + added

    @staticmethod
    def _fetch_unit_objects(
        collection: Any,
        schema: Any,
        unit_ids: list[int],
        extra_filter: Any | None = None,
    ) -> list[Any]:
        """Every object of the given units, fetched by join rather than ranked."""
        if not unit_ids:
            return []
        unit_filter = Filter.by_property(schema.LECTURE_UNIT_ID.value).contains_any(
            unit_ids
        )
        return collection.query.fetch_objects(
            filters=(
                Filter.all_of([unit_filter, extra_filter])
                if extra_filter is not None
                else unit_filter
            ),
            limit=settings.global_search_expand_fetch_limit,
        ).objects

    @staticmethod
    def _log_results(
        query: str,
        course_ids: list[int] | None,
        alpha: float,
        auto_cut: bool,
        telemetry: "_SearchTelemetry",
        top: list[_Candidate],
    ) -> None:
        """One summary line plus per-drop and per-hit detail lines."""
        logger.info(
            "[LectureSearch] query=%r course_ids=%s alpha=%.2f auto_cut=%s "
            "raw_hits=%d+%d mapped=%d dropped=%s reranked=%s rerank_ms=%s "
            "hits=%d expanded=%d entities=%d/%d pointer_tier=%s "
            "search_ms=%.0f meta_ms=%.0f expand_ms=%s",
            query,
            course_ids,
            alpha,
            auto_cut,
            telemetry.seg_hits,
            telemetry.trans_hits,
            telemetry.mapped,
            dict(telemetry.drop_counts) or "none",
            telemetry.reranked,
            f"{telemetry.rerank_ms:.0f}" if telemetry.rerank_ms is not None else "n/a",
            len(top),
            telemetry.expanded,
            telemetry.entity_kept,
            telemetry.entity_candidates,
            telemetry.pointer_tier,
            telemetry.search_ms,
            telemetry.meta_ms,
            f"{telemetry.expand_ms:.0f}" if telemetry.expand_ms is not None else "n/a",
        )
        for detail in telemetry.drop_details:
            logger.info("[LectureSearch]   dropped %s", detail)
        score_label = "rerank" if telemetry.reranked else "fused"
        for rank, candidate in enumerate(top, start=1):
            dto = candidate.dto
            if _is_entity(candidate):
                logger.info(
                    "[LectureSearch]   #%d %s=%.4f source=entity:%s course=%r "
                    "title=%r",
                    rank,
                    score_label,
                    candidate.score,
                    dto.entity_type,
                    dto.course.name if dto.course else None,
                    dto.title[:80],
                )
                continue
            logger.info(
                "[LectureSearch]   #%d %s=%.4f source=%s course=%r unit=%r "
                "page=%s snippet=%r",
                rank,
                score_label,
                candidate.score,
                dto.lecture_unit.source_type,
                dto.course.name,
                dto.lecture_unit.name,
                dto.lecture_unit.page_number,
                (dto.snippet or "")[:120],
            )

    def _safe_rerank(
        self,
        query: str,
        candidates: list["LectureSearchResultDTO | EntitySourceDTO"],
        timeout_s: float = _RERANK_TIMEOUT_S,
    ) -> tuple[float, list[float]] | None:
        """Rerank candidate snippets; return (duration_ms, per-candidate relevance).

        Returns None when no reranker is configured, on any API failure, or on
        timeout — the caller then falls back to the fused ordering, so the search
        can never degrade below pre-reranker behavior. Deliberately does NOT
        disable itself process-wide on failure (unlike RerankRequestHandler).
        """
        if self.reranker_model_id is None or not candidates:
            return None
        # Entity cards guarantee a non-empty snippet; the lecture-unit name is
        # the fallback for content DTOs only.
        documents = [
            (
                dto.snippet
                or getattr(getattr(dto, "lecture_unit", None), "name", None)
                or ""
            )[:2000]
            for dto in candidates
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
                response = future.result(timeout=timeout_s)
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
            # Log the exception TYPE too: a bare TimeoutError has an empty str(),
            # which previously logged as `error=` and hid whether the 4s tail was
            # a genuine slow call or the SDK retrying rate limits under the hood.
            logger.warning(
                "[LectureSearch] rerank_failed model=%s after_ms=%.0f "
                "timeout_s=%.1f error=%s: %s — falling back to fused ordering",
                self.reranker_model_id,
                (time.perf_counter() - t0) * 1000,
                timeout_s,
                type(e).__name__,
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
        exclude_course_ids: list[int] | None = None,
        auto_limit: int | None = None,
    ) -> list[Any]:
        filters = _course_scope_filter(
            LectureUnitSegmentSchema.COURSE_ID.value, course_ids, exclude_course_ids
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
        exclude_course_ids: list[int] | None = None,
        auto_limit: int | None = None,
    ) -> list[Any]:
        """Search LectureTranscriptions restricted to segments with no associated slide
        (page_number == -1). These are video-only moments not captured in any segment.
        """
        page_filter = Filter.by_property(
            LectureTranscriptionSchema.PAGE_NUMBER.value
        ).equal(-1)
        course_filter = _course_scope_filter(
            LectureTranscriptionSchema.COURSE_ID.value, course_ids, exclude_course_ids
        )
        filters = (
            Filter.all_of([page_filter, course_filter])
            if course_filter is not None
            else page_filter
        )
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
    ) -> dict[tuple[str, int, int], float]:
        """Batch-fetch min start_time per (base_url, unit_id, page_number) for slide-sync
        detection. base_url is part of the key for the same reason as _fetch_lecture_units:
        the numeric unit_id alone can collide across Artemis instances sharing one Weaviate.
        """
        if not unit_page_pairs:
            return {}
        unit_ids = list({uid for uid, _ in unit_page_pairs})
        transcriptions = self.transcription_collection.query.fetch_objects(
            filters=Filter.by_property(
                LectureTranscriptionSchema.LECTURE_UNIT_ID.value
            ).contains_any(unit_ids),
            limit=10_000,
        ).objects
        result: dict[tuple[str, int, int], float] = {}
        for t in transcriptions:
            props = t.properties
            base_url = props.get(LectureTranscriptionSchema.BASE_URL.value)
            uid = props.get(LectureTranscriptionSchema.LECTURE_UNIT_ID.value)
            page = props.get(LectureTranscriptionSchema.PAGE_NUMBER.value)
            start = props.get(LectureTranscriptionSchema.SEGMENT_START_TIME.value)
            if uid is None or page is None or start is None or page == -1:
                continue
            key = (base_url, int(uid), int(page))
            if key not in result or start < result[key]:
                result[key] = float(start)
        return result

    def _fetch_lecture_units(self, unit_ids: list[int]) -> dict[tuple[str, int], Any]:
        """Fetch lecture unit metadata for the given IDs in a single Weaviate query.

        Keyed by (base_url, unit_id), not the bare id: multiple Artemis instances can
        share one Weaviate, their numeric unit ids collide, and keying by id alone let
        one instance's row silently overwrite another's in the result — a hit from
        instance A would then be enriched with instance B's unrelated unit's title and
        link. The limit is deliberately larger than ``len(unit_ids)`` for the same
        reason: with ``limit=len(unit_ids)`` those collisions crowd out other requested
        ids, which then look like missing metadata and get their hits silently dropped.
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
            (
                lecture_unit.properties.get(LectureUnitSchema.BASE_URL.value),
                lecture_unit.properties[LectureUnitSchema.LECTURE_UNIT_ID.value],
            ): lecture_unit.properties
            for lecture_unit in lecture_units
        }
        found_ids = {key[1] for key in result}
        missing = set(unit_ids) - found_ids
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

    def _fetch_slides_by_display_page(
        self, unit_ids: list[int]
    ) -> dict[tuple[str, int, int], list[Any]]:
        """Group each unit's slides by the display page they are shown on.

        A display page can carry several physical slides (an overlay build),
        and a transcription segment is only visible when every slide behind
        its display page is visible, so all of them are returned per key.
        Keyed by (base_url, unit_id, display_page): the numeric unit_id alone
        can collide across Artemis instances sharing one Weaviate.
        """
        if not unit_ids:
            return {}
        chunks = self.page_chunk_collection.query.fetch_objects(
            filters=Filter.by_property(
                LectureUnitPageChunkSchema.LECTURE_UNIT_ID.value
            ).contains_any(unit_ids),
            limit=10_000,
            return_properties=[
                LectureUnitPageChunkSchema.LECTURE_UNIT_ID.value,
                LectureUnitPageChunkSchema.PAGE_NUMBER.value,
                LectureUnitPageChunkSchema.DISPLAY_PAGE_NUMBER.value,
                LectureUnitPageChunkSchema.HIDDEN_UNTIL.value,
                LectureUnitPageChunkSchema.BASE_URL.value,
            ],
        ).objects
        by_physical_page: dict[tuple[str, int, int], dict[int, Any]] = {}
        for chunk in chunks:
            properties = chunk.properties
            base_url = properties.get(LectureUnitPageChunkSchema.BASE_URL.value)
            unit_id = properties.get(LectureUnitPageChunkSchema.LECTURE_UNIT_ID.value)
            physical_page = properties.get(LectureUnitPageChunkSchema.PAGE_NUMBER.value)
            display_page = properties.get(
                LectureUnitPageChunkSchema.DISPLAY_PAGE_NUMBER.value, physical_page
            )
            if unit_id is None or display_page is None or physical_page is None:
                continue
            key = (base_url, int(unit_id), int(display_page))
            by_physical_page.setdefault(key, {})[int(physical_page)] = properties
        return {key: list(slides.values()) for key, slides in by_physical_page.items()}

    @staticmethod
    def _segment_to_dto(
        props: dict[str, Any],
        lecture_unit_by_id: dict[tuple[str, int], Any],
        transcription_start_times: dict[tuple[str, int, int], float],
        policy: "_VisibilityPolicy | None" = None,
    ) -> tuple[LectureSearchResultDTO | None, str | None]:
        """Map a segment hit to a DTO; on failure return (None, drop_reason)."""
        if policy is None:
            policy = _VisibilityPolicy.from_context(None)
        snippet = props.get(LectureUnitSegmentSchema.SEGMENT_SUMMARY.value)
        if not snippet:
            return None, "no_snippet"
        if not is_segment_visible(props, policy.now):
            return None, "segment_hidden"

        course_id = props.get(LectureUnitSegmentSchema.COURSE_ID.value)
        unit_id = props.get(LectureUnitSegmentSchema.LECTURE_UNIT_ID.value)
        base_url = props.get(LectureUnitSegmentSchema.BASE_URL.value)
        lecture_unit = (
            lecture_unit_by_id.get((base_url, unit_id)) if unit_id is not None else None
        )
        if lecture_unit is None:
            return None, "missing_unit_metadata"
        if not policy.release_bypassed(course_id) and not is_unit_released(
            lecture_unit, policy.now
        ):
            return None, "unit_unreleased"

        lecture_id = props.get(LectureUnitSegmentSchema.LECTURE_ID.value)
        page_number = props.get(LectureUnitSegmentSchema.PAGE_NUMBER.value)
        if (
            course_id is None
            or lecture_id is None
            or page_number is None
            or page_number < 0
        ):
            return None, "bad_page_or_ids"

        start_time = transcription_start_times.get(
            (base_url, int(unit_id), int(page_number))
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
        lecture_unit_by_id: dict[tuple[str, int], Any],
        slides_by_display_page: dict[tuple[str, int, int], list[Any]] | None = None,
        policy: "_VisibilityPolicy | None" = None,
    ) -> tuple[LectureSearchResultDTO | None, str | None]:
        """Map a transcription hit to a DTO; on failure return (None, drop_reason)."""
        if policy is None:
            policy = _VisibilityPolicy.from_context(None)
        snippet = props.get(
            LectureTranscriptionSchema.SEGMENT_SUMMARY.value
        ) or props.get(LectureTranscriptionSchema.SEGMENT_TEXT.value)
        if not snippet:
            return None, "no_snippet"

        course_id = props.get(LectureTranscriptionSchema.COURSE_ID.value)
        unit_id = props.get(LectureTranscriptionSchema.LECTURE_UNIT_ID.value)
        base_url = props.get(LectureTranscriptionSchema.BASE_URL.value)
        lecture_unit = (
            lecture_unit_by_id.get((base_url, unit_id)) if unit_id is not None else None
        )
        if lecture_unit is None:
            return None, "missing_unit_metadata"
        # A transcription segment inherits the visibility of the slide shown
        # over it: an unhidden segment on a hidden overlay slide must stay
        # hidden, so the associated slides are part of the check.
        associated_slides = None
        if slides_by_display_page:
            page_number = props.get(LectureTranscriptionSchema.PAGE_NUMBER.value)
            if page_number is not None:
                try:
                    associated_slides = slides_by_display_page.get(
                        (base_url, int(unit_id), int(page_number))
                    )
                except (TypeError, ValueError):
                    return None, "bad_page_or_ids"
        if not is_transcription_visible(
            props,
            lecture_unit,
            associated_slides,
            now=policy.now,
            bypass_release=policy.release_bypassed(course_id),
        ):
            return None, "transcription_hidden"

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
