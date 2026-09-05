from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from logos_worker_node.models import LaneConfig, OllamaConfig, VllmConfig, VllmEngineConfig
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
    assert resolved == [str(vllm_bin)]


def test_resolve_vllm_binary_honors_absolute_path(tmp_path: Path) -> None:
    explicit = tmp_path / "custom-vllm"
    _make_executable(explicit)

    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    resolved = handle._resolve_vllm_binary(str(explicit))
    assert resolved == [str(explicit)]


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


def test_build_cmd_includes_prompt_tokens_details_by_default(monkeypatch) -> None:
    # vLLM keeps usage.prompt_tokens_details (cached_tokens) off by default;
    # Logos lanes must enable it so consumers see the prefix-cache hit share
    # of local requests the same way they do for cloud providers (#813).
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    # Return a list, like the real _resolve_vllm_binary does: _build_cmd
    # splats the prefix, so a string would expand into a broken command.
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _configured: ["/tmp/vllm"])

    lane = LaneConfig(
        model="google/gemma-4-26B-A4B-it",
        vllm=True,
        vllm_config=VllmConfig(),
    )
    cmd = handle._build_cmd(lane)
    assert cmd[0] == "/tmp/vllm" and cmd[1] == "serve"
    assert cmd.count("--enable-prompt-tokens-details") == 1


def test_build_cmd_omits_prompt_tokens_details_when_disabled(monkeypatch) -> None:
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    # List, not string — see the default test above for why.
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _configured: ["/tmp/vllm"])

    lane = LaneConfig(
        model="google/gemma-4-26B-A4B-it",
        vllm=True,
        vllm_config=VllmConfig(enable_prompt_tokens_details=False),
    )
    cmd = handle._build_cmd(lane)
    assert cmd[0] == "/tmp/vllm" and cmd[1] == "serve"
    assert "--enable-prompt-tokens-details" not in cmd


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


def test_build_cmd_includes_tool_calling_flags_by_default(monkeypatch) -> None:
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _configured: "/tmp/vllm")

    lane = LaneConfig(
        model="google/gemma-4-26B-A4B-it",
        vllm=True,
        vllm_config=VllmConfig(),
    )
    cmd = handle._build_cmd(lane)
    # Default: parser inferred from model name (gemma-4 → gemma4)
    assert "--enable-auto-tool-choice" in cmd
    idx = cmd.index("--tool-call-parser")
    assert cmd[idx + 1] == "gemma4"


def test_build_cmd_includes_explicit_tool_call_parser(monkeypatch) -> None:
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _configured: "/tmp/vllm")

    lane = LaneConfig(
        model="NousResearch/Hermes-3-Llama-3.1-8B",
        vllm=True,
        vllm_config=VllmConfig(tool_call_parser="hermes"),
    )
    cmd = handle._build_cmd(lane)
    assert "--enable-auto-tool-choice" in cmd
    idx = cmd.index("--tool-call-parser")
    assert cmd[idx + 1] == "hermes"


def test_infer_tool_call_parser() -> None:
    from logos_worker_node.vllm_process import _infer_tool_call_parser

    # Google Gemma
    assert _infer_tool_call_parser("google/gemma-4-26B-A4B-it") == "gemma4"
    assert _infer_tool_call_parser("google/functiongemma-270m-it") == "functiongemma"
    # Meta Llama
    assert _infer_tool_call_parser("meta-llama/Llama-3.1-8B-Instruct") == "llama3_json"
    assert _infer_tool_call_parser("meta-llama/Llama-4-Scout-17B-16E-Instruct") == "llama4_pythonic"
    # Mistral
    assert _infer_tool_call_parser("mistralai/Mistral-7B-Instruct-v0.3") == "mistral"
    # DeepSeek (V3.2 > V3.1 > general)
    assert _infer_tool_call_parser("deepseek-ai/DeepSeek-V3-0324") == "deepseek_v3"
    assert _infer_tool_call_parser("deepseek-ai/DeepSeek-R1-0528") == "deepseek_v3"
    assert _infer_tool_call_parser("deepseek-ai/DeepSeek-V3.1") == "deepseek_v31"
    assert _infer_tool_call_parser("deepseek-ai/DeepSeek-V3.2") == "deepseek_v32"
    # IBM Granite
    assert _infer_tool_call_parser("ibm-granite/granite-20b-functioncalling") == "granite-20b-fc"
    assert _infer_tool_call_parser("ibm-granite/granite-4.0-h-small") == "granite4"
    assert _infer_tool_call_parser("ibm-granite/granite-3.1-8b-instruct") == "granite"
    # Zhipu GLM
    assert _infer_tool_call_parser("zai-org/GLM-4.7-Flash") == "glm47"
    assert _infer_tool_call_parser("zai-org/GLM-4.5") == "glm45"
    assert _infer_tool_call_parser("zai-org/GLM-4.6") == "glm45"
    # InternLM
    assert _infer_tool_call_parser("internlm/internlm2_5-7b-chat") == "internlm"
    # AI21 Jamba
    assert _infer_tool_call_parser("ai21labs/AI21-Jamba-1.5-Mini") == "jamba"
    # Alibaba Qwen (coder→qwen3_xml, general→hermes)
    assert _infer_tool_call_parser("Qwen/Qwen3-Coder-480B-A35B-Instruct") == "qwen3_coder"
    assert _infer_tool_call_parser("Qwen/Qwen2.5-Coder-14B-Instruct-AWQ") == "hermes"
    assert _infer_tool_call_parser("Qwen/QwQ-32B") == "hermes"
    # Qwen3 point releases emit the Qwen3-Coder XML dialect, not hermes JSON.
    assert _infer_tool_call_parser("Qwen/Qwen3.8-27B") == "qwen3_coder"
    assert _infer_tool_call_parser("Qwen/Qwen3.6-35B-A3B") == "qwen3_coder"
    assert _infer_tool_call_parser("Qwen/Qwen3.5-122B-A10B") == "qwen3_coder"
    assert _infer_tool_call_parser("RedHatAI/Qwen3.5-122B-A10B-NVFP4") == "qwen3_coder"
    # Dot-free Qwen3 stays on hermes, and Qwen2.5 must not match the dotted rule.
    assert _infer_tool_call_parser("Qwen/Qwen3-32B") == "hermes"
    assert _infer_tool_call_parser("Qwen/Qwen2.5-72B-Instruct") == "hermes"
    # Salesforce xLAM (contains "llama"/"qwen" — must match xlam first)
    assert _infer_tool_call_parser("Salesforce/Llama-xLAM-2-8B-fc-r") == "xlam"
    assert _infer_tool_call_parser("Salesforce/Qwen-xLAM-32B-fc-r") == "xlam"
    # NousResearch Hermes (contains "llama" — must match hermes first)
    assert _infer_tool_call_parser("NousResearch/Hermes-3-Llama-3.1-8B") == "hermes"
    # MiniMax
    assert _infer_tool_call_parser("MiniMaxAi/MiniMax-M2-40B") == "minimax_m2"
    assert _infer_tool_call_parser("MiniMaxAi/MiniMax-M1-40k") == "minimax"
    # Microsoft Phi
    assert _infer_tool_call_parser("microsoft/phi-4-mini") == "phi4_mini_json"
    # Allen AI OLMo
    assert _infer_tool_call_parser("allenai/Olmo-3-7B-Instruct") == "olmo3"
    # Tencent Hunyuan
    assert _infer_tool_call_parser("tencent/Hunyuan-A13B-Instruct") == "hunyuan_a13b"
    # Baidu ERNIE
    assert _infer_tool_call_parser("baidu/ERNIE-4.5-0.3B-Instruct") == "ernie45"
    # Moonshot Kimi
    assert _infer_tool_call_parser("moonshotai/Kimi-K2-Instruct") == "kimi_k2"
    # ByteDance Seed
    assert _infer_tool_call_parser("bytedance/Seed-Oss-Coder") == "seed_oss"
    # StepFun (3.5 before 3)
    assert _infer_tool_call_parser("stepfun/Step-3.5-16B") == "step3p5"
    assert _infer_tool_call_parser("stepfun/Step-3-8B") == "step3"
    # Sber GigaChat
    assert _infer_tool_call_parser("ai-sage/GigaChat3-702B-A36B-preview") == "gigachat3"
    # Meituan LongCat
    assert _infer_tool_call_parser("meituan-longcat/LongCat-Flash-Chat") == "longcat"
    # Xiaomi MIMO
    assert _infer_tool_call_parser("xiaomi/MIMO-7B") == "mimo"
    # OpenAI OSS (gpt-oss → openai parser, NOT hermes)
    assert _infer_tool_call_parser("openai/gpt-oss-120b") == "openai"
    # Unknown model falls back to hermes
    assert _infer_tool_call_parser("some/unknown-model") == "hermes"


def test_build_cmd_omits_tool_calling_when_disabled(monkeypatch) -> None:
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _configured: "/tmp/vllm")

    lane = LaneConfig(
        model="Qwen/Qwen3-Embedding-8B",
        vllm=True,
        vllm_config=VllmConfig(enable_auto_tool_choice=False),
    )
    cmd = handle._build_cmd(lane)
    assert "--enable-auto-tool-choice" not in cmd
    assert "--tool-call-parser" not in cmd


def test_build_env_auto_enables_dev_mode_for_sleep(monkeypatch) -> None:
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig(gpu_devices="all"))
    lane = LaneConfig(
        model="google/gemma-4-26B-A4B-it",
        vllm=True,
        vllm_config=VllmConfig(enable_sleep_mode=True, server_dev_mode=False),
    )
    monkeypatch.delenv("HF_HOME", raising=False)
    env = handle._build_env(lane)
    assert env["VLLM_SERVER_DEV_MODE"] == "1"


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


def test_build_cmd_includes_kv_cache_dtype(monkeypatch) -> None:
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _configured: "/tmp/vllm")

    lane = LaneConfig(
        model="Qwen/Qwen2.5-Coder-7B-Instruct",
        vllm=True,
        vllm_config=VllmConfig(kv_cache_dtype="fp8"),
    )
    cmd = handle._build_cmd(lane)
    idx = cmd.index("--kv-cache-dtype")
    assert cmd[idx + 1] == "fp8"


def test_build_cmd_omits_kv_cache_dtype_when_empty(monkeypatch) -> None:
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _configured: "/tmp/vllm")

    lane = LaneConfig(
        model="Qwen/Qwen2.5-Coder-7B-Instruct",
        vllm=True,
        vllm_config=VllmConfig(),  # kv_cache_dtype defaults to ""
    )
    cmd = handle._build_cmd(lane)
    assert "--kv-cache-dtype" not in cmd


def test_build_cmd_uses_default_chat_template_kwargs_flag(monkeypatch) -> None:
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _configured: "/tmp/vllm")

    lane = LaneConfig(
        model="Qwen/Qwen3.5-9B-Instruct",
        vllm=True,
        vllm_config=VllmConfig(chat_template_kwargs={"enable_thinking": False}),
    )
    cmd = handle._build_cmd(lane)
    idx = cmd.index("--default-chat-template-kwargs")
    assert cmd[idx + 1] == '{"enable_thinking": false}'
    assert "--chat-template-kwargs" not in cmd


# ---------------------------------------------------------------------------
# Custom chat templates — resolved from the persistent template directory
# ---------------------------------------------------------------------------


@pytest.fixture()
def chat_template_dir(monkeypatch, tmp_path: Path) -> Path:
    """Relocate the persistent chat-template directory into a tmp_path."""
    templates = tmp_path / "chat-templates"
    templates.mkdir()
    monkeypatch.setenv("LOGOS_CHAT_TEMPLATE_DIR", str(templates))
    return templates


def _handle_with_stub_binary(monkeypatch) -> VllmProcessHandle:
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _configured: "/tmp/vllm")
    return handle


def test_chat_template_dir_defaults_to_persistent_path(monkeypatch) -> None:
    from logos_worker_node.vllm_process import _chat_template_dir

    monkeypatch.delenv("LOGOS_CHAT_TEMPLATE_DIR", raising=False)
    assert _chat_template_dir() == "/opt/logos-workernode/chat-templates"


def test_build_cmd_resolves_chat_template_name(monkeypatch, chat_template_dir: Path) -> None:
    template = chat_template_dir / "qwen3-tools.jinja"
    template.write_text("{{ messages }}")
    handle = _handle_with_stub_binary(monkeypatch)

    lane = LaneConfig(
        model="Qwen/Qwen3-8B",
        vllm=True,
        vllm_config=VllmConfig(chat_template="qwen3-tools.jinja"),
    )
    cmd = handle._build_cmd(lane)
    idx = cmd.index("--chat-template")
    assert cmd[idx + 1] == str(template.resolve())


def test_build_cmd_resolves_chat_template_in_subdirectory(monkeypatch, chat_template_dir: Path) -> None:
    nested = chat_template_dir / "qwen"
    nested.mkdir()
    template = nested / "tools.jinja"
    template.write_text("{{ messages }}")
    handle = _handle_with_stub_binary(monkeypatch)

    lane = LaneConfig(
        model="Qwen/Qwen3-8B",
        vllm=True,
        vllm_config=VllmConfig(chat_template="qwen/tools.jinja"),
    )
    cmd = handle._build_cmd(lane)
    assert cmd[cmd.index("--chat-template") + 1] == str(template.resolve())


def test_build_cmd_accepts_absolute_path_inside_template_dir(monkeypatch, chat_template_dir: Path) -> None:
    template = chat_template_dir / "abs.jinja"
    template.write_text("{{ messages }}")
    handle = _handle_with_stub_binary(monkeypatch)

    lane = LaneConfig(
        model="Qwen/Qwen3-8B",
        vllm=True,
        vllm_config=VllmConfig(chat_template=str(template)),
    )
    cmd = handle._build_cmd(lane)
    assert cmd[cmd.index("--chat-template") + 1] == str(template.resolve())


def test_build_cmd_omits_chat_template_when_unset(monkeypatch, chat_template_dir: Path) -> None:
    handle = _handle_with_stub_binary(monkeypatch)

    lane = LaneConfig(model="Qwen/Qwen3-8B", vllm=True, vllm_config=VllmConfig())
    assert "--chat-template" not in handle._build_cmd(lane)


def test_build_cmd_rejects_missing_chat_template(monkeypatch, chat_template_dir: Path) -> None:
    """A typo must fail the spawn, never silently fall back to the model default."""
    handle = _handle_with_stub_binary(monkeypatch)

    lane = LaneConfig(
        model="Qwen/Qwen3-8B",
        vllm=True,
        vllm_config=VllmConfig(chat_template="does-not-exist.jinja"),
    )
    with pytest.raises(RuntimeError, match="not found"):
        handle._build_cmd(lane)


def test_build_cmd_rejects_absolute_path_outside_template_dir(monkeypatch, chat_template_dir: Path, tmp_path) -> None:
    outside = tmp_path / "elsewhere.jinja"
    outside.write_text("{{ messages }}")
    handle = _handle_with_stub_binary(monkeypatch)

    lane = LaneConfig(
        model="Qwen/Qwen3-8B",
        vllm=True,
        vllm_config=VllmConfig(chat_template=str(outside)),
    )
    with pytest.raises(RuntimeError, match="outside the persistent chat-template directory"):
        handle._build_cmd(lane)


def test_build_cmd_rejects_symlink_escaping_template_dir(monkeypatch, chat_template_dir: Path, tmp_path) -> None:
    """Symlinks are followed — a template must not live on ephemeral storage."""
    outside = tmp_path / "ephemeral.jinja"
    outside.write_text("{{ messages }}")
    (chat_template_dir / "linked.jinja").symlink_to(outside)
    handle = _handle_with_stub_binary(monkeypatch)

    lane = LaneConfig(
        model="Qwen/Qwen3-8B",
        vllm=True,
        vllm_config=VllmConfig(chat_template="linked.jinja"),
    )
    with pytest.raises(RuntimeError, match="outside the persistent chat-template directory"):
        handle._build_cmd(lane)


def test_vllm_config_rejects_path_traversal() -> None:
    with pytest.raises(ValueError, match="Path traversal"):
        VllmConfig(chat_template="../../etc/passwd")


def test_vllm_config_strips_chat_template_whitespace() -> None:
    assert VllmConfig(chat_template="  tools.jinja  ").chat_template == "tools.jinja"
    assert VllmConfig(chat_template="   ").chat_template == ""


def test_build_cmd_sets_compilation_cache_dir(monkeypatch) -> None:
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig(models_path="/data/models"))
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _configured: "/tmp/vllm")

    lane = LaneConfig(
        model="Qwen/Qwen3.5-9B-Instruct",
        vllm=True,
        vllm_config=VllmConfig(),
    )
    cmd = handle._build_cmd(lane)
    idx = cmd.index("--compilation-config")
    # The cache dir must be model-specific: with an explicit cache_dir vLLM
    # skips its hash-keyed subdirectory, so a shared path would make every
    # lane replay the first-compiled model's artifacts and crash on startup.
    assert cmd[idx + 1] == '{"cache_dir": "/data/models/.cache/vllm/lanes/Qwen__Qwen3.5-9B-Instruct"}'


def test_build_cmd_respects_explicit_compilation_config(monkeypatch) -> None:
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig(models_path="/data/models"))
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _configured: "/tmp/vllm")

    lane = LaneConfig(
        model="Qwen/Qwen3.5-9B-Instruct",
        vllm=True,
        vllm_config=VllmConfig(extra_args=["-cc", '{"mode": 3}']),
    )
    cmd = handle._build_cmd(lane)
    assert "--compilation-config" not in cmd


def test_build_cmd_omits_gpu_memory_utilization_with_kv_cache(monkeypatch) -> None:
    """When kv_cache_memory_bytes is set, --gpu-memory-utilization must NOT be
    injected.  kv_cache_memory_bytes controls the KV pool size directly; adding
    gpu_memory_utilization=0.1 would cap total VRAM to 10% and prevent model
    weights from loading."""
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _configured: "/tmp/vllm")

    lane = LaneConfig(
        model="Qwen/Qwen2.5-Coder-7B-Instruct",
        vllm=True,
        vllm_config=VllmConfig(kv_cache_memory_bytes="4G"),
    )
    cmd = handle._build_cmd(lane)
    assert "--gpu-memory-utilization" not in cmd


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


def test_build_cmd_omits_default_lane_context_cap_for_vllm(monkeypatch) -> None:
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _configured: "/tmp/vllm")

    lane = LaneConfig(
        model="Qwen/Qwen2.5-Coder-7B-Instruct",
        vllm=True,
        context_length=4096,
        vllm_config=VllmConfig(max_model_len=0),
    )
    cmd = handle._build_cmd(lane)
    # The 4096 sentinel must not be passed through as a real cap; with nothing
    # explicit the lane asks vLLM to size the window itself.
    idx = cmd.index("--max-model-len")
    assert cmd[idx + 1] == "auto"


def test_build_cmd_keeps_explicit_lane_context_cap_for_vllm(monkeypatch) -> None:
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _configured: "/tmp/vllm")

    lane = LaneConfig(
        model="Qwen/Qwen2.5-Coder-7B-Instruct",
        vllm=True,
        context_length=8192,
        vllm_config=VllmConfig(max_model_len=0),
    )
    cmd = handle._build_cmd(lane)
    idx = cmd.index("--max-model-len")
    assert cmd[idx + 1] == "8192"


def test_build_cmd_prefers_auto_over_calibrated_max_model_len(monkeypatch) -> None:
    """A recorded calibration_max_model_len does not become the start flag.

    That value is only valid for the KV budget it was measured at, so reusing
    it on a lane with a different budget serves the wrong window in either
    direction. "auto" is resolved against the budget the lane actually gets.
    """
    from logos_worker_node.model_profiles import ModelProfileRecord, ModelProfileRegistry

    registry = ModelProfileRegistry()
    registry._profiles["google/gemma-3-12b-it"] = ModelProfileRecord(
        engine="vllm",
        calibration_max_model_len=115632,
    )

    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig(), model_profiles=registry)
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _configured: "/tmp/vllm")

    lane = LaneConfig(
        model="google/gemma-3-12b-it",
        vllm=True,
        # Default context_length (4096 sentinel) and no explicit vc override.
        vllm_config=VllmConfig(max_model_len=0),
    )
    cmd = handle._build_cmd(lane)
    idx = cmd.index("--max-model-len")
    # "auto" wins over the calibrated value: that value is only valid for the
    # KV budget it was measured at, while "auto" is resolved against the budget
    # this lane actually gets.
    assert cmd[idx + 1] == "auto"


def test_build_cmd_prefers_explicit_max_model_len_over_calibrated(monkeypatch) -> None:
    """Explicit vc.max_model_len wins over the calibrated value."""
    from logos_worker_node.model_profiles import ModelProfileRecord, ModelProfileRegistry

    registry = ModelProfileRegistry()
    registry._profiles["m"] = ModelProfileRecord(engine="vllm", calibration_max_model_len=115632)

    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig(), model_profiles=registry)
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _configured: "/tmp/vllm")

    lane = LaneConfig(model="m", vllm=True, vllm_config=VllmConfig(max_model_len=65536))
    cmd = handle._build_cmd(lane)
    idx = cmd.index("--max-model-len")
    assert cmd[idx + 1] == "65536"


def test_build_cmd_prefers_explicit_lane_context_over_calibrated(monkeypatch) -> None:
    """Explicit lane_config.context_length wins over the calibrated value."""
    from logos_worker_node.model_profiles import ModelProfileRecord, ModelProfileRegistry

    registry = ModelProfileRegistry()
    registry._profiles["m"] = ModelProfileRecord(engine="vllm", calibration_max_model_len=115632)

    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig(), model_profiles=registry)
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _configured: "/tmp/vllm")

    lane = LaneConfig(model="m", vllm=True, context_length=8192, vllm_config=VllmConfig(max_model_len=0))
    cmd = handle._build_cmd(lane)
    idx = cmd.index("--max-model-len")
    assert cmd[idx + 1] == "8192"


def test_build_cmd_uses_auto_max_model_len_when_no_profile(monkeypatch) -> None:
    """Without a profile or explicit override, vLLM sizes the window itself."""
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _configured: "/tmp/vllm")

    lane = LaneConfig(model="unknown/model", vllm=True, vllm_config=VllmConfig(max_model_len=0))
    cmd = handle._build_cmd(lane)
    idx = cmd.index("--max-model-len")
    assert cmd[idx + 1] == "auto"


def test_build_cmd_uses_calibrated_max_num_seqs_when_nothing_explicit(monkeypatch) -> None:
    """Lane spawn reuses calibration's auto-detected --max-num-seqs cap for
    hybrid Mamba/SSM models — without it the lane reverts to vLLM's default
    1024 and aborts CUDA-graph capture at startup."""
    from logos_worker_node.model_profiles import ModelProfileRecord, ModelProfileRegistry

    registry = ModelProfileRegistry()
    registry._profiles["RedHatAI/Qwen3-Coder-Next-NVFP4"] = ModelProfileRecord(
        engine="vllm",
        calibration_max_num_seqs=160,
    )

    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig(), model_profiles=registry)
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _configured: "/tmp/vllm")

    lane = LaneConfig(model="RedHatAI/Qwen3-Coder-Next-NVFP4", vllm=True, vllm_config=VllmConfig(max_num_seqs=0))
    cmd = handle._build_cmd(lane)
    idx = cmd.index("--max-num-seqs")
    assert cmd[idx + 1] == "160"


def test_build_cmd_prefers_explicit_max_num_seqs_over_calibrated(monkeypatch) -> None:
    """Explicit vc.max_num_seqs wins over the calibrated value."""
    from logos_worker_node.model_profiles import ModelProfileRecord, ModelProfileRegistry

    registry = ModelProfileRegistry()
    registry._profiles["m"] = ModelProfileRecord(engine="vllm", calibration_max_num_seqs=160)

    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig(), model_profiles=registry)
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _configured: "/tmp/vllm")

    lane = LaneConfig(model="m", vllm=True, vllm_config=VllmConfig(max_num_seqs=64))
    cmd = handle._build_cmd(lane)
    idx = cmd.index("--max-num-seqs")
    assert cmd[idx + 1] == "64"


def test_build_cmd_omits_max_num_seqs_when_no_profile(monkeypatch) -> None:
    """Without a profile or explicit override, vLLM picks its own default."""
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _configured: "/tmp/vllm")

    lane = LaneConfig(model="unknown/model", vllm=True, vllm_config=VllmConfig(max_num_seqs=0))
    cmd = handle._build_cmd(lane)
    assert "--max-num-seqs" not in cmd


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

    # chmod-based read-only doesn't work when tests run as root (e.g. on
    # self-hosted runners) — root bypasses DAC. Mock os.access so the
    # preferred path looks unwritable regardless of UID.
    preferred = str(models_path / ".hf_cache")
    real_access = os.access

    def fake_access(path, mode):
        if str(path) == preferred:
            return False
        return real_access(path, mode)

    monkeypatch.setattr("logos_worker_node.vllm_process.os.access", fake_access)
    monkeypatch.delenv("HF_HOME", raising=False)
    env = handle._build_env(lane)

    # Should fall back to user cache instead of unwritable models path.
    assert env["HF_HOME"].endswith(".cache/huggingface")


def test_build_env_sets_optional_vllm_env_flags(monkeypatch) -> None:
    # nccl_p2p_available=False (default) → NCCL_P2P_DISABLE=1 globally
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig(gpu_devices="all"))
    lane = LaneConfig(
        model="deepseek-ai/DeepSeek-R1-0528-Qwen3-8B",
        vllm=True,
        vllm_config=VllmConfig(server_dev_mode=True),
    )

    monkeypatch.delenv("HF_HOME", raising=False)
    env = handle._build_env(lane)
    assert env["VLLM_SERVER_DEV_MODE"] == "1"
    assert env["NCCL_P2P_DISABLE"] == "1"


def test_build_env_sets_flashinfer_logging(monkeypatch) -> None:
    handle = VllmProcessHandle(
        "lane-test",
        19000,
        OllamaConfig(gpu_devices="all"),
        VllmEngineConfig(flashinfer_loglevel=3, flashinfer_logdest="stderr"),
    )
    lane = LaneConfig(
        model="Qwen/Qwen2.5-Coder-7B-Instruct",
        vllm=True,
        vllm_config=VllmConfig(),
    )

    monkeypatch.delenv("HF_HOME", raising=False)
    env = handle._build_env(lane)
    assert env["FLASHINFER_LOGLEVEL"] == "3"
    assert env["FLASHINFER_LOGDEST"] == "stderr"


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
    # A successful round-trip resets the wedge counter even if it was
    # previously elevated.
    assert handle.consecutive_liveness_failures == 0


@pytest.mark.asyncio
async def test_is_sleeping_tracks_transport_failures() -> None:
    import httpx as _httpx

    class HangingClient:
        async def get(self, _url: str, timeout: float = 5.0):  # noqa: ARG002
            raise _httpx.ReadTimeout("engine wedged")

    class HealthyResponse:
        status_code = 200

        @staticmethod
        def json() -> dict:
            return {"is_sleeping": False}

    class HealthyClient:
        async def get(self, _url: str, timeout: float = 5.0):  # noqa: ARG002
            return HealthyResponse()

    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    handle._lane_config = LaneConfig(
        model="deepseek-ai/DeepSeek-R1-0528-Qwen3-8B",
        vllm=True,
        vllm_config=VllmConfig(enable_sleep_mode=True),
    )

    handle._http = HangingClient()  # type: ignore[assignment]
    assert await handle.is_sleeping() is None
    assert await handle.is_sleeping() is None
    assert await handle.is_sleeping() is None
    assert handle.consecutive_liveness_failures == 3

    # A subsequent healthy probe must reset the counter; the lane is no
    # longer wedged so stuck detection must rearm cleanly.
    handle._http = HealthyClient()  # type: ignore[assignment]
    assert await handle.is_sleeping() is False
    assert handle.consecutive_liveness_failures == 0


@pytest.mark.asyncio
async def test_wake_up_uses_extended_timeout_and_resets_mm_cache() -> None:
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
        # Default mm_processor_cache_gb=4.0 means the workaround fires.
        vllm_config=VllmConfig(enable_sleep_mode=True),
    )
    client = DummyClient()
    handle._http = client  # type: ignore[assignment]

    assert await handle.wake_up() == {"ok": True}
    # /wake_up keeps its extended timeout; /reset_mm_cache rides after to
    # work around the upstream P0/P1 sender/receiver cache desync.
    assert client.calls == [
        ("http://127.0.0.1:19000/wake_up", 120.0),
        ("http://127.0.0.1:19000/reset_mm_cache", 10.0),
    ]


@pytest.mark.asyncio
async def test_wake_up_skips_mm_cache_reset_when_disabled() -> None:
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
        vllm_config=VllmConfig(
            enable_sleep_mode=True,
            mm_processor_cache_gb=0.0,  # IPC mm cache disabled — no desync to fix.
        ),
    )
    client = DummyClient()
    handle._http = client  # type: ignore[assignment]

    assert await handle.wake_up() == {"ok": True}
    assert client.calls == [("http://127.0.0.1:19000/wake_up", 120.0)]


@pytest.mark.asyncio
async def test_wake_up_swallows_mm_cache_reset_errors() -> None:
    class WakeResponse:
        status_code = 200
        content = b"{}"

        @staticmethod
        def json() -> dict:
            return {"ok": True}

    class DummyClient:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def post(self, url: str, timeout: float = 0.0):  # noqa: ARG002
            self.calls.append(url)
            if url.endswith("/reset_mm_cache"):
                import httpx

                raise httpx.ConnectTimeout("boom")
            return WakeResponse()

    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    handle._lane_config = LaneConfig(
        model="Qwen/Qwen2.5-Coder-7B-Instruct",
        vllm=True,
        vllm_config=VllmConfig(enable_sleep_mode=True),
    )
    handle._http = DummyClient()  # type: ignore[assignment]

    # Reset failure must not turn a successful wake into an error;
    # the worst case is the next image request 500s and surfaces
    # the upstream bug — same outcome as without the workaround.
    assert await handle.wake_up() == {"ok": True}


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


@pytest.mark.asyncio
async def test_get_backend_metrics_parses_vllm_0_20_metric_names() -> None:
    """vLLM 0.20 renamed gpu_cache_usage_perc → kv_cache_usage_perc and replaced
    the prefix_cache_hit_rate gauge with two counters."""

    class DummyResponse:
        status_code = 200
        text = """
# HELP ignored ignored
vllm:num_requests_waiting{model_name="Qwen"} 0
vllm:num_requests_running{model_name="Qwen"} 1
vllm:kv_cache_usage_perc{model_name="Qwen"} 0.08
vllm:gpu_prefix_cache_queries{model_name="Qwen"} 100
vllm:gpu_prefix_cache_hits{model_name="Qwen"} 51
vllm:prompt_tokens_total{model_name="Qwen"} 512
vllm:generation_tokens_total{model_name="Qwen"} 1024
vllm:time_to_first_token_seconds_bucket{model_name="Qwen",le="1.0"} 9
vllm:time_to_first_token_seconds_bucket{model_name="Qwen",le="+Inf"} 10
"""

    class DummyClient:
        async def get(self, _url: str, timeout: float = 5.0):  # noqa: ARG002
            return DummyResponse()

    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    handle._http = DummyClient()  # type: ignore[assignment]

    metrics = await handle.get_backend_metrics()
    assert metrics["queue_waiting"] == 0.0
    assert metrics["requests_running"] == 1.0
    assert metrics["gpu_cache_usage_percent"] == pytest.approx(8.0)
    assert metrics["prefix_cache_hit_rate"] == pytest.approx(0.51)
    assert metrics["prompt_tokens_total"] == 512.0
    assert metrics["generation_tokens_total"] == 1024.0
    assert metrics["ttft_histogram"]["1.0"] == 9.0
    assert metrics["ttft_histogram"]["+Inf"] == 10.0


@pytest.mark.asyncio
async def test_get_backend_metrics_prefix_hit_counter_total_suffix() -> None:
    """Accept the _total counter suffix variant used in some vLLM builds."""

    class DummyResponse:
        status_code = 200
        text = """
vllm:num_requests_waiting{model_name="m"} 0
vllm:num_requests_running{model_name="m"} 2
vllm:kv_cache_usage_perc{model_name="m"} 0.5
vllm:gpu_prefix_cache_queries_total{model_name="m"} 200
vllm:gpu_prefix_cache_hits_total{model_name="m"} 100
"""

    class DummyClient:
        async def get(self, _url: str, timeout: float = 5.0):  # noqa: ARG002
            return DummyResponse()

    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    handle._http = DummyClient()  # type: ignore[assignment]

    metrics = await handle.get_backend_metrics()
    assert metrics["gpu_cache_usage_percent"] == pytest.approx(50.0)
    assert metrics["prefix_cache_hit_rate"] == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_get_backend_metrics_prefix_cache_no_gpu_prefix() -> None:
    """vLLM 0.20+ in some builds emits prefix_cache_{queries,hits}_total
    without the gpu_ prefix; parser must fold those into the hit-rate too.
    Also: external_prefix_cache_* and mm_cache_* must NOT be folded in."""

    class DummyResponse:
        status_code = 200
        text = """
vllm:num_requests_running{engine="0",model_name="gpt"} 4
vllm:kv_cache_usage_perc{engine="0",model_name="gpt"} 0.13
vllm:prefix_cache_queries_total{engine="0",model_name="gpt"} 131894.0
vllm:prefix_cache_hits_total{engine="0",model_name="gpt"} 65712.0
vllm:external_prefix_cache_queries_total{engine="0",model_name="gpt"} 0.0
vllm:external_prefix_cache_hits_total{engine="0",model_name="gpt"} 0.0
vllm:mm_cache_queries_total{engine="0",model_name="gpt"} 0.0
vllm:mm_cache_hits_total{engine="0",model_name="gpt"} 0.0
"""

    class DummyClient:
        async def get(self, _url: str, timeout: float = 5.0):  # noqa: ARG002
            return DummyResponse()

    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    handle._http = DummyClient()  # type: ignore[assignment]

    metrics = await handle.get_backend_metrics()
    assert metrics["gpu_cache_usage_percent"] == pytest.approx(13.0)
    assert metrics["prefix_cache_hit_rate"] == pytest.approx(65712 / 131894)


@pytest.mark.asyncio
async def test_get_backend_metrics_legacy_gauge_takes_priority_over_counters() -> None:
    """When both the legacy gauge and counters are present, the gauge wins."""

    class DummyResponse:
        status_code = 200
        text = """
vllm:num_requests_running{model_name="m"} 1
vllm:prefix_cache_hit_rate{model_name="m"} 0.75
vllm:gpu_prefix_cache_queries{model_name="m"} 100
vllm:gpu_prefix_cache_hits{model_name="m"} 10
"""

    class DummyClient:
        async def get(self, _url: str, timeout: float = 5.0):  # noqa: ARG002
            return DummyResponse()

    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    handle._http = DummyClient()  # type: ignore[assignment]

    metrics = await handle.get_backend_metrics()
    # Legacy gauge (0.75) must win over counter-derived rate (0.1).
    assert metrics["prefix_cache_hit_rate"] == pytest.approx(0.75)


@pytest.mark.asyncio
async def test_get_backend_metrics_parses_spec_decode_counters() -> None:
    """MTP/speculative decoding: acceptance rate from draft/accepted counters."""

    class DummyResponse:
        status_code = 200
        text = """
vllm:num_requests_running{model_name="m"} 1
vllm:kv_cache_usage_perc{model_name="m"} 0.5
vllm:spec_decode_num_drafts_total{model_name="m"} 300
vllm:spec_decode_num_draft_tokens_total{model_name="m"} 1000
vllm:spec_decode_num_accepted_tokens_total{model_name="m"} 620
"""

    class DummyClient:
        async def get(self, _url: str, timeout: float = 5.0):  # noqa: ARG002
            return DummyResponse()

    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    handle._http = DummyClient()  # type: ignore[assignment]

    metrics = await handle.get_backend_metrics()
    assert metrics["mtp_acceptance_rate"] == pytest.approx(0.62)
    # Cumulative counters are exposed for token-weighted aggregation upstream.
    assert metrics["mtp_draft_tokens_total"] == pytest.approx(1000)
    assert metrics["mtp_accepted_tokens_total"] == pytest.approx(620)
    # No prefix-cache counters in this scrape.
    assert metrics["prefix_cache_hit_rate"] is None


@pytest.mark.asyncio
async def test_get_backend_metrics_spec_decode_counter_unsuffixed_names() -> None:
    """Accept the counter names without the _total suffix variant."""

    class DummyResponse:
        status_code = 200
        text = """
vllm:num_requests_running{model_name="m"} 1
vllm:spec_decode_num_draft_tokens{model_name="m"} 200
vllm:spec_decode_num_accepted_tokens{model_name="m"} 90
"""

    class DummyClient:
        async def get(self, _url: str, timeout: float = 5.0):  # noqa: ARG002
            return DummyResponse()

    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    handle._http = DummyClient()  # type: ignore[assignment]

    metrics = await handle.get_backend_metrics()
    assert metrics["mtp_acceptance_rate"] == pytest.approx(0.45)
    assert metrics["mtp_draft_tokens_total"] == pytest.approx(200)
    assert metrics["mtp_accepted_tokens_total"] == pytest.approx(90)


@pytest.mark.asyncio
async def test_get_backend_metrics_without_spec_decode_counters_reports_none() -> None:
    """Lanes without --speculative-config expose no spec_decode_* counters."""

    class DummyResponse:
        status_code = 200
        text = """
vllm:num_requests_running{model_name="m"} 1
vllm:kv_cache_usage_perc{model_name="m"} 0.5
vllm:gpu_prefix_cache_queries{model_name="m"} 100
vllm:gpu_prefix_cache_hits{model_name="m"} 10
"""

    class DummyClient:
        async def get(self, _url: str, timeout: float = 5.0):  # noqa: ARG002
            return DummyResponse()

    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    handle._http = DummyClient()  # type: ignore[assignment]

    metrics = await handle.get_backend_metrics()
    assert metrics["mtp_acceptance_rate"] is None
    assert metrics["mtp_draft_tokens_total"] is None
    assert metrics["mtp_accepted_tokens_total"] is None
    assert metrics["prefix_cache_hit_rate"] == pytest.approx(0.1)


@pytest.mark.asyncio
async def test_get_backend_metrics_emits_prefill_delta_fields() -> None:
    """last_prefill_s is TTFT − TPOT (genuine prefill-only, not raw TTFT).

    Both cumulative counter pairs must show a positive delta for an observation
    to be emitted; the third poll (no new completions) must produce None.
    """

    def _make_response(
        ttft_sum: float,
        ttft_count: float,
        tpot_sum: float,
        tpot_count: float,
        prompt_tokens: float,
    ) -> object:
        class DummyResponse:
            status_code = 200
            text = (
                f'vllm:time_to_first_token_seconds_sum{{model_name="m"}} {ttft_sum}\n'
                f'vllm:time_to_first_token_seconds_count{{model_name="m"}} {ttft_count}\n'
                f'vllm:time_per_output_token_seconds_sum{{model_name="m"}} {tpot_sum}\n'
                f'vllm:time_per_output_token_seconds_count{{model_name="m"}} {tpot_count}\n'
                f'vllm:prompt_tokens_total{{model_name="m"}} {prompt_tokens}\n'
                f'vllm:num_requests_running{{model_name="m"}} 1\n'
            )

        return DummyResponse()

    responses: list[object] = []

    class DummyClient:
        async def get(self, _url: str, timeout: float = 5.0):  # noqa: ARG002
            return responses.pop(0)

    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    handle._http = DummyClient()  # type: ignore[assignment]

    # First poll: 2 requests, avg_ttft=5.0s, avg_tpot=0.1s → prefill=4.9s, 500 tok.
    responses.append(_make_response(ttft_sum=10.0, ttft_count=2.0, tpot_sum=2.0, tpot_count=20.0, prompt_tokens=1000.0))
    m1 = await handle.get_backend_metrics()
    assert m1["last_prefill_s"] == pytest.approx(4.9)  # 5.0 - 0.1
    assert m1["last_prefill_tokens"] == pytest.approx(500.0)  # 1000 / 2

    # Second poll: +1 request, avg_ttft=5.0s, avg_tpot=0.1s → prefill=4.9s, 400 tok.
    responses.append(_make_response(ttft_sum=15.0, ttft_count=3.0, tpot_sum=3.0, tpot_count=30.0, prompt_tokens=1400.0))
    m2 = await handle.get_backend_metrics()
    assert m2["last_prefill_s"] == pytest.approx(4.9)  # avg_ttft=5.0 - avg_tpot=0.1
    assert m2["last_prefill_tokens"] == pytest.approx(400.0)  # 400 / 1

    # Third poll: no new completions → delta_count == 0, both fields stay None.
    responses.append(_make_response(ttft_sum=15.0, ttft_count=3.0, tpot_sum=3.0, tpot_count=30.0, prompt_tokens=1400.0))
    m3 = await handle.get_backend_metrics()
    assert m3["last_prefill_s"] is None
    assert m3["last_prefill_tokens"] is None


def test_build_env_injects_nccl_safety_for_tp_greater_than_1(monkeypatch) -> None:
    handle = VllmProcessHandle(
        "lane-test",
        19000,
        OllamaConfig(gpu_devices="all"),
        VllmEngineConfig(nccl_debug="INFO", nccl_debug_subsys="INIT,COLL,GRAPH"),
    )
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
    assert env["NCCL_DEBUG"] == "INFO"
    assert env["NCCL_DEBUG_SUBSYS"] == "INIT,COLL,GRAPH"
    # Transport knobs must NOT be set (NCCL auto-tunes based on topology)
    assert "NCCL_P2P_LEVEL" not in env
    assert "NCCL_BUFFSIZE" not in env
    assert "NCCL_SHM_USE_CUDA_MEMCPY" not in env
    assert "NCCL_NET_GDR_LEVEL" not in env


def test_build_env_no_nccl_safety_for_tp_1(monkeypatch) -> None:
    handle = VllmProcessHandle(
        "lane-test",
        19000,
        OllamaConfig(gpu_devices="all"),
        VllmEngineConfig(nccl_debug="INFO", nccl_debug_subsys="INIT,COLL,GRAPH"),
    )
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
    assert "NCCL_DEBUG" not in env
    assert "NCCL_DEBUG_SUBSYS" not in env


def test_build_env_nccl_p2p_disabled_by_default(monkeypatch) -> None:
    """NCCL P2P is disabled by default (nccl_p2p_available=False) for all lanes."""
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig(gpu_devices="all"))
    lane = LaneConfig(
        model="deepseek-ai/DeepSeek-R1-0528-Qwen3-8B",
        vllm=True,
        vllm_config=VllmConfig(tensor_parallel_size=2),
    )
    monkeypatch.delenv("HF_HOME", raising=False)
    env = handle._build_env(lane)
    assert env["NCCL_P2P_DISABLE"] == "1"


def test_build_env_nccl_p2p_not_disabled_when_available(monkeypatch) -> None:
    """When nccl_p2p_available=True, NCCL_P2P_DISABLE should NOT be set."""
    handle = VllmProcessHandle(
        "lane-test",
        19000,
        OllamaConfig(gpu_devices="all"),
        VllmEngineConfig(nccl_p2p_available=True),
    )
    lane = LaneConfig(
        model="deepseek-ai/DeepSeek-R1-0528-Qwen3-8B",
        vllm=True,
        vllm_config=VllmConfig(tensor_parallel_size=2),
    )
    monkeypatch.delenv("HF_HOME", raising=False)
    env = handle._build_env(lane)
    assert "NCCL_P2P_DISABLE" not in env


def test_build_process_env_scrubs_inherited_distributed_vars_for_all_gpus(
    monkeypatch,
) -> None:
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


def test_build_process_env_prepends_nvidia_pip_cuda_lib_dirs(monkeypatch, tmp_path: Path) -> None:
    """LD_LIBRARY_PATH should include nvidia pip-package lib dirs so PyTorch
    cu128 can find CUDA 12 shared libraries (libcudart.so.12, libcublasLt.so.12)."""
    import logos_worker_node.vllm_process as vp

    # Build a fake site-packages tree with nvidia package lib dirs
    site_packages = tmp_path / "lib" / "python3.13" / "site-packages"
    for pkg in ("cublas", "cuda_runtime", "cudnn"):
        (site_packages / "nvidia" / pkg / "lib").mkdir(parents=True)
    (site_packages / "torch" / "lib").mkdir(parents=True)

    # Patch sysconfig to return our fake site-packages and reset cache
    monkeypatch.setattr("sysconfig.get_path", lambda _key: str(site_packages))
    old_cache = vp._pip_cuda_lib_dirs
    vp._pip_cuda_lib_dirs = None

    try:
        handle = VllmProcessHandle("lane-test", 19000, OllamaConfig(gpu_devices="all"))
        lane = LaneConfig(
            model="Qwen/Qwen2.5-0.5B-Instruct",
            vllm=True,
            vllm_config=VllmConfig(),
        )
        monkeypatch.setenv("PATH", "/usr/bin")
        monkeypatch.setenv("LD_LIBRARY_PATH", "/usr/local/cuda/lib64")
        monkeypatch.delenv("HF_HOME", raising=False)

        env = handle._build_env(lane)
        process_env = handle._build_process_env(lane, env, ["/tmp/vllm", "serve"])

        ld_path = process_env["LD_LIBRARY_PATH"]
        # All three nvidia lib dirs and torch/lib should be prepended
        for pkg in ("cuda_runtime", "cublas", "cudnn"):
            assert str(site_packages / "nvidia" / pkg / "lib") in ld_path
        assert str(site_packages / "torch" / "lib") in ld_path
        # Original LD_LIBRARY_PATH should be preserved at the end
        assert ld_path.endswith("/usr/local/cuda/lib64")
    finally:
        vp._pip_cuda_lib_dirs = old_cache


def test_build_process_env_no_ld_change_without_nvidia_dirs(monkeypatch, tmp_path: Path) -> None:
    """When no nvidia pip packages exist, LD_LIBRARY_PATH should be unchanged."""
    import logos_worker_node.vllm_process as vp

    site_packages = tmp_path / "lib" / "python3.13" / "site-packages"
    site_packages.mkdir(parents=True)

    monkeypatch.setattr("sysconfig.get_path", lambda _key: str(site_packages))
    old_cache = vp._pip_cuda_lib_dirs
    vp._pip_cuda_lib_dirs = None

    try:
        handle = VllmProcessHandle("lane-test", 19000, OllamaConfig(gpu_devices="all"))
        lane = LaneConfig(
            model="Qwen/Qwen2.5-0.5B-Instruct",
            vllm=True,
            vllm_config=VllmConfig(),
        )
        monkeypatch.setenv("PATH", "/usr/bin")
        monkeypatch.setenv("LD_LIBRARY_PATH", "/usr/local/cuda/lib64")
        monkeypatch.delenv("HF_HOME", raising=False)

        env = handle._build_env(lane)
        process_env = handle._build_process_env(lane, env, ["/tmp/vllm", "serve"])

        assert process_env["LD_LIBRARY_PATH"] == "/usr/local/cuda/lib64"
    finally:
        vp._pip_cuda_lib_dirs = old_cache


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
    monkeypatch.setattr(handle, "_discover_child_pids", lambda _pid: asyncio.sleep(0, result=set()))

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
        model="test-model",
        vllm=True,
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
        model="test-model",
        vllm=True,
        vllm_config=VllmConfig(cuda_graph_sizes="1,2,4,8", enforce_eager=True),
    )
    cmd = handle._build_cmd(lc)
    assert "--cuda-graph-sizes" not in cmd


def test_build_cmd_includes_cpu_offload(monkeypatch):
    """--cpu-offload-gb should appear when cpu_offload_gb > 0."""
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _c: "/tmp/vllm")
    lc = LaneConfig(
        model="test-model",
        vllm=True,
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
        model="test-model",
        vllm=True,
        vllm_config=VllmConfig(cpu_offload_gb=0.0),
    )
    cmd = handle._build_cmd(lc)
    assert "--cpu-offload-gb" not in cmd


def test_enforce_eager_off_by_default(monkeypatch):
    """enforce_eager defaults to False so vLLM starts WITHOUT --enforce-eager
    (CUDA graph capture is enabled by default; opt in to eager mode per-lane)."""
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
    lc = LaneConfig(
        model="test-model",
        vllm=True,
        vllm_config=VllmConfig(attention_backend="TRITON_ATTN"),
    )
    cmd = handle._build_cmd(lc)
    assert "--attention-config.backend" in cmd
    idx = cmd.index("--attention-config.backend")
    assert cmd[idx + 1] == "TRITON_ATTN"


def test_auto_attention_backend_pre_ampere(monkeypatch):
    """Pre-Ampere GPU (compute < 8.0) should auto-select TRITON_ATTN."""
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    monkeypatch.setattr(handle, "_detect_cuda_arch", lambda: "7.5")
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _c: "/tmp/vllm")
    lc = LaneConfig(model="test-model", vllm=True, vllm_config=VllmConfig())
    cmd = handle._build_cmd(lc)
    assert "--attention-config.backend" in cmd
    idx = cmd.index("--attention-config.backend")
    assert cmd[idx + 1] == "TRITON_ATTN"


def test_auto_attention_backend_ampere_no_override(monkeypatch):
    """Ampere+ GPU (compute >= 8.0) should leave backend selection to vLLM."""
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    monkeypatch.setattr(handle, "_detect_cuda_arch", lambda: "8.6")
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _c: "/tmp/vllm")
    lc = LaneConfig(model="test-model", vllm=True, vllm_config=VllmConfig())
    cmd = handle._build_cmd(lc)
    assert "--attention-config.backend" not in cmd


def test_auto_attention_backend_multi_gpu_all_pre_ampere(monkeypatch):
    """Multi-GPU node where all GPUs are pre-Ampere should select TRITON_ATTN."""
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    monkeypatch.setattr(handle, "_detect_cuda_arch", lambda: "7.5;7.5")
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _c: "/tmp/vllm")
    lc = LaneConfig(model="test-model", vllm=True, vllm_config=VllmConfig())
    cmd = handle._build_cmd(lc)
    assert "--attention-config.backend" in cmd
    assert cmd[cmd.index("--attention-config.backend") + 1] == "TRITON_ATTN"


def test_auto_attention_backend_mixed_gpus_no_override(monkeypatch):
    """Mixed pre-/post-Ampere node should leave backend selection to vLLM."""
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    monkeypatch.setattr(handle, "_detect_cuda_arch", lambda: "7.5;8.6")
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _c: "/tmp/vllm")
    lc = LaneConfig(model="test-model", vllm=True, vllm_config=VllmConfig())
    cmd = handle._build_cmd(lc)
    assert "--attention-config.backend" not in cmd


def test_auto_attention_backend_no_gpu_detected(monkeypatch):
    """When GPU detection fails, no backend override should be emitted."""
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    monkeypatch.setattr(handle, "_detect_cuda_arch", lambda: None)
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _c: "/tmp/vllm")
    lc = LaneConfig(model="test-model", vllm=True, vllm_config=VllmConfig())
    cmd = handle._build_cmd(lc)
    assert "--attention-config.backend" not in cmd


def test_build_env_sets_persistent_caches(monkeypatch):
    """All compilation caches should default to gc.models_path."""
    monkeypatch.delenv("LOGOS_WORKER_CACHE_ROOT", raising=False)
    monkeypatch.delenv("VLLM_CACHE_ROOT", raising=False)
    monkeypatch.delenv("TORCHINDUCTOR_CACHE_DIR", raising=False)
    monkeypatch.delenv("TORCHINDUCTOR_FX_GRAPH_CACHE", raising=False)
    monkeypatch.delenv("FLASHINFER_WORKSPACE_BASE", raising=False)
    monkeypatch.delenv("TORCH_CUDA_ARCH_LIST", raising=False)
    gc = OllamaConfig(models_path="/data/models")
    handle = VllmProcessHandle("lane-test", 19000, gc)
    monkeypatch.setattr(handle, "_detect_cuda_arch", lambda: "7.5")
    lc = LaneConfig(model="test-model", vllm=True, vllm_config=VllmConfig())
    env = handle._build_env(lc)
    assert env["VLLM_CACHE_ROOT"] == "/data/models/.cache/vllm"
    assert env["TORCHINDUCTOR_CACHE_DIR"] == "/data/models/.cache/torch_inductor"
    assert env["TORCHINDUCTOR_FX_GRAPH_CACHE"] == "1"
    # flashinfer 0.6.x: FLASHINFER_WORKSPACE_BASE is the env var that actually
    # relocates the JIT cache; it points to the cache root (the parent of
    # .cache/flashinfer), not to .cache/flashinfer itself.
    assert env["FLASHINFER_WORKSPACE_BASE"] == "/data/models"
    assert env["TORCH_CUDA_ARCH_LIST"] == "7.5"


def test_build_env_honors_logos_worker_cache_root(monkeypatch):
    """LOGOS_WORKER_CACHE_ROOT overrides gc.models_path for every cache."""
    monkeypatch.setenv("LOGOS_WORKER_CACHE_ROOT", "/var/cache/logos-worker")
    monkeypatch.delenv("VLLM_CACHE_ROOT", raising=False)
    monkeypatch.delenv("TORCHINDUCTOR_CACHE_DIR", raising=False)
    monkeypatch.delenv("TORCHINDUCTOR_FX_GRAPH_CACHE", raising=False)
    monkeypatch.delenv("FLASHINFER_WORKSPACE_BASE", raising=False)
    monkeypatch.delenv("TORCH_CUDA_ARCH_LIST", raising=False)
    monkeypatch.delenv("HF_HOME", raising=False)
    gc = OllamaConfig(models_path="/data/models")
    handle = VllmProcessHandle("lane-test", 19000, gc)
    monkeypatch.setattr(handle, "_detect_cuda_arch", lambda: "7.5")
    # Make _resolve_hf_home deterministic — skip the writable-fallback dance
    # by bypassing the real method.
    monkeypatch.setattr(
        handle,
        "_resolve_hf_home",
        lambda root: f"{root}/.hf_cache",
    )
    lc = LaneConfig(model="test-model", vllm=True, vllm_config=VllmConfig())
    env = handle._build_env(lc)
    assert env["HF_HOME"] == "/var/cache/logos-worker/.hf_cache"
    assert env["VLLM_CACHE_ROOT"] == "/var/cache/logos-worker/.cache/vllm"
    assert env["TORCHINDUCTOR_CACHE_DIR"] == "/var/cache/logos-worker/.cache/torch_inductor"
    assert env["FLASHINFER_WORKSPACE_BASE"] == "/var/cache/logos-worker"


# ---------------------------------------------------------------------------
# Reasoning parser — _infer_reasoning_parser
# ---------------------------------------------------------------------------


def test_infer_reasoning_parser() -> None:
    from logos_worker_node.vllm_process import _infer_reasoning_parser

    # The production rule table registers only parsers shipping in
    # vllm/reasoning/__init__.py: gemma4, openai_gptoss and qwen3. Other model
    # families return None — no flag emitted — until vLLM exposes a parser
    # for them.
    # Google Gemma 4
    assert _infer_reasoning_parser("google/gemma-4-27b-it") == "gemma4"
    assert _infer_reasoning_parser("google/gemma-4-2b") == "gemma4"
    # OpenAI GPT-OSS
    assert _infer_reasoning_parser("openai/gpt-oss-120b") == "openai_gptoss"
    assert _infer_reasoning_parser("openai/gpt-oss-20b") == "openai_gptoss"
    # Qwen3 point releases think by default and have a parser since vLLM 0.27
    assert _infer_reasoning_parser("Qwen/Qwen3.8-27B") == "qwen3"
    assert _infer_reasoning_parser("Qwen/Qwen3.6-35B-A3B") == "qwen3"
    assert _infer_reasoning_parser("Qwen/Qwen3.5-4B") == "qwen3"
    # Unknown / unsupported model families → None (no flag emitted)
    assert _infer_reasoning_parser("meta-llama/Llama-3.1-8B-Instruct") is None
    assert _infer_reasoning_parser("some/unknown-model") is None
    assert _infer_reasoning_parser("deepseek-ai/DeepSeek-R1-Distill-Qwen-7B") is None
    assert _infer_reasoning_parser("Qwen/QwQ-32B") is None
    assert _infer_reasoning_parser("Qwen/Qwen3-8B") is None
    assert _infer_reasoning_parser("zai-org/GLM-4.5-Flash") is None
    assert _infer_reasoning_parser("ibm-granite/granite-3.2-8b-instruct") is None


# ---------------------------------------------------------------------------
# Default chat-template kwargs — _infer_default_chat_template_kwargs
# ---------------------------------------------------------------------------


def test_infer_default_chat_template_kwargs() -> None:
    from logos_worker_node.vllm_process import _infer_default_chat_template_kwargs

    # Google Gemma 4 → enable_thinking: True. Pattern is the substring
    # "gemma-4" (with dash) — names without the dash do not match.
    assert _infer_default_chat_template_kwargs("google/gemma-4-27b-it") == {"enable_thinking": True}
    assert _infer_default_chat_template_kwargs("google/gemma-4-2b") == {"enable_thinking": True}
    # Unknown model → empty dict
    assert _infer_default_chat_template_kwargs("Qwen/Qwen3-8B") == {}
    assert _infer_default_chat_template_kwargs("meta-llama/Llama-3.1-8B-Instruct") == {}
    assert _infer_default_chat_template_kwargs("some/unknown-model") == {}


# ---------------------------------------------------------------------------
# _build_cmd integration — reasoning-parser + chat-template-kwargs
# ---------------------------------------------------------------------------


def test_build_cmd_gemma4_gets_reasoning_parser_and_chat_template_kwargs(
    monkeypatch,
) -> None:
    """Gemma-4 with empty vllm_config: inferred reasoning-parser + inferred kwargs."""
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _configured: "/tmp/vllm")

    lane = LaneConfig(
        model="google/gemma-4-27b-it",
        vllm=True,
        vllm_config=VllmConfig(),
    )
    cmd = handle._build_cmd(lane)

    # --reasoning-parser should be inferred as gemma4
    assert "--reasoning-parser" in cmd
    idx = cmd.index("--reasoning-parser")
    assert cmd[idx + 1] == "gemma4"

    # --default-chat-template-kwargs should carry {"enable_thinking": true}
    assert "--default-chat-template-kwargs" in cmd
    import json

    idx2 = cmd.index("--default-chat-template-kwargs")
    parsed = json.loads(cmd[idx2 + 1])
    assert parsed == {"enable_thinking": True}


def test_build_cmd_explicit_reasoning_parser_overrides_inference(monkeypatch) -> None:
    """Explicit reasoning_parser in config wins over inferred value."""
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _configured: "/tmp/vllm")

    lane = LaneConfig(
        model="google/gemma-4-27b-it",
        vllm=True,
        vllm_config=VllmConfig(reasoning_parser="foo"),
    )
    cmd = handle._build_cmd(lane)

    idx = cmd.index("--reasoning-parser")
    assert cmd[idx + 1] == "foo"


def test_build_cmd_reasoning_parser_none_sentinel_suppresses_flag(monkeypatch) -> None:
    """reasoning_parser='none' suppresses --reasoning-parser even when inference matches."""
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _configured: "/tmp/vllm")

    lane = LaneConfig(
        model="Qwen/Qwen3-8B",
        vllm=True,
        vllm_config=VllmConfig(reasoning_parser="none"),
    )
    cmd = handle._build_cmd(lane)
    assert "--reasoning-parser" not in cmd


def test_build_cmd_no_reasoning_parser_for_unknown_model(monkeypatch) -> None:
    """Unknown model with no explicit reasoning_parser → flag absent from cmd."""
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _configured: "/tmp/vllm")

    lane = LaneConfig(
        model="meta-llama/Llama-3.1-8B-Instruct",
        vllm=True,
        vllm_config=VllmConfig(),
    )
    cmd = handle._build_cmd(lane)
    assert "--reasoning-parser" not in cmd


def test_build_cmd_explicit_chat_template_kwargs_win_over_inferred(monkeypatch) -> None:
    """Explicit chat_template_kwargs key wins over inferred default (key-level merge)."""
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _configured: "/tmp/vllm")

    lane = LaneConfig(
        model="google/gemma-4-27b-it",
        vllm=True,
        vllm_config=VllmConfig(chat_template_kwargs={"enable_thinking": False}),
    )
    cmd = handle._build_cmd(lane)

    import json

    idx = cmd.index("--default-chat-template-kwargs")
    parsed = json.loads(cmd[idx + 1])
    # User explicitly disabled thinking — must win over inferred default True
    assert parsed["enable_thinking"] is False


# ---------------------------------------------------------------------------
# Compile cache poisoning detection & auto-purge
# ---------------------------------------------------------------------------


def _populate_compile_cache(root: Path) -> dict[str, Path]:
    """Build a realistic <cache_root>/.cache/ subtree and return key paths.

    Idempotent — a previous (narrowed) purge leaves modelinfos/ and friends
    behind, and a re-populate must not trip over them.
    """
    cache_root = root / ".cache"
    vllm_cache = cache_root / "vllm"
    inductor_cache = cache_root / "torch_inductor"
    flashinfer_cache = cache_root / "flashinfer"
    modelinfos = vllm_cache / "modelinfos"
    modelinfos.mkdir(parents=True, exist_ok=True)
    (modelinfos / "model.json").write_text("{}")
    (vllm_cache / "rank_0_0" / "backbone").mkdir(parents=True, exist_ok=True)
    (vllm_cache / "rank_0_0" / "backbone" / "artifact.bin").write_text("blob")
    (vllm_cache / "torch_compile_cache" / "deadbeef" / "inductor_cache" / "ol").mkdir(parents=True, exist_ok=True)
    (vllm_cache / "torch_compile_cache" / "deadbeef" / "inductor_cache" / "ol" / "frag.py").write_text("x = 1\n")
    inductor_cache.mkdir(parents=True, exist_ok=True)
    (inductor_cache / "artifact.bin").write_text("blob")
    flashinfer_cache.mkdir(parents=True, exist_ok=True)
    (flashinfer_cache / "keep.so").write_text("preserved")
    return {
        "cache_root": cache_root,
        "vllm": vllm_cache,
        "inductor": inductor_cache,
        "flashinfer": flashinfer_cache,
        "modelinfos": modelinfos,
    }


def test_has_poisoned_compile_cache_detects_cache_dir_in_stack(tmp_path: Path) -> None:
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    # Realistic snippet from a gemma-4 startup failure where the cached
    # AOT-compiled inductor file is executed and raises.
    handle._recent_logs.extend(
        [
            "(EngineCore) ERROR core.py:1140   File "
            '"/usr/share/ollama/.ollama/models/.cache/vllm/torch_compile_cache/'
            'deadbeef/inductor_cache/ol/frag.py", line 664, in call',
            "(EngineCore) ERROR core.py:1140 RuntimeError: Expected result >= 0",
        ]
    )
    assert handle.has_poisoned_compile_cache is True


def test_has_poisoned_compile_cache_ignores_unrelated_errors() -> None:
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    handle._recent_logs.extend(
        [
            "ValueError: Could not load model weights from HuggingFace hub",
            "ImportError: No module named 'foo'",
        ]
    )
    assert handle.has_poisoned_compile_cache is False


def test_has_poisoned_compile_cache_false_when_no_logs() -> None:
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    assert handle.has_poisoned_compile_cache is False


def test_purge_compile_caches_removes_artifacts_only(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOGOS_WORKER_CACHE_ROOT", str(tmp_path))
    paths = _populate_compile_cache(tmp_path)
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())

    removed = handle._purge_compile_caches()

    assert set(removed) == {
        str(paths["vllm"] / "torch_compile_cache"),
        str(paths["vllm"] / "rank_0_0"),
        str(paths["inductor"]),
    }
    assert not (paths["vllm"] / "torch_compile_cache").exists()
    assert not (paths["vllm"] / "rank_0_0").exists()
    assert not paths["inductor"].exists()
    # The vllm cache dir itself survives — only the artifact subdirs are wiped.
    assert paths["vllm"].exists()
    # modelinfos/ is safe JSON metadata and must never be touched by
    # auto-recovery.
    assert (paths["modelinfos"] / "model.json").exists()
    # FlashInfer JIT cache + HF weights are not implicated in compile-cache
    # poisoning and must survive a purge.
    assert paths["flashinfer"].exists()
    assert (paths["flashinfer"] / "keep.so").exists()


def test_purge_compile_caches_per_model_only_touches_that_lane(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOGOS_WORKER_CACHE_ROOT", str(tmp_path))
    paths = _populate_compile_cache(tmp_path)
    lanes_root = paths["vllm"] / "lanes"
    for lane_name in ("alpha__model-a", "beta__model-b"):
        (lanes_root / lane_name / "torch_compile_cache" / "deadbeef").mkdir(parents=True)
        (lanes_root / lane_name / "rank_0_0" / "backbone").mkdir(parents=True)
        (lanes_root / lane_name / "modelinfos").mkdir(parents=True)
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())

    removed = handle._purge_compile_caches("alpha/model-a")

    assert set(removed) == {
        str(lanes_root / "alpha__model-a" / "torch_compile_cache"),
        str(lanes_root / "alpha__model-a" / "rank_0_0"),
    }
    # A poisoned model must not force every other model on the node to
    # recompile — the sibling lane's cache is left in place.
    assert (lanes_root / "beta__model-b" / "torch_compile_cache").exists()
    assert (lanes_root / "beta__model-b" / "rank_0_0").exists()
    # And modelinfos/ is never touched, even for the purged lane.
    assert (lanes_root / "alpha__model-a" / "modelinfos").exists()
    assert (paths["modelinfos"] / "model.json").exists()


def test_purge_compile_caches_is_noop_when_nothing_to_remove(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOGOS_WORKER_CACHE_ROOT", str(tmp_path))
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    assert handle._purge_compile_caches() == []


def test_purge_compile_caches_if_versions_changed_purges_on_mismatch(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOGOS_WORKER_CACHE_ROOT", str(tmp_path))
    paths = _populate_compile_cache(tmp_path)
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())

    # Stamp records the previous vLLM version.
    import json

    stamp_path = paths["cache_root"] / handle._COMPILE_CACHE_STAMP_FILENAME
    stamp_path.write_text(json.dumps({"vllm": "0.21.0", "torch": "2.11.0"}))

    monkeypatch.setattr(
        VllmProcessHandle,
        "_current_compile_versions",
        staticmethod(lambda: {"vllm": "0.22.0", "torch": "2.11.0"}),
    )

    removed = handle._purge_compile_caches_if_versions_changed()
    assert set(removed) == {
        str(paths["vllm"] / "torch_compile_cache"),
        str(paths["vllm"] / "rank_0_0"),
        str(paths["inductor"]),
    }
    assert not (paths["vllm"] / "torch_compile_cache").exists()
    assert not paths["inductor"].exists()
    assert (paths["modelinfos"] / "model.json").exists()
    assert paths["flashinfer"].exists()


def test_purge_compile_caches_if_versions_changed_noop_when_match(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOGOS_WORKER_CACHE_ROOT", str(tmp_path))
    paths = _populate_compile_cache(tmp_path)
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())

    import json

    stamp_path = paths["cache_root"] / handle._COMPILE_CACHE_STAMP_FILENAME
    stamp_path.write_text(json.dumps({"vllm": "0.22.0", "torch": "2.11.0"}))

    monkeypatch.setattr(
        VllmProcessHandle,
        "_current_compile_versions",
        staticmethod(lambda: {"vllm": "0.22.0", "torch": "2.11.0"}),
    )

    assert handle._purge_compile_caches_if_versions_changed() == []
    assert paths["vllm"].exists()
    assert paths["inductor"].exists()


def test_purge_compile_caches_if_versions_changed_purges_when_no_stamp(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOGOS_WORKER_CACHE_ROOT", str(tmp_path))
    paths = _populate_compile_cache(tmp_path)
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())

    monkeypatch.setattr(
        VllmProcessHandle,
        "_current_compile_versions",
        staticmethod(lambda: {"vllm": "0.22.0", "torch": "2.11.0"}),
    )

    removed = handle._purge_compile_caches_if_versions_changed()
    assert set(removed) == {
        str(paths["vllm"] / "torch_compile_cache"),
        str(paths["vllm"] / "rank_0_0"),
        str(paths["inductor"]),
    }
    assert (paths["modelinfos"] / "model.json").exists()


def test_purge_compile_caches_if_versions_changed_skips_when_no_cache(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOGOS_WORKER_CACHE_ROOT", str(tmp_path))
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    monkeypatch.setattr(
        VllmProcessHandle,
        "_current_compile_versions",
        staticmethod(lambda: {"vllm": "0.22.0"}),
    )
    assert handle._purge_compile_caches_if_versions_changed() == []
    # And no stamp was created — writing one would be misleading because no
    # artifacts exist yet.
    assert not (tmp_path / ".cache" / handle._COMPILE_CACHE_STAMP_FILENAME).exists()


def test_write_compile_cache_stamp_records_current_versions(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOGOS_WORKER_CACHE_ROOT", str(tmp_path))
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    monkeypatch.setattr(
        VllmProcessHandle,
        "_current_compile_versions",
        staticmethod(lambda: {"vllm": "0.22.0", "torch": "2.11.0"}),
    )

    handle._write_compile_cache_stamp()

    import json

    stamp_path = tmp_path / ".cache" / handle._COMPILE_CACHE_STAMP_FILENAME
    assert stamp_path.exists()
    assert json.loads(stamp_path.read_text()) == {"vllm": "0.22.0", "torch": "2.11.0"}


@pytest.mark.asyncio
async def test_spawn_retries_once_on_poisoned_compile_cache(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOGOS_WORKER_CACHE_ROOT", str(tmp_path))
    paths = _populate_compile_cache(tmp_path)
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    # Pretend the stamp matches so the proactive purge stays out of the
    # way — we want to exercise the reactive purge-then-retry path.
    import json as _json

    (paths["cache_root"] / handle._COMPILE_CACHE_STAMP_FILENAME).write_text(
        _json.dumps({"vllm": "0.22.0", "torch": "2.11.0"})
    )
    monkeypatch.setattr(
        VllmProcessHandle,
        "_current_compile_versions",
        staticmethod(lambda: {"vllm": "0.22.0", "torch": "2.11.0"}),
    )

    lane = LaneConfig(model="google/gemma-4-27b-it", vllm=True, vllm_config=VllmConfig())

    attempt_calls: list[int] = []

    async def _fake_spawn_once(_lc):  # noqa: ANN001
        attempt_calls.append(len(attempt_calls) + 1)
        if len(attempt_calls) == 1:
            # Simulate the deioma failure: stack trace ends inside the
            # cached AOT-compiled inductor file.
            handle._recent_logs.extend(
                [
                    '  File "/tmp/x/.cache/vllm/torch_compile_cache/abc/' 'inductor_cache/ol/frag.py", line 1, in call',
                    "RuntimeError: Expected result >= 0",
                ]
            )
            raise RuntimeError("Engine core init failed")
        # Successful second attempt.
        handle._recent_logs.clear()
        return handle.status()

    monkeypatch.setattr(handle, "_spawn_once", _fake_spawn_once)

    await handle.spawn(lane)

    assert attempt_calls == [1, 2]
    # The reactive purge wiped the compile artifacts between attempts. The
    # per-lane dir held nothing (this fixture uses the legacy shared
    # location), so the worker-wide fallback fired.
    assert not (paths["vllm"] / "torch_compile_cache").exists()
    assert not (paths["vllm"] / "rank_0_0").exists()
    assert not paths["inductor"].exists()
    assert (paths["modelinfos"] / "model.json").exists()
    assert paths["flashinfer"].exists()


@pytest.mark.asyncio
async def test_spawn_does_not_retry_on_unrelated_startup_failure(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOGOS_WORKER_CACHE_ROOT", str(tmp_path))
    paths = _populate_compile_cache(tmp_path)
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())

    import json as _json

    (paths["cache_root"] / handle._COMPILE_CACHE_STAMP_FILENAME).write_text(
        _json.dumps({"vllm": "0.22.0", "torch": "2.11.0"})
    )
    monkeypatch.setattr(
        VllmProcessHandle,
        "_current_compile_versions",
        staticmethod(lambda: {"vllm": "0.22.0", "torch": "2.11.0"}),
    )

    lane = LaneConfig(model="google/gemma-4-27b-it", vllm=True, vllm_config=VllmConfig())
    calls: list[int] = []

    async def _fake_spawn_once(_lc):  # noqa: ANN001
        calls.append(1)
        handle._recent_logs.extend(["ValueError: missing HF token"])
        raise RuntimeError("auth failure")

    monkeypatch.setattr(handle, "_spawn_once", _fake_spawn_once)

    with pytest.raises(RuntimeError, match="auth failure"):
        await handle.spawn(lane)
    assert len(calls) == 1
    # Unrelated failure must not wipe the compile cache.
    assert paths["vllm"].exists()
    assert paths["inductor"].exists()


@pytest.mark.asyncio
async def test_spawn_does_not_widen_worker_wide_on_fingerprint_only(tmp_path: Path, monkeypatch) -> None:
    """A fingerprint match whose traceback names no compile-cache file, on a
    lane with an empty per-lane dir, must NOT widen to the worker-wide purge —
    that would force every other model on the node to recompile on a
    heuristic match. The failure propagates instead."""
    monkeypatch.setenv("LOGOS_WORKER_CACHE_ROOT", str(tmp_path))
    paths = _populate_compile_cache(tmp_path)
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())

    import json as _json

    # Stamp matches so the proactive purge stays out of the way.
    (paths["cache_root"] / handle._COMPILE_CACHE_STAMP_FILENAME).write_text(
        _json.dumps({"vllm": "0.22.0", "torch": "2.11.0"})
    )
    monkeypatch.setattr(
        VllmProcessHandle,
        "_current_compile_versions",
        staticmethod(lambda: {"vllm": "0.22.0", "torch": "2.11.0"}),
    )

    lane = LaneConfig(model="org/brand-new-model", vllm=True, vllm_config=VllmConfig())
    calls: list[int] = []

    async def _fake_spawn_once(_lc):  # noqa: ANN001
        calls.append(1)
        # copy_misaligned_inputs fingerprint, but the traceback names only
        # torch internals — no compile-cache path, so no strong signal.
        handle._recent_logs.extend(
            [
                '  File "/opt/venv/lib/python3.12/site-packages/torch/_inductor/utils.py", '
                "line 3442, in copy_misaligned_inputs",
                "AssertionError: Expected tensors only, but got: <class 'int'>",
            ]
        )
        raise RuntimeError("Engine core init failed")

    monkeypatch.setattr(handle, "_spawn_once", _fake_spawn_once)

    with pytest.raises(RuntimeError, match="Engine core init failed"):
        await handle.spawn(lane)
    # No retry: the fingerprint-only match on an empty per-lane dir did not
    # widen to the worker-wide cache.
    assert len(calls) == 1
    # The shared compile cache is untouched.
    assert (paths["vllm"] / "torch_compile_cache").exists()
    assert (paths["vllm"] / "rank_0_0").exists()
    assert paths["inductor"].exists()


# Fingerprint matching — failures that die inside torch/vllm library code,
# where no frame of the traceback points into the cache directory.


def test_has_poisoned_compile_cache_detects_copy_misaligned_inputs_fingerprint() -> None:
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    # The GLM-OCR incident: the cached AOT artifact asserts deep inside
    # torch on a stale input signature — the traceback never names the
    # cache directory, only the fingerprint does.
    handle._recent_logs.extend(
        [
            "(EngineCore) ERROR core.py:1140 Traceback (most recent call last):",
            "(EngineCore) ERROR core.py:1140   File "
            '"/opt/venv/lib/python3.12/site-packages/transformers/models/glm4_1v/modeling_glm4_1v.py", '
            "line 1679, in forward",
            '(EngineCore) ERROR core.py:1140   File "/opt/venv/lib/python3.12/site-packages/'
            'torch/_inductor/utils.py", line 3442, in copy_misaligned_inputs',
            "(EngineCore) ERROR core.py:1140 AssertionError: Expected tensors only, but got: <class 'int'>",
            "(EngineCore) ERROR core.py:1140 RuntimeError: Engine core initialization failed.",
        ]
    )
    assert handle.has_poisoned_compile_cache is True
    assert handle._matched_cache_poisoning_fingerprint() == "copy_misaligned_inputs"


@pytest.mark.parametrize(
    ("fingerprint", "log_lines"),
    [
        (
            "copy_misaligned_inputs",
            [
                '  File ".../torch/_inductor/utils.py", line 3442, in copy_misaligned_inputs',
                "AssertionError: Expected tensors only, but got: <class 'int'>",
            ],
        ),
        (
            "aot_artifact_assertion",
            [
                '  File ".../torch/_inductor/standalone_compile.py", line 122, in CacheCompiledArtifact._compiled_fn',
                "AssertionError: shape mismatch in cached graph",
            ],
        ),
        (
            "inductor_artifact_missing",
            [
                '  File ".../torch/_inductor/standalone_compile.py", line 122, in _compiled_fn',
                "FileNotFoundError: .../torch_compile_cache/torch_aot_compile/deadbeef/graph",
            ],
        ),
        (
            "compilation_cache_key_error",
            [
                '  File ".../vllm/compilation/caching.py", line 217, in optimized_call',
                "KeyError: 'f5096f3c'",
            ],
        ),
    ],
)
def test_matched_cache_poisoning_fingerprints(fingerprint: str, log_lines: list[str]) -> None:
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    handle._recent_logs.extend(log_lines)
    assert handle._matched_cache_poisoning_fingerprint() == fingerprint
    assert handle.has_poisoned_compile_cache is True


def test_matched_cache_poisoning_fingerprint_requires_all_fragments() -> None:
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    # A KeyError that is not from the compilation cache module, and a
    # FileNotFoundError whose path is not under the compile cache, must not
    # match.
    handle._recent_logs.extend(
        [
            '  File ".../vllm/config.py", line 10, in load',
            "KeyError: 'model'",
            '  File ".../vllm/worker/worker.py", line 5, in init_device',
            "FileNotFoundError: '/models/weights.safetensors'",
        ]
    )
    assert handle._matched_cache_poisoning_fingerprint() is None
    assert handle.has_poisoned_compile_cache is False


def test_inductor_artifact_missing_matches_cache_path_file_not_found() -> None:
    """A FileNotFoundError under a compile-cache path is a genuinely missing
    cache artifact. The path uses a custom cache root so it is not one of the
    generic path fragments — only the tightened fingerprint can match it."""
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    handle._recent_logs.extend(
        [
            '  File ".../torch/_inductor/standalone_compile.py", line 122, in _compiled_fn',
            "FileNotFoundError: [Errno 2] No such file or directory: "
            "'/mnt/custom-root/vllm/torch_compile_cache/deadbeef/ol/frag.py'",
        ]
    )
    assert handle._matched_cache_poisoning_fingerprint() == "inductor_artifact_missing"
    assert handle.has_poisoned_compile_cache is True


def test_inductor_artifact_missing_ignores_unrelated_file_not_found() -> None:
    """The false positive from review: a brand-new model that fails to load
    (mistyped repo id, gated repo) raises FileNotFoundError, and ordinary
    torch.compile output logs torch/_inductor frames in the same window. The
    missing file is a HuggingFace path, not a compile-cache artifact, so the
    fingerprint must NOT match."""
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    handle._recent_logs.extend(
        [
            '  File "/opt/venv/lib/python3.12/site-packages/torch/_inductor/runtime/' "triton_heuristics.py",
            " line 12, in run",
            "FileNotFoundError: [Errno 2] No such file or directory: " "'/models/org__typo-model/weights.safetensors'",
        ]
    )
    assert handle._matched_cache_poisoning_fingerprint() is None
    assert handle.has_poisoned_compile_cache is False


# Per-lane cache_meta.json pre-flight validation


def _populate_lane_cache(root: Path, model: str) -> Path:
    """Build the per-lane compile cache dir for ``model`` and return it."""
    lane_dir = root / ".cache" / "vllm" / "lanes" / model.replace("/", "__")
    (lane_dir / "torch_compile_cache" / "deadbeef").mkdir(parents=True)
    (lane_dir / "rank_0_0" / "backbone").mkdir(parents=True)
    (lane_dir / "modelinfos").mkdir(parents=True)
    (lane_dir / "modelinfos" / "model.json").write_text("{}")
    return lane_dir


def test_purge_lane_cache_if_meta_changed_purges_on_version_mismatch(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOGOS_WORKER_CACHE_ROOT", str(tmp_path))
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    monkeypatch.setattr(
        VllmProcessHandle,
        "_current_compile_versions",
        staticmethod(lambda: {"vllm": "0.22.0", "torch": "2.11.0"}),
    )

    lane = LaneConfig(model="zai-org/GLM-OCR", vllm=True, vllm_config=VllmConfig())
    lane_dir = _populate_lane_cache(tmp_path, "zai-org/GLM-OCR")
    import json

    # The meta records the vLLM version that produced the cached artifacts.
    meta = handle._current_cache_meta(lane)
    meta["vllm"] = "0.21.0"
    (lane_dir / handle._CACHE_META_FILENAME).write_text(json.dumps(meta, sort_keys=True))

    removed = handle._purge_lane_cache_if_meta_changed(lane)

    assert set(removed) == {str(lane_dir / "torch_compile_cache"), str(lane_dir / "rank_0_0")}
    assert not (lane_dir / "torch_compile_cache").exists()
    assert not (lane_dir / "rank_0_0").exists()
    # modelinfos/ is never touched by auto-recovery.
    assert (lane_dir / "modelinfos" / "model.json").exists()


def test_purge_lane_cache_if_meta_changed_noop_on_match(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOGOS_WORKER_CACHE_ROOT", str(tmp_path))
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    monkeypatch.setattr(
        VllmProcessHandle,
        "_current_compile_versions",
        staticmethod(lambda: {"vllm": "0.22.0", "torch": "2.11.0"}),
    )

    lane = LaneConfig(model="zai-org/GLM-OCR", vllm=True, vllm_config=VllmConfig())
    lane_dir = _populate_lane_cache(tmp_path, "zai-org/GLM-OCR")
    import json

    (lane_dir / handle._CACHE_META_FILENAME).write_text(json.dumps(handle._current_cache_meta(lane), sort_keys=True))

    assert handle._purge_lane_cache_if_meta_changed(lane) == []
    assert (lane_dir / "torch_compile_cache").exists()
    assert (lane_dir / "rank_0_0").exists()


def test_purge_lane_cache_if_meta_changed_purges_when_no_meta(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOGOS_WORKER_CACHE_ROOT", str(tmp_path))
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    monkeypatch.setattr(
        VllmProcessHandle,
        "_current_compile_versions",
        staticmethod(lambda: {"vllm": "0.22.0", "torch": "2.11.0"}),
    )

    lane = LaneConfig(model="zai-org/GLM-OCR", vllm=True, vllm_config=VllmConfig())
    lane_dir = _populate_lane_cache(tmp_path, "zai-org/GLM-OCR")

    # Cache exists but no meta — produced by a worker version that predates
    # the per-lane meta check. Treated as unknown and wiped.
    removed = handle._purge_lane_cache_if_meta_changed(lane)

    assert set(removed) == {str(lane_dir / "torch_compile_cache"), str(lane_dir / "rank_0_0")}
    assert (lane_dir / "modelinfos" / "model.json").exists()


def test_purge_lane_cache_if_meta_changed_noop_without_artifacts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOGOS_WORKER_CACHE_ROOT", str(tmp_path))
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())

    lane = LaneConfig(model="zai-org/GLM-OCR", vllm=True, vllm_config=VllmConfig())
    # No artifacts yet (first start of this model) — nothing to validate,
    # and no meta is read either.
    assert handle._purge_lane_cache_if_meta_changed(lane) == []


def test_purge_lane_cache_if_meta_changed_skips_user_overridden_compilation_config(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOGOS_WORKER_CACHE_ROOT", str(tmp_path))
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())

    # The lane manages its own --compilation-config — that cache dir is not
    # one we resolve, so no pre-flight validation and no meta are applied.
    lane = LaneConfig(
        model="zai-org/GLM-OCR",
        vllm=True,
        vllm_config=VllmConfig(extra_args=["--compilation-config", '{"cache_dir": "/custom"}']),
    )
    assert handle._lane_compile_cache_dir(lane) is None
    assert handle._purge_lane_cache_if_meta_changed(lane) == []
    handle._write_lane_cache_meta(lane)
    assert not (tmp_path / ".cache" / "vllm" / "lanes").exists()


@pytest.mark.asyncio
async def test_spawn_writes_lane_cache_meta_after_healthy_start(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOGOS_WORKER_CACHE_ROOT", str(tmp_path))
    monkeypatch.setenv("LOGOS_IMAGE_VERSION", "logos-workernode-vllm:2026.08.29")
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    monkeypatch.setattr(
        VllmProcessHandle,
        "_current_compile_versions",
        staticmethod(lambda: {"vllm": "0.22.0", "torch": "2.11.0"}),
    )

    lane = LaneConfig(model="zai-org/GLM-OCR", vllm=True, vllm_config=VllmConfig())
    calls: list[int] = []

    async def _fake_spawn_once(_lc):  # noqa: ANN001
        calls.append(1)
        return handle.status()

    monkeypatch.setattr(handle, "_spawn_once", _fake_spawn_once)

    await handle.spawn(lane)
    assert calls == [1]

    import json

    lane_dir = tmp_path / ".cache" / "vllm" / "lanes" / "zai-org__GLM-OCR"
    meta_path = lane_dir / handle._CACHE_META_FILENAME
    assert meta_path.exists()
    meta = json.loads(meta_path.read_text())
    assert meta["vllm"] == "0.22.0"
    assert meta["torch"] == "2.11.0"
    assert meta["model"] == "zai-org/GLM-OCR"
    assert meta["image"] == "logos-workernode-vllm:2026.08.29"
    assert "compilation_config" in meta


# Reactive recovery cooldown + structured log line


@pytest.mark.asyncio
async def test_spawn_reactive_recovery_is_capped_per_model_hour(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOGOS_WORKER_CACHE_ROOT", str(tmp_path))
    paths = _populate_compile_cache(tmp_path)
    import json as _json

    (paths["cache_root"] / VllmProcessHandle._COMPILE_CACHE_STAMP_FILENAME).write_text(
        _json.dumps({"vllm": "0.22.0", "torch": "2.11.0"})
    )
    monkeypatch.setattr(
        VllmProcessHandle,
        "_current_compile_versions",
        staticmethod(lambda: {"vllm": "0.22.0", "torch": "2.11.0"}),
    )
    monkeypatch.setattr("logos_worker_node.vllm_process._last_reactive_cache_recovery", {})

    lane = LaneConfig(model="zai-org/GLM-OCR", vllm=True, vllm_config=VllmConfig())
    # A strong-signal poisoning: the traceback names a compile-cache file
    # (path fragment), so the worker-wide fallback fires on this empty
    # per-lane (legacy shared-location) fixture.
    poisoned_logs = [
        '  File "/tmp/x/.cache/vllm/torch_compile_cache/abc/inductor_cache/ol/frag.py", line 1, in call',
        '  File ".../torch/_inductor/utils.py", line 3442, in copy_misaligned_inputs',
        "AssertionError: Expected tensors only, but got: <class 'int'>",
    ]

    # First handle: one auto-recovery (purge + retry) succeeds.
    handle1 = VllmProcessHandle("lane-1", 19000, OllamaConfig())
    attempts1: list[int] = []

    async def _spawn_once_fail_then_ok(_lc):  # noqa: ANN001
        attempts1.append(1)
        if len(attempts1) == 1:
            handle1._recent_logs.extend(poisoned_logs)
            raise RuntimeError("Engine core init failed")
        handle1._recent_logs.clear()
        return handle1.status()

    monkeypatch.setattr(handle1, "_spawn_once", _spawn_once_fail_then_ok)
    await handle1.spawn(lane)
    assert attempts1 == [1, 1]

    # The lane manager restarts the lane (a fresh handle). The same failure
    # must NOT trigger a second recovery within the cooldown window.
    _populate_compile_cache(tmp_path)
    handle2 = VllmProcessHandle("lane-2", 19001, OllamaConfig())
    attempts2: list[int] = []

    async def _spawn_once_always_fail(_lc):  # noqa: ANN001
        attempts2.append(1)
        handle2._recent_logs.extend(poisoned_logs)
        raise RuntimeError("Engine core init failed")

    monkeypatch.setattr(handle2, "_spawn_once", _spawn_once_always_fail)
    with pytest.raises(RuntimeError, match="Engine core init failed"):
        await handle2.spawn(lane)
    assert attempts2 == [1]  # no second retry
    # ... and the cache was not purged again.
    assert (tmp_path / ".cache" / "vllm" / "torch_compile_cache").exists()


@pytest.mark.asyncio
async def test_spawn_logs_structured_auto_recovery_line(tmp_path: Path, monkeypatch, caplog) -> None:
    monkeypatch.setenv("LOGOS_WORKER_CACHE_ROOT", str(tmp_path))
    paths = _populate_compile_cache(tmp_path)
    import json as _json
    import logging

    (paths["cache_root"] / VllmProcessHandle._COMPILE_CACHE_STAMP_FILENAME).write_text(
        _json.dumps({"vllm": "0.22.0", "torch": "2.11.0"})
    )
    monkeypatch.setattr(
        VllmProcessHandle,
        "_current_compile_versions",
        staticmethod(lambda: {"vllm": "0.22.0", "torch": "2.11.0"}),
    )
    monkeypatch.setattr("logos_worker_node.vllm_process._last_reactive_cache_recovery", {})

    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    lane = LaneConfig(model="zai-org/GLM-OCR", vllm=True, vllm_config=VllmConfig())
    attempts: list[int] = []

    async def _fake_spawn_once(_lc):  # noqa: ANN001
        attempts.append(1)
        if len(attempts) == 1:
            # Strong signal (cache path in the traceback) so the worker-wide
            # fallback fires on this empty per-lane fixture, plus the
            # copy_misaligned_inputs fingerprint the assertion checks for.
            handle._recent_logs.extend(
                [
                    '  File "/tmp/x/.cache/vllm/torch_compile_cache/abc/inductor_cache/ol/frag.py", line 1, in call',
                    '  File ".../torch/_inductor/utils.py", line 3442, in copy_misaligned_inputs',
                    "AssertionError: Expected tensors only, but got: <class 'int'>",
                ]
            )
            raise RuntimeError("Engine core init failed")
        handle._recent_logs.clear()
        return handle.status()

    monkeypatch.setattr(handle, "_spawn_once", _fake_spawn_once)

    with caplog.at_level(logging.WARNING, logger="logos_worker_node.vllm_process"):
        await handle.spawn(lane)

    recovered = [r for r in caplog.records if "cache_auto_recovered=true" in r.getMessage()]
    assert len(recovered) == 1
    message = recovered[0].getMessage()
    assert "model=zai-org/GLM-OCR" in message
    assert "fingerprint=copy_misaligned_inputs" in message


def test_build_cmd_emits_speculative_config(monkeypatch) -> None:
    """The MTP draft head is configured per model, not through extra_args."""
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _configured: "/tmp/vllm")

    spec = '{"method":"qwen3_5_mtp","num_speculative_tokens":3}'
    lane = LaneConfig(model="Qwen/Qwen3.8-27B", vllm=True, vllm_config=VllmConfig(speculative_config=spec))
    cmd = handle._build_cmd(lane)
    idx = cmd.index("--speculative-config")
    assert cmd[idx + 1] == spec


def test_build_cmd_omits_speculative_config_when_unset(monkeypatch) -> None:
    handle = VllmProcessHandle("lane-test", 19000, OllamaConfig())
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _configured: "/tmp/vllm")

    lane = LaneConfig(model="m", vllm=True, vllm_config=VllmConfig())
    assert "--speculative-config" not in handle._build_cmd(lane)


def test_speculative_decoding_requested_detects_both_spellings() -> None:
    """A raw --speculative-config in extra_args counts too.

    Either spelling produces a lane with a draft model, and the draft model is
    what makes the sharded checkpoint cache unusable — so the detection cannot
    key on the typed field alone.
    """
    from logos_worker_node.vllm_process import _speculative_decoding_requested

    assert not _speculative_decoding_requested(VllmConfig())
    assert _speculative_decoding_requested(VllmConfig(speculative_config='{"method":"qwen3_5_mtp"}'))
    assert _speculative_decoding_requested(VllmConfig(extra_args=["--speculative-config", '{"method":"mtp"}']))
    assert _speculative_decoding_requested(VllmConfig(extra_args=['--speculative-config={"method":"mtp"}']))
    assert not _speculative_decoding_requested(VllmConfig(extra_args=["--enable-prefix-caching"]))
    assert not _speculative_decoding_requested(VllmConfig(speculative_config="   "))


@pytest.mark.asyncio
async def test_sharded_checkpoint_skipped_for_speculative_lane(monkeypatch, tmp_path) -> None:
    """A speculative lane must serve the full checkpoint.

    vLLM loads the draft model with the main model's --load-format, and the
    sharded cache carries shards only for the main model, so the lane dies with
    "only pre-sharded checkpoints are currently supported". Skipping is per
    lane, so one model using MTP does not cost the whole node its cache.
    """
    handle = VllmProcessHandle(
        "lane-test",
        19000,
        OllamaConfig(),
        vllm_engine_config=VllmEngineConfig(sharded_checkpoint_enabled=True),
    )
    monkeypatch.setattr(handle, "_resolve_persistent_cache_root", lambda _cfg: str(tmp_path))

    lane = LaneConfig(
        model="Qwen/Qwen3.8-27B",
        vllm=True,
        vllm_config=VllmConfig(
            tensor_parallel_size=2,
            speculative_config='{"method":"qwen3_5_mtp","num_speculative_tokens":3}',
        ),
    )
    # A ready cache is present, so the only reason not to use it is the draft
    # model. Without this the assertion below would hold for the wrong reason.
    from logos_worker_node import sharded_checkpoint as sc

    monkeypatch.setattr(sc, "is_sharded_checkpoint_ready", lambda _target: True)

    await handle._maybe_prepare_sharded_checkpoint(lane)
    assert handle._sharded_model_dir is None

    # Same lane, same ready cache, no draft model — now it is used. This is what
    # makes the assertion above meaningful.
    plain = LaneConfig(model="Qwen/Qwen3.8-27B", vllm=True, vllm_config=VllmConfig(tensor_parallel_size=2))
    await handle._maybe_prepare_sharded_checkpoint(plain)
    assert handle._sharded_model_dir is not None
