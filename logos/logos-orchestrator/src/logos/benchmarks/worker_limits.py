"""Hardware limits for benchmark edits, derived from live worker telemetry."""

from .configuration import ServingOverrides
from .guidellm_runner import extract_serving_configuration


def worker_limits(snapshot: dict | None, model: str) -> dict:
    runtime = (snapshot or {}).get("runtime") or {}
    summary = runtime.get("devices") or {}
    devices = [(index, d) for index, d in enumerate(summary.get("devices", [])) if d.get("kind") == "nvidia"]
    known = bool(summary.get("nvidia_smi_available"))
    lane = next((lane for lane in runtime.get("lanes", []) if lane.get("model") == model), {})
    config = lane.get("lane_config") or {}
    selectors = [runtime.get("gpu_devices", "all")]
    if lane.get("is_static"):
        selectors.append(config.get("gpu_devices", ""))
    for selector in selectors:
        if selector and selector.lower() not in {"all", "none"}:
            allowed = set(selector.split(","))
            devices = [(index, d) for index, d in devices if str((d.get("extra") or {}).get("index", index)) in allowed]
        elif selector == "none":
            devices = []
    memories = [float(d.get("memory_total_mb") or 0) for _, d in devices]
    return {
        "gpu_count": len(devices) if known else None,
        "gpu_memory_bytes": int(min(memories) * 1024**2) if memories and min(memories) > 0 else None,
        "current": extract_serving_configuration(snapshot, model),
    }


def validate_worker_overrides(overrides: ServingOverrides, limits: dict) -> None:
    requested = overrides.model_dump(exclude_none=True)
    if not requested:
        return
    count = limits["gpu_count"]
    if count is None:
        raise ValueError(
            "Worker GPU information is unavailable. Wait for its next status report before changing vLLM settings."
        )
    if count == 0:
        raise ValueError("This worker has no available NVIDIA GPUs for this model.")
    effective = {**limits["current"], **requested}
    tp = int(effective.get("tensor_parallel_size") or 1)
    pp = int(effective.get("pipeline_parallel_size") or 1)
    if tp * pp > count:
        raise ValueError(
            f"Tensor parallel size ({tp}) × pipeline parallel size ({pp}) requires {tp * pp} GPUs, "
            f"but this worker has only {count} available for this model."
        )
    seqs = effective.get("max_num_seqs") or 0
    tokens = effective.get("max_num_batched_tokens") or 0
    if tokens and seqs and tokens < seqs:
        raise ValueError("Max batched tokens must be at least max sequences.")
    raw_cache = requested.get("kv_cache_memory_bytes")
    if raw_cache:
        value = raw_cache.upper()
        multiplier = {"K": 1024, "M": 1024**2, "G": 1024**3}.get(value[-1], 1)
        cache_bytes = float(value[:-1] if multiplier != 1 else value) * multiplier
        if cache_bytes <= 0:
            raise ValueError("KV cache memory must be greater than zero, or empty to keep the current setting.")
        ceiling = limits.get("gpu_memory_bytes")
        if ceiling is not None and cache_bytes >= ceiling:
            raise ValueError(
                f"KV cache memory per GPU must be smaller than its total memory ({ceiling / 1024**3:g} GiB); "
                "model weights also need GPU memory."
            )
