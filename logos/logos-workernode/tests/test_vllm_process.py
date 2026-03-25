from __future__ import annotations

import asyncio
import os
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


def test_build_cmd_injects_low_gpu_memory_utilization_with_kv_cache(monkeypatch) -> None:
    """When kv_cache_memory_bytes is set but gpu_memory_utilization is not,
    a low fallback value (0.1) must be injected to satisfy vLLM's startup
    free-memory guard while letting kv_cache_memory_bytes control cache sizing."""
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _configured: "/tmp/vllm")

    lane = LaneConfig(
        model="Qwen/Qwen2.5-Coder-7B-Instruct",
        vllm=True,
        vllm_config=VllmConfig(kv_cache_memory_bytes="4G"),
    )
    cmd = handle._build_cmd(lane)
    idx = cmd.index("--gpu-memory-utilization")
    assert cmd[idx + 1] == "0.1"


def test_build_cmd_omits_gpu_memory_utilization_when_no_kv_cache(monkeypatch) -> None:
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _configured: "/tmp/vllm")

    lane = LaneConfig(
        model="Qwen/Qwen2.5-Coder-7B-Instruct",
        vllm=True,
        vllm_config=VllmConfig(),
    )
    cmd = handle._build_cmd(lane)
    assert "--gpu-memory-utilization" not in cmd


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
async def test_wake_up_uses_extended_timeout() -> None:
    class DummyResponse:
        status_code = 200
        content = b"{}"

        @staticmethod
        def json() -> dict:
            return {"ok": True}

    class DummyClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, float]] = []

        async def post(self, url: str, timeout: float = 0.0):
            self.calls.append((url, timeout))
            return DummyResponse()

    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    handle._lane_config = LaneConfig(
        model="Qwen/Qwen2.5-Coder-7B-Instruct",
        vllm=True,
        vllm_config=VllmConfig(enable_sleep_mode=True),
    )
    client = DummyClient()
    handle._http = client  # type: ignore[assignment]

    assert await handle.wake_up() == {"ok": True}
    assert client.calls == [("http://127.0.0.1:19000/wake_up", 120.0)]


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



def test_build_env_injects_nccl_safety_for_tp_greater_than_1(monkeypatch) -> None:
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig(gpu_devices="all"))
    lane = LaneConfig(
        model="deepseek-ai/DeepSeek-R1-0528-Qwen3-8B",
        vllm=True,
        vllm_config=VllmConfig(tensor_parallel_size=2),
    )
    monkeypatch.delenv("HF_HOME", raising=False)
    env = handle._build_env(lane)
    # Only universally safe vars — no transport tuning (NCCL auto-detects)
    assert env["TORCH_NCCL_ASYNC_ERROR_HANDLING"] == "1"
    assert env["NCCL_CUMEM_ENABLE"] == "0"
    assert env["NCCL_TIMEOUT"] == "1800"
    assert env["VLLM_DISTRIBUTED_TIMEOUT_MINUTES"] == "30"
    # Transport knobs must NOT be set (NCCL auto-tunes based on topology)
    assert "NCCL_P2P_LEVEL" not in env
    assert "NCCL_BUFFSIZE" not in env
    assert "NCCL_SHM_USE_CUDA_MEMCPY" not in env
    assert "NCCL_NET_GDR_LEVEL" not in env


def test_build_env_no_nccl_safety_for_tp_1(monkeypatch) -> None:
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig(gpu_devices="all"))
    lane = LaneConfig(
        model="deepseek-ai/DeepSeek-R1-0528-Qwen3-8B",
        vllm=True,
        vllm_config=VllmConfig(tensor_parallel_size=1),
    )
    monkeypatch.delenv("HF_HOME", raising=False)
    env = handle._build_env(lane)
    # NCCL safety vars should NOT be injected for TP=1
    assert "NCCL_ASYNC_ERROR_HANDLING" not in env
    assert "NCCL_CUMEM_ENABLE" not in env


def test_build_env_nccl_safety_respects_explicit_disable_nccl_p2p(monkeypatch) -> None:
    """When disable_nccl_p2p is explicitly set in config, it should still be set for TP>1."""
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig(gpu_devices="all"))
    lane = LaneConfig(
        model="deepseek-ai/DeepSeek-R1-0528-Qwen3-8B",
        vllm=True,
        vllm_config=VllmConfig(tensor_parallel_size=2, disable_nccl_p2p=True),
    )
    monkeypatch.delenv("HF_HOME", raising=False)
    env = handle._build_env(lane)
    assert env["NCCL_P2P_DISABLE"] == "1"


def test_build_process_env_scrubs_inherited_distributed_vars_for_all_gpus(monkeypatch) -> None:
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig(gpu_devices="all"))
    lane = LaneConfig(
        model="Qwen/Qwen2.5-0.5B-Instruct",
        vllm=True,
        vllm_config=VllmConfig(),
    )

    monkeypatch.setenv("LOCAL_RANK", "1")
    monkeypatch.setenv("RANK", "1")
    monkeypatch.setenv("WORLD_SIZE", "2")
    monkeypatch.setenv("MASTER_ADDR", "127.0.0.1")
    monkeypatch.setenv("MASTER_PORT", "29500")
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "1")
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.delenv("HF_HOME", raising=False)

    env = handle._build_env(lane)
    process_env = handle._build_process_env(lane, env, ["/tmp/vllm", "serve"])
    expected_prefix = str(Path("/tmp/vllm").resolve().parent)

    assert "LOCAL_RANK" not in process_env
    assert "RANK" not in process_env
    assert "WORLD_SIZE" not in process_env
    assert "MASTER_ADDR" not in process_env
    assert "MASTER_PORT" not in process_env
    assert "CUDA_VISIBLE_DEVICES" not in process_env
    assert process_env["PATH"] == f"{expected_prefix}{os.pathsep}/usr/bin"


def test_build_process_env_keeps_explicit_gpu_pin(monkeypatch) -> None:
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig(gpu_devices="all"))
    lane = LaneConfig(
        model="Qwen/Qwen2.5-0.5B-Instruct",
        vllm=True,
        gpu_devices="0",
        vllm_config=VllmConfig(),
    )

    monkeypatch.setenv("LOCAL_RANK", "1")
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "1")
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.delenv("HF_HOME", raising=False)

    env = handle._build_env(lane)
    process_env = handle._build_process_env(lane, env, ["/tmp/vllm", "serve"])
    expected_prefix = str(Path("/tmp/vllm").resolve().parent)

    assert "LOCAL_RANK" not in process_env
    assert process_env["CUDA_VISIBLE_DEVICES"] == "0"
    assert process_env["PATH"] == f"{expected_prefix}{os.pathsep}/usr/bin"


@pytest.mark.asyncio
async def test_spawn_uses_new_process_session(monkeypatch) -> None:
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    lane = LaneConfig(
        model="Qwen/Qwen2.5-Coder-7B-Instruct",
        vllm=True,
        vllm_config=VllmConfig(),
    )

    class DummyProcess:
        pid = 4242
        returncode = None
        stdout = None

    captured: dict[str, object] = {}

    async def _fake_exec(*cmd, **kwargs):  # noqa: ANN001
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return DummyProcess()

    monkeypatch.setattr(handle, "_build_cmd", lambda _lane: ["/tmp/vllm", "serve"])
    monkeypatch.setattr(handle, "_build_env", lambda _lane: {})
    monkeypatch.setattr(handle, "_require_c_compiler", lambda: None)
    monkeypatch.setattr(handle, "_require_nvcc", lambda _lane: None)
    
    async def _fake_wait_for_ready(timeout):  # noqa: ANN001
        return True
    
    monkeypatch.setattr(handle, "_wait_for_ready", _fake_wait_for_ready)
    monkeypatch.setattr("logos_worker_node.vllm_process.asyncio.create_subprocess_exec", _fake_exec)

    status = await handle.spawn(lane)

    assert status.pid == 4242
    assert captured["kwargs"]["start_new_session"] is True
    assert handle._process_group_id == 4242


@pytest.mark.asyncio
async def test_kill_process_targets_process_group(monkeypatch) -> None:
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())

    class DummyProcess:
        pid = 4242
        returncode = None

        async def wait(self):
            self.returncode = 0
            return 0

        def send_signal(self, _sig):  # noqa: ANN001
            raise AssertionError("fallback send_signal should not be used")

        def kill(self):
            raise AssertionError("fallback kill should not be used")

    calls: list[tuple[int, object]] = []

    def _fake_killpg(pgid: int, sig) -> None:  # noqa: ANN001
        calls.append((pgid, sig))

    handle._process = DummyProcess()
    handle._process_group_id = 4242
    monkeypatch.setattr("logos_worker_node.vllm_process.os.killpg", _fake_killpg)

    await handle._kill_process()

    assert calls
    assert calls[0][0] == 4242


@pytest.mark.asyncio
async def test_kill_process_does_not_wait_forever_after_sigkill(monkeypatch) -> None:
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())

    class DummyProcess:
        pid = 4242
        returncode = None

        async def wait(self):
            return None

        def send_signal(self, _sig):  # noqa: ANN001
            raise AssertionError("fallback send_signal should not be used")

        def kill(self):
            raise AssertionError("fallback kill should not be used")

    calls: list[tuple[int, object]] = []

    def _fake_killpg(pgid: int, sig) -> None:  # noqa: ANN001
        calls.append((pgid, sig))

    call_count = 0

    async def _fake_wait_for(awaitable, timeout):  # noqa: ANN001
        nonlocal call_count
        call_count += 1
        await awaitable
        raise asyncio.TimeoutError

    handle._process = DummyProcess()
    handle._process_group_id = 4242
    monkeypatch.setattr("logos_worker_node.vllm_process.os.killpg", _fake_killpg)
    monkeypatch.setattr("logos_worker_node.vllm_process.asyncio.wait_for", _fake_wait_for)

    await handle._kill_process()

    assert len(calls) == 2
    assert handle._process_group_id is None


# ---------------------------------------------------------------------------
# Phase 4: Cold start optimization
# ---------------------------------------------------------------------------


def test_build_cmd_includes_cuda_graph_sizes_when_set(monkeypatch):
    """CUDA graph sizes should appear in cmd when set and not enforce_eager."""
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _c: "/tmp/vllm")
    lc = LaneConfig(
        model="test-model", vllm=True,
        vllm_config=VllmConfig(cuda_graph_sizes="1,2,4,8", enforce_eager=False),
    )
    cmd = handle._build_cmd(lc)
    assert "--cuda-graph-sizes" in cmd
    idx = cmd.index("--cuda-graph-sizes")
    assert cmd[idx + 1] == "1,2,4,8"


def test_build_cmd_skips_cuda_graph_sizes_with_enforce_eager(monkeypatch):
    """CUDA graph sizes should be skipped when enforce_eager is True."""
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _c: "/tmp/vllm")
    lc = LaneConfig(
        model="test-model", vllm=True,
        vllm_config=VllmConfig(cuda_graph_sizes="1,2,4,8", enforce_eager=True),
    )
    cmd = handle._build_cmd(lc)
    assert "--cuda-graph-sizes" not in cmd


def test_build_cmd_includes_cpu_offload(monkeypatch):
    """--cpu-offload-gb should appear when cpu_offload_gb > 0."""
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _c: "/tmp/vllm")
    lc = LaneConfig(
        model="test-model", vllm=True,
        vllm_config=VllmConfig(cpu_offload_gb=10.0),
    )
    cmd = handle._build_cmd(lc)
    assert "--cpu-offload-gb" in cmd
    idx = cmd.index("--cpu-offload-gb")
    assert cmd[idx + 1] == "10.0"


def test_build_cmd_no_cpu_offload_when_zero(monkeypatch):
    """--cpu-offload-gb should not appear when cpu_offload_gb == 0 (explicitly disabled)."""
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _c: "/tmp/vllm")
    lc = LaneConfig(
        model="test-model", vllm=True,
        vllm_config=VllmConfig(cpu_offload_gb=0.0),
    )
    cmd = handle._build_cmd(lc)
    assert "--cpu-offload-gb" not in cmd


def test_enforce_eager_off_by_default(monkeypatch):
    """enforce_eager defaults to False — --enforce-eager should not be in cmd."""
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _c: "/tmp/vllm")
    lc = LaneConfig(model="test-model", vllm=True, vllm_config=VllmConfig())
    cmd = handle._build_cmd(lc)
    assert "--enforce-eager" not in cmd


def test_enforce_eager_can_be_enabled(monkeypatch):
    """Setting enforce_eager=True should add --enforce-eager."""
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _c: "/tmp/vllm")
    lc = LaneConfig(model="test-model", vllm=True, vllm_config=VllmConfig(enforce_eager=True))
    cmd = handle._build_cmd(lc)
    assert "--enforce-eager" in cmd


def test_no_attn_override_by_default(monkeypatch):
    """By default no attention backend override — let vLLM pick (FlashInfer)."""
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _c: "/tmp/vllm")
    lc = LaneConfig(model="test-model", vllm=True, vllm_config=VllmConfig())
    cmd = handle._build_cmd(lc)
    assert "--attention-config.backend" not in cmd


def test_explicit_attention_backend_config(monkeypatch):
    """Explicit attention_backend in config should be passed to vLLM."""
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _c: "/tmp/vllm")
    lc = LaneConfig(model="test-model", vllm=True, vllm_config=VllmConfig(attention_backend="TRITON_ATTN"))
    cmd = handle._build_cmd(lc)
    assert "--attention-config.backend" in cmd
    idx = cmd.index("--attention-config.backend")
    assert cmd[idx + 1] == "TRITON_ATTN"


def test_build_env_sets_persistent_caches(monkeypatch):
    """All compilation caches should point to models_path for persistence."""
    monkeypatch.delenv("TORCHINDUCTOR_CACHE_DIR", raising=False)
    monkeypatch.delenv("TORCHINDUCTOR_FX_GRAPH_CACHE", raising=False)
    monkeypatch.delenv("FLASHINFER_JIT_DIR", raising=False)
    monkeypatch.delenv("VLLM_TORCH_COMPILE_CACHE", raising=False)
    monkeypatch.delenv("TORCH_CUDA_ARCH_LIST", raising=False)
    gc = OllamaConfig(models_path="/data/models")
    handle = VllmProcessHandle("lane-test", 19000, gc)
    monkeypatch.setattr(handle, "_detect_cuda_arch", lambda: "7.5")
    lc = LaneConfig(model="test-model", vllm=True, vllm_config=VllmConfig())
    env = handle._build_env(lc)
    assert env["TORCHINDUCTOR_CACHE_DIR"] == "/data/models/.cache/torch_inductor"
    assert env["TORCHINDUCTOR_FX_GRAPH_CACHE"] == "1"
    assert env["FLASHINFER_JIT_DIR"] == "/data/models/.cache/flashinfer"
    assert env["VLLM_TORCH_COMPILE_CACHE"] == "/data/models/.cache/vllm_compile"
    assert env["TORCH_CUDA_ARCH_LIST"] == "7.5"
