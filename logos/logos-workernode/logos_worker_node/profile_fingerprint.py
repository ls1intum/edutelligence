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
from logos_worker_node.models import AppConfig, DeviceInfo, model_can_sleep

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
    """The GPUs a calibration of this plan runs on."""
    from logos_worker_node.calibration import calibration_gpu_slice, parse_gpu_indices  # noqa: PLC0415

    indexed = {int((d.extra or {}).get("index", -1)): d for d in devices if (d.extra or {}).get("index") is not None}
    if not indexed:
        return list(devices)
    pinned = parse_gpu_indices(str(plan.get("gpu_devices") or ""))
    indices = pinned if pinned is not None else calibration_gpu_slice(len(indexed))
    return [indexed[i] for i in indices if i in indexed]


def compute_calibration_key(
    cfg: AppConfig,
    plan: dict[str, Any],
    devices: list[DeviceInfo],
    vllm_version: str,
) -> dict[str, Any]:
    model_name = str(plan.get("model") or "")
    metal = is_metal_backend()
    return {
        "schema": _KEY_SCHEMA,
        "backend": "metal" if metal else "cuda",
        "gpus": gpu_classes(calibration_devices(plan, devices)),
        "vllm_version": vllm_version,
        "nccl_p2p_available": bool(cfg.engines.vllm.nccl_p2p_available) if cfg.engines else False,
        "sleep_enabled": (not metal) and model_can_sleep(cfg, model_name),
        "plan_hash": plan_hash(plan),
    }


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
