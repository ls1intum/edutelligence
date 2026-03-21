from __future__ import annotations

from pathlib import Path

import pytest

from logos_worker_node.models import LaneConfig, OllamaConfig, VllmConfig
from logos_worker_node.vllm_process import VllmProcessHandle


def _make_executable(path: Path) -> None:
    path.write_text("#!/usr/bin/env bash\nexit 0\n")
    path.chmod(0o755)


def test_resolve_vllm_binary_uses_venv_sibling(monkeypatch, tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    python_bin = bin_dir / "python"
    vllm_bin = bin_dir / "vllm"
    _make_executable(python_bin)
    _make_executable(vllm_bin)

    monkeypatch.setattr("logos_worker_node.vllm_process.sys.executable", str(python_bin))
    monkeypatch.setattr("logos_worker_node.vllm_process.shutil.which", lambda _cmd: None)

    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    resolved = handle._resolve_vllm_binary("vllm")
    assert resolved == str(vllm_bin)


def test_resolve_vllm_binary_honors_absolute_path(tmp_path: Path) -> None:
    explicit = tmp_path / "custom-vllm"
    _make_executable(explicit)

    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    resolved = handle._resolve_vllm_binary(str(explicit))
    assert resolved == str(explicit)


def test_build_cmd_does_not_duplicate_enforce_eager(monkeypatch) -> None:
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _configured: "/tmp/vllm")

    lane = LaneConfig(
        model="deepseek-ai/DeepSeek-R1-0528-Qwen3-8B",
        vllm=True,
        flash_attention=False,
        vllm_config=VllmConfig(enforce_eager=True),
    )
    cmd = handle._build_cmd(lane)
    assert cmd.count("--enforce-eager") == 1


def test_build_cmd_includes_stability_and_sleep_flags(monkeypatch) -> None:
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _configured: "/tmp/vllm")

    lane = LaneConfig(
        model="deepseek-ai/DeepSeek-R1-0528-Qwen3-8B",
        vllm=True,
        vllm_config=VllmConfig(
            disable_custom_all_reduce=True,
            enable_sleep_mode=True,
        ),
    )
    cmd = handle._build_cmd(lane)
    assert "--disable-custom-all-reduce" in cmd
    assert "--enable-sleep-mode" in cmd


def test_build_cmd_includes_kv_cache_memory_bytes(monkeypatch) -> None:
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _configured: "/tmp/vllm")

    lane = LaneConfig(
        model="Qwen/Qwen2.5-Coder-7B-Instruct",
        vllm=True,
        vllm_config=VllmConfig(kv_cache_memory_bytes="4G"),
    )
    cmd = handle._build_cmd(lane)
    idx = cmd.index("--kv-cache-memory-bytes")
    assert cmd[idx + 1] == "4G"


def test_build_cmd_omits_kv_cache_when_empty(monkeypatch) -> None:
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _configured: "/tmp/vllm")

    lane = LaneConfig(
        model="Qwen/Qwen2.5-Coder-7B-Instruct",
        vllm=True,
        vllm_config=VllmConfig(),  # kv_cache_memory_bytes defaults to ""
    )
    cmd = handle._build_cmd(lane)
    assert "--kv-cache-memory-bytes" not in cmd


def test_vllm_config_kv_cache_validation() -> None:
    import pytest

    # Valid values
    VllmConfig(kv_cache_memory_bytes="4G")
    VllmConfig(kv_cache_memory_bytes="2048M")
    VllmConfig(kv_cache_memory_bytes="512000000")
    VllmConfig(kv_cache_memory_bytes="2.5G")
    VllmConfig(kv_cache_memory_bytes="")

    # Invalid values
    with pytest.raises(Exception):
        VllmConfig(kv_cache_memory_bytes="abc")
    with pytest.raises(Exception):
        VllmConfig(kv_cache_memory_bytes="-1G")


def test_build_env_uses_writable_hf_cache_fallback(monkeypatch, tmp_path: Path) -> None:
    models_path = tmp_path / "models"
    models_path.mkdir(parents=True, exist_ok=True)
    models_path.chmod(0o555)

    handle = VllmProcessHandle(
        "lane-test",
        19000,
        OllamaConfig(models_path=str(models_path), gpu_devices="all"),
    )

    lane = LaneConfig(
        model="deepseek-ai/DeepSeek-R1-0528-Qwen3-8B",
        vllm=True,
        vllm_config=VllmConfig(),
    )

    monkeypatch.delenv("HF_HOME", raising=False)
    env = handle._build_env(lane)

    # Should fall back to user cache instead of unwritable models path.
    assert env["HF_HOME"].endswith(".cache/huggingface")
    models_path.chmod(0o755)


def test_build_env_sets_optional_vllm_env_flags(monkeypatch) -> None:
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig(gpu_devices="all"))
    lane = LaneConfig(
        model="deepseek-ai/DeepSeek-R1-0528-Qwen3-8B",
        vllm=True,
        vllm_config=VllmConfig(server_dev_mode=True, disable_nccl_p2p=True),
    )

    monkeypatch.delenv("HF_HOME", raising=False)
    env = handle._build_env(lane)
    assert env["VLLM_SERVER_DEV_MODE"] == "1"
    assert env["NCCL_P2P_DISABLE"] == "1"


def test_require_c_compiler_honors_cc_absolute_path(monkeypatch, tmp_path: Path) -> None:
    custom_cc = tmp_path / "custom-cc"
    _make_executable(custom_cc)

    monkeypatch.setenv("CC", str(custom_cc))
    monkeypatch.setattr("logos_worker_node.vllm_process.shutil.which", lambda _cmd: None)

    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    handle._require_c_compiler()


def test_require_c_compiler_raises_actionable_error(monkeypatch) -> None:
    monkeypatch.delenv("CC", raising=False)
    monkeypatch.setattr("logos_worker_node.vllm_process.shutil.which", lambda _cmd: None)

    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    with pytest.raises(RuntimeError, match="No C compiler found in runtime"):
        handle._require_c_compiler()


@pytest.mark.asyncio
async def test_sleep_raises_when_sleep_mode_disabled() -> None:
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    handle._lane_config = LaneConfig(
        model="deepseek-ai/DeepSeek-R1-0528-Qwen3-8B",
        vllm=True,
        vllm_config=VllmConfig(enable_sleep_mode=False),
    )
    await handle.init()
    try:
        with pytest.raises(RuntimeError, match="Sleep mode is disabled"):
            await handle.sleep()
    finally:
        await handle.close()


@pytest.mark.asyncio
async def test_is_sleeping_parses_boolean_payload() -> None:
    class DummyResponse:
        status_code = 200

        @staticmethod
        def json() -> dict:
            return {"is_sleeping": True}

    class DummyClient:
        async def get(self, _url: str, timeout: float = 5.0):  # noqa: ARG002
            return DummyResponse()

    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    handle._lane_config = LaneConfig(
        model="deepseek-ai/DeepSeek-R1-0528-Qwen3-8B",
        vllm=True,
        vllm_config=VllmConfig(enable_sleep_mode=True),
    )
    handle._http = DummyClient()  # type: ignore[assignment]

    assert await handle.is_sleeping() is True


@pytest.mark.asyncio
async def test_get_backend_metrics_parses_labeled_prometheus_lines() -> None:
    class DummyResponse:
        status_code = 200
        text = """
# HELP ignored ignored
vllm:num_requests_waiting{model_name=\"Qwen\"} 3
vllm:num_requests_running{model_name=\"Qwen\"} 5
vllm:gpu_cache_usage_perc{model_name=\"Qwen\"} 0.82
vllm:prefix_cache_hit_rate{model_name=\"Qwen\"} 0.35
vllm:prompt_tokens_total{model_name=\"Qwen\"} 2048
vllm:generation_tokens_total{model_name=\"Qwen\"} 4096
vllm:time_to_first_token_seconds_bucket{model_name=\"Qwen\",le=\"0.1\"} 8
vllm:time_to_first_token_seconds_bucket{model_name=\"Qwen\",le=\"+Inf\"} 10
"""

    class DummyClient:
        async def get(self, _url: str, timeout: float = 5.0):  # noqa: ARG002
            return DummyResponse()

    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    handle._http = DummyClient()  # type: ignore[assignment]

    metrics = await handle.get_backend_metrics()
    assert metrics["queue_waiting"] == 3.0
    assert metrics["requests_running"] == 5.0
    assert metrics["gpu_cache_usage_percent"] == 82.0
    assert metrics["prefix_cache_hit_rate"] == 0.35
    assert metrics["prompt_tokens_total"] == 2048.0
    assert metrics["generation_tokens_total"] == 4096.0
    assert metrics["ttft_histogram"]["0.1"] == 8.0
    assert metrics["ttft_histogram"]["+Inf"] == 10.0
