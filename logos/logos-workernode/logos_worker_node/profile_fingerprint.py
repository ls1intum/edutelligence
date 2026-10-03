"""Calibration keys: the hardware, vLLM and config a calibration is valid for.

Logos compares a node's current key with the key a calibration was measured
under; any difference marks the calibration stale.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Iterable

from logos_worker_node.metal import is_metal_backend
from logos_worker_node.models import AppConfig, DeviceInfo, MetalConfig, model_can_sleep

logger = logging.getLogger(__name__)

_KEY_SCHEMA = 1


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def key_hash(key: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(key).encode("utf-8")).hexdigest()


def plan_hash(plan: dict[str, Any]) -> str:
    """Hash of everything the operator configured for the model's lane.

    The GPU pin is node layout, not configuration; ``_``-keys are plan
    bookkeeping.
    """
    relevant = {k: v for k, v in plan.items() if k not in ("model", "gpu_devices") and not str(k).startswith("_")}
    return hashlib.sha256(_canonical(relevant).encode("utf-8")).hexdigest()


def gpu_classes(devices: Iterable[DeviceInfo]) -> list[dict[str, Any]]:
    """Distinct GPU classes; the count is left out so TP can be compared."""
    classes = {
        (
            device.name,
            int(round(float(device.memory_total_mb or 0.0) / 256.0)) * 256,
            (device.extra or {}).get("compute_capability"),
        )
        for device in devices
    }
    return [
        {"name": name, "memory_mb": memory_mb, "compute_capability": capability}
        for name, memory_mb, capability in sorted(classes, key=_canonical)
    ]


def calibration_devices(plan: dict[str, Any], devices: list[DeviceInfo]) -> list[DeviceInfo]:
    """The GPUs whose classes a calibration of this plan depends on.

    An unpinned plan may be probed on whichever GPUs are idle and served on
    any of them later, so every GPU of the node counts.
    """
    from logos_worker_node.calibration import parse_gpu_indices  # noqa: PLC0415

    indexed = {int((d.extra or {}).get("index", -1)): d for d in devices if (d.extra or {}).get("index") is not None}
    pinned = parse_gpu_indices(str(plan.get("gpu_devices") or ""))
    if not indexed or pinned is None:
        return list(devices)
    return [indexed[i] for i in pinned if i in indexed]


def compute_calibration_key(
    cfg: AppConfig,
    plan: dict[str, Any],
    devices: list[DeviceInfo],
    vllm_version: str,
) -> dict[str, Any]:
    model_name = str(plan.get("model") or "")
    metal = is_metal_backend()
    key = {
        "schema": _KEY_SCHEMA,
        "backend": "metal" if metal else "cuda",
        "gpus": gpu_classes(calibration_devices(plan, devices)),
        "vllm_version": vllm_version,
        "nccl_p2p_available": bool(cfg.engines.vllm.nccl_p2p_available) if cfg.engines else False,
        "sleep_enabled": (not metal) and model_can_sleep(cfg, model_name),
        "plan_hash": plan_hash(plan),
    }
    if metal and cfg.engines:
        key["metal"] = _metal_engine_settings(cfg.engines.metal)
    return key


def _metal_engine_settings(metal_config: MetalConfig) -> dict[str, Any]:
    """The node-wide Metal knobs calibration and serving both apply.

    The key is stored in clear, so free-form env overrides only as a hash.
    """
    return {
        "memory_fraction": metal_config.memory_fraction,
        "use_paged_attention": metal_config.use_paged_attention,
        "multimodal_mode": metal_config.multimodal_mode,
        "env_overrides_hash": hashlib.sha256(_canonical(metal_config.env_overrides).encode("utf-8")).hexdigest(),
    }


def serving_vllm_binary(cfg: AppConfig, default_binary: str) -> str:
    """The vllm CLI whose version a calibration on this node depends on.

    Metal serves from its own venv, never from the worker's environment.
    """
    if not is_metal_backend():
        return default_binary
    from logos_worker_node.metal import resolve_metal_vllm_binary  # noqa: PLC0415

    worker_binary = cfg.engines.metal.vllm_binary if cfg.engines else ""
    return resolve_metal_vllm_binary(default_binary, worker_binary) or default_binary


def calibration_keys(
    cfg: AppConfig,
    plans: list[dict[str, Any]],
    model_names: Iterable[str],
    devices: list[DeviceInfo],
    vllm_version: str,
) -> dict[str, dict[str, Any]]:
    """Calibration key per model; models without a plan use a bare one."""
    plan_by_model = {p["model"]: p for p in plans if p.get("model")}
    return {
        name: compute_calibration_key(cfg, plan_by_model.get(name) or {"model": name}, devices, vllm_version)
        for name in model_names
    }


_vllm_versions: dict[str, str] = {}


def cached_vllm_version(vllm_binary: str) -> str:
    """vLLM version of the serving interpreter; resolving it may fork.

    An unknown version is not cached: a probe that timed out once would
    otherwise change every calibration key of this process.
    """
    if vllm_binary in _vllm_versions:
        return _vllm_versions[vllm_binary]
    from logos_worker_node.sharded_checkpoint import resolve_vllm_version  # noqa: PLC0415

    try:
        version = resolve_vllm_version(vllm_binary)
    except Exception:  # noqa: BLE001
        version = ""
    if version:
        _vllm_versions[vllm_binary] = version
    else:
        logger.warning("vLLM version of %s is unknown; calibration keys omit it", vllm_binary)
    return version
