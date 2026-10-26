"""The calibration probe runs with the serving lane's attention backend."""

from __future__ import annotations

import pytest

from logos_worker_node import vllm_process
from logos_worker_node.calibration import _build_vllm_cmd, plans_from_config
from logos_worker_node.model_profiles import ModelProfileRegistry
from logos_worker_node.models import AppConfig, DeviceInfo, LaneConfig, VllmConfig, WorkerConfig
from logos_worker_node.profile_fingerprint import compute_calibration_key
from logos_worker_node.vllm_process import (
    ATTENTION_BACKEND_FLAG,
    VllmProcessHandle,
    attention_backend_args,
    auto_attention_backend,
    extra_args_set_attention_backend,
    reset_cuda_arch_cache,
)


def _cmd(plan: dict, monkeypatch: pytest.MonkeyPatch, arch: str | None = "12.0") -> list[str]:
    monkeypatch.setattr(vllm_process, "detect_cuda_arch", lambda: arch)
    return _build_vllm_cmd({"model": "org/model", **plan}, "vllm", "127.0.0.1", 18000, "8G")


def _backends(cmd: list[str]) -> list[str]:
    return [cmd[i + 1] for i, tok in enumerate(cmd) if tok == ATTENTION_BACKEND_FLAG]


def test_probe_uses_the_plans_attention_backend(monkeypatch):
    cmd = _cmd({"attention_backend": "TRITON_ATTN"}, monkeypatch)
    assert _backends(cmd) == ["TRITON_ATTN"]


def test_explicit_backend_wins_over_auto_detection(monkeypatch):
    cmd = _cmd({"attention_backend": "FLASH_ATTN"}, monkeypatch, arch="7.5")
    assert _backends(cmd) == ["FLASH_ATTN"]


def test_probe_auto_selects_triton_on_pre_ampere(monkeypatch):
    assert _backends(_cmd({}, monkeypatch, arch="7.5")) == ["TRITON_ATTN"]


@pytest.mark.parametrize("arch", ["8.6", "12.0", "7.5;8.6", None])
def test_probe_leaves_the_backend_to_vllm_otherwise(monkeypatch, arch):
    assert _backends(_cmd({}, monkeypatch, arch=arch)) == []


@pytest.mark.parametrize(
    "raw",
    [
        [ATTENTION_BACKEND_FLAG, "FLASHINFER"],
        [f"{ATTENTION_BACKEND_FLAG}=FLASHINFER"],
        ["--attention-config", '{"backend": "FLASHINFER"}'],
        ['--attention-config={"backend": "FLASHINFER", "flash_attn_version": 2}'],
        ["--attention-config", "backend=FLASHINFER"],
        ["--attention-backend", "FLASHINFER"],
        ["--attention-backend=FLASHINFER"],
        ["-ac", '{"backend": "FLASHINFER"}'],
    ],
)
def test_backend_in_extra_args_is_not_emitted_twice(monkeypatch, raw):
    cmd = _cmd({"attention_backend": "TRITON_ATTN", "extra_args": raw}, monkeypatch)
    assert "TRITON_ATTN" not in cmd
    assert cmd[-len(raw) :] == raw


def test_override_from_config_reaches_the_probe_command(monkeypatch, tmp_path):
    config = tmp_path / "config.yml"
    config.write_text(
        "logos:\n"
        "  capabilities_models:\n"
        "    - org/model\n"
        "engines:\n"
        "  vllm:\n"
        "    model_overrides:\n"
        "      org/model:\n"
        "        attention_backend: TRITON_ATTN\n"
    )
    (plan,) = plans_from_config(config)
    monkeypatch.setattr(vllm_process, "detect_cuda_arch", lambda: "12.0")
    cmd = _build_vllm_cmd(plan, "vllm", "127.0.0.1", 18000, "8G")
    assert _backends(cmd) == ["TRITON_ATTN"]


def test_probe_and_serving_lane_choose_the_same_backend(monkeypatch, tmp_path):
    monkeypatch.setattr(vllm_process, "detect_cuda_arch", lambda: "7.5")
    handle = VllmProcessHandle("lane-test", 19000, WorkerConfig(models_path=str(tmp_path)))
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _c: "/tmp/vllm")
    for vc_kwargs, plan in (
        ({}, {}),
        ({"attention_backend": "FLASHINFER"}, {"attention_backend": "FLASHINFER"}),
    ):
        serving = handle._build_cmd(LaneConfig(model="org/model", vllm=True, vllm_config=VllmConfig(**vc_kwargs)))
        probe = _build_vllm_cmd({"model": "org/model", **plan}, "vllm", "127.0.0.1", 18000, "8G")
        assert _backends(serving) == _backends(probe)


def test_serving_lane_does_not_duplicate_a_raw_backend_flag(monkeypatch, tmp_path):
    handle = VllmProcessHandle("lane-test", 19000, WorkerConfig(models_path=str(tmp_path)))
    monkeypatch.setattr(handle, "_detect_cuda_arch", lambda: "7.5")
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _c: "/tmp/vllm")
    vc = VllmConfig(extra_args=[ATTENTION_BACKEND_FLAG, "FLASHINFER"])
    cmd = handle._build_cmd(LaneConfig(model="org/model", vllm=True, vllm_config=vc))
    assert _backends(cmd) == ["FLASHINFER"]


def test_attention_backend_args_calls_auto_only_without_explicit_value():
    def boom() -> str:
        raise AssertionError("auto detection must not run")

    assert attention_backend_args("TRITON_ATTN", [], boom) == [ATTENTION_BACKEND_FLAG, "TRITON_ATTN"]
    assert attention_backend_args("", [ATTENTION_BACKEND_FLAG, "X"], boom) == []
    assert attention_backend_args(" ", [], lambda: "") == []


def test_auto_attention_backend_ignores_unparsable_capabilities():
    assert auto_attention_backend("sm_75") == ""
    assert auto_attention_backend("") == ""


@pytest.mark.parametrize(
    "raw",
    [
        ["--attention-config.flash_attn_version=2"],
        ["--attention-config.flash_attn_version", "2"],
        ["--attention-config", '{"flash_attn_version": 2}'],
        ["-ac", '{"use_prefill_decode_attention": true}'],
        ["--attention-config"],
    ],
)
def test_other_attention_settings_keep_the_backend_choice(monkeypatch, raw):
    assert not extra_args_set_attention_backend(raw)
    assert _backends(_cmd({"attention_backend": "TRITON_ATTN", "extra_args": raw}, monkeypatch)) == ["TRITON_ATTN"]
    assert _backends(_cmd({"extra_args": raw}, monkeypatch, arch="7.5")) == ["TRITON_ATTN"]


def test_reset_cuda_arch_cache_probes_again(monkeypatch):
    calls = []

    def fake_run(*_args, **_kwargs):
        calls.append(1)
        return type("R", (), {"returncode": 0, "stdout": "7.5\n"})()

    monkeypatch.setattr(vllm_process.subprocess, "run", fake_run)
    reset_cuda_arch_cache()
    try:
        assert vllm_process.detect_cuda_arch() == "7.5"
        assert vllm_process.detect_cuda_arch() == "7.5"
        assert len(calls) == 1
        reset_cuda_arch_cache()
        vllm_process.detect_cuda_arch()
        assert len(calls) == 2
    finally:
        reset_cuda_arch_cache()


def _gpu() -> DeviceInfo:
    return DeviceInfo(device_id="gpu0", name="NVIDIA RTX PRO 6000", memory_total_mb=97887.0, extra={"index": 0})


def _calibration_key(plan: dict, monkeypatch: pytest.MonkeyPatch, arch: str | None) -> dict:
    monkeypatch.setenv("LOGOS_WORKER_BACKEND", "cuda")
    monkeypatch.setattr(vllm_process, "detect_cuda_arch", lambda: arch)
    return compute_calibration_key(AppConfig(), {"model": "org/model", **plan}, [_gpu()], "0.30.0")


@pytest.mark.parametrize(
    "plan, arch, backend",
    [({"attention_backend": "TRITON_ATTN"}, "12.0", "TRITON_ATTN"), ({}, "7.5", "TRITON_ATTN")],
)
def test_calibration_key_names_the_backend_the_probe_passes(monkeypatch, plan, arch, backend):
    assert _calibration_key(plan, monkeypatch, arch)["attention_backend"] == backend


@pytest.mark.parametrize(
    "plan, arch",
    [({}, "12.0"), ({"attention_backend": "TRITON_ATTN", "extra_args": [ATTENTION_BACKEND_FLAG, "X"]}, "12.0")],
)
def test_calibration_key_is_unchanged_when_the_probe_passes_no_backend(monkeypatch, plan, arch):
    assert "attention_backend" not in _calibration_key(plan, monkeypatch, arch)


def test_profile_measured_without_the_backend_is_calibrated_again(monkeypatch):
    """A profile measured while the probe dropped attention_backend gets a new key, so it turns stale."""
    plan = {"attention_backend": "TRITON_ATTN"}
    old_key = {k: v for k, v in _calibration_key(plan, monkeypatch, "12.0").items() if k != "attention_backend"}
    registry = ModelProfileRegistry()
    registry.replace_from_sync({"org/model": {"base_residency_mb": 1000.0, "sync_revision": 1, "calibration_id": 7}})
    registry.set_calibration_keys({"org/model": old_key})
    assert registry.get_profile("org/model").calibration_stale is not True

    changed = registry.set_calibration_keys({"org/model": _calibration_key(plan, monkeypatch, "12.0")})

    assert changed == ["org/model"]
    assert registry.get_profile("org/model").calibration_stale is True
