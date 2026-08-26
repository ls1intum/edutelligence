"""Tests for MetalVllmProcessHandle.

The core concern is the command line: vllm-metal ships a different vLLM
version than the CUDA image, so a flag that is correct on one side can be
rejected on the other. These tests pin exactly which flags may appear.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from logos_worker_node.metal_process import MetalVllmProcessHandle
from logos_worker_node.models import LaneConfig, MetalConfig, OllamaConfig, VllmConfig, VllmEngineConfig

# Flags that exist only in the CUDA build, or that vllm-metal ignores. Emitting
# any of these either aborts argparse or silently misconfigures the lane.
FORBIDDEN_FLAGS = {
    "--tensor-parallel-size",
    "--attention-config.backend",
    "--cuda-graph-sizes",
    "--enable-sleep-mode",
    "--gpu-memory-utilization",
    "--kv-cache-dtype",
    "--cpu-offload-gb",
    "--compilation-config",
    "--load-format",
    "--disable-custom-all-reduce",
}

METAL_VENV_VLLM = Path.home() / ".venv-vllm-metal" / "bin" / "vllm"
HAS_METAL_VENV = METAL_VENV_VLLM.is_file()


def make_handle(metal_config: MetalConfig | None = None) -> MetalVllmProcessHandle:
    return MetalVllmProcessHandle(
        "lane-metal-0",
        11436,
        OllamaConfig(),
        VllmEngineConfig(),
        metal_config=metal_config or MetalConfig(),
    )


def make_lane(**vllm_kwargs) -> LaneConfig:
    return LaneConfig(
        model="mlx-community/Qwen3.8-27B-8bit",
        vllm=True,
        vllm_config=VllmConfig(**vllm_kwargs),
        **{k: v for k, v in vllm_kwargs.pop("_lane", {}).items()} if "_lane" in vllm_kwargs else {},
    )


@pytest.fixture
def handle():
    # Pin the binary so resolution does not depend on the host having a venv.
    with patch.object(MetalVllmProcessHandle, "_resolve_vllm_binary", return_value=["/fake/vllm"]):
        yield make_handle()


class TestBuildCmd:
    def test_emits_no_cuda_only_flags(self, handle) -> None:
        cmd = handle._build_cmd(make_lane())
        leaked = FORBIDDEN_FLAGS.intersection(cmd)
        assert not leaked, f"CUDA-only flags leaked into the Metal command line: {leaked}"

    def test_emits_the_expected_core_flags(self, handle) -> None:
        cmd = handle._build_cmd(make_lane())
        assert cmd[:3] == ["/fake/vllm", "serve", "mlx-community/Qwen3.8-27B-8bit"]
        for flag in ("--host", "--port", "--dtype", "--max-model-len", "--mm-processor-cache-gb"):
            assert flag in cmd
        assert cmd[cmd.index("--port") + 1] == "11436"

    def test_rejects_tensor_parallelism(self, handle) -> None:
        with pytest.raises(RuntimeError, match="tensor_parallel_size"):
            handle._build_cmd(make_lane(tensor_parallel_size=2))

    def test_rejects_a_lane_without_vllm_config(self, handle) -> None:
        lane = LaneConfig(model="m", vllm=True)
        lane.vllm_config = None
        with pytest.raises(RuntimeError, match="Missing vllm_config"):
            handle._build_cmd(lane)

    def test_explicit_max_model_len_wins(self, handle) -> None:
        cmd = handle._build_cmd(make_lane(max_model_len=32768))
        assert cmd[cmd.index("--max-model-len") + 1] == "32768"

    def test_defaults_context_to_auto(self, handle) -> None:
        """The 4096 lane default is a shared-schema sentinel, not a request."""
        cmd = handle._build_cmd(make_lane())
        assert cmd[cmd.index("--max-model-len") + 1] == "auto"

    def test_non_default_lane_context_is_honoured(self, handle) -> None:
        lane = LaneConfig(
            model="mlx-community/Qwen3.8-27B-8bit",
            vllm=True,
            context_length=16384,
            vllm_config=VllmConfig(),
        )
        cmd = handle._build_cmd(lane)
        assert cmd[cmd.index("--max-model-len") + 1] == "16384"

    def test_infers_the_tool_call_parser(self, handle) -> None:
        cmd = handle._build_cmd(make_lane())
        assert "--enable-auto-tool-choice" in cmd
        assert cmd[cmd.index("--tool-call-parser") + 1]

    def test_reasoning_parser_none_suppresses_the_flag(self, handle) -> None:
        cmd = handle._build_cmd(make_lane(reasoning_parser="none"))
        assert "--reasoning-parser" not in cmd

    def test_enforce_eager_is_passed_through(self, handle) -> None:
        assert "--enforce-eager" in handle._build_cmd(make_lane(enforce_eager=True))

    def test_extra_args_are_appended_last(self, handle) -> None:
        cmd = handle._build_cmd(make_lane(extra_args=["--seed", "42"]))
        assert cmd[-2:] == ["--seed", "42"]

    def test_quantization_is_omitted_unless_set(self, handle) -> None:
        """MLX checkpoints declare quantization in config.json; vLLM infers it."""
        assert "--quantization" not in handle._build_cmd(make_lane())
        assert "--quantization" in handle._build_cmd(make_lane(quantization="awq"))


class TestReasoningParserSuppression:
    """Qwen3.5/3.6/3.8 must not get an inferred reasoning parser on Metal.

    Measured against vllm-metal 0.2.0 (vLLM 0.19.1): with
    --reasoning-parser qwen3 the response comes back with content=None AND
    reasoning_content=None while usage still counts the generated tokens —
    the answer is silently parsed away. Without the flag it returns normally.
    """

    @pytest.mark.parametrize(
        "model",
        [
            "mlx-community/Qwen3.8-27B-8bit",
            "mlx-community/Qwen3.5-2B-8bit",
            "mlx-community/Qwen3.6-9B-4bit",
        ],
    )
    def test_no_parser_is_inferred_for_the_affected_families(self, handle, model) -> None:
        lane = LaneConfig(model=model, vllm=True, vllm_config=VllmConfig())
        assert "--reasoning-parser" not in handle._build_cmd(lane)

    def test_an_explicit_parser_still_wins(self, handle) -> None:
        """Suppression applies to guesses, never to an operator's choice."""
        lane = LaneConfig(
            model="mlx-community/Qwen3.8-27B-8bit",
            vllm=True,
            vllm_config=VllmConfig(reasoning_parser="qwen3"),
        )
        cmd = handle._build_cmd(lane)
        assert cmd[cmd.index("--reasoning-parser") + 1] == "qwen3"

    def test_explicit_none_still_suppresses(self, handle) -> None:
        lane = LaneConfig(
            model="mlx-community/Qwen3.8-27B-8bit",
            vllm=True,
            vllm_config=VllmConfig(reasoning_parser="none"),
        )
        assert "--reasoning-parser" not in handle._build_cmd(lane)

    def test_unaffected_families_keep_their_inferred_parser(self, handle) -> None:
        """The suppression must stay narrow, not disable inference wholesale."""
        lane = LaneConfig(model="google/gemma-4-9b-it", vllm=True, vllm_config=VllmConfig())
        cmd = handle._build_cmd(lane)
        assert cmd[cmd.index("--reasoning-parser") + 1] == "gemma4"


class TestBuildEnv:
    def test_sets_no_cuda_or_nccl_variables(self, handle) -> None:
        env = handle._build_env(make_lane())
        polluted = [k for k in env if any(t in k for t in ("CUDA", "NCCL", "FLASHINFER", "TORCHINDUCTOR"))]
        assert not polluted, f"CUDA-side variables leaked into the Metal env: {polluted}"

    def test_maps_metal_knobs_to_env(self, handle) -> None:
        handle._metal_config = MetalConfig(
            memory_fraction=0.85,
            use_paged_attention=True,
            block_size=32,
            multimodal_mode="text-only-compat",
            prefix_cache_fraction=0.25,
        )
        env = handle._build_env(make_lane())
        assert env["VLLM_METAL_MEMORY_FRACTION"] == "0.85"
        assert env["VLLM_METAL_USE_PAGED_ATTENTION"] == "1"
        assert env["VLLM_METAL_BLOCK_SIZE"] == "32"
        assert env["VLLM_METAL_MULTIMODAL_MODE"] == "text-only-compat"
        assert env["VLLM_METAL_PREFIX_CACHE_FRACTION"] == "0.25"

    def test_unset_knobs_emit_nothing(self, handle) -> None:
        """An unset knob must leave vllm-metal's own default alone."""
        env = handle._build_env(make_lane())
        for key in (
            "VLLM_METAL_MEMORY_FRACTION",
            "VLLM_METAL_USE_PAGED_ATTENTION",
            "VLLM_METAL_BLOCK_SIZE",
            "VLLM_METAL_MULTIMODAL_MODE",
        ):
            assert key not in env

    def test_prefix_cache_switch_follows_the_cli_flag(self, handle) -> None:
        assert handle._build_env(make_lane(enable_prefix_caching=True))["VLLM_METAL_PREFIX_CACHE"] == "1"
        assert handle._build_env(make_lane(enable_prefix_caching=False))["VLLM_METAL_PREFIX_CACHE"] == "0"

    def test_model_overrides_beat_worker_wide_ones(self, handle) -> None:
        handle._metal_config = MetalConfig(env_overrides={"VLLM_METAL_DEBUG": "0", "SHARED": "worker"})
        env = handle._build_env(make_lane(env_overrides={"SHARED": "model"}))
        assert env["SHARED"] == "model"
        assert env["VLLM_METAL_DEBUG"] == "0"

    def test_sleep_mode_never_enables_server_dev_mode(self, handle) -> None:
        """The CUDA path couples these; here the sleep endpoints do not exist."""
        env = handle._build_env(make_lane(enable_sleep_mode=True))
        assert "VLLM_SERVER_DEV_MODE" not in env

    def test_server_dev_mode_is_still_honoured_explicitly(self, handle) -> None:
        env = handle._build_env(make_lane(server_dev_mode=True))
        assert env["VLLM_SERVER_DEV_MODE"] == "1"


class TestProcessEnv:
    def test_strips_inherited_cuda_variables(self, handle, monkeypatch) -> None:
        monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0,1")
        monkeypatch.setenv("CUDA_HOME", "/usr/local/cuda")
        monkeypatch.setenv("NCCL_P2P_DISABLE", "1")
        process_env = handle._build_process_env(make_lane(), {}, ["/fake/bin/vllm", "serve"])
        for key in ("CUDA_VISIBLE_DEVICES", "CUDA_HOME", "NCCL_P2P_DISABLE"):
            assert key not in process_env

    def test_prepends_the_venv_bin_directory(self, handle) -> None:
        process_env = handle._build_process_env(make_lane(), {}, ["/fake/bin/vllm", "serve"])
        assert process_env["PATH"].startswith("/fake/bin")


class TestDisabledCudaMachinery:
    def test_preflight_guards_are_noops(self, handle) -> None:
        handle._require_c_compiler()
        handle._require_nvcc(make_lane())

    def test_no_attention_backend_or_cuda_arch(self, handle) -> None:
        assert handle._auto_attention_backend() == ""
        assert handle._detect_cuda_arch() is None

    def test_no_stuck_vram_or_fatal_cuda_state(self, handle) -> None:
        assert handle.has_stuck_vram() is False
        assert handle.has_fatal_cuda_errors is False

    def test_compile_cache_purge_is_a_noop(self, handle) -> None:
        assert handle._purge_compile_caches_if_versions_changed() == []

    @pytest.mark.asyncio
    async def test_sharded_checkpoint_preparation_is_skipped(self, handle) -> None:
        await handle._maybe_prepare_sharded_checkpoint(make_lane())
        assert handle._sharded_model_dir is None

    @pytest.mark.asyncio
    async def test_sleep_and_wake_report_unsupported(self, handle) -> None:
        assert (await handle.sleep())["supported"] is False
        assert (await handle.wake_up())["supported"] is False
        # None means "not applicable" — distinct from False, which means awake.
        assert await handle.is_sleeping() is None


class TestMetalAllocationFailure:
    @pytest.mark.parametrize(
        "line",
        [
            "[metal::malloc] Attempting to allocate 30000000000 bytes",
            "buffer size greater than the maximum allowed buffer size",
            "RuntimeError: Insufficient Memory",
            "failed to allocate MTLBuffer",
        ],
    )
    def test_detects_known_allocation_failures(self, handle, line) -> None:
        handle._recent_logs.append(line)
        assert handle.has_metal_allocation_failure is True

    def test_quiet_logs_are_not_a_failure(self, handle) -> None:
        handle._recent_logs.append("INFO: Application startup complete.")
        assert handle.has_metal_allocation_failure is False

    def test_empty_logs_are_not_a_failure(self, handle) -> None:
        assert handle.has_metal_allocation_failure is False


class TestBinaryResolution:
    def test_prefers_the_configured_metal_binary(self, tmp_path) -> None:
        fake = tmp_path / "vllm"
        fake.write_text("#!/bin/sh\n")
        fake.chmod(0o755)
        handle = make_handle(MetalConfig(vllm_binary=str(fake)))
        assert handle._resolve_vllm_binary("vllm") == [str(fake)]

    def test_lane_level_path_beats_the_worker_default(self, tmp_path) -> None:
        lane_bin = tmp_path / "lane-vllm"
        lane_bin.write_text("#!/bin/sh\n")
        lane_bin.chmod(0o755)
        worker_bin = tmp_path / "worker-vllm"
        worker_bin.write_text("#!/bin/sh\n")
        worker_bin.chmod(0o755)
        handle = make_handle(MetalConfig(vllm_binary=str(worker_bin)))
        assert handle._resolve_vllm_binary(str(lane_bin)) == [str(lane_bin)]

    def test_schema_default_is_not_treated_as_a_path(self, tmp_path) -> None:
        """vllm_config.vllm_binary defaults to the bare string "vllm"."""
        worker_bin = tmp_path / "worker-vllm"
        worker_bin.write_text("#!/bin/sh\n")
        worker_bin.chmod(0o755)
        handle = make_handle(MetalConfig(vllm_binary=str(worker_bin)))
        assert handle._resolve_vllm_binary("vllm") == [str(worker_bin)]


class TestCacheRoot:
    def test_env_override_wins(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setenv("LOGOS_WORKER_CACHE_ROOT", str(tmp_path))
        assert MetalVllmProcessHandle._resolve_persistent_cache_root(OllamaConfig()) == str(tmp_path)

    def test_falls_back_to_a_macos_path_not_the_ollama_one(self, monkeypatch) -> None:
        """The inherited default points into /usr/share/ollama, absent on macOS."""
        monkeypatch.delenv("LOGOS_WORKER_CACHE_ROOT", raising=False)
        root = MetalVllmProcessHandle._resolve_persistent_cache_root(OllamaConfig())
        assert "/usr/share/ollama" not in root
        assert root.startswith(str(Path.home()))

    def test_uses_models_path_when_it_actually_exists(self, monkeypatch, tmp_path) -> None:
        monkeypatch.delenv("LOGOS_WORKER_CACHE_ROOT", raising=False)
        cfg = OllamaConfig(models_path=str(tmp_path))
        assert MetalVllmProcessHandle._resolve_persistent_cache_root(cfg) == str(tmp_path)


@pytest.mark.skipif(not HAS_METAL_VENV, reason="vllm-metal venv not installed on this host")
class TestAgainstRealVllmMetal:
    """Cross-check the generated command against the installed vllm-metal.

    Skipped in CI (Linux). On a Mac with the venv present this is the test that
    catches an upstream flag rename before it reaches a node.
    """

    @staticmethod
    def _supported_flags() -> set[str]:
        import subprocess

        result = subprocess.run(
            [str(METAL_VENV_VLLM), "serve", "--help=all"],
            capture_output=True,
            text=True,
            timeout=300,
        )
        flags: set[str] = set()
        for line in result.stdout.splitlines():
            stripped = line.strip()
            if stripped.startswith("--"):
                flags.add(stripped.split()[0].split("=")[0].rstrip(","))
        return flags

    def test_every_generated_flag_exists(self) -> None:
        supported = self._supported_flags()
        assert supported, "could not read the flag list from vllm serve --help=all"

        handle = make_handle()
        with patch.object(MetalVllmProcessHandle, "_resolve_vllm_binary", return_value=["/fake/vllm"]):
            cmd = handle._build_cmd(make_lane())

        used = {arg for arg in cmd if arg.startswith("--")}
        unknown = used - supported
        assert not unknown, f"flags not accepted by the installed vllm-metal: {sorted(unknown)}"
