"""Calibration keys decide whether a stored calibration still applies here."""

from __future__ import annotations

import json

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


def test_every_gpu_counts_for_an_unpinned_plan():
    """Calibration prefers idle GPUs, so a probe may run on GPU 2; replacing
    it with another class must mark the calibration stale."""
    plan = {"model": "org/m"}
    assert _key(plan, [_gpu(0), _gpu(1), _gpu(2)]) != _key(plan, [_gpu(0), _gpu(1), _gpu(2, name="Other GPU")])


def test_only_the_pinned_gpus_count_for_a_pinned_plan():
    plan = {"model": "org/m", "gpu_devices": "0,1"}
    assert _key(plan, [_gpu(0), _gpu(1), _gpu(2)]) == _key(plan, [_gpu(0), _gpu(1), _gpu(2, name="Other GPU")])
    assert _key(plan, [_gpu(0), _gpu(1), _gpu(2)]) != _key(plan, [_gpu(0), _gpu(1, name="Other GPU"), _gpu(2)])


def test_models_without_a_plan_get_a_bare_key():
    keys = calibration_keys(AppConfig(), [{"model": "org/a", "dtype": "half"}], ["org/a", "org/b"], [_gpu(0)], "0.30.0")
    assert set(keys) == {"org/a", "org/b"}
    assert keys["org/a"]["plan_hash"] != keys["org/b"]["plan_hash"]


def test_unknown_vllm_version_is_probed_again(monkeypatch):
    from logos_worker_node import profile_fingerprint, sharded_checkpoint

    answers = iter(["", "0.30.0", "0.31.0"])
    monkeypatch.setattr(profile_fingerprint, "_vllm_versions", {})
    monkeypatch.setattr(sharded_checkpoint, "resolve_vllm_version", lambda binary: next(answers))

    assert profile_fingerprint.cached_vllm_version("vllm") == ""
    assert profile_fingerprint.cached_vllm_version("vllm") == "0.30.0"
    assert profile_fingerprint.cached_vllm_version("vllm") == "0.30.0"


def test_metal_engine_settings_change_the_key(monkeypatch):
    monkeypatch.setenv("LOGOS_WORKER_BACKEND", "metal")
    plan = {"model": "org/m"}
    reference = _key(plan, [_gpu(0)])
    for change in ({"memory_fraction": 0.5}, {"use_paged_attention": False}, {"env_overrides": {"VLLM_METAL_X": "1"}}):
        cfg = AppConfig.model_validate({"engines": {"metal": change}})
        assert _key(plan, [_gpu(0)], cfg=cfg) != reference
    secret = AppConfig.model_validate({"engines": {"metal": {"env_overrides": {"HF_TOKEN": "hf_secret123"}}}})
    assert "hf_secret123" not in json.dumps(compute_calibration_key(secret, plan, [_gpu(0)], "0"))


def test_cuda_keys_carry_no_metal_settings():
    cfg = AppConfig.model_validate({"engines": {"metal": {"memory_fraction": 0.5}}})
    assert _key({"model": "org/m"}, [_gpu(0)], cfg=cfg) == _key({"model": "org/m"}, [_gpu(0)])


def test_metal_versions_come_from_the_metal_binary(monkeypatch, tmp_path):
    from logos_worker_node.profile_fingerprint import serving_vllm_binary

    binary = tmp_path / "vllm"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    cfg = AppConfig.model_validate({"engines": {"metal": {"vllm_binary": str(binary)}}})
    assert serving_vllm_binary(cfg, "vllm") == "vllm"
    monkeypatch.setenv("LOGOS_WORKER_BACKEND", "metal")
    assert serving_vllm_binary(cfg, "vllm") == str(binary)
