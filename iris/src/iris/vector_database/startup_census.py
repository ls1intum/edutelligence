"""Startup census of the Weaviate vector store, emitted at INFO for Grafana.

On boot this logs a self-contained report of what is actually stored in *this*
server's Weaviate and which embedding model queries it now, so an embedding-model
swap (e.g. OpenAI -> qwen3) that leaves stored vectors on a different dimension is
visible in Grafana without SSHing in or running an ad-hoc script.

Everything here is READ-ONLY and defensively wrapped: the census must never crash
or delay startup. It is meant to run in a daemon thread from the app lifespan.

Key facts it relies on:
  * Collections are self-provided (BYOV) HNSW indexes. Weaviate stores NO model
    label per object, and one index holds exactly ONE vector dimension. So a
    collection's stored dimension is the fingerprint of the model that built ALL
    of its data — a single collection cannot mix embedding models.
  * Retrieval can only work when a collection's stored dimension equals the
    dimension the current query embedding produces. That boolean is the headline,
    and the live probe below reproduces the actual success/failure.

Log lines use a stable ``[weaviate-census]`` prefix and key=value fields so they
can be parsed in LogQL / Grafana.
"""

from __future__ import annotations

import math
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any

from weaviate import WeaviateClient
from weaviate.classes.aggregate import GroupByAggregate
from weaviate.classes.query import Filter, MetadataQuery, Sort

from iris.common.logging_config import get_logger
from iris.config import settings
from iris.llm import CompletionArguments, LlmRequestHandler
from iris.llm.langchain import IrisLangchainChatModel
from iris.llm.llm_configuration import resolve_model
from iris.llm.llm_manager import LlmManager
from iris.pipeline.prompts.global_search_prompts import hyde_system_prompt
from iris.retrieval.lecture.lecture_global_search_retrieval import (
    QWEN3_RETRIEVAL_INSTRUCTION,
    resolve_reranker_model,
)
from iris.vector_database.database import VectorDatabase

logger = get_logger(__name__)

_PREFIX = "[weaviate-census]"
_PROBE_TEXT = "What is dynamic programming?"
_SAMPLE_SIZE = 64  # objects sampled per collection to detect the stored dimension
_TOP_COURSES = 10  # per-collection: log this many largest courses by object count
_PROBE_LIMIT = 3  # results requested by the live retrieval probe
_EMPTY_SEGMENT_PREFIX = "There is no content"  # placeholder summaries, dropped at query

# --- Extended probe experiment knobs -------------------------------------- #
# Deep hybrid probe: in Weaviate the requested limit also sets each sub-search's
# candidate depth (HNSW dynamic-ef, BM25 WAND pruning) AND the relativeScoreFusion
# normalization window. Production searches at limit 5-10; probing at 50 shows
# whether the right documents exist at depth and merely lose the shallow fusion.
_DEEP_PROBE_LIMIT = 50
_DEEP_LOG_TOP = 10  # per-hit lines logged for the deep probe (all hits summarized)
# Full stored text logged by the bm25_full probe: BM25's top hits with untruncated
# summaries reveal WHICH tokens matched (data pollution vs ranking failure).
_FULL_SNIPPET_LEN = 800
# Qwen3-Embedding is instruction-tuned for asymmetric retrieval: queries are
# prefixed with an instruction while documents stay raw. The census probes use
# the SAME instruction as production retrieval (imported) so the A/B stays
# representative across deploys.
# Alpha sweep for the two fix-candidate vector variants (instruct + hyde).
# 0.5 is what production uses today; 0.25 leans keyword, 0.75 leans vector.
# The empty label keeps the existing probe names (hybrid_hyde, hybrid_instruct)
# stable for the 0.5 baseline so runs stay comparable across deploys.
_ALPHA_SWEEP: list[tuple[str, float]] = [("_a25", 0.25), ("", 0.5), ("_a75", 0.75)]
# Collections that get the extended (deep / instruct / hyde / bm25_full) probes:
# the one global search actually queries, and the raw-slide-text collection that
# is the structural alternative substrate (used today only by lecture chat
# retrieval). Running HyDE probes on BOTH is deliberate: hyde-on-Segments is the
# current production path, hyde-on-Lectures is the candidate fix path, and the
# side-by-side comparison on identical queries is the decision evidence.
_EXTENDED_PROBE_COLLECTIONS = {"LectureUnitSegments", "Lectures"}


@dataclass(frozen=True)
class _ProbeQuery:
    """One configured probe query with every vector variant used by the probes."""

    text: str
    raw_vector: list[float] | None
    instruct_vector: list[float] | None
    hyde_text: str | None
    hyde_vector: list[float] | None


# (pipeline_id, short_label, is_query_side)
_EMBEDDING_ROLES: list[tuple[str, str, bool]] = [
    ("global_search_pipeline", "query_global_search", True),
    ("lecture_retrieval_pipeline", "query_lecture_chat", True),
    ("lecture_unit_segment_summary_pipeline", "ingest_segments", False),
    ("transcription_ingestion_pipeline", "ingest_transcripts", False),
    ("lecture_unit_pipeline", "ingest_units", False),
    ("faq_ingestion_pipeline", "ingest_faqs", False),
]

# Dimension -> likely model family. Only a hint for historical (untagged) data;
# the resolved config + live embed below give the exact current model name.
_DIM_HINTS = {
    1536: "openai-text-embedding-3-small",
    3072: "openai-text-embedding-3-large",
    1024: "qwen3-0.6B_or_cohere-v3",
    2560: "qwen3-4B",
    4096: "qwen3-8B",
}

# (display_name, VectorDatabase attribute)
_COLLECTIONS: list[tuple[str, str]] = [
    ("LectureUnitSegments", "lecture_segments"),
    ("LectureTranscriptions", "transcriptions"),
    ("LectureUnits", "lecture_units"),
    ("Lectures", "lectures"),  # real Weaviate name; holds lecture unit page chunks
    ("Faqs", "faqs"),
]

_COURSE_PROP = "course_id"
_COURSE_NAME_PROP = "course_name"
_UNIT_PROP = "lecture_unit_id"
_BASE_URL_PROP = "base_url"
_SUMMARY_PROPS = ("segment_summary", "lecture_unit_summary")

# Human-readable title fields, tried in order when describing a stored object.
_NAME_PROPS = ("lecture_unit_name", "lecture_name", "question_title")
# Content/body fields, tried in order for the snippet preview.
_CONTENT_PROPS = (
    "segment_summary",
    "page_text_content",
    "segment_text",
    "question_answer",
    "lecture_unit_summary",
)
_SNIPPET_LEN = 120  # chars of content shown per hit/sample
_SAMPLE_CONTENT_N = 5  # unfiltered sample objects logged per collection (exposes junk)
_COURSE_NAME_FETCH = 5000  # objects scanned to build course_id -> name map

# Chat roles pinged with a tiny completion to confirm the answer path is reachable.
_CHAT_ROLES: list[tuple[str, str, str]] = [
    ("global_search_pipeline", "hyde", "global_search_hyde"),
    ("global_search_pipeline", "answer", "global_search_answer"),
    ("lecture_retrieval_pipeline", "chat", "lecture_chat"),
]
# Reranker roles: registration-only check. We must NOT invoke .rerank() here — it
# self-disables the reranker process-wide on any failure, which would degrade the
# live service just from running the census.
_RERANK_ROLES: list[tuple[str, str, str]] = [
    ("lecture_retrieval_pipeline", "reranker", "lecture_reranker"),
]


def log_weaviate_census(client: WeaviateClient | None = None) -> None:
    """Entry point: log the full census. Safe to call from a daemon thread."""
    started = time.perf_counter()
    try:
        logger.info("%s START host=%s", _PREFIX, settings.weaviate.host)
        if client is None:
            client = VectorDatabase().get_client()

        _log_server_health(client)
        query_dims, probe_norm, probe_model = _log_embedding_config()
        probe_queries = _build_probe_queries(probe_model)
        collection_dims, unit_counts = _log_collections(
            query_dims, probe_norm, probe_queries
        )
        _log_unit_coverage(unit_counts)
        _log_unit_referential_integrity()
        _census_searchable_entities(client, query_dims, probe_queries)
        _probe_entity_rerank(client)
        _log_dimension_histogram(collection_dims, query_dims)
        if settings.weaviate_census_ping_llms:
            _log_llm_reachability()
    except Exception as e:  # noqa: BLE001 - census must never break startup
        logger.warning("%s aborted with error: %s", _PREFIX, e, exc_info=True)
    finally:
        logger.info(
            "%s DONE duration_ms=%.0f",
            _PREFIX,
            (time.perf_counter() - started) * 1000,
        )


# --------------------------------------------------------------------------- #
# Server health
# --------------------------------------------------------------------------- #
def _log_server_health(client: WeaviateClient) -> None:
    ready = _safe(client.is_ready, default=None)
    version = _safe(lambda: client.get_meta().get("version"), default="unknown")
    logger.info(
        "%s server ready=%s weaviate_version=%s local_llm_enabled=%s",
        _PREFIX,
        ready,
        version,
        settings.local_llm_enabled,
    )

    all_names = _safe(lambda: set(client.collections.list_all().keys()), default=set())
    known = {name for name, _ in _COLLECTIONS}
    orphans = sorted(all_names - known) if all_names else []
    missing = sorted(known - all_names) if all_names else []
    logger.info(
        "%s collections present=%d orphans=%s not_yet_created=%s",
        _PREFIX,
        len(all_names),
        orphans or "none",
        missing or "none",
    )


# --------------------------------------------------------------------------- #
# Embedding configuration + live fingerprint
# --------------------------------------------------------------------------- #
def _log_embedding_config() -> tuple[set[int], float | None, str | None]:
    """Resolve every embedding role and measure each distinct model's real output.

    Returns (query_dims, probe_norm, probe_model_id). probe_norm is the L2 norm of a
    query embedding (for the stored-vs-query norm fingerprint) and probe_model_id is
    the query-side embedding model used, so the configured probe queries can be
    embedded with the same model the real search uses.
    """
    dim_cache: dict[str, int | None] = {}
    query_dims: set[int] = set()
    ingest_dims: set[int] = set()
    probe_norm: float | None = None
    probe_model: str | None = None

    for pipeline_id, label, is_query in _EMBEDDING_ROLES:
        for env_local in (True, False):
            env = "local" if env_local else "cloud"
            model = _safe(
                lambda pid=pipeline_id, el=env_local: resolve_model(
                    pid, "default", "embedding", local=el
                ),
                default=None,
            )
            if not model:
                logger.info(
                    "%s embedding role=%s env=%s model=UNRESOLVED", _PREFIX, label, env
                )
                continue
            dim, norm, latency_ms, vector = _measure_model(model, dim_cache)
            logger.info(
                "%s embedding role=%s env=%s model=%s dim=%s l2norm=%s "
                "embed_ms=%s family=%s",
                _PREFIX,
                label,
                env,
                model,
                dim if dim is not None else "UNCALLABLE",
                f"{norm:.4f}" if norm is not None else "n/a",
                f"{latency_ms:.0f}" if latency_ms is not None else "n/a",
                _DIM_HINTS.get(dim, "unknown") if dim else "n/a",
            )
            if dim is not None:
                (query_dims if is_query else ingest_dims).add(dim)
            if is_query and vector is not None and probe_model is None:
                probe_norm, probe_model = norm, model

    logger.info(
        "%s query_side_dimensions=%s ingest_side_dimensions=%s",
        _PREFIX,
        sorted(query_dims) or "unknown",
        sorted(ingest_dims) or "unknown",
    )
    if query_dims and ingest_dims and not query_dims & ingest_dims:
        logger.warning(
            "%s INGEST/QUERY EMBEDDING MISMATCH: data is ingested at %s dims but "
            "queried at %s dims — freshly ingested data will also be unqueryable",
            _PREFIX,
            sorted(ingest_dims),
            sorted(query_dims),
        )
    return query_dims, probe_norm, probe_model


def _build_probe_queries(model_id: str | None) -> list[_ProbeQuery]:
    """Embed each configured probe query in every variant the probes need.

    Variants per query: raw text (what the census probed so far), the Qwen3
    instruction-prefixed text (query-side-only A/B), and the HyDE hypothetical
    answer (the vector production global search actually retrieves with). A None
    vector means that embed failed; the query still gets a bm25 keyword probe.
    """
    queries = settings.weaviate_census_probe_queries
    handler = _safe(lambda: LlmRequestHandler(model_id=model_id)) if model_id else None
    hyde_answers = _generate_hyde_answers(queries)
    probes: list[_ProbeQuery] = []
    for query in queries:
        hyde_text = hyde_answers.get(query)
        probes.append(
            _ProbeQuery(
                text=query,
                raw_vector=(
                    _safe(lambda q=query: handler.embed(q)) if handler else None
                ),
                instruct_vector=(
                    _safe(
                        lambda q=query: handler.embed(QWEN3_RETRIEVAL_INSTRUCTION + q)
                    )
                    if handler
                    else None
                ),
                hyde_text=hyde_text,
                hyde_vector=(
                    _safe(lambda t=hyde_text: handler.embed(t))
                    if handler and hyde_text
                    else None
                ),
            )
        )
    return probes


def _generate_hyde_answers(queries: list[str]) -> dict[str, str]:
    """Generate the HyDE hypothetical answer per probe query (cloud path).

    Uses the same model, prompt and max_tokens as the real global search pipeline,
    so the logged text + latency show exactly what production embeds. Gated behind
    the llm-ping setting because it costs one small completion per query per boot.
    """
    if not settings.weaviate_census_ping_llms:
        return {}
    model = _safe(
        lambda: resolve_model("global_search_pipeline", "default", "hyde", local=False)
    )
    if not model:
        return {}
    llm = _safe(
        lambda: IrisLangchainChatModel(
            request_handler=LlmRequestHandler(model_id=model),
            completion_args=CompletionArguments(max_tokens=150),
        )
    )
    if llm is None:
        return {}
    answers: dict[str, str] = {}
    for query in queries:
        t0 = time.perf_counter()
        text = _safe(
            lambda q=query: llm.invoke(
                [("system", hyde_system_prompt), ("user", q)]
            ).content
        )
        if text:
            answers[query] = text
            logger.info(
                "%s hyde_probe query=%r model=%s hyde_ms=%.0f hyde_text=%r",
                _PREFIX,
                query,
                model,
                (time.perf_counter() - t0) * 1000,
                text[:300],
            )
        else:
            logger.warning(
                "%s hyde_probe query=%r model=%s hyde_failed_or_empty",
                _PREFIX,
                query,
                model,
            )
    return answers


def _measure_model(
    model_id: str, cache: dict[str, int | None]
) -> tuple[int | None, float | None, float | None, list[float] | None]:
    """Embed the probe once per model id; return (dim, l2norm, latency_ms, vector).

    Repeated model ids (the same model is used by several roles) return the cached
    dimension without re-embedding, so startup makes one embed call per distinct
    model rather than one per role.
    """
    if model_id in cache:
        return cache[model_id], None, None, None
    t0 = time.perf_counter()
    try:
        vec = LlmRequestHandler(model_id=model_id).embed(_PROBE_TEXT)
        latency_ms = (time.perf_counter() - t0) * 1000
        dim = len(vec)
        norm = math.sqrt(sum(x * x for x in vec))
        cache[model_id] = dim
        return dim, norm, latency_ms, vec
    except Exception as e:  # noqa: BLE001 - a model may be unreachable on this host
        logger.warning("%s live embed with '%s' failed: %s", _PREFIX, model_id, e)
        cache.setdefault(model_id, None)
        return None, None, None, None


# --------------------------------------------------------------------------- #
# Per-collection census
# --------------------------------------------------------------------------- #
def _log_collections(
    query_dims: set[int],
    probe_norm: float | None,
    probe_queries: list[_ProbeQuery],
) -> tuple[dict[str, int | None], dict[str, int]]:
    """Log a census per collection.

    Returns ({collection_name: stored_dim|None}, {collection_name: distinct_units}).
    """
    db = VectorDatabase()
    attr_map = {
        "lecture_segments": db.lecture_segments,
        "transcriptions": db.transcriptions,
        "lecture_units": db.lecture_units,
        "lectures": db.lectures,
        "faqs": db.faqs,
    }
    course_names = _build_course_names(attr_map)
    logger.info("%s course_names_resolved=%d", _PREFIX, len(course_names))
    logger.debug(
        "%s course_name_map=%s",
        _PREFIX,
        {cid: name for cid, name in sorted(course_names.items())},
    )
    collection_dims: dict[str, int | None] = {}
    unit_counts: dict[str, int] = {}
    total_vectors = 0

    for name, attr in _COLLECTIONS:
        collection = attr_map.get(attr)
        if collection is None:
            continue
        dim, count, units = _census_one(
            name,
            collection,
            query_dims,
            probe_norm,
            probe_queries,
            course_names,
        )
        collection_dims[name] = dim
        if units is not None:
            unit_counts[name] = units
        if count > 0:
            total_vectors += count

    logger.info("%s total_vectors_all_collections=%d", _PREFIX, total_vectors)
    return collection_dims, unit_counts


def _census_one(
    name: str,
    collection: Any,
    query_dims: set[int],
    probe_norm: float | None,
    probe_queries: list[_ProbeQuery],
    course_names: dict[int, str],
) -> tuple[int | None, int, int | None]:
    """Log one collection's census; return (stored_dim, object_count, distinct_units)."""
    count = _safe(
        lambda: collection.aggregate.over_all(total_count=True).total_count, default=-1
    )
    if not count or count < 0:
        logger.info(
            "%s collection=%s count=%s (empty or unreadable)", _PREFIX, name, count
        )
        return None, 0, None

    prop_names = _safe(
        lambda: {p.name for p in collection.config.get().properties}, default=set()
    )

    dim, dim_counts, stored_norm = _sample_dims(collection)
    oldest, newest = _ingestion_bounds(collection)
    usable = dim is not None and dim in query_dims

    logger.info(
        "%s collection=%s count=%d stored_dim=%s query_dim=%s usable=%s family=%s "
        "stored_l2norm=%s query_l2norm=%s ingested=%s..%s",
        _PREFIX,
        name,
        count,
        dim if dim is not None else "unknown",
        sorted(query_dims) or "unknown",
        usable,
        _DIM_HINTS.get(dim, "unknown") if dim else "unknown",
        f"{stored_norm:.4f}" if stored_norm is not None else "n/a",
        f"{probe_norm:.4f}" if probe_norm is not None else "n/a",
        oldest or "n/a",
        newest or "n/a",
    )
    if dim_counts and len(dim_counts) > 1:
        logger.warning(
            "%s collection=%s MULTIPLE stored dims in sample=%s (unexpected)",
            _PREFIX,
            name,
            dict(dim_counts),
        )

    _log_index_config(name, collection)
    units = _log_course_and_unit_breakdown(name, collection, prop_names, course_names)
    _log_data_quality(name, collection, count, prop_names)
    _log_base_urls(name, collection, prop_names)
    _log_sample_content(name, collection, course_names)
    _probe_retrieval(name, collection, probe_queries, course_names)
    return dim, count, units


def _sample_dims(collection: Any) -> tuple[int | None, Counter, float | None]:
    """Sample objects; return (dominant_dim, dim_histogram, mean_vector_l2norm)."""
    sample = _safe(
        lambda: collection.query.fetch_objects(
            limit=_SAMPLE_SIZE, include_vector=True
        ).objects,
        default=[],
    )
    dim_counts: Counter = Counter()
    norms = []
    for obj in sample:
        vec = obj.vector
        if isinstance(vec, dict):
            vec = next(iter(vec.values()), None) if vec else None
        if vec is not None:
            dim_counts[len(vec)] += 1
            norms.append(math.sqrt(sum(x * x for x in vec)))
    dim = dim_counts.most_common(1)[0][0] if dim_counts else None
    mean_norm = sum(norms) / len(norms) if norms else None
    return dim, dim_counts, mean_norm


def _ingestion_bounds(collection: Any) -> tuple[str | None, str | None]:
    """Exact oldest/newest ingestion date via two single-object sorted fetches."""

    def _edge(ascending: bool) -> str | None:
        objs = _safe(
            lambda: collection.query.fetch_objects(
                limit=1,
                sort=Sort.by_creation_time(ascending=ascending),
                return_metadata=MetadataQuery(creation_time=True),
            ).objects,
            default=[],
        )
        if objs and objs[0].metadata and objs[0].metadata.creation_time:
            return str(objs[0].metadata.creation_time.date())
        return None

    return _edge(True), _edge(False)


def _log_index_config(name: str, collection: Any) -> None:
    cfg = _safe(collection.config.get)
    if cfg is None:
        return
    distance = (
        _safe(lambda: cfg.vector_index_config.distance)
        or _safe(lambda: str(cfg.vector_index_config.distance_metric))
        or "unknown"
    )
    quantizer = _safe(lambda: type(cfg.vector_index_config.quantizer).__name__)
    props = _safe(
        lambda: {p.name: str(p.data_type) for p in cfg.properties}, default={}
    )
    # The BM25 half of every hybrid search runs ONLY over these properties.
    searchable = _safe(
        lambda: [
            p.name for p in cfg.properties if getattr(p, "index_searchable", False)
        ],
        default=[],
    )
    logger.info(
        "%s collection=%s index_distance=%s quantizer=%s bm25_searchable=%s "
        "properties=%s",
        _PREFIX,
        name,
        distance,
        quantizer or "none",
        searchable or "unknown",
        props or "unknown",
    )


def _log_course_and_unit_breakdown(
    name: str, collection: Any, prop_names: set[str], course_names: dict[int, str]
) -> int | None:
    if _COURSE_PROP in prop_names:
        groups = _safe(
            lambda: collection.aggregate.over_all(
                group_by=GroupByAggregate(prop=_COURSE_PROP), total_count=True
            ).groups,
            default=[],
        )
        rows = sorted(
            ((g.grouped_by.value, g.total_count) for g in groups),
            key=lambda r: r[1],
            reverse=True,
        )
        logger.info("%s collection=%s distinct_courses=%d", _PREFIX, name, len(rows))
        for course_id, c in rows[:_TOP_COURSES]:
            logger.debug(
                "%s collection=%s course_id=%s name=%r objects=%d",
                _PREFIX,
                name,
                course_id,
                _course_label(course_id, course_names),
                c,
            )

    if _UNIT_PROP in prop_names:
        unit_groups = _safe(
            lambda: collection.aggregate.over_all(
                group_by=GroupByAggregate(prop=_UNIT_PROP), total_count=True
            ).groups,
            default=None,
        )
        if unit_groups is not None:
            logger.info(
                "%s collection=%s distinct_lecture_units=%d",
                _PREFIX,
                name,
                len(unit_groups),
            )
            return len(unit_groups)
    return None


def _log_data_quality(
    name: str, collection: Any, count: int, prop_names: set[str]
) -> None:
    summary_prop = next((p for p in _SUMMARY_PROPS if p in prop_names), None)
    if summary_prop:
        empties = _safe(
            lambda: collection.aggregate.over_all(
                total_count=True,
                filters=Filter.by_property(summary_prop).like(
                    f"{_EMPTY_SEGMENT_PREFIX}*"
                ),
            ).total_count,
            default=None,
        )
        if empties is not None:
            pct = (empties / count * 100) if count else 0.0
            logger.info(
                "%s collection=%s placeholder_summaries=%d (%.1f%%)",
                _PREFIX,
                name,
                empties,
                pct,
            )

    if _UNIT_PROP in prop_names:
        missing = _safe(
            lambda: collection.aggregate.over_all(
                total_count=True,
                filters=Filter.by_property(_UNIT_PROP).is_none(True),
            ).total_count,
            default=None,
        )
        if missing:
            logger.warning(
                "%s collection=%s objects_missing_%s=%d (dropped at query)",
                _PREFIX,
                name,
                _UNIT_PROP,
                missing,
            )


def _log_base_urls(name: str, collection: Any, prop_names: set[str]) -> None:
    if _BASE_URL_PROP not in prop_names:
        return
    groups = _safe(
        lambda: collection.aggregate.over_all(
            group_by=GroupByAggregate(prop=_BASE_URL_PROP), total_count=True
        ).groups,
        default=[],
    )
    urls = {g.grouped_by.value: g.total_count for g in groups}
    if len(urls) > 1:
        logger.warning(
            "%s collection=%s MULTIPLE base_urls=%s (cross-instance data?)",
            _PREFIX,
            name,
            urls,
        )
    elif urls:
        logger.info("%s collection=%s base_urls=%s", _PREFIX, name, urls)


def _build_course_names(attr_map: dict[str, Any]) -> dict[int, str]:
    """Map course_id -> course_name using the collections that store the name.

    Only ``LectureUnits`` and ``Faqs`` carry ``course_name``; segments, page chunks
    and transcriptions store just ``course_id``. Every other log line joins against
    this map so results are human-readable (e.g. "Deep Learning" not course 16).
    """
    names: dict[int, str] = {}
    for attr in ("lecture_units", "faqs"):
        collection = attr_map.get(attr)
        if collection is None:
            continue
        objs = _safe(
            lambda c=collection: c.query.fetch_objects(
                limit=_COURSE_NAME_FETCH
            ).objects,
            default=[],
        )
        for obj in objs:
            cid = obj.properties.get(_COURSE_PROP)
            cname = obj.properties.get(_COURSE_NAME_PROP)
            if cid is not None and cname:
                names[int(cid)] = str(cname)
    return names


def _course_label(course_id: Any, course_names: dict[int, str]) -> str:
    if course_id is None:
        return "?"
    try:
        return course_names.get(int(course_id), f"course#{int(course_id)}")
    except (TypeError, ValueError):
        return str(course_id)


def _describe_hit(
    props: dict[str, Any],
    course_names: dict[int, str],
    snippet_len: int = _SNIPPET_LEN,
) -> str:
    """One-line human description of a stored object: course, title, page, snippet."""
    course = _course_label(props.get(_COURSE_PROP), course_names)
    title = next((props[p] for p in _NAME_PROPS if props.get(p)), None)
    content = next((props[p] for p in _CONTENT_PROPS if props.get(p)), None)
    if content is None:
        # Unknown schema (e.g. Artemis-managed entity collections): fall back to
        # the first non-empty string property so probe hits stay identifiable.
        content = next(
            (
                v
                for k, v in props.items()
                if isinstance(v, str) and v.strip() and k != _BASE_URL_PROP
            ),
            None,
        )
    page = props.get("page_number")
    parts = [f"course={course!r}"]
    if title:
        parts.append(f"title={str(title)[:60]!r}")
    if page is not None:
        parts.append(f"page={page}")
    if content:
        parts.append(f"snippet={str(content)[:snippet_len]!r}")
    return " ".join(parts)


def _log_sample_content(
    name: str, collection: Any, course_names: dict[int, str]
) -> None:
    """Log a few unfiltered stored objects so junk data (empty/garbage) is visible."""
    objs = _safe(
        lambda: collection.query.fetch_objects(limit=_SAMPLE_CONTENT_N).objects,
        default=[],
    )
    for i, obj in enumerate(objs, start=1):
        logger.debug(
            "%s collection=%s sample#%d %s",
            _PREFIX,
            name,
            i,
            _describe_hit(obj.properties, course_names),
        )


def _probe_retrieval(
    name: str,
    collection: Any,
    probe_queries: list[_ProbeQuery],
    course_names: dict[int, str],
) -> None:
    """For each configured query, run bm25 / near_vector / hybrid and log every hit.

    Running the three modalities separately (rather than only the fused hybrid the UI
    uses) lets you decompose a bad result: if bm25 ranks the right doc high but hybrid
    buries it, the vector half + alpha=0.5 is drowning the keyword match; if bm25 also
    buries it, it is a tokenization/IDF problem. Per-hit course/title/snippet output
    shows whether the *relevant* content actually ranks.

    Extended probes (selected collections only) A/B the candidate remedies:
      * hybrid_deep       — limit=50: deeper candidate pool + wider fusion window
      * near_vector_instruct / hybrid_instruct(_a25/_a75) — Qwen3 query-side
        instruction prefix vs raw query, swept over alpha (results-list fix)
      * bm25_full         — top keyword hits with untruncated summaries (token audit)
      * near_vector_hyde / hybrid_hyde(_a25/_a75) — the vector production actually
        searches with, swept over alpha (AI-answer path fix)
      * hybrid_hyde_autocut — Weaviate cuts at natural score cliffs: how many
        sources carry real signal for the generation context
      * hybrid_videoonly  — the page=-1 transcription sub-search production runs
      * gen_context       — top hit's segment_summary vs the same slide's raw
        page text: the two candidate generation inputs side by side
    """
    for probe in probe_queries:
        query, vector = probe.text, probe.raw_vector
        _log_probe(
            name,
            "bm25",
            "score",
            query,
            course_names,
            lambda q=query: collection.query.bm25(
                query=q,
                limit=_PROBE_LIMIT,
                return_metadata=MetadataQuery(score=True),
            ),
        )
        if name in _EXTENDED_PROBE_COLLECTIONS:
            _log_probe(
                name,
                "bm25_full",
                "score",
                query,
                course_names,
                lambda q=query: collection.query.bm25(
                    query=q,
                    limit=_PROBE_LIMIT,
                    return_metadata=MetadataQuery(score=True),
                ),
                snippet_len=_FULL_SNIPPET_LEN,
            )
        if vector is None:
            continue
        _log_probe(
            name,
            "near_vector",
            "distance",
            query,
            course_names,
            lambda v=vector: collection.query.near_vector(
                near_vector=v,
                limit=_PROBE_LIMIT,
                return_metadata=MetadataQuery(distance=True),
            ),
        )
        _log_probe(
            name,
            "hybrid",
            "score",
            query,
            course_names,
            lambda q=query, v=vector: collection.query.hybrid(
                query=q,
                vector=v,
                alpha=0.5,
                limit=_PROBE_LIMIT,
                return_metadata=MetadataQuery(score=True),
            ),
        )
        if name == "LectureTranscriptions":
            # Reproduces the exact transcription sub-search global search runs:
            # only video-only segments (page_number == -1) compete, and their
            # fused scores merge 1:1 with the segment list. This is the pool the
            # junk hits come from.
            _log_probe(
                name,
                "hybrid_videoonly",
                "score",
                query,
                course_names,
                lambda q=query, v=vector: collection.query.hybrid(
                    query=q,
                    vector=v,
                    alpha=0.5,
                    filters=Filter.by_property("page_number").equal(-1),
                    limit=_PROBE_LIMIT,
                    return_metadata=MetadataQuery(score=True),
                ),
            )
        if name in _EXTENDED_PROBE_COLLECTIONS:
            _log_probe(
                name,
                "hybrid_deep",
                "score",
                query,
                course_names,
                lambda q=query, v=vector: collection.query.hybrid(
                    query=q,
                    vector=v,
                    alpha=0.5,
                    limit=_DEEP_PROBE_LIMIT,
                    return_metadata=MetadataQuery(score=True),
                ),
                log_top=_DEEP_LOG_TOP,
            )
            if probe.instruct_vector is not None:
                _log_probe(
                    name,
                    "near_vector_instruct",
                    "distance",
                    query,
                    course_names,
                    lambda v=probe.instruct_vector: collection.query.near_vector(
                        near_vector=v,
                        limit=_PROBE_LIMIT,
                        return_metadata=MetadataQuery(distance=True),
                    ),
                )
                # The fused variant of the instruct-prefix fix: what the plain
                # results list would actually return if only the query embedding
                # changed (BM25 half stays on the raw query). Swept over alpha to
                # find the best keyword/vector weighting for the results list.
                for alpha_label, alpha in _ALPHA_SWEEP:
                    _log_probe(
                        name,
                        f"hybrid_instruct{alpha_label}",
                        "score",
                        query,
                        course_names,
                        lambda q=query, v=probe.instruct_vector, a=alpha: (
                            collection.query.hybrid(
                                query=q,
                                vector=v,
                                alpha=a,
                                limit=_PROBE_LIMIT,
                                return_metadata=MetadataQuery(score=True),
                            )
                        ),
                    )
        if name in _EXTENDED_PROBE_COLLECTIONS and probe.hyde_vector is not None:
            _log_probe(
                name,
                "near_vector_hyde",
                "distance",
                query,
                course_names,
                lambda v=probe.hyde_vector: collection.query.near_vector(
                    near_vector=v,
                    limit=_PROBE_LIMIT,
                    return_metadata=MetadataQuery(distance=True),
                ),
            )
            # Alpha sweep on the production (HyDE) path: how the AI answer's
            # source list changes with the keyword/vector weighting.
            hyde_hits: list[Any] | None = None
            for alpha_label, alpha in _ALPHA_SWEEP:
                hits = _log_probe(
                    name,
                    f"hybrid_hyde{alpha_label}",
                    "score",
                    query,
                    course_names,
                    lambda q=query, v=probe.hyde_vector, a=alpha: (
                        collection.query.hybrid(
                            query=q,
                            vector=v,
                            alpha=a,
                            limit=_PROBE_LIMIT,
                            return_metadata=MetadataQuery(score=True),
                        )
                    ),
                )
                if alpha == 0.5:
                    hyde_hits = hits
            # Autocut: let Weaviate cut the fused list at the natural score
            # cliffs. hits=N here answers "how many sources carry real signal"
            # for the generation context (vs the fixed limit=5 used today).
            _log_probe(
                name,
                "hybrid_hyde_autocut",
                "score",
                query,
                course_names,
                lambda q=query, v=probe.hyde_vector: collection.query.hybrid(
                    query=q,
                    vector=v,
                    alpha=0.5,
                    auto_limit=2,
                    limit=_DEEP_PROBE_LIMIT,
                    return_metadata=MetadataQuery(score=True),
                ),
                log_top=3,
            )
            if name == "LectureUnitSegments" and hyde_hits:
                for rank, hit in enumerate(hyde_hits[:3], start=1):
                    _log_generation_context(query, rank, hit, course_names)


def _log_generation_context(
    query: str, rank: int, top_obj: Any, course_names: dict[int, str]
) -> None:
    """Side-by-side of the two candidate generation inputs for the same slide.

    The answer LLM currently receives ``segment_summary`` snippets (LLM-written
    meta-prose). The alternative substrate is the raw slide text stored in the
    ``Lectures`` collection. The answer models are light (nano/mini class), so
    the whole generation context is only a handful of sources — logging the
    side-by-side for each top hit shows nearly the complete context the model
    would receive under either substrate, plus the token cost of each (chars/4
    is a coarse token proxy; the live path logs exact input_tokens).
    """
    props = top_obj.properties
    uid = props.get(_UNIT_PROP)
    page = props.get("page_number")
    summary = str(props.get("segment_summary") or "")
    if uid is None or page is None:
        return
    chunks = _safe(
        lambda: VectorDatabase()
        .lectures.query.fetch_objects(
            filters=Filter.all_of(
                [
                    Filter.by_property(_UNIT_PROP).equal(int(uid)),
                    Filter.by_property("page_number").equal(int(page)),
                ]
            ),
            limit=1,
        )
        .objects,
        default=[],
    )
    page_text = (
        str(chunks[0].properties.get("page_text_content") or "") if chunks else ""
    )
    logger.info(
        "%s gen_context #%d query=%r course=%r unit=%s page=%s summary_len=%d "
        "page_text_len=%d",
        _PREFIX,
        rank,
        query,
        _course_label(props.get(_COURSE_PROP), course_names),
        uid,
        page,
        len(summary),
        len(page_text),
    )
    logger.info(
        "%s gen_context #%d summary=%r", _PREFIX, rank, summary[:_FULL_SNIPPET_LEN]
    )
    logger.info(
        "%s gen_context #%d page_text=%r",
        _PREFIX,
        rank,
        page_text[:_FULL_SNIPPET_LEN] or "NO_MATCHING_PAGE_CHUNK",
    )


def _log_probe(
    name: str,
    label: str,
    score_attr: str,
    query: str,
    course_names: dict[int, str],
    fn,
    snippet_len: int = _SNIPPET_LEN,
    log_top: int | None = None,
) -> list[Any] | None:
    """Run one probe query and log the header plus one line per hit (score + content).

    Returns the hit objects (None on failure) so callers can chain follow-up
    probes on the top result. ``log_top`` caps the per-hit lines; when hits
    exceed it, a distribution line summarizes which courses fill the full result
    list (deep-probe recall signal). The header carries ``duration_ms`` so each
    modality's latency cost is visible.
    """
    t0 = time.perf_counter()
    try:
        objs = fn().objects
    except Exception as e:  # noqa: BLE001 - the failure text IS the diagnostic signal
        # WARNING (not ERROR text) so a real probe failure surfaces without Loki
        # misclassifying the line's level from the word "error" in the message.
        logger.warning(
            "%s collection=%s probe=%s query=%r query_failed=%s",
            _PREFIX,
            name,
            label,
            query,
            str(e)[:200],
        )
        return None
    duration_ms = (time.perf_counter() - t0) * 1000
    logger.info(
        "%s collection=%s probe=%s query=%r hits=%d duration_ms=%.0f",
        _PREFIX,
        name,
        label,
        query,
        len(objs),
        duration_ms,
    )
    shown = objs if log_top is None else objs[:log_top]
    for rank, obj in enumerate(shown, start=1):
        score = getattr(obj.metadata, score_attr, None)
        logger.info(
            "%s   probe=%s #%d %s=%s %s",
            _PREFIX,
            label,
            rank,
            score_attr,
            f"{score:.4f}" if isinstance(score, float) else score,
            _describe_hit(obj.properties, course_names, snippet_len=snippet_len),
        )
    if log_top is not None and len(objs) > log_top:
        course_counts = Counter(
            _course_label(obj.properties.get(_COURSE_PROP), course_names)
            for obj in objs
        )
        logger.info(
            "%s   probe=%s courses_in_all_%d_hits=%s",
            _PREFIX,
            label,
            len(objs),
            dict(course_counts.most_common()),
        )
    return objs


# --------------------------------------------------------------------------- #
# Cross-collection roll-ups
# --------------------------------------------------------------------------- #
def _log_unit_coverage(unit_counts: dict[str, int]) -> None:
    """Compare units that have a summary row vs units that have segments.

    A unit present in LectureUnits but absent from LectureUnitSegments is a 'hole'
    — typically a re-ingest that deleted old segments then failed to insert new ones.
    """
    units = unit_counts.get("LectureUnits")
    segments_units = unit_counts.get("LectureUnitSegments")
    if units is None or segments_units is None:
        return
    gap = units - segments_units
    logger.info(
        "%s unit_coverage lecture_units=%d units_with_segments=%d gap=%d",
        _PREFIX,
        units,
        segments_units,
        gap,
    )
    if gap > 0:
        logger.warning(
            "%s %d lecture unit(s) have NO segments — likely wiped by a failed "
            "re-ingest (deleted old, insert rejected on dimension mismatch)",
            _PREFIX,
            gap,
        )


def _log_unit_referential_integrity() -> None:
    """Cross-check every lecture_unit_id referenced by search hits against LectureUnits.

    Global search maps each segment/transcription hit to a DTO by joining on its
    ``LectureUnits`` metadata row; a hit whose unit has no row is SILENTLY dropped
    (drop reason ``missing_unit_metadata``). Two data shapes cause that:
      * orphaned references — the unit's metadata row was never written or deleted;
      * duplicate unit_ids  — several Artemis instances share one Weaviate, their
        numeric ids collide, and one id maps to multiple rows (the retrieval fetch
        can then truncate or pick the wrong instance's row).
    This logs both shapes with per-course/base_url attribution.
    """
    db = VectorDatabase()
    unit_rows = _safe(
        lambda: db.lecture_units.query.fetch_objects(limit=10_000).objects,
        default=[],
    )
    unit_id_counts: Counter = Counter()
    for obj in unit_rows:
        uid = obj.properties.get(_UNIT_PROP)
        if uid is not None:
            unit_id_counts[int(uid)] += 1
    duplicate_ids = {uid: n for uid, n in unit_id_counts.items() if n > 1}
    logger.info(
        "%s unit_integrity lecture_units_rows=%d distinct_unit_ids=%d "
        "duplicate_unit_ids=%d",
        _PREFIX,
        len(unit_rows),
        len(unit_id_counts),
        len(duplicate_ids),
    )
    if duplicate_ids:
        logger.warning(
            "%s unit_integrity DUPLICATE unit_ids in LectureUnits (id->rows)=%s — "
            "cross-instance id collisions; retrieval joins on unit_id only and may "
            "attach the wrong course or truncate its metadata fetch",
            _PREFIX,
            dict(sorted(duplicate_ids.items())[:30]),
        )

    for coll_name, collection in (
        ("LectureUnitSegments", db.lecture_segments),
        ("LectureTranscriptions", db.transcriptions),
    ):
        groups = _safe(
            lambda c=collection: c.aggregate.over_all(
                group_by=GroupByAggregate(prop=_UNIT_PROP), total_count=True
            ).groups,
            default=[],
        )
        referenced = {
            int(g.grouped_by.value): g.total_count
            for g in groups
            if g.grouped_by.value is not None
        }
        missing = {uid: n for uid, n in referenced.items() if uid not in unit_id_counts}
        orphaned_objects = sum(missing.values())
        logger.info(
            "%s unit_integrity collection=%s referenced_units=%d missing_units=%d "
            "orphaned_objects=%d",
            _PREFIX,
            coll_name,
            len(referenced),
            len(missing),
            orphaned_objects,
        )
        if not missing:
            continue
        # Attribute the orphaned objects to courses/instances so the affected
        # content is identifiable from the log alone.
        sample = _safe(
            lambda c=collection, ids=list(missing): c.query.fetch_objects(
                filters=Filter.by_property(_UNIT_PROP).contains_any(ids[:200]),
                limit=1000,
            ).objects,
            default=[],
        )
        by_course: Counter = Counter()
        for obj in sample:
            course = obj.properties.get(_COURSE_PROP)
            base_url = obj.properties.get(_BASE_URL_PROP)
            by_course[f"course={course} base_url={base_url}"] += 1
        logger.warning(
            "%s unit_integrity collection=%s ORPHANED unit_ids=%s "
            "affected_objects_by_course=%s — these hits are silently dropped "
            "(missing_unit_metadata) on every search",
            _PREFIX,
            coll_name,
            sorted(missing)[:50],
            dict(by_course.most_common(20)),
        )


_ENTITY_MARKER = "SearchableEntities"
# Candidate depth for the entity rerank rehearsal: matches the Artemis-side
# prefetch limit (ENTITY_PREFETCH_LIMIT) in the SearchableEntities PR, so the
# rehearsal scores the same candidate-set shape the real merge stage will see.
_ENTITY_PROBE_LIMIT = 15
# Property names tried (in order) when grouping entities by type and when
# building the typed rerank document — the Artemis schema is not owned by Iris,
# so the census discovers the field names instead of assuming them.
_ENTITY_TYPE_PROPS = ("type", "entity_type", "searchable_type", "category")
_ENTITY_DOC_PROPS = (
    "type",
    "entity_type",
    "course_title",
    "course_name",
    "title",
    "short_name",
    "description",
)


def _census_searchable_entities(
    client: WeaviateClient, query_dims: set[int], probe_queries: list[_ProbeQuery]
) -> None:
    """Fingerprint the Artemis-managed SearchableEntities collections.

    Artemis writes one such collection per connected instance (they appear as
    census orphans). An open PR expands the global-search answer to use these
    entities (exercise / faq / communication channel / lecture metadata) as
    additional answer sources. Before that lands, the census answers:
      * can Iris's query embedding search them at all (stored dim vs query dim)?
      * which properties are BM25-searchable, and what does a real probe return?
      * how large are the stored texts? Metadata entities are far shorter than
        lecture content; BM25 length normalization favors short documents and
        relativeScoreFusion normalizes per collection, so sparse metadata can
        systematically outscore dense content once both are merged. The size
        numbers logged here are the input for that per-type gating decision.
    """
    names = _safe(lambda: sorted(client.collections.list_all().keys()), default=[])
    entity_names = [n for n in names if _ENTITY_MARKER in n]
    if not entity_names:
        return
    probe = next((p for p in probe_queries if p.raw_vector is not None), None)
    for name in entity_names:
        collection = _safe(lambda n=name: client.collections.get(n))
        if collection is None:
            continue
        count = _safe(
            lambda c=collection: c.aggregate.over_all(total_count=True).total_count,
            default=-1,
        )
        if not count or count < 0:
            logger.info(
                "%s entity_collection=%s count=%s (empty or unreadable)",
                _PREFIX,
                name,
                count,
            )
            continue
        dim, _, _ = _sample_dims(collection)
        cfg = _safe(collection.config.get)
        searchable = _safe(
            lambda c=cfg: [
                p.name for p in c.properties if getattr(p, "index_searchable", False)
            ],
            default=[],
        )
        usable = dim is not None and dim in query_dims
        logger.info(
            "%s entity_collection=%s count=%d stored_dim=%s usable_by_iris_embedding=%s "
            "bm25_searchable=%s",
            _PREFIX,
            name,
            count,
            dim if dim is not None else "unknown",
            usable,
            searchable or "none",
        )
        type_counts = _entity_type_counts(collection)
        if type_counts:
            logger.info(
                "%s entity_collection=%s type_counts=%s",
                _PREFIX,
                name,
                type_counts,
            )
        objs = _safe(
            lambda c=collection: c.query.fetch_objects(limit=3).objects, default=[]
        )
        for i, obj in enumerate(objs, start=1):
            text_props = {
                k: f"{str(v)[:80]!r}"
                for k, v in obj.properties.items()
                if isinstance(v, str) and v.strip()
            }
            total_chars = sum(
                len(v) for v in obj.properties.values() if isinstance(v, str)
            )
            logger.debug(
                "%s entity_collection=%s sample#%d total_text_chars=%d props=%s",
                _PREFIX,
                name,
                i,
                total_chars,
                text_props,
            )
        if probe is None:
            continue
        _log_probe(
            name,
            "bm25",
            "score",
            probe.text,
            {},
            lambda q=probe.text, c=collection: c.query.bm25(
                query=q,
                limit=_PROBE_LIMIT,
                return_metadata=MetadataQuery(score=True),
            ),
        )
        if usable:
            _log_probe(
                name,
                "hybrid",
                "score",
                probe.text,
                {},
                lambda q=probe.text, v=probe.raw_vector, c=collection: c.query.hybrid(
                    query=q,
                    vector=v,
                    alpha=0.5,
                    limit=_PROBE_LIMIT,
                    return_metadata=MetadataQuery(score=True),
                ),
            )


def _entity_type_counts(collection: Any) -> dict[str, int] | None:
    """Per-type object counts for a SearchableEntities collection.

    This is the shape data for the grounding-contract design: a negative answer
    like 'this course has no exams' is only safe when an existence count says
    zero exist — absence from a 15-entity prefetch proves nothing. The type
    property name is discovered, not assumed (the schema is Artemis-owned).
    """
    for prop in _ENTITY_TYPE_PROPS:
        groups = _safe(
            lambda p=prop: collection.aggregate.over_all(
                group_by=GroupByAggregate(prop=p), total_count=True
            ).groups
        )
        if groups:
            return {str(g.grouped_by.value): g.total_count for g in groups}
    return None


def _entity_document(props: dict[str, Any]) -> str:
    """Build the typed rerank document for an entity hit (TYPE/COURSE/NAME/...).

    Mirrors the typed-context idea from the SearchableEntities PR: the reranker
    scores what the merge stage would actually compare, not raw property dumps.
    """
    parts = []
    for key in _ENTITY_DOC_PROPS:
        value = props.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(f"{key}: {value.strip()}")
    if parts:
        return " | ".join(parts)
    fallback = {k: v for k, v in props.items() if isinstance(v, str) and v.strip()}
    return str(fallback)[:300]


def _probe_entity_rerank(client: WeaviateClient) -> None:
    """Deploy C rehearsal: entity-shaped queries through the production reranker.

    Runs a hybrid candidate search on ONE Artemis SearchableEntities collection
    at the Artemis prefetch depth, then scores the candidates with the SAME
    reranker role and threshold production lecture retrieval uses, logging fused
    vs rerank scores per hit. This answers, before the SearchableEntities branch
    is built on the assumption: does the lecture-calibrated rerank threshold
    also separate relevant from junk on sparse metadata entities?

    Invoking .rerank() directly on the LlmManager client is safe here — unlike
    RerankRequestHandler it does not self-disable process-wide on failure; this
    is the same access pattern production _safe_rerank uses.
    """
    name = settings.weaviate_census_entity_probe_collection
    queries = settings.weaviate_census_entity_probe_queries
    if not name or not queries:
        return
    collection = _safe(lambda: client.collections.get(name))
    if collection is None:
        logger.warning("%s entity_probe collection=%s not found", _PREFIX, name)
        return
    embed_model = _safe(
        lambda: resolve_model(
            "global_search_pipeline", "default", "embedding", local=False
        )
    )
    handler = (
        _safe(lambda: LlmRequestHandler(model_id=embed_model)) if embed_model else None
    )
    reranker_model = _safe(lambda: resolve_reranker_model(local=False))
    reranker = (
        _safe(lambda: LlmManager().get_llm_by_id(reranker_model))
        if reranker_model
        else None
    )
    threshold = settings.global_search_rerank_threshold
    logger.info(
        "%s entity_probe collection=%s queries=%d embedding=%s reranker=%s "
        "threshold=%.2f",
        _PREFIX,
        name,
        len(queries),
        embed_model,
        reranker_model,
        threshold,
    )
    for query in queries:
        vector = (
            _safe(lambda q=query: handler.embed(QWEN3_RETRIEVAL_INSTRUCTION + q))
            if handler
            else None
        )
        t0 = time.perf_counter()
        if vector is not None:
            response = _safe(
                lambda q=query, v=vector, c=collection: c.query.hybrid(
                    query=q,
                    vector=v,
                    alpha=0.5,
                    limit=_ENTITY_PROBE_LIMIT,
                    return_metadata=MetadataQuery(score=True),
                )
            )
        else:
            response = _safe(
                lambda q=query, c=collection: c.query.bm25(
                    query=q,
                    limit=_ENTITY_PROBE_LIMIT,
                    return_metadata=MetadataQuery(score=True),
                )
            )
        hits = list(getattr(response, "objects", None) or [])
        search_ms = (time.perf_counter() - t0) * 1000
        if not hits:
            logger.info(
                "%s entity_probe query=%r hits=0 search_ms=%.0f",
                _PREFIX,
                query,
                search_ms,
            )
            continue
        docs = [_entity_document(h.properties) for h in hits]
        rerank_scores: list[float] | None = None
        rerank_ms: float | None = None
        if reranker is not None:
            t1 = time.perf_counter()
            resp = _safe(
                lambda q=query, d=docs, r=reranker: r.rerank(
                    query=q, documents=d, top_n=len(d)
                )
            )
            results = list(getattr(resp, "results", None) or [])
            if results:
                rerank_ms = (time.perf_counter() - t1) * 1000
                rerank_scores = [0.0] * len(docs)
                for item in results:
                    rerank_scores[item.index] = float(item.relevance_score)
        above = (
            sum(1 for s in rerank_scores if s >= threshold)
            if rerank_scores is not None
            else None
        )
        logger.info(
            "%s entity_probe query=%r hits=%d search_ms=%.0f rerank_ms=%s "
            "above_threshold=%s",
            _PREFIX,
            query,
            len(hits),
            search_ms,
            f"{rerank_ms:.0f}" if rerank_ms is not None else "n/a",
            above if above is not None else "n/a",
        )
        order = (
            sorted(range(len(hits)), key=rerank_scores.__getitem__, reverse=True)
            if rerank_scores is not None
            else list(range(len(hits)))
        )
        for rank, i in enumerate(order, start=1):
            fused = (
                hits[i].metadata.score
                if hits[i].metadata and hits[i].metadata.score is not None
                else None
            )
            relevance = rerank_scores[i] if rerank_scores is not None else None
            logger.info(
                "%s entity_probe   #%d rerank=%s fused=%s doc=%r",
                _PREFIX,
                rank,
                f"{relevance:.4f}" if relevance is not None else "n/a",
                f"{fused:.4f}" if fused is not None else "n/a",
                docs[i][:200],
            )


def _log_dimension_histogram(
    collection_dims: dict[str, int | None], query_dims: set[int]
) -> None:
    by_dim: dict[int, list[str]] = {}
    for coll_name, dim in collection_dims.items():
        if dim is not None:
            by_dim.setdefault(dim, []).append(coll_name)
    for dim, names in sorted(by_dim.items()):
        logger.info(
            "%s dimension_histogram dim=%d indexes=%d collections=%s usable=%s family=%s",
            _PREFIX,
            dim,
            len(names),
            names,
            dim in query_dims,
            _DIM_HINTS.get(dim, "unknown"),
        )

    unusable = [
        coll_name
        for coll_name, dim in collection_dims.items()
        if dim is not None and dim not in query_dims
    ]
    if unusable:
        logger.warning(
            "%s UNQUERYABLE collections (stored dim != query dim %s): %s "
            "-> re-ingest with the current embedding model or revert the query model",
            _PREFIX,
            sorted(query_dims) or "unknown",
            unusable,
        )


def _log_llm_reachability() -> None:
    """Ping the answer-path models so retrieval-vs-LLM failures can be told apart.

    Chat models get a tiny real chat request; the reranker gets a registration check
    only (invoking it would self-disable the reranker for the whole process).
    """
    pinged: dict[str, str] = {}  # model_id -> compact result, to ping each model once
    for pipeline_id, role, label in _CHAT_ROLES:
        for env_local in (True, False):
            env = "local" if env_local else "cloud"
            model = _safe(
                lambda pid=pipeline_id, r=role, el=env_local: resolve_model(
                    pid, "default", r, local=el
                ),
                default=None,
            )
            if not model:
                logger.info(
                    "%s llm_ping role=%s env=%s model=UNRESOLVED", _PREFIX, label, env
                )
                continue
            if model not in pinged:
                pinged[model] = _ping_chat(model)
            result = pinged[model]
            # Genuine unreachability is a WARNING so it stands out and isn't hidden
            # by an INFO-level filter; a healthy ping stays INFO.
            log = logger.warning if result.startswith("unreachable") else logger.info
            log(
                "%s llm_ping role=%s env=%s model=%s %s",
                _PREFIX,
                label,
                env,
                model,
                result,
            )

    for pipeline_id, role, label in _RERANK_ROLES:
        model = _safe(
            lambda pid=pipeline_id, r=role: resolve_model(
                pid, "default", r, local=False
            ),
            default=None,
        )
        if not model:
            logger.info("%s llm_ping role=%s model=UNRESOLVED", _PREFIX, label)
            continue
        registered = _safe(
            lambda m=model: LlmManager().get_llm_by_id(m) is not None, default=False
        )
        logger.info(
            "%s llm_ping role=%s model=%s registered=%s (not invoked)",
            _PREFIX,
            label,
            model,
            registered,
        )


def _ping_chat(model_id: str) -> str:
    """Send a minimal CHAT request; return 'ok latency_ms=..' or 'ERROR=..'.

    Must use the chat path (via IrisLangchainChatModel), not ``complete()``: the
    HyDE/answer models are registered as ChatModels and the pipeline invokes them
    through ``.chat()``. Probing with ``.complete()`` looks up CompletionModels and
    would falsely report "No CompletionModel found" for a perfectly working model.
    """
    t0 = time.perf_counter()
    try:
        llm = IrisLangchainChatModel(
            request_handler=LlmRequestHandler(model_id=model_id),
            completion_args=CompletionArguments(temperature=0, max_tokens=5),
        )
        llm.invoke("ping")
        return f"ok latency_ms={(time.perf_counter() - t0) * 1000:.0f}"
    except Exception as e:  # noqa: BLE001 - unreachable answer model is the signal
        # Neutral token (not "ERROR") so Loki doesn't misread the line's level.
        return f"unreachable={str(e)[:200]}"


def _safe(fn, default=None):
    """Run a read-only probe; on any error return default (census is best-effort)."""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        logger.debug("%s probe failed: %s", _PREFIX, e)
        return default
