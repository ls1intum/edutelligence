"""
Pydantic models for the Node Controller.

Covers: configuration, Ollama status, GPU metrics, API requests/responses.
"""

from __future__ import annotations

import enum
import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


_GPU_DEVICE_LIST_PATTERN = re.compile(r"^\d+(,\d+)*$")


def _normalize_gpu_devices(raw: str) -> str:
    """Normalize and validate a GPU device selector string.

    Supported values:
    - ``all`` (all visible GPUs)
    - ``none`` (CPU-only mode)
    - ``0,1,2`` (explicit GPU IDs)
    - ``""`` (inherit from global/default)
    """
    value = (raw or "").strip().replace(" ", "")
    lowered = value.lower()
    if lowered in {"", "all", "none"}:
        return lowered
    if not _GPU_DEVICE_LIST_PATTERN.fullmatch(value):
        raise ValueError(
            "Invalid gpu_devices value. Use 'all', 'none', or a comma-separated "
            "GPU index list like '0,1'."
        )
    return value


def _gpu_device_count(value: str) -> int | None:
    """Return explicit GPU count for '0,1,...' selectors, else None."""
    normalized = _normalize_gpu_devices(value)
    if normalized in {"", "all", "none"}:
        return None
    return len(normalized.split(","))


# ---------------------------------------------------------------------------
# Configuration models (mirror config.yml)
# ---------------------------------------------------------------------------

class OllamaConfig(BaseModel):
    """Runtime configuration for the managed Ollama process."""

    # Path to the Ollama binary on the host
    ollama_binary: str = "/usr/local/bin/ollama"

    # Port the Ollama server listens on (OLLAMA_HOST=0.0.0.0:<port>)
    port: int = 11435

    # GPU visibility:
    #   "all"  — all GPUs visible (default, no CUDA_VISIBLE_DEVICES set)
    #   "none" — CPU-only (CUDA_VISIBLE_DEVICES="")
    #   "0,1"  — specific GPU device IDs
    gpu_devices: str = "all"

    # Ollama runtime params (all become environment variables, require restart)
    num_parallel: int = 4
    max_loaded_models: int = 3
    keep_alive: str = "5m"
    max_queue: int = 512
    context_length: int = 4096
    flash_attention: bool = True
    kv_cache_type: str = "q8_0"

    # Multi-GPU scheduling: spread layers across all GPUs instead of
    # packing onto one.  Useful for models that barely fit a single GPU.
    sched_spread: bool = False

    # Enable shared prompt cache across concurrent requests to the same
    # model.  Reduces VRAM when many users send similar prefixes.
    multiuser_cache: bool = False

    # Reserved VRAM (bytes) that Ollama should NOT allocate for models.
    # Prevents OOM when the system/other processes need GPU memory.
    gpu_overhead_bytes: int = 0

    # Maximum time Ollama waits for a model to load (e.g. "5m", "300s").
    # Empty string = Ollama default.
    load_timeout: str = ""

    # Allowed CORS origins for direct Ollama access (e.g. ["http://localhost:3000"]).
    # Empty list = Ollama default (* for same-origin).
    origins: list[str] = Field(default_factory=list)

    # Prevent Ollama from automatically pruning unused model blobs.
    noprune: bool = False

    # Force a specific CUDA backend.  Ollama ships both cuda_v12 and cuda_v13.
    # On compute-capability 7.x GPUs the v13 backend has a ~75s graph-compile
    # penalty on every fresh process start, while v12 loads in ~7s.  Set to
    # "cuda_v12" to avoid this.  Empty string = let Ollama auto-detect.
    llm_library: str = ""

    # Where Ollama stores downloaded models
    models_path: str = "/usr/share/ollama/.ollama/models"
    preload_models: list[str] = Field(default_factory=list)
    env_overrides: dict[str, str] = Field(default_factory=dict)

    @field_validator("gpu_devices")
    @classmethod
    def _validate_gpu_devices(cls, value: str) -> str:
        return _normalize_gpu_devices(value)


class ControllerConfig(BaseModel):
    """Settings for the controller itself."""

    port: int = 8444
    api_key: str = "change-me-to-a-random-secret"
    tls_enabled: bool = False
    tls_cert_path: str = "certs/cert.pem"
    tls_key_path: str = "certs/key.pem"
    gpu_poll_interval: int = 5
    ollama_poll_interval: int = 5
    # Lane ports are allocated from this inclusive range.  Keep this range
    # away from ``ollama.port`` (legacy single-process endpoint) to avoid
    # accidental collisions when both are active.
    lane_port_start: int = 11436
    lane_port_end: int = 11499


class AppConfig(BaseModel):
    """Top-level application configuration."""

    controller: ControllerConfig = Field(default_factory=ControllerConfig)
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    lanes: list[LaneConfig] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Process state
# ---------------------------------------------------------------------------

class ProcessState(str, enum.Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    NOT_STARTED = "not_started"
    ERROR = "error"


class ProcessStatus(BaseModel):
    """Current state of the managed Ollama process."""

    state: ProcessState
    pid: int | None = None
    return_code: int | None = None


# ---------------------------------------------------------------------------
# Ollama model information
# ---------------------------------------------------------------------------

class LoadedModel(BaseModel):
    """A model currently loaded in Ollama VRAM."""

    name: str
    size: int = 0                  # total model size in bytes
    size_vram: int = 0             # bytes currently in VRAM
    expires_at: datetime | None = None
    digest: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class AvailableModel(BaseModel):
    """A model available (downloaded) in Ollama."""

    name: str
    size: int = 0
    digest: str | None = None
    modified_at: datetime | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class OllamaStatus(BaseModel):
    """Combined status of the Ollama instance."""

    reachable: bool = False
    loaded_models: list[LoadedModel] = Field(default_factory=list)
    available_models: list[AvailableModel] = Field(default_factory=list)
    version: str | None = None


# ---------------------------------------------------------------------------
# GPU metrics
# ---------------------------------------------------------------------------

class GpuInfo(BaseModel):
    """Metrics for a single GPU from nvidia-smi."""

    index: int
    uuid: str = ""
    name: str = ""
    memory_used_mb: float = 0.0
    memory_total_mb: float = 0.0
    memory_free_mb: float = 0.0
    utilization_percent: float = 0.0
    temperature_celsius: float = 0.0
    power_draw_watts: float | None = None


class GpuSnapshot(BaseModel):
    """Timestamped snapshot of all GPU metrics."""

    timestamp: datetime
    gpus: list[GpuInfo] = Field(default_factory=list)
    total_vram_mb: float = 0.0
    used_vram_mb: float = 0.0
    free_vram_mb: float = 0.0
    nvidia_smi_available: bool = False


# ---------------------------------------------------------------------------
# Combined status (what Logos polls)
# ---------------------------------------------------------------------------

class NodeStatus(BaseModel):
    """Full node status — the primary endpoint Logos polls.

    ``loaded_models`` mirrors Ollama's ``/api/ps`` output (models currently
    in VRAM).  For the full list of downloaded models use the dedicated
    ``/models/available`` endpoint.

    When running in multi-lane mode, ``lanes`` contains per-lane status
    including model, port, backend and VRAM usage.  For vLLM lanes,
    ``num_parallel`` is reported as 0 because concurrency is dynamic.
    Logos should route inference requests to the lane's port for its model.
    """

    timestamp: datetime
    process: ProcessStatus
    ollama_reachable: bool = False
    ollama_version: str | None = None
    loaded_models: list[LoadedModel] = Field(default_factory=list)
    gpu: GpuSnapshot
    config: OllamaConfig
    lanes: list["LaneStatus"] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# API request / response models
# ---------------------------------------------------------------------------

class ReconfigureRequest(BaseModel):
    """
    Partial Ollama config update.  Only provided fields are changed.
    Triggers process restart if runtime params differ.
    """

    num_parallel: int | None = None
    max_loaded_models: int | None = None
    keep_alive: str | None = None
    max_queue: int | None = None
    context_length: int | None = None
    flash_attention: bool | None = None
    kv_cache_type: str | None = None
    gpu_devices: str | None = None
    port: int | None = None
    preload_models: list[str] | None = None
    env_overrides: dict[str, str] | None = None

    # Tuning fields
    sched_spread: bool | None = None
    multiuser_cache: bool | None = None
    gpu_overhead_bytes: int | None = None
    load_timeout: str | None = None
    origins: list[str] | None = None
    noprune: bool | None = None
    llm_library: str | None = None


class ModelCreateRequest(BaseModel):
    """Create a model variant from a Modelfile specification.

    This wraps Ollama's ``POST /api/create``.  Use it to set per-model
    defaults like ``num_ctx``, ``temperature``, system prompts, or
    to quantize / merge adapters.

    Example modelfile content::

        FROM llama3.2
        PARAMETER num_ctx 8192
        PARAMETER temperature 0.7
        SYSTEM You are a helpful coding assistant.
    """

    name: str = Field(..., description="Name for the new model variant, e.g. 'llama3.2-code:8k'")
    modelfile: str = Field(..., description="Modelfile content (FROM, PARAMETER, SYSTEM, etc.)")


# ---------------------------------------------------------------------------
# Lane models — multi-process Ollama serving
# ---------------------------------------------------------------------------

class VllmConfig(BaseModel):
    """vLLM-specific configuration for a lane.

    vLLM uses continuous batching — no fixed ``num_parallel``.  It handles
    arbitrary concurrency dynamically and exposes an OpenAI-compatible API.
    """

    model_config = ConfigDict(extra="forbid")

    vllm_binary: str = Field(default="vllm", description="Path to vllm CLI or 'vllm' if on PATH")
    tensor_parallel_size: int = Field(default=1, ge=1, description="Number of GPUs for tensor parallelism")
    max_model_len: int = Field(default=0, ge=0, description="Max context length (0 = model default)")
    dtype: str = Field(default="auto", description="Data type: auto | half | float16 | bfloat16 | float32")
    quantization: str = Field(default="", description="Quantization method: awq | gptq | squeezellm | '' (none)")
    gpu_memory_utilization: float = Field(default=0.90, ge=0.1, le=1.0, description="Fraction of GPU memory to use")
    enforce_eager: bool = Field(default=False, description="Disable CUDA graphs (saves memory, slower)")
    enable_prefix_caching: bool = Field(default=True, description="Cache KV-cache for shared prefixes (system prompts). Major throughput win.")
    disable_custom_all_reduce: bool = Field(
        default=False,
        description="Use NCCL all-reduce instead of custom all-reduce kernels. Can improve stability on some systems.",
    )
    disable_nccl_p2p: bool = Field(
        default=False,
        description="Set NCCL_P2P_DISABLE=1 for this lane. Useful when GPU P2P causes hangs on specific drivers/topologies.",
    )
    enable_sleep_mode: bool = Field(
        default=False,
        description="Enable vLLM /sleep and /wake_up endpoints (--enable-sleep-mode).",
    )
    server_dev_mode: bool = Field(
        default=False,
        description="Set VLLM_SERVER_DEV_MODE=1 (required for some development-only server endpoints).",
    )
    extra_args: list[str] = Field(default_factory=list, description="Additional CLI args passed to vllm serve")


class LaneConfig(BaseModel):
    """Desired configuration for a single model lane.

    Each lane runs an isolated process dedicated to one model.  The
    ``backend`` field selects the inference engine:

    - ``"ollama"`` (default): Ollama with fixed ``num_parallel`` KV-cache
      slots.  Good for predictable workloads.
    - ``"vllm"``: vLLM with continuous batching — handles any concurrency
      level dynamically.  Exposes an OpenAI-compatible API.  Best for
      high-throughput lanes where request rate is unpredictable.
    """

    model_config = ConfigDict(extra="forbid")

    model: str = Field(..., description="Model to load in this lane, e.g. 'llama3.2'")
    backend: Literal["ollama", "vllm"] = Field(default="ollama", description="Inference backend: 'ollama' | 'vllm'")
    num_parallel: int = Field(default=4, ge=1, description="Concurrent inference slots (Ollama only)")
    context_length: int = Field(default=4096, ge=128, description="Max context window (num_ctx)")
    keep_alive: str = Field(default="5m", description="How long the model stays loaded after last use (Ollama only)")
    kv_cache_type: str = Field(default="q8_0", description="KV cache quantisation: q8_0 | f16 (Ollama only)")
    flash_attention: bool = Field(default=True, description="Enable Flash Attention")
    gpu_devices: str = Field(default="", description="GPU devices for this lane (empty = inherit global)")
    vllm: VllmConfig = Field(default_factory=VllmConfig, description="vLLM-specific settings (only when backend='vllm')")

    @field_validator("gpu_devices")
    @classmethod
    def _validate_gpu_devices(cls, value: str) -> str:
        return _normalize_gpu_devices(value)

    @model_validator(mode="after")
    def _validate_backend_specific_fields(self) -> LaneConfig:
        if self.backend == "ollama":
            if self.vllm != VllmConfig():
                raise ValueError(
                    "Custom 'vllm' settings were provided but backend='ollama'. "
                    "Remove the vllm block or set backend='vllm'."
                )
            return self

        explicit_gpu_count = _gpu_device_count(self.gpu_devices)
        tp_size = self.vllm.tensor_parallel_size
        if explicit_gpu_count is not None and tp_size > explicit_gpu_count:
            raise ValueError(
                "vLLM tensor_parallel_size is larger than the lane's explicit gpu_devices set "
                f"({tp_size} > {explicit_gpu_count})."
            )
        return self


class LaneStatus(BaseModel):
    """Runtime state of a single lane."""

    lane_id: str
    lane_uid: str = Field(
        default="",
        description="Globally unique lane identifier (<backend>:<lane_id>).",
    )
    model: str
    port: int
    backend: str = "ollama"
    process: ProcessStatus
    runtime_state: Literal[
        "running",
        "sleeping",
        "stopped",
        "not_started",
        "error",
        "unknown",
    ] = Field(
        default="unknown",
        description="Normalized lane state for routing decisions.",
    )
    routing_url: str = Field(default="", description="Base URL used by Logos to route requests to this lane.")
    inference_endpoint: str = Field(
        default="",
        description="Primary inference path for this lane backend.",
    )
    num_parallel: int = Field(description="Ollama fixed parallel slots; 0 means dynamic batching (vLLM)")
    context_length: int
    kv_cache_type: str
    flash_attention: bool
    gpu_devices: str = ""
    effective_gpu_devices: str = Field(
        default="",
        description="Resolved GPU selector after lane override/global fallback.",
    )
    sleep_mode_enabled: bool = Field(
        default=False,
        description="True when vLLM sleep mode endpoints are enabled for this lane.",
    )
    sleep_state: Literal["unsupported", "unknown", "awake", "sleeping"] = "unsupported"
    loaded_models: list[LoadedModel] = Field(default_factory=list)
    lane_config: LaneConfig | None = None
    backend_params: dict[str, Any] = Field(default_factory=dict)
    vram_reported_mb: float = 0.0
    vram_by_pid_mb: float = 0.0
    vram_device_mb: float = 0.0
    vram_source: Literal["pid", "reported", "device", "unknown"] = "unknown"
    vram_used_mb: float = 0.0


class LaneSetRequest(BaseModel):
    """Declarative request: describe the desired set of lanes.

    The controller diffs current vs desired and executes the minimal
    set of transitions (remove stale, modify changed, add new).
    """

    model_config = ConfigDict(extra="forbid")

    lanes: list[LaneConfig]

    @model_validator(mode="after")
    def _validate_unique_lane_models(self) -> LaneSetRequest:
        # Lane ID is derived from model name; duplicates silently overwriting
        # each other would be surprising for operators.
        lane_ids: dict[str, str] = {}
        for lane in self.lanes:
            lane_id = lane.model.replace("/", "_").replace(":", "_")
            if lane_id in lane_ids:
                prev_model = lane_ids[lane_id]
                raise ValueError(
                    "Duplicate lane model detected after lane-id normalization: "
                    f"{prev_model!r} and {lane.model!r} both map to lane_id={lane_id!r}."
                )
            lane_ids[lane_id] = lane.model
        return self


class LaneReconfigureRequest(BaseModel):
    """Partial update for a single lane.  Only provided fields change."""

    model_config = ConfigDict(extra="forbid")

    num_parallel: int | None = None
    context_length: int | None = None
    keep_alive: str | None = None
    kv_cache_type: str | None = None
    flash_attention: bool | None = None
    gpu_devices: str | None = None
    vllm: VllmConfig | None = None


class LaneSleepRequest(BaseModel):
    """Request body for vLLM lane sleep endpoint."""

    model_config = ConfigDict(extra="forbid")

    level: int = Field(
        default=1,
        ge=1,
        le=2,
        description="Sleep level (1=offload weights, 2=discard GPU state).",
    )
    mode: str = Field(
        default="wait",
        description="vLLM sleep mode parameter, typically 'wait'.",
    )


class LaneAction(BaseModel):
    """A single action taken during lane apply."""

    action: str  # "added" | "removed" | "reconfigured" | "unchanged"
    lane_id: str
    model: str
    details: str = ""


class LaneApplyResult(BaseModel):
    """Result of a declarative lane-apply operation."""

    success: bool
    actions: list[LaneAction] = Field(default_factory=list)
    lanes: list[LaneStatus] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    rolled_back: bool = False


class LaneEvent(BaseModel):
    """A recorded lane state transition for debugging and auditing."""

    timestamp: datetime
    lane_id: str
    event: str  # "spawned" | "stopped" | "hot_swap_start" | "hot_swap_ok" | "hot_swap_rollback" | "removed" | "sleep" | "wake" | "error"
    model: str = ""
    details: str = ""
    port: int | None = None
    num_parallel: int | None = None
    old_port: int | None = None


class ModelActionRequest(BaseModel):
    """Request body for pull / delete / unload / preload operations."""

    model: str


class ActionResponse(BaseModel):
    """Generic response for admin actions."""

    success: bool
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    """Minimal health check response (public endpoint)."""

    status: str = "ok"
    ollama_running: bool = False
    gpu_available: bool = False


class ModelInfoResponse(BaseModel):
    """Detailed model information from Ollama's /api/show."""

    model_config = {"protected_namespaces": ()}

    name: str
    modelfile: str = ""
    parameters: str = ""
    template: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
    model_info: dict[str, Any] = Field(default_factory=dict)

    status: str = "ok"
    controller_version: str = "1.0.0"
    ollama_running: bool = False
    gpu_available: bool = False
