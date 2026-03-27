"""Auto-calibrating model VRAM profiles.

Records observed lane reservation after model load and sleeping_residual_mb after
sleep. Logos uses these observations as calibration input, but may derive a
different planning budget for vLLM based on current gpu_memory_utilization.
Uses exponential moving average after the first measurement. Persists in
config.yml.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

try:
    import urllib.request
    import json as _json

    _HAS_URLLIB = True
except ImportError:  # pragma: no cover
    _HAS_URLLIB = False

logger = logging.getLogger(__name__)

_EMA_ALPHA = 0.3  # weight for new measurement vs historical average
_MODEL_SCALE_RE = re.compile(r"(?i)(\d+(?:\.\d+)?)([bm])")

# Bytes per parameter for common dtypes used in HuggingFace safetensors metadata
_DTYPE_BYTES: dict[str, float] = {
    "F64": 8.0, "F32": 4.0, "F16": 2.0, "BF16": 2.0,
    "I64": 8.0, "I32": 4.0, "I16": 2.0, "I8": 1.0, "U8": 1.0,
    "F8_E5M2": 1.0, "F8_E4M3": 1.0,
}


def _ema(previous: float | None, current: float) -> float:
    if previous is None:
        return current
    return (_EMA_ALPHA * current) + ((1 - _EMA_ALPHA) * previous)


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


def _fetch_hf_model_size_bytes(model_name: str) -> int | None:
    """Query HuggingFace API for the real model weight size in bytes.

    Uses the safetensors metadata from the HF model API which gives
    exact parameter counts per dtype. Returns total weight bytes or None.
    """
    if not _HAS_URLLIB:
        return None
    # Only query for names that look like HF model IDs (org/model)
    if "/" not in model_name:
        return None
    url = f"https://huggingface.co/api/models/{model_name}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "logos-worker/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = _json.loads(resp.read())
    except Exception:
        logger.debug("HF API query failed for %s", model_name, exc_info=True)
        return None

    safetensors = data.get("safetensors")
    if not isinstance(safetensors, dict):
        return None
    params_by_dtype = safetensors.get("parameters")
    if not isinstance(params_by_dtype, dict):
        return None

    total_bytes = 0
    for dtype_name, param_count in params_by_dtype.items():
        bpp = _DTYPE_BYTES.get(dtype_name.upper(), 2.0)
        total_bytes += int(param_count) * bpp

    if total_bytes > 0:
        logger.info(
            "HF API: %s weight size = %.0f MB (%s)",
            model_name, total_bytes / (1024 * 1024),
            ", ".join(f"{k}={v}" for k, v in params_by_dtype.items()),
        )
        return int(total_bytes)
    return None


def _fetch_hf_kv_params(model_name: str) -> dict[str, int] | None:
    """Fetch model architecture params from HuggingFace config.json for KV cache calculation.

    Returns {"num_layers", "num_kv_heads", "head_dim", "max_context"} or None.
    """
    if not _HAS_URLLIB:
        return None
    if "/" not in model_name:
        return None
    url = f"https://huggingface.co/{model_name}/resolve/main/config.json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "logos-worker/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            cfg = _json.loads(resp.read())
    except Exception:
        logger.debug("HF config.json fetch failed for %s", model_name, exc_info=True)
        return None

    num_layers = cfg.get("num_hidden_layers")
    num_heads = cfg.get("num_attention_heads")
    hidden_size = cfg.get("hidden_size")
    if num_layers is None or num_heads is None or hidden_size is None:
        return None

    num_kv_heads = cfg.get("num_key_value_heads", num_heads)
    head_dim = cfg.get("head_dim") or (hidden_size // num_heads)
    max_context = cfg.get("max_position_embeddings") or 8192

    logger.info(
        "HF config.json: %s — layers=%d, kv_heads=%d, head_dim=%d, max_ctx=%d",
        model_name, num_layers, num_kv_heads, head_dim, max_context,
    )
    return {
        "num_layers": int(num_layers),
        "num_kv_heads": int(num_kv_heads),
        "head_dim": int(head_dim),
        "max_context": int(max_context),
    }


def _compute_kv_per_token_bytes(kv_params: dict[str, int]) -> int:
    """Compute KV cache bytes per token from architecture params.

    Formula: 2 (key+value) × num_layers × num_kv_heads × head_dim × 2 (BF16 bytes)
    """
    return (
        2
        * kv_params["num_layers"]
        * kv_params["num_kv_heads"]
        * kv_params["head_dim"]
        * 2  # BF16
    )


def _base_residency_from_bytes(disk_size_bytes: int | None) -> float | None:
    """Convert model weight bytes to estimated GPU residency in MB.

    Adds 20% overhead for CUDA kernels, activation buffers, and runtime
    (per EleutherAI inference overhead research).
    """
    if disk_size_bytes is None or disk_size_bytes <= 0:
        return None
    return (disk_size_bytes / (1024 * 1024)) * 1.2


@dataclass
class ModelProfileRecord:
    loaded_vram_mb: float | None = None
    sleeping_residual_mb: float | None = None
    disk_size_bytes: int | None = None
    base_residency_mb: float | None = None
    kv_budget_mb: float | None = None
    engine: str | None = None
    observed_gpu_memory_utilization: float | None = None
    min_gpu_memory_utilization_to_load: float | None = None
    tensor_parallel_size: int | None = None
    kv_per_token_bytes: int | None = None
    max_context_length: int | None = None
    measurement_count: int = 0
    last_measured_epoch: float = 0.0

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
        return 4096.0

    def estimate_base_residency_mb(self, model_name: str | None = None) -> float | None:
        if self.base_residency_mb is not None:
            return self.base_residency_mb
        disk_size_bytes = self.disk_size_bytes
        if (disk_size_bytes is None or disk_size_bytes <= 0) and model_name:
            disk_size_bytes = _estimated_disk_size_bytes_from_model_name(model_name)
        return _base_residency_from_bytes(disk_size_bytes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "loaded_vram_mb": self.loaded_vram_mb,
            "sleeping_residual_mb": self.sleeping_residual_mb,
            "disk_size_bytes": self.disk_size_bytes,
            "base_residency_mb": self.base_residency_mb,
            "kv_budget_mb": self.kv_budget_mb,
            "engine": self.engine,
            "observed_gpu_memory_utilization": self.observed_gpu_memory_utilization,
            "min_gpu_memory_utilization_to_load": self.min_gpu_memory_utilization_to_load,
            "tensor_parallel_size": self.tensor_parallel_size,
            "kv_per_token_bytes": self.kv_per_token_bytes,
            "max_context_length": self.max_context_length,
            "measurement_count": self.measurement_count,
            "last_measured_epoch": self.last_measured_epoch,
        }


class ModelProfileRegistry:
    """Auto-calibrating model VRAM profiles. Optionally persisted in config.yml."""

    def __init__(self, config_path: Path | None = None) -> None:
        self._profiles: dict[str, ModelProfileRecord] = {}
        self._config_path = config_path
        self._lock = threading.Lock()
        self._hf_fetch_attempted: set[str] = set()  # models we already tried HF API for
        # Manual overrides from config.yml — operator-provided values that
        # take priority over HF API fetch and name-based estimation.
        self._manual_overrides: dict[str, dict[str, Any]] = {}
        self._load_persisted()

    def _update_metadata(
        self,
        profile: ModelProfileRecord,
        *,
        engine: str | None = None,
        observed_gpu_memory_utilization: float | None = None,
        tensor_parallel_size: int | None = None,
    ) -> None:
        if isinstance(engine, str) and engine.strip():
            profile.engine = engine.strip()
        if observed_gpu_memory_utilization is not None and observed_gpu_memory_utilization > 0:
            profile.observed_gpu_memory_utilization = observed_gpu_memory_utilization
        if tensor_parallel_size is not None and tensor_parallel_size > 0:
            profile.tensor_parallel_size = tensor_parallel_size

    def seed_capabilities(self, model_names: list[str], engine: str = "vllm") -> None:
        """Pre-create profiles for capabilities models before any lane is loaded.

        Fetches HF metadata (disk size, KV params) so the server-side planner
        knows the engine type and can compute VRAM estimates for cold loads.
        """
        for model_name in model_names:
            with self._lock:
                if model_name in self._profiles:
                    profile = self._profiles[model_name]
                    if profile.engine is None:
                        profile.engine = engine
                    continue
                profile = ModelProfileRecord(engine=engine)
                self._profiles[model_name] = profile
            self._ensure_disk_size(model_name, profile)
            logger.info(
                "Seeded capability profile: %s engine=%s disk_size=%s "
                "base_residency=%.0fMB kv_per_token=%s max_ctx=%s",
                model_name, engine,
                profile.disk_size_bytes,
                profile.base_residency_mb or 0,
                profile.kv_per_token_bytes,
                profile.max_context_length,
            )
        self._persist()

    def _apply_manual_overrides(self, model_name: str, profile: ModelProfileRecord) -> bool:
        """Apply manual overrides from config.yml if available.

        Returns True if overrides were applied (may skip HF fetch).
        """
        overrides = self._manual_overrides.get(model_name)
        if overrides is None:
            return False

        applied = []
        if "disk_size_bytes" in overrides:
            profile.disk_size_bytes = int(overrides["disk_size_bytes"])
            profile.base_residency_mb = _base_residency_from_bytes(profile.disk_size_bytes)
            applied.append(f"disk_size={profile.disk_size_bytes}")
        if "base_residency_mb" in overrides:
            profile.base_residency_mb = float(overrides["base_residency_mb"])
            applied.append(f"base_residency={profile.base_residency_mb:.0f}MB")
        if "kv_per_token_bytes" in overrides:
            profile.kv_per_token_bytes = int(overrides["kv_per_token_bytes"])
            applied.append(f"kv_per_token={profile.kv_per_token_bytes}")
        if "max_context_length" in overrides:
            profile.max_context_length = int(overrides["max_context_length"])
            applied.append(f"max_ctx={profile.max_context_length}")
        if "engine" in overrides:
            profile.engine = str(overrides["engine"])
            applied.append(f"engine={profile.engine}")
        if "tensor_parallel_size" in overrides:
            profile.tensor_parallel_size = int(overrides["tensor_parallel_size"])
            applied.append(f"tp={profile.tensor_parallel_size}")
        if "loaded_vram_mb" in overrides:
            profile.loaded_vram_mb = float(overrides["loaded_vram_mb"])
            applied.append(f"loaded_vram={profile.loaded_vram_mb:.0f}MB")
        if "kv_budget_mb" in overrides:
            profile.kv_budget_mb = float(overrides["kv_budget_mb"])
            applied.append(f"kv_budget={profile.kv_budget_mb:.0f}MB")

        if applied:
            logger.info(
                "Applied manual overrides for %s: %s",
                model_name, ", ".join(applied),
            )
        return bool(applied)

    def _ensure_disk_size(self, model_name: str, profile: ModelProfileRecord) -> None:
        """Fetch model metadata from HF API if not already known. Called outside lock.

        Manual overrides from config.yml take priority — if they provide the
        needed values, HF fetch is skipped entirely.
        """
        # Apply manual overrides first — these are operator-provided values
        # for models with incorrect or unavailable HF metadata.
        self._apply_manual_overrides(model_name, profile)

        if model_name in self._hf_fetch_attempted:
            return
        needs_size = profile.disk_size_bytes is None or profile.disk_size_bytes <= 0
        needs_kv = profile.kv_per_token_bytes is None
        if not needs_size and not needs_kv:
            return
        self._hf_fetch_attempted.add(model_name)
        if needs_size:
            hf_bytes = _fetch_hf_model_size_bytes(model_name)
            if hf_bytes is not None and hf_bytes > 0:
                profile.disk_size_bytes = hf_bytes
                profile.base_residency_mb = _base_residency_from_bytes(hf_bytes)
        if needs_kv:
            kv_params = _fetch_hf_kv_params(model_name)
            if kv_params is not None:
                profile.kv_per_token_bytes = _compute_kv_per_token_bytes(kv_params)
                profile.max_context_length = kv_params["max_context"]

    def record_loaded_vram(
        self,
        model_name: str,
        effective_vram_mb: float,
        *,
        engine: str | None = None,
        observed_gpu_memory_utilization: float | None = None,
        tensor_parallel_size: int | None = None,
    ) -> None:
        """Called after lane reaches loaded/running with measured effective_vram_mb > 0.

        First measurement sets value. Subsequent measurements update via EMA.
        """
        if effective_vram_mb <= 0:
            return

        # Fetch HF model size outside the lock (network I/O)
        with self._lock:
            profile = self._profiles.setdefault(model_name, ModelProfileRecord())
        self._ensure_disk_size(model_name, profile)

        with self._lock:
            self._update_metadata(
                profile,
                engine=engine,
                observed_gpu_memory_utilization=observed_gpu_memory_utilization,
                tensor_parallel_size=tensor_parallel_size,
            )
            base_estimate = profile.estimate_base_residency_mb(model_name)
            if base_estimate is not None:
                profile.base_residency_mb = _ema(profile.base_residency_mb, base_estimate)
                if engine == "vllm":
                    profile.kv_budget_mb = _ema(
                        profile.kv_budget_mb,
                        max(effective_vram_mb - profile.base_residency_mb, 0.0),
                    )
            if profile.loaded_vram_mb is None:
                profile.loaded_vram_mb = effective_vram_mb
            else:
                profile.loaded_vram_mb = _ema(profile.loaded_vram_mb, effective_vram_mb)
            profile.measurement_count += 1
            profile.last_measured_epoch = time.time()
            logger.info(
                "Model profile updated: %s base_residency=%.0fMB kv_budget=%.0fMB "
                "loaded_vram=%.0fMB disk_size=%s (count=%d)",
                model_name,
                profile.base_residency_mb or 0,
                profile.kv_budget_mb or 0,
                profile.loaded_vram_mb or 0,
                profile.disk_size_bytes,
                profile.measurement_count,
            )
        self._persist()

    def record_successful_load_util(self, model_name: str, gpu_memory_utilization: float) -> None:
        """Record the lowest known-good gpu_memory_utilization that reached loaded/running."""
        if gpu_memory_utilization <= 0:
            return

        with self._lock:
            profile = self._profiles.setdefault(model_name, ModelProfileRecord())
            if (
                profile.min_gpu_memory_utilization_to_load is None
                or gpu_memory_utilization < profile.min_gpu_memory_utilization_to_load
            ):
                profile.min_gpu_memory_utilization_to_load = gpu_memory_utilization
                profile.last_measured_epoch = time.time()
        self._persist()

    def record_sleeping_vram(
        self,
        model_name: str,
        residual_vram_mb: float,
        *,
        engine: str | None = None,
        observed_gpu_memory_utilization: float | None = None,
        tensor_parallel_size: int | None = None,
    ) -> None:
        """Called after successful sleep. residual_vram_mb is the lane's effective_vram_mb
        while in sleeping state."""
        if residual_vram_mb < 0:
            return

        with self._lock:
            profile = self._profiles.setdefault(model_name, ModelProfileRecord())
        self._ensure_disk_size(model_name, profile)

        with self._lock:
            self._update_metadata(
                profile,
                engine=engine,
                observed_gpu_memory_utilization=observed_gpu_memory_utilization,
                tensor_parallel_size=tensor_parallel_size,
            )
            base_estimate = profile.estimate_base_residency_mb(model_name)
            if base_estimate is not None:
                profile.base_residency_mb = _ema(profile.base_residency_mb, base_estimate)
            if profile.sleeping_residual_mb is None:
                profile.sleeping_residual_mb = residual_vram_mb
            else:
                profile.sleeping_residual_mb = _ema(profile.sleeping_residual_mb, residual_vram_mb)
            profile.last_measured_epoch = time.time()
        self._persist()

    def record_disk_size(self, model_name: str, disk_size_bytes: int) -> None:
        """Called from Ollama /api/tags response."""
        if disk_size_bytes <= 0:
            return

        with self._lock:
            profile = self._profiles.setdefault(model_name, ModelProfileRecord())
            profile.disk_size_bytes = disk_size_bytes
            base_estimate = profile.estimate_base_residency_mb(model_name)
            if base_estimate is not None:
                profile.base_residency_mb = _ema(profile.base_residency_mb, base_estimate)
                if profile.engine == "vllm" and profile.loaded_vram_mb is not None:
                    profile.kv_budget_mb = _ema(
                        profile.kv_budget_mb,
                        max(profile.loaded_vram_mb - profile.base_residency_mb, 0.0),
                    )
        self._persist()

    def get_profile(self, model_name: str) -> ModelProfileRecord | None:
        with self._lock:
            return self._profiles.get(model_name)

    def get_all_profiles(self) -> dict[str, dict[str, Any]]:
        """Return all profiles as serializable dicts for websocket payload."""
        with self._lock:
            return {name: profile.to_dict() for name, profile in self._profiles.items()}

    def _persist(self) -> None:
        """Append model_profiles section to config.yml."""
        if self._config_path is None or yaml is None:
            return
        try:
            with self._lock:
                data = {name: profile.to_dict() for name, profile in self._profiles.items()}
            if not data:
                return

            existing: dict = {}
            if self._config_path.exists():
                try:
                    with self._config_path.open() as f:
                        existing = yaml.safe_load(f) or {}
                except Exception:  # noqa: BLE001
                    existing = {}

            existing["model_profiles"] = data
            with self._config_path.open("w") as f:
                yaml.safe_dump(existing, f, default_flow_style=False)
        except Exception:  # noqa: BLE001
            logger.debug("Failed to persist model profiles", exc_info=True)

    def _load_persisted(self) -> None:
        """Read model_profiles and model_profile_overrides from config.yml on startup."""
        if self._config_path is None or yaml is None:
            return
        if not self._config_path.exists():
            return
        try:
            with self._config_path.open() as f:
                data = yaml.safe_load(f) or {}

            # Load manual overrides (operator-provided values for niche models)
            overrides = data.get("model_profile_overrides")
            if isinstance(overrides, dict):
                for model_name, ov in overrides.items():
                    if isinstance(ov, dict):
                        self._manual_overrides[str(model_name)] = dict(ov)
                if self._manual_overrides:
                    logger.info(
                        "Loaded manual profile overrides for %d model(s): %s",
                        len(self._manual_overrides),
                        ", ".join(sorted(self._manual_overrides)),
                    )

            profiles = data.get("model_profiles")
            if not isinstance(profiles, dict):
                return
            for model_name, profile_data in profiles.items():
                if not isinstance(profile_data, dict):
                    continue
                self._profiles[str(model_name)] = ModelProfileRecord(
                    loaded_vram_mb=profile_data.get("loaded_vram_mb"),
                    sleeping_residual_mb=profile_data.get("sleeping_residual_mb"),
                    disk_size_bytes=profile_data.get("disk_size_bytes"),
                    base_residency_mb=profile_data.get("base_residency_mb"),
                    kv_budget_mb=profile_data.get("kv_budget_mb"),
                    engine=profile_data.get("engine"),
                    observed_gpu_memory_utilization=profile_data.get("observed_gpu_memory_utilization"),
                    min_gpu_memory_utilization_to_load=profile_data.get("min_gpu_memory_utilization_to_load"),
                    tensor_parallel_size=profile_data.get("tensor_parallel_size"),
                    kv_per_token_bytes=profile_data.get("kv_per_token_bytes"),
                    max_context_length=profile_data.get("max_context_length"),
                    measurement_count=int(profile_data.get("measurement_count", 0) or 0),
                    last_measured_epoch=float(profile_data.get("last_measured_epoch", 0.0) or 0.0),
                )
            logger.info("Loaded %d model profiles from %s", len(self._profiles), self._config_path)
        except Exception:  # noqa: BLE001
            logger.debug("Failed to load persisted model profiles", exc_info=True)
