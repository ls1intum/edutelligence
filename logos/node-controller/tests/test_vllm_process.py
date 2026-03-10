from __future__ import annotations

from pathlib import Path

import pytest

from node_controller.models import LaneConfig, OllamaConfig, VllmConfig
from node_controller.vllm_process import VllmProcessHandle


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

    monkeypatch.setattr("node_controller.vllm_process.sys.executable", str(python_bin))
    monkeypatch.setattr("node_controller.vllm_process.shutil.which", lambda _cmd: None)

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
        backend="vllm",
        flash_attention=False,
        vllm=VllmConfig(enforce_eager=True),
    )
    cmd = handle._build_cmd(lane)
    assert cmd.count("--enforce-eager") == 1


def test_build_cmd_includes_stability_and_sleep_flags(monkeypatch) -> None:
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _configured: "/tmp/vllm")

    lane = LaneConfig(
        model="deepseek-ai/DeepSeek-R1-0528-Qwen3-8B",
        backend="vllm",
        vllm=VllmConfig(
            disable_custom_all_reduce=True,
            enable_sleep_mode=True,
        ),
    )
    cmd = handle._build_cmd(lane)
    assert "--disable-custom-all-reduce" in cmd
    assert "--enable-sleep-mode" in cmd


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
        backend="vllm",
        vllm=VllmConfig(),
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
        backend="vllm",
        vllm=VllmConfig(server_dev_mode=True, disable_nccl_p2p=True),
    )

    monkeypatch.delenv("HF_HOME", raising=False)
    env = handle._build_env(lane)
    assert env["VLLM_SERVER_DEV_MODE"] == "1"
    assert env["NCCL_P2P_DISABLE"] == "1"


def test_require_c_compiler_honors_cc_absolute_path(monkeypatch, tmp_path: Path) -> None:
    custom_cc = tmp_path / "custom-cc"
    _make_executable(custom_cc)

    monkeypatch.setenv("CC", str(custom_cc))
    monkeypatch.setattr("node_controller.vllm_process.shutil.which", lambda _cmd: None)

    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    handle._require_c_compiler()


def test_require_c_compiler_raises_actionable_error(monkeypatch) -> None:
    monkeypatch.delenv("CC", raising=False)
    monkeypatch.setattr("node_controller.vllm_process.shutil.which", lambda _cmd: None)

    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    with pytest.raises(RuntimeError, match="No C compiler found in runtime"):
        handle._require_c_compiler()


@pytest.mark.asyncio
async def test_sleep_raises_when_sleep_mode_disabled() -> None:
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    handle._lane_config = LaneConfig(
        model="deepseek-ai/DeepSeek-R1-0528-Qwen3-8B",
        backend="vllm",
        vllm=VllmConfig(enable_sleep_mode=False),
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
        backend="vllm",
        vllm=VllmConfig(enable_sleep_mode=True),
    )
    handle._http = DummyClient()  # type: ignore[assignment]

    assert await handle.is_sleeping() is True
