"""Prometheus metrics for LogosWorkerNode.

Defines all custom metrics and exposes a WSGI app for the /metrics endpoint.
"""

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    Info,
    generate_latest,
    CONTENT_TYPE_LATEST,
)

registry = CollectorRegistry()

# ---------------------------------------------------------------------------
# Service info
# ---------------------------------------------------------------------------

WORKER_INFO = Info(
    "logos_worker",
    "Static worker node metadata",
    registry=registry,
)

# ---------------------------------------------------------------------------
# GPU telemetry (per device)
# ---------------------------------------------------------------------------

GPU_MEMORY_USED_MB = Gauge(
    "logos_worker_gpu_memory_used_mb",
    "GPU memory currently used (MB)",
    ["device_id", "gpu_index", "gpu_name"],
    registry=registry,
)

GPU_MEMORY_TOTAL_MB = Gauge(
    "logos_worker_gpu_memory_total_mb",
    "GPU total memory (MB)",
    ["device_id", "gpu_index", "gpu_name"],
    registry=registry,
)

GPU_MEMORY_FREE_MB = Gauge(
    "logos_worker_gpu_memory_free_mb",
    "GPU free memory (MB)",
    ["device_id", "gpu_index", "gpu_name"],
    registry=registry,
)

GPU_UTILIZATION_PERCENT = Gauge(
    "logos_worker_gpu_utilization_percent",
    "GPU utilization percentage",
    ["device_id", "gpu_index", "gpu_name"],
    registry=registry,
)

GPU_TEMPERATURE_CELSIUS = Gauge(
    "logos_worker_gpu_temperature_celsius",
    "GPU temperature in Celsius",
    ["device_id", "gpu_index", "gpu_name"],
    registry=registry,
)

GPU_POWER_DRAW_WATTS = Gauge(
    "logos_worker_gpu_power_draw_watts",
    "GPU power draw in Watts",
    ["device_id", "gpu_index", "gpu_name"],
    registry=registry,
)

# Aggregate GPU metrics
GPU_DEVICES_TOTAL = Gauge(
    "logos_worker_gpu_devices_total",
    "Number of GPU devices detected",
    registry=registry,
)

GPU_VRAM_TOTAL_MB = Gauge(
    "logos_worker_gpu_vram_total_mb",
    "Total VRAM across all GPUs (MB)",
    registry=registry,
)

GPU_VRAM_USED_MB = Gauge(
    "logos_worker_gpu_vram_used_mb",
    "Total VRAM used across all GPUs (MB)",
    registry=registry,
)

GPU_VRAM_FREE_MB = Gauge(
    "logos_worker_gpu_vram_free_mb",
    "Total VRAM free across all GPUs (MB)",
    registry=registry,
)

# ---------------------------------------------------------------------------
# Lane metrics
# ---------------------------------------------------------------------------

LANES_BY_STATE = Gauge(
    "logos_worker_lanes_by_state",
    "Number of lanes in each runtime state",
    ["state"],  # cold, starting, loaded, running, sleeping, stopped, error
    registry=registry,
)

LANES_TOTAL = Gauge(
    "logos_worker_lanes_total",
    "Total number of lanes",
    registry=registry,
)

LANE_ACTIVE_REQUESTS = Gauge(
    "logos_worker_lane_active_requests",
    "Number of active (in-flight) requests per lane",
    ["lane_id", "model"],
    registry=registry,
)

LANE_VRAM_EFFECTIVE_MB = Gauge(
    "logos_worker_lane_vram_effective_mb",
    "Effective VRAM used by each lane (MB)",
    ["lane_id", "model"],
    registry=registry,
)

LANE_TRANSITIONS_TOTAL = Counter(
    "logos_worker_lane_transitions_total",
    "Total lane state transitions",
    ["action"],  # apply, sleep, wake, delete, reconfigure, error
    registry=registry,
)

# ---------------------------------------------------------------------------
# Logos bridge connectivity
# ---------------------------------------------------------------------------

BRIDGE_CONNECTED = Gauge(
    "logos_worker_bridge_connected",
    "Whether the worker is connected to the Logos server (1=yes, 0=no)",
    registry=registry,
)

BRIDGE_HEARTBEATS_TOTAL = Counter(
    "logos_worker_bridge_heartbeats_total",
    "Total heartbeats sent to Logos server",
    registry=registry,
)

BRIDGE_RECONNECTS_TOTAL = Counter(
    "logos_worker_bridge_reconnects_total",
    "Total WebSocket reconnection attempts",
    registry=registry,
)

BRIDGE_ERRORS_TOTAL = Counter(
    "logos_worker_bridge_errors_total",
    "Total bridge communication errors",
    registry=registry,
)

# ---------------------------------------------------------------------------
# Inference (per lane)
# ---------------------------------------------------------------------------

INFERENCE_REQUESTS_TOTAL = Counter(
    "logos_worker_inference_requests_total",
    "Total inference requests received by the worker",
    ["lane_id", "model"],
    registry=registry,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def metrics_response() -> tuple[bytes, str]:
    """Return (body, content_type) suitable for a FastAPI Response."""
    return generate_latest(registry), CONTENT_TYPE_LATEST


async def update_from_runtime(app: object) -> None:
    """Snapshot current runtime state into Prometheus gauges.

    Called on each /metrics scrape so gauges are always fresh.
    """
    from logos_worker_node.runtime import build_runtime_status

    try:
        runtime = await build_runtime_status(app)
    except Exception:
        return

    # Worker info
    WORKER_INFO.info({
        "name": runtime.worker_name or "",
        "version": runtime.service_version or "",
        "worker_id": runtime.worker_id or "",
    })

    # GPU devices
    devices = runtime.devices
    GPU_DEVICES_TOTAL.set(len(devices.devices) if devices.devices else 0)
    GPU_VRAM_TOTAL_MB.set(devices.total_memory_mb)
    GPU_VRAM_USED_MB.set(devices.used_memory_mb)
    GPU_VRAM_FREE_MB.set(devices.free_memory_mb)

    for device in (devices.devices or []):
        labels = {
            "device_id": device.device_id or "",
            "gpu_index": str((device.extra or {}).get("index", "")),
            "gpu_name": device.name or "",
        }
        GPU_MEMORY_USED_MB.labels(**labels).set(device.memory_used_mb)
        GPU_MEMORY_TOTAL_MB.labels(**labels).set(device.memory_total_mb)
        GPU_MEMORY_FREE_MB.labels(**labels).set(device.memory_free_mb)
        if device.utilization_percent is not None:
            GPU_UTILIZATION_PERCENT.labels(**labels).set(device.utilization_percent)
        if device.temperature_celsius is not None:
            GPU_TEMPERATURE_CELSIUS.labels(**labels).set(device.temperature_celsius)
        if device.power_draw_watts is not None:
            GPU_POWER_DRAW_WATTS.labels(**labels).set(device.power_draw_watts)

    # Lane metrics
    state_counts: dict[str, int] = {}
    LANES_TOTAL.set(runtime.capacity.lane_count)
    for lane in runtime.lanes:
        state = lane.runtime_state or "unknown"
        state_counts[state] = state_counts.get(state, 0) + 1
        lane_labels = {"lane_id": lane.lane_id or "", "model": lane.model or ""}
        LANE_ACTIVE_REQUESTS.labels(**lane_labels).set(lane.active_requests or 0)
        LANE_VRAM_EFFECTIVE_MB.labels(**lane_labels).set(lane.effective_vram_mb or 0)

    for state in ("cold", "starting", "loaded", "running", "sleeping", "stopped", "error"):
        LANES_BY_STATE.labels(state=state).set(state_counts.get(state, 0))

    # Bridge connectivity
    BRIDGE_CONNECTED.set(1 if runtime.transport.connected else 0)
