"""Pydantic models for LogosWorkerNode runtime, API, and transport."""

from __future__ import annotations

import enum
import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_GPU_DEVICE_LIST_PATTERN = re.compile(r"^\d+(,\d+)*$")
_DEFAULT_LANE_CONTEXT_LENGTH = 4096


def _normalize_gpu_devices(raw: str) -> str:
    value = (raw or "").strip().replace(" ", "")
    lowered = value.lower()
    if lowered in {"", "all", "none"}:
        return lowered
    if not _GPU_DEVICE_LIST_PATTERN.fullmatch(value):
        raise ValueError(
            "Invalid gpu_devices value. Use 'all', 'none', or a comma-separated GPU index list like '0,1'."
        )
    return value


def _gpu_device_count(value: str) -> int | None:
    normalized = _normalize_gpu_devices(value)
    if normalized in {"", "all", "none"}:
        return None
    return len(normalized.split(","))


class OllamaConfig(BaseModel):
    """Shared Ollama engine defaults for all non-vLLM lanes."""

    ollama_binary: str = "/usr/local/bin/ollama"
    gpu_devices: str = "all"
    max_queue: int = 512
    sched_spread: bool = False
    multiuser_cache: bool = False
    gpu_overhead_bytes: int = 0
    load_timeout: str = ""
    origins: list[str] = Field(default_factory=list)
    noprune: bool = False
    llm_library: str = ""
    models_path: str = "/usr/share/ollama/.ollama/models"
    env_overrides: dict[str, str] = Field(default_factory=dict)

    @field_validator("gpu_devices")
    @classmethod
    def _validate_gpu_devices(cls, value: str) -> str:
        return _normalize_gpu_devices(value)


class VllmConfig(BaseModel):
    """vLLM-specific per-lane configuration."""

    model_config = ConfigDict(extra="forbid")

    vllm_binary: str = Field(
        default="vllm", description="Path to vllm CLI or 'vllm' on PATH"
    )
    tensor_parallel_size: int = Field(default=1, ge=1)
    max_model_len: int = Field(default=0, ge=0)
    dtype: str = Field(default="auto")
    quantization: str = Field(default="")
    gpu_memory_utilization: float | None = Field(
        default=None,
        ge=0.1,
        le=1.0,
        description="Per-GPU VRAM fraction passed to vLLM as "
        "--gpu-memory-utilization. vLLM uses this as a startup-floor gate: "
        "free_per_gpu must be >= gmu * total_per_gpu or the engine refuses "
        "to start, even when kv_cache_memory_bytes is set. None (default) "
        "auto-derives from the calibrated profile so the gate matches the "
        "lane's actual measured footprint: loaded_vram_mb / tp / "
        "total_per_gpu, clamped to [0.5, 0.95]. The planner's separate "
        "PER_GPU_COLD_START_MB headroom remains the sole safety buffer; "
        "gmu itself stays free of margin to avoid double-counting. Set an "
        "explicit float per model under engines.vllm.model_overrides.<model>"
        ".gpu_memory_utilization to opt out of auto-derivation; vLLM falls "
        "back to its own 0.9 default when neither this field nor a profile "
        "is available.",
    )
    kv_cache_memory_bytes: str = Field(
        default="",
        description="KV cache size per GPU, e.g. '4G', '2048M', or raw bytes. "
        "Empty = let vLLM decide from gpu_memory_utilization when that value is explicitly set.",
    )
    kv_cache_dtype: str = Field(
        default="",
        description="KV cache dtype passed to vLLM as --kv-cache-dtype "
        "(e.g. 'auto', 'fp8', 'fp8_e5m2', 'fp8_e4m3'). Empty (default) = "
        "let vLLM use its own default ('auto'), which matches the model "
        "dtype. Set to 'fp8' to halve KV cache footprint on supported GPUs.",
    )
    enforce_eager: bool = False
    attention_backend: str = Field(
        default="",
        description="Attention backend override (e.g. 'TRITON_ATTN', 'FLASHINFER'). "
        "Empty = auto-detect (TRITON_ATTN on pre-Ampere, FlashInfer on Ampere+).",
    )
    enable_prefix_caching: bool = True
    disable_custom_all_reduce: bool = False
    enable_sleep_mode: bool = False
    server_dev_mode: bool = False
    enable_auto_tool_choice: bool = Field(
        default=True,
        description="Enable automatic tool choice for function calling. "
        "Passes --enable-auto-tool-choice to vLLM. Set to false to disable.",
    )
    tool_call_parser: str = Field(
        default="",
        description="Tool call parser for function calling (e.g. 'hermes', 'mistral', 'llama3_json'). "
        "Empty (default) = infer from the model name (gemma4→gemma4, llama3→llama3_json, "
        "qwen→hermes, etc.; falls back to hermes). Set explicitly to override.",
    )
    reasoning_parser: str = Field(
        default="",
        description="Reasoning parser for structured reasoning output (e.g. 'deepseek_r1', 'qwen3', 'gemma4'). "
        "Empty (default) = infer from the model name when the model is a known reasoning model; "
        "no flag is emitted for unknown models. Set explicitly to force a specific parser. "
        "Set to 'none' to suppress the flag even when inference would match.",
    )
    cuda_graph_sizes: str = Field(
        default="",
        description="Comma-separated batch sizes for CUDA graph capture (e.g. '1,2,4,8'). "
        "Empty = vLLM default. Only effective when enforce_eager is False.",
    )
    cpu_offload_gb: float = Field(
        default=0.0,
        ge=0.0,
        description="CPU RAM for KV cache offloading (GB). Passed as --cpu-offload-gb to vLLM. 0 = disabled.",
    )
    mm_processor_cache_gb: float = Field(
        default=4.0,
        ge=0.0,
        description=(
            "Per-engine multimodal processor cache size (GB). Forwarded as "
            "--mm-processor-cache-gb. Matches vLLM's own 4 GB default so "
            "behaviour is unchanged unless overridden. The workernode also "
            "uses this field as a gate: when >0 it POSTs /reset_mm_cache "
            "after every successful /wake_up, because vLLM's /sleep clears "
            "only the EngineCore-side (P1) mm receiver cache and leaves the "
            "API-server-side (P0) sender cache populated. A request that "
            "re-uses an image hash from before the sleep cycle then sends "
            "mm_item=None to P1, which asserts on the cache miss and wedges "
            "the engine (cache.py:644 in vllm 0.20). Set to 0 to disable the "
            "IPC mm cache entirely; the post-wake re-sync is then skipped."
        ),
    )
    chat_template_kwargs: dict[str, Any] = Field(
        default_factory=dict,
        description="Default chat_template_kwargs passed to vLLM via --default-chat-template-kwargs. "
        'e.g. {"enable_thinking": false} to disable Qwen3/3.5 thinking mode.',
    )
    extra_args: list[str] = Field(default_factory=list)
    env_overrides: dict[str, str] = Field(
        default_factory=dict,
        description="Extra environment variables for this vLLM process. "
        "e.g. {\"VLLM_USE_V1\": \"0\"} to force V0 engine for models "
        "whose head dimensions exceed V1 attention kernel limits.",
    )

    @field_validator("kv_cache_memory_bytes")
    @classmethod
    def _validate_kv_cache(cls, value: str) -> str:
        if not value or not value.strip():
            return ""
        v = value.strip().upper()
        if re.fullmatch(r"\d+(\.\d+)?[GMK]?", v):
            return v
        raise ValueError(
            f"Invalid kv_cache_memory_bytes: {value!r}. "
            "Use e.g. '4G', '2048M', or raw byte count."
        )


class VllmEngineConfig(BaseModel):
    """Worker-wide vLLM defaults and telemetry settings."""

    metrics_path: str = "/metrics"
    metrics_timeout_seconds: int = Field(default=5, ge=1)
    flashinfer_loglevel: int = Field(
        default=0,
        ge=0,
        le=10,
        description="FlashInfer logging level (0, 1, 3, 5, 10). 0 disables logging.",
    )
    flashinfer_logdest: str = Field(
        default="",
        description="FlashInfer log destination: stdout, stderr, or a file path. Empty = FlashInfer default.",
    )
    nccl_p2p_available: bool = Field(
        default=False,
        description="Set to true when GPUs are connected via NVLink and NCCL peer-to-peer "
        "communication is available. Default false (PCIe-only topology) disables "
        "NCCL P2P globally for all TP>1 lanes to prevent hangs.",
    )
    nccl_debug: str = Field(
        default="",
        description="NCCL debug log level (e.g. INFO, WARN, VERSION). Empty = disabled.",
    )
    nccl_debug_subsys: str = Field(
        default="",
        description="Comma-separated NCCL debug subsystems (e.g. INIT,COLL,GRAPH). Empty = NCCL default.",
    )
    model_overrides: dict[str, dict] = Field(
        default_factory=dict,
        description="Per-model vLLM config overrides applied by this worker before launching a lane. "
        "Keys are model names; values are partial VllmConfig dicts (e.g. "
        "{disable_custom_all_reduce: true, quantization: awq}). "
        "Overrides are merged on top of whatever the Logos server sends, so the worker "
        "can enforce Turing/SM-7.5 workarounds without touching the server.",
    )
    global_extra_args: list[str] = Field(
        default_factory=list,
        description=(
            "Worker-wide vLLM CLI flags appended to every lane's command line, "
            "after the lane's own vllm_config.extra_args. Use this for flags "
            "that should apply uniformly across all lanes on this worker — for "
            "example '--safetensors-load-strategy=prefetch' when the model "
            "store is a network filesystem that vLLM's own detection misses "
            "(EXT4 over rbd-nbd / kernel block layer rather than NFS/Lustre)."
        ),
    )

    @field_validator("model_overrides", mode="before")
    @classmethod
    def _coerce_model_overrides(cls, value: Any) -> dict:
        if not value:
            return {}
        return value

    @field_validator("nccl_debug", "nccl_debug_subsys")
    @classmethod
    def _normalize_nccl_debug_fields(cls, value: str) -> str:
        return (value or "").strip().upper()


class EnginesConfig(BaseModel):
    """Shared engine defaults."""

    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    vllm: VllmEngineConfig = Field(default_factory=VllmEngineConfig)


class WorkerConfig(BaseModel):
    """LogosWorkerNode service settings."""

    port: int = 80
    tls_enabled: bool = False
    tls_cert_path: str = "certs/cert.pem"
    tls_key_path: str = "certs/key.pem"
    gpu_poll_interval: int = 5
    lane_port_start: int = 11436
    lane_port_end: int = 11499
    name: str = "logos-workernode"
    max_lanes: int = 0  # 0 = unlimited (backwards compatible)
    cache_path: str = Field(
        default="",
        description=(
            "Persistent root directory for HF model weights, vLLM compilation "
            "cache, torch inductor cache, and FlashInfer JIT kernels. Empty "
            "(default) → fall back to engines.ollama.models_path so existing "
            "ollama-aware deployments keep working unchanged. The env var "
            "LOGOS_WORKER_CACHE_ROOT, when set, takes precedence over this "
            "field."
        ),
    )
    auto_reboot_on_stuck_gpu: bool = Field(
        default=True,
        description=(
            "Initiate a host OS reboot when all lanes exhaust their crash-restart budget "
            "and at least one has stuck VRAM (unrecoverable GPU state). "
            "Tries 'sudo reboot' first; falls back to writing a sentinel file at "
            "reboot_sentinel_path for a host-side watchdog."
        ),
    )
    reboot_sentinel_path: str = Field(
        default="/host/reboot-requested",
        description=(
            "Path for the reboot-request sentinel file written when 'sudo reboot' is "
            "unavailable. Mount the host's /tmp or a dedicated directory so a "
            "host-side watchdog can detect and act on it."
        ),
    )
    gpu_performance_score: int = Field(
        default=100,
        ge=1,
        description=(
            "Operator-declared GPU capability weight used by the Logos request "
            "scheduler for weighted round-robin tie-breaks. When two warm "
            "workers tie on corrected_score for a model, traffic is split "
            "across them in proportion to this value. Examples: A6000 → 20, "
            "Blackwell RTX 6000 Pro → 40, H100 → 100. Default 100 means a "
            "homogeneous cluster gets uniform random distribution (no "
            "sticky-first bias). Set heterogeneous clusters explicitly so the "
            "faster GPU receives proportionally more requests."
        ),
    )


class LogosConfig(BaseModel):
    """Outbound control-plane connection to Logos.

    capabilities_models accepts both plain strings and dicts with inline overrides:
        capabilities_models:
          - "org/model-a"
          - model: "org/model-b"
            base_residency_mb: 5800
    Dict entries are normalized to plain model name strings; the overrides are
    extracted into capabilities_overrides for the profile registry.
    """

    enabled: bool = False
    logos_url: str = ""
    allow_insecure_http: bool = False
    shared_key: str = ""
    capabilities_models: list[str] = Field(default_factory=list)
    capabilities_overrides: dict[str, dict] = Field(default_factory=dict)
    heartbeat_interval_seconds: int = Field(default=5, ge=1)
    reconnect_backoff_seconds: int = Field(default=3, ge=1)
    # Max time between full runtime-status pushes regardless of lane churn.
    # Without this, VRAM/host-memory telemetry only reaches the server when a
    # lane state changes — so an idle worker that recently freed VRAM keeps
    # reporting the stale snapshot from the last lane transition. Signature
    # dedupe in _send_runtime_status still suppresses true no-op resends.
    status_refresh_interval_seconds: int = Field(default=15, ge=1)

    @model_validator(mode="before")
    @classmethod
    def _parse_capabilities(cls, values):
        """Normalize capabilities_models: extract inline overrides from dict entries."""
        raw = values.get("capabilities_models")
        if not isinstance(raw, list):
            return values
        names = []
        overrides = dict(values.get("capabilities_overrides") or {})
        for entry in raw:
            if isinstance(entry, str):
                names.append(entry)
            elif isinstance(entry, dict) and "model" in entry:
                model_name = str(entry["model"])
                names.append(model_name)
                # Extract everything except "model" as profile overrides
                ov = {k: v for k, v in entry.items() if k != "model"}
                if ov:
                    overrides[model_name] = ov
        values["capabilities_models"] = names
        values["capabilities_overrides"] = overrides
        return values


class LaneConfig(BaseModel):
    """Desired configuration for a single model lane."""

    model_config = ConfigDict(extra="forbid")

    lane_id: str | None = None
    model: str
    vllm: bool = False
    num_parallel: int = Field(default=20, ge=1)
    context_length: int = Field(default=_DEFAULT_LANE_CONTEXT_LENGTH, ge=128)
    keep_alive: str = "2m"
    kv_cache_type: str = "q8_0"
    flash_attention: bool = True
    gpu_devices: str = ""
    vllm_config: VllmConfig | None = None

    @field_validator("gpu_devices")
    @classmethod
    def _validate_gpu_devices(cls, value: str) -> str:
        return _normalize_gpu_devices(value)

    @model_validator(mode="after")
    def _validate_backend_specific_fields(self) -> LaneConfig:
        if not self.vllm:
            if self.vllm_config is not None:
                raise ValueError("Remove vllm_config or set vllm=true.")
            return self

        if self.vllm_config is None:
            self.vllm_config = VllmConfig()

        explicit_gpu_count = _gpu_device_count(self.gpu_devices)
        tp_size = self.vllm_config.tensor_parallel_size
        if explicit_gpu_count is not None and tp_size > explicit_gpu_count:
            raise ValueError(
                "vLLM tensor_parallel_size is larger than the lane's explicit gpu_devices set "
                f"({tp_size} > {explicit_gpu_count})."
            )
        return self


class AppConfig(BaseModel):
    """Top-level LogosWorkerNode configuration."""

    worker: WorkerConfig = Field(default_factory=WorkerConfig)
    logos: LogosConfig = Field(default_factory=LogosConfig)
    engines: EnginesConfig = Field(default_factory=EnginesConfig)
    lanes: list[LaneConfig] = Field(default_factory=list)
    static_lanes: list[LaneConfig] = Field(default_factory=list)
    model_profile_overrides: dict[str, dict] = Field(
        default_factory=dict,
        description="Per-model VRAM profile overrides for niche models with "
        "incorrect or unavailable HF metadata. Keys are model names; values are "
        "dicts with fields like base_residency_mb, kv_per_token_bytes, etc.",
    )


class ProcessState(str, enum.Enum):
    STARTING = "starting"
    RUNNING = "running"
    STOPPED = "stopped"
    NOT_STARTED = "not_started"
    ERROR = "error"


class ProcessStatus(BaseModel):
    state: ProcessState
    pid: int | None = None
    return_code: int | None = None


class LoadedModel(BaseModel):
    name: str
    size: int = 0
    size_vram: int = 0
    expires_at: datetime | None = None
    digest: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class DeviceInfo(BaseModel):
    device_id: str
    kind: Literal["nvidia", "derived"] = "nvidia"
    name: str = ""
    memory_used_mb: float = 0.0
    memory_total_mb: float = 0.0
    memory_free_mb: float = 0.0
    utilization_percent: float | None = None
    temperature_celsius: float | None = None
    power_draw_watts: float | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class DeviceSummary(BaseModel):
    timestamp: datetime
    mode: Literal["nvidia", "derived", "none"] = "none"
    nvidia_smi_available: bool = False
    degraded_reason: str = ""
    devices: list[DeviceInfo] = Field(default_factory=list)
    total_memory_mb: float = 0.0
    used_memory_mb: float = 0.0
    free_memory_mb: float = 0.0


class HostMemorySummary(BaseModel):
    """Host-RAM telemetry independent of GPU memory.

    Sourced from /proc/meminfo. The planner needs this to gate cold loads:
    vLLM's sleep_l1 frees VRAM but retains weights in host RAM, so VRAM
    headroom alone is insufficient when picking eviction victims.
    """

    timestamp: datetime
    source: Literal["proc-meminfo", "unavailable"] = "unavailable"
    total_mb: float = 0.0
    available_mb: float = 0.0
    used_mb: float = 0.0
    swap_total_mb: float = 0.0
    swap_used_mb: float = 0.0


class WorkerTransportStatus(BaseModel):
    connected: bool = False
    worker_id: str = ""
    last_connected_at: datetime | None = None
    last_status_sent_at: datetime | None = None
    consecutive_failures: int = 0


class CapacitySummary(BaseModel):
    lane_count: int = 0
    active_requests: int = 0
    loaded_lane_count: int = 0
    sleeping_lane_count: int = 0
    cold_lane_count: int = 0
    total_effective_vram_mb: float = 0.0
    free_memory_mb: float = 0.0


class LaneStatus(BaseModel):
    lane_id: str
    lane_uid: str = ""
    model: str
    port: int
    vllm: bool = False
    is_static: bool = False
    process: ProcessStatus
    runtime_state: Literal[
        "cold", "starting", "loaded", "running", "sleeping", "stopped", "error"
    ]
    routing_url: str = ""
    inference_endpoint: str = "/v1/chat/completions"
    num_parallel: int = 0
    context_length: int = 0
    keep_alive: str = ""
    kv_cache_type: str = ""
    flash_attention: bool = False
    gpu_devices: str = ""
    effective_gpu_devices: str = ""
    sleep_mode_enabled: bool = False
    sleep_state: Literal["unsupported", "unknown", "awake", "sleeping"] = "unsupported"
    active_requests: int = Field(default=0, ge=0)
    loaded_models: list[LoadedModel] = Field(default_factory=list)
    lane_config: LaneConfig | None = None
    backend_metrics: dict[str, Any] = Field(default_factory=dict)
    reported_vram_mb: float = 0.0
    pid_vram_mb: float = 0.0
    device_vram_mb: float = 0.0
    effective_vram_mb: float = 0.0
    vram_source: Literal["pid", "reported", "device", "unknown"] = "unknown"
    # Host-RAM footprint of the lane's process tree (PSS preferred, RSS
    # fallback). Includes child workers — vLLM TP=N spawns N Worker_TPx
    # subprocesses whose RSS each carries a full copy of the weights.
    host_ram_mb: float = 0.0
    host_ram_source: Literal["pss", "rss", "unknown"] = "unknown"


class WorkerRuntimeStatus(BaseModel):
    worker_name: str
    worker_id: str
    service_version: str
    timestamp: datetime
    transport: WorkerTransportStatus
    devices: DeviceSummary
    host_memory: HostMemorySummary | None = None
    capacity: CapacitySummary
    lanes: list[LaneStatus] = Field(default_factory=list)
    model_profiles: dict[str, dict[str, Any]] | None = None
    max_lanes: int = 0  # 0 = unlimited
    # Operator-declared GPU capability weight (default 100). Used by the
    # Logos request scheduler for weighted round-robin tie-breaks among
    # workers with the same model loaded warm.
    gpu_performance_score: int = 100


class LaneSetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lanes: list[LaneConfig]

    @model_validator(mode="after")
    def _validate_unique_lane_models(self) -> LaneSetRequest:
        lane_ids: dict[str, str] = {}
        for lane in self.lanes:
            lane_id = (lane.lane_id or lane.model).replace("/", "_").replace(":", "_")
            if lane_id in lane_ids:
                prev_model = lane_ids[lane_id]
                raise ValueError(
                    "Duplicate lane_id detected after normalization: "
                    f"{prev_model!r} and {lane.model!r} both map to lane_id={lane_id!r}. "
                    "Use unique lanes[].lane_id for replicas."
                )
            lane_ids[lane_id] = lane.model
        return self


class LaneAction(BaseModel):
    action: str
    lane_id: str
    model: str
    details: str = ""


class LaneApplyResult(BaseModel):
    success: bool
    actions: list[LaneAction] = Field(default_factory=list)
    lanes: list[LaneStatus] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    rolled_back: bool = False


class LaneEvent(BaseModel):
    event_id: str
    timestamp: datetime
    lane_id: str
    event: str
    model: str = ""
    details: str = ""
    port: int | None = None
    old_port: int | None = None
