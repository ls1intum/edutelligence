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
from iris.vector_database.database import VectorDatabase

logger = get_logger(__name__)

_PREFIX = "[weaviate-census]"
_PROBE_TEXT = "What is dynamic programming?"
_SAMPLE_SIZE = 64  # objects sampled per collection to detect the stored dimension
_TOP_COURSES = 10  # per-collection: log this many largest courses by object count
_PROBE_LIMIT = 3  # results requested by the live retrieval probe
_EMPTY_SEGMENT_PREFIX = "There is no content"  # placeholder summaries, dropped at query

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
        probe_queries = _embed_probe_queries(probe_model)
        collection_dims, unit_counts = _log_collections(
            query_dims, probe_norm, probe_queries
        )
        _log_unit_coverage(unit_counts)
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


def _embed_probe_queries(model_id: str | None) -> dict[str, list[float] | None]:
    """Embed each configured probe query with the query-side embedding model.

    Returns {query_text: vector|None}. A None vector means the embed failed; that
    query still gets a bm25 (keyword-only) probe, just no vector/hybrid probe.
    """
    queries = settings.weaviate_census_probe_queries
    if not model_id:
        return {q: None for q in queries}
    handler = _safe(lambda: LlmRequestHandler(model_id=model_id))
    result: dict[str, list[float] | None] = {}
    for query in queries:
        result[query] = (
            _safe(lambda q=query: handler.embed(q)) if handler is not None else None
        )
    return result


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
    probe_queries: dict[str, list[float] | None],
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
    logger.info(
        "%s course_names_resolved=%d map=%s",
        _PREFIX,
        len(course_names),
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
    probe_queries: dict[str, list[float] | None],
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
    logger.info(
        "%s collection=%s index_distance=%s quantizer=%s properties=%s",
        _PREFIX,
        name,
        distance,
        quantizer or "none",
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
            logger.info(
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


def _describe_hit(props: dict[str, Any], course_names: dict[int, str]) -> str:
    """One-line human description of a stored object: course, title, page, snippet."""
    course = _course_label(props.get(_COURSE_PROP), course_names)
    title = next((props[p] for p in _NAME_PROPS if props.get(p)), None)
    content = next((props[p] for p in _CONTENT_PROPS if props.get(p)), None)
    page = props.get("page_number")
    parts = [f"course={course!r}"]
    if title:
        parts.append(f"title={str(title)[:60]!r}")
    if page is not None:
        parts.append(f"page={page}")
    if content:
        parts.append(f"snippet={str(content)[:_SNIPPET_LEN]!r}")
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
        logger.info(
            "%s collection=%s sample#%d %s",
            _PREFIX,
            name,
            i,
            _describe_hit(obj.properties, course_names),
        )


def _probe_retrieval(
    name: str,
    collection: Any,
    probe_queries: dict[str, list[float] | None],
    course_names: dict[int, str],
) -> None:
    """For each configured query, run bm25 / near_vector / hybrid and log every hit.

    Running the three modalities separately (rather than only the fused hybrid the UI
    uses) lets you decompose a bad result: if bm25 ranks the right doc high but hybrid
    buries it, the vector half + alpha=0.5 is drowning the keyword match; if bm25 also
    buries it, it is a tokenization/IDF problem. Per-hit course/title/snippet output
    shows whether the *relevant* content actually ranks.
    """
    for query, vector in probe_queries.items():
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


def _log_probe(
    name: str,
    label: str,
    score_attr: str,
    query: str,
    course_names: dict[int, str],
    fn,
) -> None:
    """Run one probe query and log the header plus one line per hit (score + content)."""
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
        return
    logger.info(
        "%s collection=%s probe=%s query=%r hits=%d",
        _PREFIX,
        name,
        label,
        query,
        len(objs),
    )
    for rank, obj in enumerate(objs, start=1):
        score = getattr(obj.metadata, score_attr, None)
        logger.info(
            "%s   probe=%s #%d %s=%s %s",
            _PREFIX,
            label,
            rank,
            score_attr,
            f"{score:.4f}" if isinstance(score, float) else score,
            _describe_hit(obj.properties, course_names),
        )


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
