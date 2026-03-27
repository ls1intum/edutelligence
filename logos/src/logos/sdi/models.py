"""
Data models for Scheduling Data Interface.

Type-safe data classes for SDI responses. These provide an alternative
to raw dictionaries with better IDE support and type checking.
"""

from dataclasses import dataclass, field
from datetime import datetime
import re
from typing import Any, Dict, Optional, List

# Import queue state from queue subsystem
from logos.queue.models import QueueStatePerPriority


_MODEL_SCALE_RE = re.compile(r"(?i)(\d+(?:\.\d+)?)([bm])")


def _estimated_disk_size_bytes_from_model_name(model_name: str) -> int | None:
    lowered = (model_name or "").lower()
    match = _MODEL_SCALE_RE.search(lowered)
    if match is None:
        return None

    magnitude = float(match.group(1))
    unit = match.group(2).lower()
    params = magnitude * (1_000_000_000 if unit == "b" else 1_000_000)

    bytes_per_param = 2.0
    if any(token in lowered for token in ("q2", "2bit")):
        bytes_per_param = 0.35
    elif any(token in lowered for token in ("q3", "3bit")):
        bytes_per_param = 0.45
    elif any(token in lowered for token in ("q4", "4bit", "int4", "awq", "gptq")):
        bytes_per_param = 0.60
    elif any(token in lowered for token in ("q5", "5bit")):
        bytes_per_param = 0.70
    elif any(token in lowered for token in ("q6", "6bit")):
        bytes_per_param = 0.80
    elif any(token in lowered for token in ("q8", "8bit", "int8")):
        bytes_per_param = 1.00

    return int(params * bytes_per_param)


def _base_residency_from_bytes(disk_size_bytes: Optional[int]) -> Optional[float]:
    """Convert model weight bytes to estimated GPU residency in MB.

    Adds 20% overhead for CUDA kernels, activation buffers, and runtime
    (per EleutherAI inference overhead research).
    """
    if disk_size_bytes is None or disk_size_bytes <= 0:
        return None
    return (disk_size_bytes / (1024 * 1024)) * 1.2


@dataclass
class ModelStatus:
    """
    Status data for a single model.

    Provides raw data only - schedulers should derive predictions from this data.
    For example, to predict cold starts:
    - Ollama: Check if is_loaded=False or expires_at < now
    - Cloud: Always False (no cold starts in cloud providers)

    Queue State:
    - queue_state: Breakdown of queue depth by priority level
      * Ollama: Real 3-level breakdown (we control the queue)
      * Cloud: None (they control the queue, we have no visibility)
    - queue_depth: Total queue depth (computed property)
      * Returns 0 if queue_state is None (cloud providers)
    """

    model_id: int
    provider_id: int
    is_loaded: bool
    vram_mb: int
    expires_at: Optional[datetime]
    queue_state: Optional[QueueStatePerPriority]  # None for cloud providers
    active_requests: int
    provider_type: str  # 'logosnode' | 'azure'

    @property
    def queue_depth(self) -> int:
        """
        Total queue depth across all priority levels.

        Returns 0 for cloud providers (no queue visibility).
        For Ollama providers, returns sum of all priority queues.

        This is a computed property for backward compatibility.
        """
        if self.queue_state is None:
            return 0  # Cloud providers: no queue control
        return self.queue_state.total

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'model_id': self.model_id,
            'is_loaded': self.is_loaded,
            'vram_mb': self.vram_mb,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'queue_depth': self.queue_depth,  # Computed property
            'queue_state': {
                'low': self.queue_state.low,
                'normal': self.queue_state.normal,
                'high': self.queue_state.high,
                'total': self.queue_state.total,
            } if self.queue_state else None,
            'active_requests': self.active_requests,
            'provider_type': self.provider_type
        }


@dataclass
class OllamaCapacity:
    """
    Capacity information for Ollama providers.

    Schedulers can determine if new models can be loaded based on available_vram_mb.
    """

    available_vram_mb: int
    total_vram_mb: int
    loaded_models: List[str]

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'available_vram_mb': self.available_vram_mb,
            'total_vram_mb': self.total_vram_mb,
            'loaded_models': self.loaded_models
        }


@dataclass
class AzureCapacity:
    """Capacity information for Azure providers with per-deployment rate limits."""

    deployment_name: str
    rate_limit_remaining_requests: Optional[int]
    rate_limit_remaining_tokens: Optional[int]
    rate_limit_total_requests: Optional[int]
    rate_limit_total_tokens: Optional[int]
    rate_limit_resets_at: Optional[datetime]
    last_header_age_seconds: Optional[float]
    has_capacity: bool

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'deployment_name': self.deployment_name,
            'rate_limit_remaining_requests': self.rate_limit_remaining_requests,
            'rate_limit_remaining_tokens': self.rate_limit_remaining_tokens,
            'rate_limit_total_requests': self.rate_limit_total_requests,
            'rate_limit_total_tokens': self.rate_limit_total_tokens,
            'rate_limit_resets_at': self.rate_limit_resets_at.isoformat() if self.rate_limit_resets_at else None,
            'last_header_age_seconds': self.last_header_age_seconds,
            'has_capacity': self.has_capacity
        }


@dataclass
class LaneSchedulerSignals:
    """Per-lane runtime signals for ETTFT estimation and capacity planning."""

    lane_id: str
    model_name: str
    runtime_state: str  # cold|starting|loaded|running|sleeping|stopped|error
    sleep_state: str  # unsupported|unknown|awake|sleeping
    is_vllm: bool
    active_requests: int
    queue_waiting: float  # from backend_metrics (vLLM) or 0 (Ollama)
    requests_running: float  # from backend_metrics (vLLM) or active_requests (Ollama)
    gpu_cache_usage_percent: Optional[float]  # vLLM only
    ttft_p95_seconds: float  # computed from ttft_histogram, 0.0 if unavailable
    effective_vram_mb: float
    num_parallel: int  # Ollama: explicit, vLLM: 0 (continuous batching)
    gpu_memory_utilization: Optional[float] = None  # vLLM planner target
    tensor_parallel_size: Optional[int] = None  # vLLM topology hint
    gpu_devices: Optional[str] = None  # GPU device indices e.g. "0,1"

    def to_dict(self) -> dict:
        return {
            'lane_id': self.lane_id,
            'model_name': self.model_name,
            'runtime_state': self.runtime_state,
            'sleep_state': self.sleep_state,
            'is_vllm': self.is_vllm,
            'active_requests': self.active_requests,
            'queue_waiting': self.queue_waiting,
            'requests_running': self.requests_running,
            'gpu_cache_usage_percent': self.gpu_cache_usage_percent,
            'ttft_p95_seconds': self.ttft_p95_seconds,
            'effective_vram_mb': self.effective_vram_mb,
            'num_parallel': self.num_parallel,
            'gpu_memory_utilization': self.gpu_memory_utilization,
            'tensor_parallel_size': self.tensor_parallel_size,
            'gpu_devices': self.gpu_devices,
        }


# Warmth ordering for runtime_state — lower index = warmer.
_STATE_WARMTH_ORDER = ["running", "loaded", "sleeping", "starting", "cold", "stopped", "error"]
_SLEEP_WARMTH_ORDER = ["awake", "unknown", "sleeping", "unsupported"]


@dataclass
class ModelSchedulerView:
    """Aggregated scheduling view for one model across all its lanes on a provider."""

    model_id: int
    model_name: str
    provider_id: int
    is_loaded: bool  # any lane in loaded/running state
    best_lane_state: str  # warmest runtime_state among matching lanes
    best_sleep_state: str  # warmest sleep_state among matching lanes
    aggregate_active_requests: int  # sum across all matching lanes
    aggregate_queue_waiting: float  # sum of queue_waiting across lanes
    warmest_ttft_p95_seconds: float  # min ttft_p95 among loaded lanes (best case)
    gpu_cache_pressure_max: Optional[float]  # max gpu_cache_usage_percent across lanes
    lanes: List[LaneSchedulerSignals] = field(default_factory=list)

    @staticmethod
    def warmest_state(states: List[str]) -> str:
        """Return the warmest runtime_state from a list, using _STATE_WARMTH_ORDER."""
        if not states:
            return "error"
        best_idx = len(_STATE_WARMTH_ORDER)
        best = "error"
        for s in states:
            try:
                idx = _STATE_WARMTH_ORDER.index(s)
            except ValueError:
                idx = len(_STATE_WARMTH_ORDER)
            if idx < best_idx:
                best_idx = idx
                best = s
        return best

    @staticmethod
    def warmest_sleep(states: List[str]) -> str:
        """Return the warmest sleep_state from a list."""
        if not states:
            return "unsupported"
        best_idx = len(_SLEEP_WARMTH_ORDER)
        best = "unsupported"
        for s in states:
            try:
                idx = _SLEEP_WARMTH_ORDER.index(s)
            except ValueError:
                idx = len(_SLEEP_WARMTH_ORDER)
            if idx < best_idx:
                best_idx = idx
                best = s
        return best

    def to_dict(self) -> dict:
        return {
            'model_id': self.model_id,
            'model_name': self.model_name,
            'provider_id': self.provider_id,
            'is_loaded': self.is_loaded,
            'best_lane_state': self.best_lane_state,
            'best_sleep_state': self.best_sleep_state,
            'aggregate_active_requests': self.aggregate_active_requests,
            'aggregate_queue_waiting': self.aggregate_queue_waiting,
            'warmest_ttft_p95_seconds': self.warmest_ttft_p95_seconds,
            'gpu_cache_pressure_max': self.gpu_cache_pressure_max,
            'lanes': [lane.to_dict() for lane in self.lanes],
        }


@dataclass
class CapacityPlanAction:
    """A single capacity change to be validated and executed."""

    action: str  # sleep_l1|sleep_l2|wake|stop|load|reconfigure_gpu_util
    provider_id: int
    lane_id: str
    model_name: str
    params: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            'action': self.action,
            'provider_id': self.provider_id,
            'lane_id': self.lane_id,
            'model_name': self.model_name,
            'params': self.params,
            'reason': self.reason,
        }


@dataclass
class ModelProfile:
    """Auto-calibrated model resource profile from worker measurements."""

    model_name: str
    loaded_vram_mb: Optional[float] = None
    sleeping_residual_mb: Optional[float] = None
    disk_size_bytes: Optional[int] = None
    base_residency_mb: Optional[float] = None
    kv_budget_mb: Optional[float] = None
    engine: Optional[str] = None
    observed_gpu_memory_utilization: Optional[float] = None
    min_gpu_memory_utilization_to_load: Optional[float] = None
    tensor_parallel_size: Optional[int] = None
    kv_per_token_bytes: Optional[int] = None
    max_context_length: Optional[int] = None
    measurement_count: int = 0
    last_measured_epoch: float = 0.0
    residency_source: Optional[str] = None

    def estimate_vram_mb(self) -> float:
        """Best estimate of model footprint (not GPU reservation).

        For vLLM, loaded_vram_mb is the full GPU reservation (gpu_util × device_vram),
        which vastly overestimates the actual model size. Prefer base_residency_mb
        (model weights + runtime overhead) for vLLM engines.
        """
        if self.engine == "vllm":
            base = self.estimate_base_residency_mb()
            if base is not None:
                return base
        if self.loaded_vram_mb is not None:
            return self.loaded_vram_mb
        base = self.estimate_base_residency_mb()
        if base is not None:
            return base
        return 4096.0  # conservative fallback

    def estimate_base_residency_mb(self) -> Optional[float]:
        if self.base_residency_mb is not None:
            return self.base_residency_mb
        disk_size_bytes = self.disk_size_bytes
        if (disk_size_bytes is None or disk_size_bytes <= 0) and self.model_name:
            disk_size_bytes = _estimated_disk_size_bytes_from_model_name(self.model_name)
        return _base_residency_from_bytes(disk_size_bytes)

    def to_dict(self) -> dict:
        return {
            'model_name': self.model_name,
            'loaded_vram_mb': self.loaded_vram_mb,
            'sleeping_residual_mb': self.sleeping_residual_mb,
            'disk_size_bytes': self.disk_size_bytes,
            'base_residency_mb': self.base_residency_mb,
            'kv_budget_mb': self.kv_budget_mb,
            'engine': self.engine,
            'observed_gpu_memory_utilization': self.observed_gpu_memory_utilization,
            'min_gpu_memory_utilization_to_load': self.min_gpu_memory_utilization_to_load,
            'tensor_parallel_size': self.tensor_parallel_size,
            'kv_per_token_bytes': self.kv_per_token_bytes,
            'max_context_length': self.max_context_length,
            'measurement_count': self.measurement_count,
            'last_measured_epoch': self.last_measured_epoch,
            'residency_source': self.residency_source,
        }


@dataclass
class RequestMetrics:
    """Metrics collected for a completed request."""

    queue_wait_ms: float
    was_cold_start: bool
    duration_ms: float
    queue_depth_at_arrival: int
    priority: str

    def to_dict(self) -> dict:
        """Convert to dictionary for database logging."""
        return {
            'queue_wait_ms': self.queue_wait_ms,
            'was_cold_start': self.was_cold_start,
            'duration_ms': self.duration_ms,
            'queue_depth_at_arrival': self.queue_depth_at_arrival,
            'priority': self.priority
        }
