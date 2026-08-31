"""Best-effort Hugging Face model metadata for the calibration pre-check.

Fetches config.json + safetensors sibling sizes from the HF Hub and converts
them into a weight footprint / KV-cache-per-token / max-context estimate,
used to skip models that provably can't fit on a node before spending a
maintenance-window slot probing them, and to narrow the TP/KV-cache search
calibration actually runs.

Network failures, missing config fields, or a model with no HF page must
never raise and must never block calibration — callers get an
HfModelMetadata with the relevant fields left None, and calibration proceeds
exactly as it does today, with no extra bounds. This module itself never
decides to skip anything; that's logos_bridge.py's precheck branch, which
skips on a nonexistent repo (permanent), an unfittable model (permanent), or
a gated repo the worker's HF_TOKEN can't access (temporary — retried every
session, since access can be granted later).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CACHE_FILENAME = "hf_model_info_cache.json"
_SUCCESS_CACHE_TTL_S = 24 * 3600  # config.json/safetensors rarely change
_ERROR_CACHE_TTL_S = 3600  # retry failures (network blips, rate limits) sooner

# "can serve at least one short request" bar for the min-KV skip gate.
MIN_VIABLE_CONTEXT_TOKENS = 2048

# proactive skip reason codes — deliberately distinct from calibration.py's
# reactive _FATAL_LOAD_ERROR_PATTERNS, which mean "vLLM itself rejected this
# after an actual load attempt". These fire before any process is spawned.
REASON_INSUFFICIENT_VRAM_FOR_WEIGHTS = "insufficient-vram-for-weights"
REASON_INSUFFICIENT_VRAM_FOR_MIN_KV = "insufficient-vram-for-min-kv-cache"
REASON_MODEL_NOT_FOUND = "model-not-found"
REASON_MODEL_GATED = "model-gated"
REASON_UNSUPPORTED_QUANTIZATION = "unsupported-quantization-method"

_DTYPE_BYTES = {
    "float32": 4,
    "fp32": 4,
    "float16": 2,
    "fp16": 2,
    "bfloat16": 2,
    "bf16": 2,
    "float8_e4m3fn": 1,
    "float8_e5m2": 1,
    "fp8": 1,
    "int8": 1,
    "float8": 1,
}


@dataclass(frozen=True)
class HfModelMetadata:
    weight_bytes: int | None = None  # sum of *.safetensors sibling sizes
    kv_per_token_bytes: int | None = None
    max_context_length: int | None = None
    # config.json's quantization_config.quant_method (e.g. "awq", "gptq").
    # This module just extracts the raw string; logos_bridge.py checks it
    # against the installed vLLM's supported methods separately (see
    # calibration.query_vllm_quantization_methods).
    quantization_method: str | None = None
    fetched_at: float = 0.0
    source: str = "error:unknown"  # "hf" on success, "error:<reason>" otherwise
    error: str | None = None


def _get_config_field(config: dict[str, Any], key: str) -> Any:
    # Multimodal checkpoints (Llava, Qwen-VL, ...) nest the LM config under
    # text_config; fall back to it when the top level doesn't have the field.
    if key in config:
        return config[key]
    text_cfg = config.get("text_config") or {}
    return text_cfg.get(key)


def _effective_max_context_length(config: dict[str, Any], base: int | None) -> int | None:
    """Stretch ``base`` (raw max_position_embeddings) by an active
    YaRN/linear RoPE factor, only when
    ``original_max_position_embeddings`` equals ``base`` (proof it's
    pre-scaling); left untouched otherwise, "dynamic" included."""
    if not base:
        return base
    rope_scaling = _get_config_field(config, "rope_scaling")
    if not isinstance(rope_scaling, dict):
        return base
    rope_type = rope_scaling.get("type") or rope_scaling.get("rope_type")
    if rope_type not in ("yarn", "linear"):
        return base
    original = rope_scaling.get("original_max_position_embeddings")
    factor = rope_scaling.get("factor")
    if not isinstance(original, (int, float)) or not isinstance(factor, (int, float)):
        return base
    if int(original) != int(base):
        return base
    return int(base * factor)


def _derive_kv_per_token_bytes(config: dict[str, Any], kv_cache_dtype_override: str | None) -> int | None:
    num_hidden_layers = _get_config_field(config, "num_hidden_layers")
    hidden_size = _get_config_field(config, "hidden_size")
    num_attention_heads = _get_config_field(config, "num_attention_heads")
    num_key_value_heads = _get_config_field(config, "num_key_value_heads") or num_attention_heads
    head_dim = _get_config_field(config, "head_dim")
    if head_dim is None and hidden_size and num_attention_heads:
        head_dim = hidden_size / num_attention_heads

    if not (num_hidden_layers and num_key_value_heads and head_dim):
        return None

    dtype_name = str(kv_cache_dtype_override or _get_config_field(config, "torch_dtype") or "").lower()
    dtype_bytes = _DTYPE_BYTES.get(dtype_name, 2)
    return int(2 * num_hidden_layers * num_key_value_heads * head_dim * dtype_bytes)


def _fetch_uncached(model_name: str, *, token: str | None, timeout_s: float) -> HfModelMetadata:
    try:
        from huggingface_hub import HfApi, hf_hub_download
        from huggingface_hub.utils import GatedRepoError, RepositoryNotFoundError
    except ImportError as exc:
        return HfModelMetadata(source="error:huggingface_hub-unavailable", error=str(exc))

    # GatedRepoError is a RepositoryNotFoundError subclass (a real, existing
    # repo the caller just lacks access to) — must be excluded from the
    # not-found verdict, or a gated model would wrongly look nonexistent.
    gated = False
    weight_bytes: int | None = None
    try:
        info = HfApi().model_info(model_name, token=token, files_metadata=True, timeout=timeout_s)
        sizes = [s.size for s in (info.siblings or []) if s.rfilename.endswith(".safetensors") and s.size]
        weight_bytes = sum(sizes) if sizes else None
    except GatedRepoError as exc:
        gated = True
        logger.debug("[HF precheck] model_info gated for %s: %s", model_name, exc)
    except RepositoryNotFoundError as exc:
        return HfModelMetadata(source="error:model-not-found", error=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.debug("[HF precheck] model_info failed for %s: %s", model_name, exc)

    kv_per_token_bytes: int | None = None
    max_context_length: int | None = None
    quantization_method: str | None = None
    try:
        # etag_timeout only bounds the existence check, not the (tiny)
        # config.json transfer itself — hf_hub_download has no knob for that.
        config_path = hf_hub_download(model_name, filename="config.json", token=token, etag_timeout=timeout_s)
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)
        kv_per_token_bytes = _derive_kv_per_token_bytes(config, None)
        max_context_length = _effective_max_context_length(config, _get_config_field(config, "max_position_embeddings"))
        quant_cfg = _get_config_field(config, "quantization_config")
        if isinstance(quant_cfg, dict):
            quant_method = quant_cfg.get("quant_method")
            quantization_method = str(quant_method) if quant_method else None
    except GatedRepoError as exc:
        gated = True
        logger.debug("[HF precheck] config.json gated for %s: %s", model_name, exc)
    except RepositoryNotFoundError as exc:
        return HfModelMetadata(source="error:model-not-found", error=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.debug("[HF precheck] config.json fetch failed for %s: %s", model_name, exc)

    # Real calibration needs every file this precheck touched, so partial
    # access (e.g. metadata visible, weights gated) is still a block — but a
    # temporary one, unlike model-not-found, since an admin adding a working
    # HF_TOKEN resolves it without any code/data change on our side.
    if gated:
        return HfModelMetadata(source="error:model-gated", error="repository access requires an authorized HF_TOKEN")

    if weight_bytes is None and kv_per_token_bytes is None and max_context_length is None:
        return HfModelMetadata(source="error:no-data", error="neither weights nor config.json were reachable")

    return HfModelMetadata(
        weight_bytes=weight_bytes,
        kv_per_token_bytes=kv_per_token_bytes,
        max_context_length=max_context_length,
        quantization_method=quantization_method,
        fetched_at=time.time(),
        source="hf",
    )


class HfModelInfoCache:
    """Small on-disk JSON cache at ``<state_dir>/hf_model_info_cache.json``.

    Mirrors ModelProfileRegistry's lock + best-effort persist pattern: reads
    and writes are never allowed to raise into the calibration loop.
    """

    def __init__(self, state_dir: Path | None) -> None:
        self._path = (state_dir / _CACHE_FILENAME) if state_dir is not None else None
        self._lock = threading.Lock()
        self._entries: dict[str, dict[str, Any]] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if self._path is None or not self._path.exists():
            return
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self._entries = data
        except Exception:  # noqa: BLE001
            logger.debug("[HF precheck] could not read cache at %s", self._path, exc_info=True)

    @staticmethod
    def _is_expired(entry: dict[str, Any]) -> bool:
        ttl = _SUCCESS_CACHE_TTL_S if entry.get("source") == "hf" else _ERROR_CACHE_TTL_S
        return time.time() - (entry.get("fetched_at") or 0) > ttl

    def get(self, model_name: str) -> HfModelMetadata | None:
        with self._lock:
            self._ensure_loaded()
            entry = self._entries.get(model_name)
            if entry is None:
                return None
            if self._is_expired(entry):
                # Drop it here too, not just on the next put() sweep — a
                # model checked often should never accumulate stale copies.
                del self._entries[model_name]
                return None
            return HfModelMetadata(**entry)

    def put(self, model_name: str, meta: HfModelMetadata) -> None:
        with self._lock:
            self._ensure_loaded()
            # Sweep everything past its TTL, not just model_name — otherwise
            # a model dropped from configured_models (so never looked up
            # again) would keep its stale entry forever.
            for name in [n for n, e in self._entries.items() if self._is_expired(e)]:
                del self._entries[name]
            self._entries[model_name] = {
                "weight_bytes": meta.weight_bytes,
                "kv_per_token_bytes": meta.kv_per_token_bytes,
                "max_context_length": meta.max_context_length,
                "quantization_method": meta.quantization_method,
                "fetched_at": meta.fetched_at or time.time(),
                "source": meta.source,
                "error": meta.error,
            }
            if self._path is None:
                return
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with open(self._path, "w", encoding="utf-8") as f:
                    json.dump(self._entries, f)
            except Exception:  # noqa: BLE001
                logger.debug("[HF precheck] could not persist cache at %s", self._path, exc_info=True)


def fetch_hf_model_metadata(
    model_name: str,
    *,
    token: str | None,
    cache: HfModelInfoCache | None = None,
    timeout_s: float = 15.0,
) -> HfModelMetadata:
    """Best-effort HF metadata lookup. Never raises."""
    if cache is not None:
        cached = cache.get(model_name)
        if cached is not None:
            return cached

    try:
        meta = _fetch_uncached(model_name, token=token, timeout_s=timeout_s)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[HF precheck] unexpected failure for %s", model_name, exc_info=True)
        meta = HfModelMetadata(source="error:unexpected", error=str(exc))

    if cache is not None:
        cache.put(model_name, meta)
    return meta


def min_feasible_tp(
    weight_bytes: int,
    per_gpu_free_mb: float,
    hardware_max_tp: int,
    *,
    safety_ratio: float = 0.9,
    min_kv_mb: float = 0.0,
) -> int | None:
    """Smallest power-of-2 TP in [1, hardware_max_tp] where the weights (plus
    ``min_kv_mb`` of KV cache) fit within ``per_gpu_free_mb * safety_ratio``.

    Returns None if infeasible even at hardware_max_tp. safety_ratio=0.9 is
    deliberately generous — this is a skip gate, and a false skip (wrongly
    declaring a model incompatible) is much costlier than a false proceed.
    """
    tp = 1
    while tp <= hardware_max_tp:
        per_gpu_weight_mb = (weight_bytes / (1024 * 1024)) / tp
        if per_gpu_weight_mb + min_kv_mb <= per_gpu_free_mb * safety_ratio:
            return tp
        tp *= 2
    return None
