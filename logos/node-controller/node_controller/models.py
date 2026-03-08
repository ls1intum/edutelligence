"""
Pydantic models for the Node Controller.

Covers: configuration, Ollama status, GPU metrics, API requests/responses.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Configuration models (mirror config.yml)
# ---------------------------------------------------------------------------

class OllamaConfig(BaseModel):
    """Runtime configuration for the managed Ollama container."""

    image: str = "ollama/ollama:latest"
    container_name: str = "ollama-server"
    host_port: int = 11434
    container_port: int = 11434

    # GPU passthrough mode:
    #   "none" — CPU-only, no device_requests sent to Docker (works everywhere)
    #   "all"  — request all GPUs (needs NVIDIA Container Toolkit on the host)
    #   "0,1"  — specific GPU device IDs
    gpu_devices: str = "all"

    # Ollama runtime params (all become environment variables, require restart)
    num_parallel: int = 4
    max_num_parallel: int = 0  # 0 = auto (use num_parallel). When >0, this is the
    # actual OLLAMA_NUM_PARALLEL sent to the process. num_parallel becomes the
    # *advertised* virtual limit that Logos uses for scheduling.  Changing
    # num_parallel (within max) is instant — no container restart.  Changing
    # max_num_parallel triggers a restart.  Over-provision to avoid 80s
    # cold-start penalty on every parallelism change.
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

    models_path: str = "/root/.ollama/models"
    preload_models: list[str] = Field(default_factory=list)
    env_overrides: dict[str, str] = Field(default_factory=dict)

    # Host-binary mode: run the host's Ollama binary inside a thin container
    # instead of the full ollama/ollama Docker image.  This uses the host's
    # CUDA v12 backend (~7s cold start) instead of the Docker image's CUDA v13
    # backend (~80s cold start on compute-capability 7.5 GPUs).
    use_host_binary: bool = False
    host_binary_path: str = "/usr/local/bin/ollama"
    host_lib_path: str = "/usr/local/lib/ollama"
    base_image: str = "debian:bookworm-slim"


class ControllerConfig(BaseModel):
    """Settings for the controller itself."""

    port: int = 8443
    api_key: str = "change-me-to-a-random-secret"
    tls_enabled: bool = False
    tls_cert_path: str = "/app/certs/cert.pem"
    tls_key_path: str = "/app/certs/key.pem"
    gpu_poll_interval: int = 5
    ollama_poll_interval: int = 5


class DockerConfig(BaseModel):
    """Docker networking / volume names."""

    network_name: str = "node-controller-net"
    volume_name: str = "ollama-models"
    models_host_path: str | None = None


class AppConfig(BaseModel):
    """Top-level application configuration."""

    controller: ControllerConfig = Field(default_factory=ControllerConfig)
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    docker: DockerConfig = Field(default_factory=DockerConfig)


# ---------------------------------------------------------------------------
# Container state
# ---------------------------------------------------------------------------

class ContainerState(str, enum.Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    RESTARTING = "restarting"
    CREATING = "creating"
    NOT_FOUND = "not_found"
    ERROR = "error"


class ContainerStatus(BaseModel):
    """Current state of the managed Ollama container."""

    state: ContainerState
    container_name: str
    container_id: str | None = None
    uptime_seconds: float | None = None
    started_at: datetime | None = None
    error_message: str | None = None


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
    """Full node status — the primary endpoint Logos polls."""

    timestamp: datetime
    container: ContainerStatus
    ollama: OllamaStatus
    gpu: GpuSnapshot
    config: OllamaConfig


# ---------------------------------------------------------------------------
# API request / response models
# ---------------------------------------------------------------------------

class ReconfigureRequest(BaseModel):
    """
    Partial Ollama config update.  Only provided fields are changed.
    Triggers container recreation if runtime params differ.
    """

    num_parallel: int | None = None
    max_num_parallel: int | None = None
    max_loaded_models: int | None = None
    keep_alive: str | None = None
    max_queue: int | None = None
    context_length: int | None = None
    flash_attention: bool | None = None
    kv_cache_type: str | None = None
    gpu_devices: str | None = None
    image: str | None = None
    host_port: int | None = None
    preload_models: list[str] | None = None
    env_overrides: dict[str, str] | None = None

    # New tuning fields
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
