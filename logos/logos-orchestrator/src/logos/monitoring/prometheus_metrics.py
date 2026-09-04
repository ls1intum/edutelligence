"""Prometheus metrics for Logos server.

Defines all custom metrics and exposes a WSGI app for the /metrics endpoint.
"""

from typing import Any

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, Histogram, generate_latest

registry = CollectorRegistry()

# ---------------------------------------------------------------------------
# Request pipeline
# ---------------------------------------------------------------------------

REQUESTS_TOTAL = Counter(
    "logos_requests_total",
    "Total requests entering the pipeline",
    ["status"],  # enqueued, scheduled, completed, timeout, error
    registry=registry,
)

REQUEST_DURATION_SECONDS = Histogram(
    "logos_request_duration_seconds",
    "End-to-end request duration from enqueue to completion",
    ["model", "provider", "status"],
    # `histogram_quantile` cannot report above the highest *finite* bucket:
    # everything beyond it lands in +Inf and the quantile is pinned to that
    # boundary. Topping out at 120s therefore reported every high percentile
    # as exactly "2 minutes" — with 5% of production requests over 120s, p95
    # sat on the edge and p99 (really ~300s) was clamped to 120s outright.
    # The upper buckets now cover what a request can legitimately take: the
    # queue wait alone is bounded at 1200s (LOGOS_TIMEOUT_S), and cold-load
    # plus generation can add to that.
    buckets=(
        0.1,
        0.25,
        0.5,
        1.0,
        2.5,
        5.0,
        10.0,
        30.0,
        60.0,
        120.0,
        300.0,
        600.0,
        1200.0,
        1800.0,
        3600.0,
    ),
    registry=registry,
)

REQUESTS_IN_FLIGHT = Gauge(
    "logos_requests_in_flight",
    "Requests currently being processed",
    registry=registry,
)

COLD_STARTS_TOTAL = Counter(
    "logos_cold_starts_total",
    "Number of requests served by a cold (freshly loaded) model",
    ["model", "provider"],
    registry=registry,
)

QUEUE_DEPTH = Gauge(
    "logos_queue_depth",
    "Current total queue depth across all providers",
    registry=registry,
)

REQUEST_RETRIES_TOTAL = Counter(
    "logos_request_retries_total",
    "Internal re-dispatches of failed requests instead of returning the error raw (#815)",
    ["kind"],  # retry (pre-completion), resume (mid-flight stream)
    registry=registry,
)

# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

CLASSIFICATION_DURATION_SECONDS = Histogram(
    "logos_classification_duration_seconds",
    "Time spent in the classification stage",
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
    registry=registry,
)

CLASSIFICATION_CANDIDATES = Histogram(
    "logos_classification_candidates",
    "Number of candidate models returned by classification",
    buckets=(0, 1, 2, 3, 5, 10, 20),
    registry=registry,
)

# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------

SCHEDULING_DECISIONS_TOTAL = Counter(
    "logos_scheduling_decisions_total",
    "Scheduling outcomes",
    ["result"],  # scheduled, no_capacity, timeout
    registry=registry,
)

ADMISSION_HOLDS_TOTAL = Counter(
    "logos_admission_holds_total",
    "Requests held at orchestrator level instead of being forwarded to a worker",
    # worker_capacity, backend_queue, kv_cache_pressure, engine_at_capacity
    ["reason"],
    registry=registry,
)

PREFIX_AFFINITY_TOTAL = Counter(
    "logos_prefix_affinity_total",
    "Prefix-cache affinity lookups and how the scheduler acted on them",
    ["result"],  # hit, miss, honored, diverted
    registry=registry,
)

WORKER_CANCELLATIONS_TOTAL = Counter(
    "logos_worker_cancellations_total",
    "Cancellations sent to a worker for a request whose client went away",
    # aborted    — the worker stopped a generation that was still running
    # already_done — the cancel raced a stream that had just finished
    # unsupported  — worker predates the cancel action; the request runs on
    # failed       — the cancel could not be delivered
    ["result"],
    registry=registry,
)

# ---------------------------------------------------------------------------
# Demand tracker
# ---------------------------------------------------------------------------

DEMAND_SCORE = Gauge(
    "logos_demand_score",
    "Current exponential-decay demand score per model",
    ["model"],
    registry=registry,
)

DEMAND_RAW_COUNT = Gauge(
    "logos_demand_raw_count",
    "Cumulative raw request count per model (non-decayed)",
    ["model"],
    registry=registry,
)

DEMAND_LATENT_TOTAL = Counter(
    "logos_demand_latent_total",
    "Latent demand recordings: classification preferred a model the scheduler did not select",
    ["model"],
    registry=registry,
)

# ---------------------------------------------------------------------------
# Capacity planner
# ---------------------------------------------------------------------------

CAPACITY_PLANNER_ACTIONS_TOTAL = Counter(
    "logos_capacity_planner_actions_total",
    "Actions taken by the capacity planner",
    ["action"],  # sleep, wake, load, stop, tune_gpu
    registry=registry,
)

CAPACITY_PLANNER_CYCLE_DURATION_SECONDS = Histogram(
    "logos_capacity_planner_cycle_duration_seconds",
    "Duration of one capacity planner evaluation cycle",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
    registry=registry,
)

CAPACITY_PLANNER_SWITCHES_TOTAL = Counter(
    "logos_capacity_planner_switches_total",
    "Total model switch events (wake/load of a different model)",
    registry=registry,
)

CAPACITY_PLANNER_SWITCH_GAP_SECONDS = Histogram(
    "logos_capacity_planner_switch_gap_seconds",
    "Time between consecutive model switches",
    buckets=[1, 2, 5, 10, 20, 30, 60, 120, 300],
    registry=registry,
)

# ---------------------------------------------------------------------------
# Worker node connectivity (as seen from the server)
# ---------------------------------------------------------------------------

WORKER_NODES_CONNECTED = Gauge(
    "logos_worker_nodes_connected",
    "Number of worker nodes currently connected",
    registry=registry,
)

WORKER_LANES_BY_STATE = Gauge(
    "logos_worker_lanes_by_state",
    "Number of worker lanes in each state (as reported to the server)",
    ["state"],  # cold, starting, loaded, running, sleeping, stopped, error
    registry=registry,
)

WORKER_VRAM_USED_MB = Gauge(
    "logos_worker_vram_used_mb",
    "Total effective VRAM used across all connected worker nodes (MB)",
    registry=registry,
)

WORKER_VRAM_FREE_MB = Gauge(
    "logos_worker_vram_free_mb",
    "Total free VRAM across all connected worker nodes (MB)",
    registry=registry,
)

# ---------------------------------------------------------------------------
# Engine telemetry (per provider/model pair)
# ---------------------------------------------------------------------------

PREFIX_CACHE_HIT_RATE = Gauge(
    "logos_prefix_cache_hit_rate",
    "vLLM prefix-cache hit rate per provider/model pair (0..1, cumulative since lane start)",
    ["model", "provider"],
    registry=registry,
)

MTP_ACCEPTANCE_RATE = Gauge(
    "logos_mtp_acceptance_rate",
    "MTP/speculative-decoding draft-token acceptance rate per provider/model pair (0..1, "
    "cumulative since lane start); absent for models running without speculative decoding",
    ["model", "provider"],
    registry=registry,
)

# ---------------------------------------------------------------------------
# Token usage (per request, cloud and local providers alike)
# ---------------------------------------------------------------------------

PROMPT_TOKENS_TOTAL = Counter(
    "logos_prompt_tokens_total",
    "Input (prompt) tokens processed per model/provider pair, all request outcomes",
    ["model", "provider"],
    registry=registry,
)

GENERATION_TOKENS_TOTAL = Counter(
    "logos_generation_tokens_total",
    "Output (generation) tokens produced per model/provider pair, all request outcomes",
    ["model", "provider"],
    registry=registry,
)

CACHED_PROMPT_TOKENS_TOTAL = Counter(
    "logos_cached_prompt_tokens_total",
    "Prompt tokens served from the prefix cache per model/provider pair; rate = "
    "this counter / logos_prompt_tokens_total in Grafana",
    ["model", "provider"],
    registry=registry,
)

REQUEST_CONTEXT_TOKENS = Histogram(
    "logos_request_context_tokens",
    "Context window used by a completed request (prompt + generation tokens), per model",
    ["model"],
    # Top out at 512k: calibrated lanes run at up to 262144 tokens, and a
    # generation can push the used window past the prompt length. Anything
    # beyond the highest bucket would clamp every high percentile to the
    # boundary, the same failure mode documented on REQUEST_DURATION_SECONDS.
    buckets=(256, 512, 1024, 2048, 4096, 8192, 16384, 32768, 65536, 131072, 262144, 524288),
    registry=registry,
)

# Label sets published by update_engine_cache_metrics(), so pairs whose lanes
# are gone can be removed instead of keeping their last value forever.
_PUBLISHED_ENGINE_METRIC_KEYS: set[tuple[str, str]] = set()


def _remove_label_silently(metric: Any, model: str, provider: str) -> None:
    """Remove a (model, provider) label set, tolerating a never-published gauge.

    ``prometheus_client``'s ``remove()`` raises ``KeyError`` for a label set
    that was never created, and a pair can legitimately be missing one side:
    a model without speculative decoding never publishes an MTP acceptance
    rate (no ``MTP_ACCEPTANCE_RATE`` child exists for it), and a lane that
    reports no prefix data never publishes a prefix rate. Retiring such a pair
    must not raise — a raised error here would abort the planner cycle before
    it does any capacity planning.
    """
    try:
        # `remove()` lives on the parent metric and takes positional label
        # values; a child obtained from .labels() has no working remove of its own.
        metric.remove(model, provider)
    except KeyError:
        pass


def update_engine_cache_metrics(entries: list[tuple[str, str, float | None, float | None]]) -> None:
    """Publish per-(model, provider) engine rates and retire stale label sets.

    Each entry is ``(model, provider, prefix_cache_hit_rate, mtp_acceptance_rate)``;
    a ``None`` rate is simply not published for that metric (the previous value
    stays until the pair disappears). Label sets that were published before but
    are missing from *entries* are removed from the gauges that hold them.

    The tracked-key state is refreshed in a ``finally`` so that a failure
    during retirement can never leave it frozen — a stale diff set would
    re-raise on every subsequent call and keep the caller (the planner cycle)
    dead.
    """
    current: set[tuple[str, str]] = set()
    for model, provider, prefix_rate, mtp_rate in entries:
        current.add((model, provider))
        if prefix_rate is not None:
            PREFIX_CACHE_HIT_RATE.labels(model=model, provider=provider).set(prefix_rate)
        if mtp_rate is not None:
            MTP_ACCEPTANCE_RATE.labels(model=model, provider=provider).set(mtp_rate)
    try:
        for model, provider in _PUBLISHED_ENGINE_METRIC_KEYS - current:
            _remove_label_silently(PREFIX_CACHE_HIT_RATE, model, provider)
            _remove_label_silently(MTP_ACCEPTANCE_RATE, model, provider)
    finally:
        _PUBLISHED_ENGINE_METRIC_KEYS.clear()
        _PUBLISHED_ENGINE_METRIC_KEYS.update(current)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def metrics_response() -> tuple[bytes, str]:
    """Return (body, content_type) suitable for a FastAPI Response."""
    return generate_latest(registry), CONTENT_TYPE_LATEST
