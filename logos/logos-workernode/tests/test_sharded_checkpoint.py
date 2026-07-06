from __future__ import annotations

import asyncio
from pathlib import Path

from logos_worker_node import sharded_checkpoint as sc
from logos_worker_node.models import LaneConfig, OllamaConfig, VllmConfig, VllmEngineConfig
from logos_worker_node.vllm_process import VllmProcessHandle


def test_sharded_checkpoint_dir_layout() -> None:
    d = sc.sharded_checkpoint_dir("/cache", "org/Model-A", 4)
    assert d == Path("/cache") / ".sharded_cache" / "org__Model-A" / "tp4"


def test_is_ready_tracks_marker(tmp_path: Path) -> None:
    d = sc.sharded_checkpoint_dir(str(tmp_path), "org/m", 2)
    d.mkdir(parents=True)
    assert sc.is_sharded_checkpoint_ready(d) is False
    (d / sc._COMPLETION_MARKER).write_text("ok")
    assert sc.is_sharded_checkpoint_ready(d) is True


def test_resolve_cache_root_prefers_env(monkeypatch) -> None:
    monkeypatch.setenv("LOGOS_WORKER_CACHE_ROOT", "/override")
    assert sc.resolve_cache_root("/models") == "/override"
    monkeypatch.delenv("LOGOS_WORKER_CACHE_ROOT", raising=False)
    assert sc.resolve_cache_root("/models") == "/models"


def test_resolve_vllm_python_picks_sibling(monkeypatch, tmp_path: Path) -> None:
    bin_dir = tmp_path / "venv" / "bin"
    bin_dir.mkdir(parents=True)
    py = bin_dir / "python"
    py.write_text("#!/bin/sh\nexit 0\n")
    py.chmod(0o755)
    vllm = bin_dir / "vllm"
    vllm.write_text("#!/bin/sh\nexit 0\n")
    vllm.chmod(0o755)
    monkeypatch.setattr("logos_worker_node.sharded_checkpoint.shutil.which", lambda _c: None)
    assert sc.resolve_vllm_python(str(vllm)) == str(py)


def test_ensure_returns_none_for_tp1(tmp_path: Path) -> None:
    assert sc.ensure_sharded_checkpoint(model="org/m", tensor_parallel_size=1, cache_root=str(tmp_path)) is None


def test_ensure_returns_existing_without_converting(tmp_path: Path, monkeypatch) -> None:
    d = sc.sharded_checkpoint_dir(str(tmp_path), "org/m", 2)
    d.mkdir(parents=True)
    (d / sc._COMPLETION_MARKER).write_text("ok")

    def _boom(*_a, **_k):  # conversion must not run when already ready
        raise AssertionError("should not convert an already-ready checkpoint")

    monkeypatch.setattr(sc, "_run_conversion_subprocess", _boom)
    out = sc.ensure_sharded_checkpoint(model="org/m", tensor_parallel_size=2, cache_root=str(tmp_path))
    assert out == d


def test_ensure_success_writes_marker(tmp_path: Path, monkeypatch) -> None:
    def _fake_convert(cmd, env, log_path, timeout_s, cancel_event):
        # Emulate the converter writing a shard file into --output.
        out = Path(cmd[cmd.index("--output") + 1])
        (out / "model-rank-0-part-0.safetensors").write_text("weights")
        return True

    monkeypatch.setattr(sc, "_run_conversion_subprocess", _fake_convert)
    out = sc.ensure_sharded_checkpoint(model="org/m", tensor_parallel_size=2, cache_root=str(tmp_path))
    assert out is not None
    assert sc.is_sharded_checkpoint_ready(out)


def test_ensure_failure_cleans_up(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(sc, "_run_conversion_subprocess", lambda *a, **k: False)
    out = sc.ensure_sharded_checkpoint(model="org/m", tensor_parallel_size=2, cache_root=str(tmp_path))
    assert out is None
    # Partial output directory must be removed so a retry starts clean.
    assert not sc.sharded_checkpoint_dir(str(tmp_path), "org/m", 2).exists()


def test_ensure_no_shard_files_is_failure(tmp_path: Path, monkeypatch) -> None:
    # Subprocess reports success but produced no shards → treated as failure.
    monkeypatch.setattr(sc, "_run_conversion_subprocess", lambda *a, **k: True)
    out = sc.ensure_sharded_checkpoint(model="org/m", tensor_parallel_size=2, cache_root=str(tmp_path))
    assert out is None


def _lane(tp: int, tmp_path: Path) -> LaneConfig:
    return LaneConfig(
        model="org/Model-A",
        vllm=True,
        gpu_devices="0,1",
        vllm_config=VllmConfig(tensor_parallel_size=tp, enable_sleep_mode=True),
    )


def test_build_cmd_uses_sharded_dir(tmp_path: Path, monkeypatch) -> None:
    handle = VllmProcessHandle("lane-x", 19010, OllamaConfig(), VllmEngineConfig())
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _c: ["/tmp/vllm"])
    lane = _lane(2, tmp_path)
    handle._sharded_model_dir = "/cache/.sharded_cache/org__Model-A/tp2"
    cmd = handle._build_cmd(lane)
    # The serve *target* is the sharded directory (so each rank reads its shard)...
    assert cmd[cmd.index("serve") + 1] == "/cache/.sharded_cache/org__Model-A/tp2"
    assert "--load-format" in cmd
    assert cmd[cmd.index("--load-format") + 1] == "sharded_state"
    # ...but the served *name* must alias back to the real model id, or every
    # request addressing the model by name gets HTTP 404 from vLLM.
    assert "--served-model-name" in cmd
    assert cmd[cmd.index("--served-model-name") + 1] == "org/Model-A"


def test_build_cmd_full_checkpoint_when_not_sharded(tmp_path: Path, monkeypatch) -> None:
    handle = VllmProcessHandle("lane-y", 19011, OllamaConfig(), VllmEngineConfig())
    monkeypatch.setattr(handle, "_resolve_vllm_binary", lambda _c: ["/tmp/vllm"])
    lane = _lane(2, tmp_path)
    cmd = handle._build_cmd(lane)
    assert "org/Model-A" in cmd
    assert "--load-format" not in cmd


def test_maybe_prepare_uses_existing_checkpoint(tmp_path: Path) -> None:
    gc = OllamaConfig(models_path=str(tmp_path))
    handle = VllmProcessHandle("lane-z", 19012, gc, VllmEngineConfig())
    lane = _lane(2, tmp_path)
    ready = sc.sharded_checkpoint_dir(str(tmp_path), "org/Model-A", 2)
    ready.mkdir(parents=True)
    (ready / sc._COMPLETION_MARKER).write_text("ok")

    asyncio.run(handle._maybe_prepare_sharded_checkpoint(lane))
    assert handle._sharded_model_dir == str(ready)


def test_maybe_prepare_skips_when_disabled(tmp_path: Path) -> None:
    gc = OllamaConfig(models_path=str(tmp_path))
    handle = VllmProcessHandle("lane-d", 19013, gc, VllmEngineConfig(sharded_checkpoint_enabled=False))
    lane = _lane(2, tmp_path)
    ready = sc.sharded_checkpoint_dir(str(tmp_path), "org/Model-A", 2)
    ready.mkdir(parents=True)
    (ready / sc._COMPLETION_MARKER).write_text("ok")

    asyncio.run(handle._maybe_prepare_sharded_checkpoint(lane))
    assert handle._sharded_model_dir is None


def test_maybe_prepare_tp1_noop(tmp_path: Path) -> None:
    gc = OllamaConfig(models_path=str(tmp_path))
    handle = VllmProcessHandle("lane-1", 19014, gc, VllmEngineConfig())
    lane = _lane(1, tmp_path)
    asyncio.run(handle._maybe_prepare_sharded_checkpoint(lane))
    assert handle._sharded_model_dir is None


def test_maybe_prepare_convert_on_spawn_disabled(tmp_path: Path, monkeypatch) -> None:
    gc = OllamaConfig(models_path=str(tmp_path))
    handle = VllmProcessHandle("lane-c", 19015, gc, VllmEngineConfig(sharded_checkpoint_convert_on_spawn=False))
    lane = _lane(2, tmp_path)

    def _boom(*_a, **_k):
        raise AssertionError("should not convert when convert_on_spawn is False")

    monkeypatch.setattr(sc, "ensure_sharded_checkpoint", _boom)
    asyncio.run(handle._maybe_prepare_sharded_checkpoint(lane))
    assert handle._sharded_model_dir is None
