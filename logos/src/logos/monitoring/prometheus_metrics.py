"""Prometheus metrics for Logos server.

Defines all custom metrics and exposes a WSGI app for the /metrics endpoint.
"""

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    CONTENT_TYPE_LATEST,
)

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
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0),
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
    ["model"],
    registry=registry,
)

QUEUE_DEPTH = Gauge(
    "logos_queue_depth",
    "Current total queue depth across all providers",
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
# Helpers
# ---------------------------------------------------------------------------

def metrics_response() -> tuple[bytes, str]:
    """Return (body, content_type) suitable for a FastAPI Response."""
    return generate_latest(registry), CONTENT_TYPE_LATEST
