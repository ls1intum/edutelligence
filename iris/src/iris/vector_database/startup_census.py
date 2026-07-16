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
_UNIT_PROP = "lecture_unit_id"
_BASE_URL_PROP = "base_url"
_SUMMARY_PROPS = ("segment_summary", "lecture_unit_summary")

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
        query_dims, probe_vector, probe_norm = _log_embedding_config()
        collection_dims, unit_counts = _log_collections(
            query_dims, probe_vector, probe_norm
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
def _log_embedding_config() -> tuple[set[int], list[float] | None, float | None]:
    """Resolve every embedding role, measure each distinct model's real output, and
    capture one live query vector as the retrieval probe.

    Returns (query_dims, probe_vector, probe_norm).
    """
    dim_cache: dict[str, int | None] = {}
    query_dims: set[int] = set()
    ingest_dims: set[int] = set()
    probe_vector: list[float] | None = None
    probe_norm: float | None = None

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
            if is_query and vector is not None and probe_vector is None:
                probe_vector, probe_norm = vector, norm

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
    return query_dims, probe_vector, probe_norm


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
    probe_vector: list[float] | None,
    probe_norm: float | None,
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
    collection_dims: dict[str, int | None] = {}
    unit_counts: dict[str, int] = {}
    total_vectors = 0

    for name, attr in _COLLECTIONS:
        collection = attr_map.get(attr)
        if collection is None:
            continue
        dim, count, units = _census_one(
            name, collection, query_dims, probe_vector, probe_norm
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
    probe_vector: list[float] | None,
    probe_norm: float | None,
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
    units = _log_course_and_unit_breakdown(name, collection, prop_names)
    _log_data_quality(name, collection, count, prop_names)
    _log_base_urls(name, collection, prop_names)
    _probe_retrieval(name, collection, probe_vector)
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
    name: str, collection: Any, prop_names: set[str]
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
                "%s collection=%s course_id=%s objects=%d", _PREFIX, name, course_id, c
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


def _probe_retrieval(
    name: str, collection: Any, probe_vector: list[float] | None
) -> None:
    """Run real bm25 / vector / hybrid searches so the actual failure is recorded.

    bm25 uses no vector (should work regardless of dimension); near_vector and hybrid
    use the current query vector and will surface the dimension-mismatch error text
    if the stored vectors were built by a different embedding model.
    """
    # BM25: keyword-only, dimension-independent — proves the text index works.
    bm25 = _probe(
        lambda: collection.query.bm25(
            query=_PROBE_TEXT,
            limit=_PROBE_LIMIT,
            return_metadata=MetadataQuery(score=True),
        )
    )
    logger.info("%s collection=%s probe=bm25 %s", _PREFIX, name, bm25)

    if probe_vector is None:
        return

    # Vector-only: isolates the vector space — this is where a dim mismatch throws.
    near = _probe(
        lambda: collection.query.near_vector(
            near_vector=probe_vector,
            limit=_PROBE_LIMIT,
            return_metadata=MetadataQuery(distance=True),
        ),
        score_attr="distance",
    )
    logger.info("%s collection=%s probe=near_vector %s", _PREFIX, name, near)

    # Hybrid: the actual retrieval path used by lecture/global search.
    hybrid = _probe(
        lambda: collection.query.hybrid(
            query=_PROBE_TEXT,
            vector=probe_vector,
            alpha=0.5,
            limit=_PROBE_LIMIT,
            return_metadata=MetadataQuery(score=True),
        )
    )
    logger.info("%s collection=%s probe=hybrid %s", _PREFIX, name, hybrid)


def _probe(fn, score_attr: str = "score") -> str:
    """Run a probe query, returning a compact 'hits=.. top=.. ' or 'ERROR=..' string."""
    try:
        objs = fn().objects
        if not objs:
            return "hits=0"
        top = getattr(objs[0].metadata, score_attr, None)
        return f"hits={len(objs)} top_{score_attr}={top}"
    except Exception as e:  # noqa: BLE001 - the error text IS the diagnostic signal
        return f"ERROR={str(e)[:200]}"


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

    Chat models get a tiny real completion; the reranker gets a registration check
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
            logger.info(
                "%s llm_ping role=%s env=%s model=%s %s",
                _PREFIX,
                label,
                env,
                model,
                pinged[model],
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
    """Send a minimal completion; return 'ok latency_ms=..' or 'ERROR=..'."""
    t0 = time.perf_counter()
    try:
        LlmRequestHandler(model_id=model_id).complete(
            "ping", CompletionArguments(temperature=0, max_tokens=5)
        )
        return f"ok latency_ms={(time.perf_counter() - t0) * 1000:.0f}"
    except Exception as e:  # noqa: BLE001 - unreachable answer model is the signal
        return f"ERROR={str(e)[:200]}"


def _safe(fn, default=None):
    """Run a read-only probe; on any error return default (census is best-effort)."""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        logger.debug("%s probe failed: %s", _PREFIX, e)
        return default
