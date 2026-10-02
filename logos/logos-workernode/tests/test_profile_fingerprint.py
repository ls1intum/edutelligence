"""Calibration keys decide whether a stored calibration still applies here."""

from __future__ import annotations

import pytest

from logos_worker_node.models import AppConfig, DeviceInfo
from logos_worker_node.profile_fingerprint import calibration_keys, compute_calibration_key, key_hash, plan_hash


@pytest.fixture(autouse=True)
def _cuda(monkeypatch):
    monkeypatch.setenv("LOGOS_WORKER_BACKEND", "cuda")


def _gpu(index: int, name: str = "NVIDIA RTX A4000", memory_mb: float = 16376.0) -> DeviceInfo:
    return DeviceInfo(
        device_id=f"gpu{index}",
        name=name,
        memory_total_mb=memory_mb,
        extra={"index": index, "compute_capability": "8.6"},
    )


def _key(plan: dict, devices: list[DeviceInfo], vllm_version: str = "0.30.0", cfg: AppConfig | None = None) -> str:
    return key_hash(compute_calibration_key(cfg or AppConfig(), plan, devices, vllm_version))


def test_the_key_is_deterministic():
    plan = {"model": "org/m", "dtype": "auto", "extra_args": ["--a", "1"]}
    assert _key(plan, [_gpu(0), _gpu(1)]) == _key(dict(plan), [_gpu(0), _gpu(1)])


def test_node_layout_and_bookkeeping_do_not_change_the_plan_hash():
    base = {"model": "org/m", "dtype": "auto"}
    assert plan_hash(base) == plan_hash({**base, "gpu_devices": "0,1", "_detected_model_kind": "chat"})
    assert plan_hash(base) == plan_hash({**base, "model": "org/other"})


@pytest.mark.parametrize(
    "change",
    [
        {"extra_args": ["--hf-overrides", "{}"]},
        {"kv_cache_dtype": "fp8"},
        {"kv_cache_memory_bytes": "6G"},
        {"speculative_config": "{}"},
    ],
)
def test_every_configured_serving_option_changes_the_key(change):
    plan = {"model": "org/m"}
    assert _key(plan, [_gpu(0)]) != _key({**plan, **change}, [_gpu(0)])


def test_vllm_version_gpu_class_and_memory_change_the_key():
    plan = {"model": "org/m"}
    reference = _key(plan, [_gpu(0)])
    assert reference != _key(plan, [_gpu(0)], vllm_version="0.31.0")
    assert reference != _key(plan, [_gpu(0, name="NVIDIA A100")])
    assert reference != _key(plan, [_gpu(0, memory_mb=24564.0)])


def test_backend_changes_the_key(monkeypatch):
    plan = {"model": "org/m"}
    cuda = _key(plan, [_gpu(0)])
    monkeypatch.setenv("LOGOS_WORKER_BACKEND", "metal")
    assert cuda != _key(plan, [_gpu(0)])


def test_gpu_count_is_left_out_so_tp_stays_comparable():
    plan = {"model": "org/m"}
    assert _key(plan, [_gpu(0), _gpu(1)]) == _key(plan, [_gpu(0), _gpu(1), _gpu(2), _gpu(3)])


def test_only_the_calibration_slice_counts():
    """3 GPUs calibrate on the power-of-two slice 0,1; a different leftover
    GPU 2 is never touched and must not split the key."""
    plan = {"model": "org/m"}
    assert _key(plan, [_gpu(0), _gpu(1), _gpu(2)]) == _key(plan, [_gpu(0), _gpu(1), _gpu(2, name="Other GPU")])


def test_models_without_a_plan_get_a_bare_key():
    keys = calibration_keys(AppConfig(), [{"model": "org/a", "dtype": "half"}], ["org/a", "org/b"], [_gpu(0)], "0.30.0")
    assert set(keys) == {"org/a", "org/b"}
    assert keys["org/a"]["plan_hash"] != keys["org/b"]["plan_hash"]
