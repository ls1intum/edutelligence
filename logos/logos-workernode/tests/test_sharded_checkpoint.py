from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

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


def _lane(tp: int, tmp_path: Path, sharded: bool | None = None) -> LaneConfig:
    return LaneConfig(
        model="org/Model-A",
        vllm=True,
        gpu_devices="0,1",
        vllm_config=VllmConfig(
            tensor_parallel_size=tp,
            enable_sleep_mode=True,
            **({"sharded_checkpoint_enabled": sharded} if sharded is not None else {}),
        ),
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


# ---------------------------------------------------------------------------
# A checkpoint the loader rejects
#
# The conversion can report success — shards written, marker placed — and still
# produce something vLLM refuses to load (observed with an MXFP4 model at tp=2:
# "size of tensor a (1536) must match the size of tensor b (6144)"). Nothing in
# the produced files says so, so every later spawn picks the same directory up
# as ready. For a model the worker keeps warm that is a permanent outage of
# that model, surfacing only as a failed add_lane.
# ---------------------------------------------------------------------------


def test_invalidate_removes_a_ready_checkpoint(tmp_path: Path) -> None:
    target = sc.sharded_checkpoint_dir(str(tmp_path), "org/Model-A", 2)
    target.mkdir(parents=True)
    (target / sc._COMPLETION_MARKER).write_text("ok")
    (target / "model-rank-0-part-0.safetensors").write_bytes(b"junk")

    assert sc.invalidate_sharded_checkpoint(target) is True
    assert not target.exists()
    assert sc.is_sharded_checkpoint_ready(target) is False


def test_invalidate_is_a_noop_when_nothing_is_cached(tmp_path: Path) -> None:
    target = sc.sharded_checkpoint_dir(str(tmp_path), "org/Model-A", 2)
    assert sc.invalidate_sharded_checkpoint(target) is False


def test_a_rejected_checkpoint_is_detected_from_the_logs(tmp_path: Path) -> None:
    handle = VllmProcessHandle("lane-s", 19020, OllamaConfig(), VllmEngineConfig())
    handle._recent_logs = [
        'File ".../vllm/model_executor/model_loader/sharded_state_loader.py", line 154, in load_weights',
        "RuntimeError: The size of tensor a (1536) must match the size of tensor b (6144)",
    ]

    # Only while this lane actually serves a sharded checkpoint — the same
    # traceback for a lane on the full checkpoint means something else.
    assert handle.has_broken_sharded_checkpoint is False
    handle._sharded_model_dir = "/cache/.sharded_cache/org__Model-A/tp2"
    assert handle.has_broken_sharded_checkpoint is True


def test_an_unrelated_startup_failure_is_not_blamed_on_the_checkpoint() -> None:
    handle = VllmProcessHandle("lane-s", 19021, OllamaConfig(), VllmEngineConfig())
    handle._sharded_model_dir = "/cache/.sharded_cache/org__Model-A/tp2"
    handle._recent_logs = ["torch.OutOfMemoryError: CUDA out of memory."]

    assert handle.has_broken_sharded_checkpoint is False


def test_spawn_retries_from_the_full_checkpoint_after_a_rejection(tmp_path: Path, monkeypatch) -> None:
    """The lane must come up on the full checkpoint instead of failing. Without
    this a rejected conversion takes the model down for good: a model pinned
    awake (enable_sleep_mode: false) has no other path back up."""
    gc = OllamaConfig(models_path=str(tmp_path))
    handle = VllmProcessHandle("lane-r", 19022, gc, VllmEngineConfig())
    lane = _lane(2, tmp_path)
    target = sc.sharded_checkpoint_dir(str(tmp_path), "org/Model-A", 2)
    target.mkdir(parents=True)
    (target / sc._COMPLETION_MARKER).write_text("ok")

    monkeypatch.setattr(handle, "_purge_compile_caches_if_versions_changed", lambda: [])
    monkeypatch.setattr(handle, "_write_compile_cache_stamp", lambda: None)
    attempts: list[str | None] = []

    async def _spawn_once(lane_config):
        handle._sharded_model_dir = None  # as the real _spawn_once does
        await handle._maybe_prepare_sharded_checkpoint(lane_config)
        attempts.append(handle._sharded_model_dir)
        if handle._sharded_model_dir:
            handle._recent_logs = ["... sharded_state_loader.py, line 154, in load_weights"]
            raise RuntimeError("vLLM exited during startup (return_code=1)")
        return "ok"

    monkeypatch.setattr(handle, "_spawn_once", _spawn_once)

    assert asyncio.run(handle.spawn(lane)) == "ok"
    assert attempts == [str(target), None], "second attempt must serve the full checkpoint"
    assert not target.exists(), "the unusable conversion must be discarded"


def test_spawn_does_not_retry_twice_for_the_same_reason(tmp_path: Path, monkeypatch) -> None:
    """One retry. A failure that survives serving the full checkpoint is a real
    fault and has to reach the caller."""
    gc = OllamaConfig(models_path=str(tmp_path))
    handle = VllmProcessHandle("lane-r2", 19023, gc, VllmEngineConfig())
    lane = _lane(2, tmp_path)
    target = sc.sharded_checkpoint_dir(str(tmp_path), "org/Model-A", 2)
    target.mkdir(parents=True)
    (target / sc._COMPLETION_MARKER).write_text("ok")

    monkeypatch.setattr(handle, "_purge_compile_caches_if_versions_changed", lambda: [])
    monkeypatch.setattr(handle, "_write_compile_cache_stamp", lambda: None)
    monkeypatch.setattr(handle, "_purge_compile_caches", lambda: [])
    attempts: list[str | None] = []

    async def _spawn_once(lane_config):
        handle._sharded_model_dir = None  # as the real _spawn_once does
        await handle._maybe_prepare_sharded_checkpoint(lane_config)
        attempts.append(handle._sharded_model_dir)
        handle._recent_logs = ["... sharded_state_loader.py, line 154, in load_weights"]
        raise RuntimeError("vLLM exited during startup (return_code=1)")

    monkeypatch.setattr(handle, "_spawn_once", _spawn_once)

    with pytest.raises(RuntimeError, match="exited during startup"):
        asyncio.run(handle.spawn(lane))
    assert len(attempts) == 2


def test_maybe_prepare_per_model_opt_out(tmp_path: Path) -> None:
    """A per-model false must beat the worker-wide true: this one model loads
    the full checkpoint while every other model keeps the optimization."""
    gc = OllamaConfig(models_path=str(tmp_path))
    handle = VllmProcessHandle("lane-p1", 19031, gc, VllmEngineConfig())  # worker-wide ON
    lane = _lane(2, tmp_path, sharded=False)
    ready = sc.sharded_checkpoint_dir(str(tmp_path), "org/Model-A", 2)
    ready.mkdir(parents=True)
    (ready / sc._COMPLETION_MARKER).write_text("ok")

    asyncio.run(handle._maybe_prepare_sharded_checkpoint(lane))
    assert handle._sharded_model_dir is None


def test_maybe_prepare_per_model_opt_in_overrides_worker_off(tmp_path: Path) -> None:
    gc = OllamaConfig(models_path=str(tmp_path))
    handle = VllmProcessHandle("lane-p2", 19032, gc, VllmEngineConfig(sharded_checkpoint_enabled=False))
    lane = _lane(2, tmp_path, sharded=True)
    ready = sc.sharded_checkpoint_dir(str(tmp_path), "org/Model-A", 2)
    ready.mkdir(parents=True)
    (ready / sc._COMPLETION_MARKER).write_text("ok")

    asyncio.run(handle._maybe_prepare_sharded_checkpoint(lane))
    assert handle._sharded_model_dir == str(ready)


# ---------------------------------------------------------------------------
# Memory of a rejected conversion
#
# The discard + full-checkpoint retry gets the spawn that found the broken
# shards through, but the rejection is otherwise only remembered per handle:
# a fresh spawn (worker restart, lane re-placement) re-runs the same broken
# conversion from scratch — up to an hour of GPU time — only to discard the
# result again. The persistent rejection record breaks that loop.
# ---------------------------------------------------------------------------


def test_invalidate_writes_a_rejection_record(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(sc, "_current_engine_versions", lambda: {"vllm": "0.27.1"})
    target = sc.sharded_checkpoint_dir(str(tmp_path), "org/Model-A", 2)
    target.mkdir(parents=True)
    (target / sc._COMPLETION_MARKER).write_text("ok")
    (target / "model-rank-0-part-0.safetensors").write_bytes(b"junk")

    assert sc.invalidate_sharded_checkpoint(target) is True
    assert not target.exists()

    marker = target.parent / sc._REJECTED_MARKER
    assert marker.is_file()
    record = json.loads(marker.read_text(encoding="utf-8"))
    assert record["tp2"]["vllm"] == "0.27.1"
    assert "at" in record["tp2"]
    assert sc.is_sharded_checkpoint_rejected(target) is True


def test_rejection_record_does_not_block_other_tp_or_models(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(sc, "_current_engine_versions", lambda: {"vllm": "0.27.1"})
    target = sc.sharded_checkpoint_dir(str(tmp_path), "org/Model-A", 2)
    target.mkdir(parents=True)
    (target / sc._COMPLETION_MARKER).write_text("ok")
    sc.invalidate_sharded_checkpoint(target)

    assert sc.is_sharded_checkpoint_rejected(target) is True
    assert sc.is_sharded_checkpoint_rejected(sc.sharded_checkpoint_dir(str(tmp_path), "org/Model-A", 4)) is False
    assert sc.is_sharded_checkpoint_rejected(sc.sharded_checkpoint_dir(str(tmp_path), "org/Other", 2)) is False


def test_ensure_skips_conversion_for_a_rejected_build(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(sc, "_current_engine_versions", lambda: {"vllm": "0.27.1"})
    target = sc.sharded_checkpoint_dir(str(tmp_path), "org/Model-A", 2)
    target.mkdir(parents=True)
    (target / sc._COMPLETION_MARKER).write_text("ok")
    sc.invalidate_sharded_checkpoint(target)

    def _boom(*_a, **_k):
        raise AssertionError("a rejected conversion must not be re-run")

    monkeypatch.setattr(sc, "_run_conversion_subprocess", _boom)
    assert sc.ensure_sharded_checkpoint(model="org/Model-A", tensor_parallel_size=2, cache_root=str(tmp_path)) is None


def test_ensure_retries_conversion_after_an_engine_bump(tmp_path: Path, monkeypatch) -> None:
    # The rejection is pinned to the build that produced the bad shards; a
    # newer build may round-trip the layout, so the verdict clears.
    monkeypatch.setattr(sc, "_current_engine_versions", lambda: {"vllm": "0.27.1"})
    target = sc.sharded_checkpoint_dir(str(tmp_path), "org/Model-A", 2)
    target.mkdir(parents=True)
    (target / sc._COMPLETION_MARKER).write_text("ok")
    sc.invalidate_sharded_checkpoint(target)
    monkeypatch.setattr(sc, "_current_engine_versions", lambda: {"vllm": "0.28.0"})

    def _fake_convert(cmd, env, log_path, timeout_s, cancel_event):
        out = Path(cmd[cmd.index("--output") + 1])
        (out / "model-rank-0-part-0.safetensors").write_text("weights")
        return True

    monkeypatch.setattr(sc, "_run_conversion_subprocess", _fake_convert)
    out = sc.ensure_sharded_checkpoint(model="org/Model-A", tensor_parallel_size=2, cache_root=str(tmp_path))
    assert out is not None
    assert sc.is_sharded_checkpoint_ready(out)


def test_unresolvable_engine_version_keeps_the_rejection(tmp_path: Path, monkeypatch) -> None:
    # No readable vLLM/torch metadata means the build cannot be proven to have
    # changed, so the rejection stands — the lane keeps working on the full
    # checkpoint instead of looping reconversions.
    monkeypatch.setattr(sc, "_current_engine_versions", lambda: {})
    target = sc.sharded_checkpoint_dir(str(tmp_path), "org/Model-A", 2)
    target.mkdir(parents=True)
    (target / sc._COMPLETION_MARKER).write_text("ok")
    sc.invalidate_sharded_checkpoint(target)

    assert sc.is_sharded_checkpoint_rejected(target) is True

    def _boom(*_a, **_k):
        raise AssertionError("a rejected conversion must not be re-run")

    monkeypatch.setattr(sc, "_run_conversion_subprocess", _boom)
    assert sc.ensure_sharded_checkpoint(model="org/Model-A", tensor_parallel_size=2, cache_root=str(tmp_path)) is None


def test_fresh_handle_after_rejection_serves_full_checkpoint_without_converting(
    tmp_path: Path, monkeypatch
) -> None:
    """A fresh handle (worker restart, re-placed lane) must not re-run a
    conversion the loader already rejected. The lane comes up from the full
    checkpoint without paying for — and failing — the same broken conversion
    again; for a model the worker keeps awake that is a permanent outage,
    surfacing only as a failed add_lane."""
    gc = OllamaConfig(models_path=str(tmp_path))
    handle = VllmProcessHandle("lane-restart", 19030, gc, VllmEngineConfig())
    lane = _lane(2, tmp_path)
    target = sc.sharded_checkpoint_dir(str(tmp_path), "org/Model-A", 2)
    target.mkdir(parents=True)
    (target / sc._COMPLETION_MARKER).write_text("ok")

    # An earlier spawn rejected the conversion; the discard recorded it.
    monkeypatch.setattr(sc, "_current_engine_versions", lambda: {"vllm": "0.27.1"})
    assert sc.invalidate_sharded_checkpoint(target) is True

    # This handle has no in-memory memory of the rejection — only the
    # persistent record does. The conversion must not run at all.
    monkeypatch.setattr(handle, "_purge_compile_caches_if_versions_changed", lambda: [])
    monkeypatch.setattr(handle, "_write_compile_cache_stamp", lambda: None)

    def _boom(*_a, **_k):
        raise AssertionError("must not re-convert a checkpoint the loader already rejected")

    monkeypatch.setattr(sc, "_run_conversion_subprocess", _boom)
    attempts: list[str | None] = []

    async def _spawn_once(lane_config):
        handle._sharded_model_dir = None  # as the real _spawn_once does
        await handle._maybe_prepare_sharded_checkpoint(lane_config)
        attempts.append(handle._sharded_model_dir)
        return "ok"

    monkeypatch.setattr(handle, "_spawn_once", _spawn_once)

    assert asyncio.run(handle.spawn(lane)) == "ok"
    assert attempts == [None], "the restarted lane must serve the full checkpoint"
