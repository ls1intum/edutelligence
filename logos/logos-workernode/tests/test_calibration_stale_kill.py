"""Calibration cleanup kills leftover probe processes and never a serving lane."""

from __future__ import annotations

from pathlib import Path

import pytest

from logos_worker_node import calibration
from logos_worker_node.vllm_compat import LANE_ENV_MARKER, PROBE_ENV_MARKER

PROBE_PORT = str(calibration._CALIBRATION_PORT)


def _process(root: Path, pid: int, args: list[str], *, pgid: int, env: dict[str, str] | None = None) -> None:
    entry = root / str(pid)
    entry.mkdir()
    (entry / "cmdline").write_bytes(b"\0".join(a.encode() for a in args) + b"\0")
    (entry / "environ").write_bytes(b"\0".join(f"{k}={v}".encode() for k, v in (env or {}).items()))
    # comm may contain spaces and parentheses; the pgid is field 5 after it.
    (entry / "stat").write_text(f"{pid} (VLLM::Worker (x)) S 1 {pgid} {pgid} 0 -1")


@pytest.fixture
def proc_root(tmp_path, monkeypatch):
    killed: list[int] = []
    monkeypatch.setattr(calibration, "_PROC_ROOT", tmp_path)
    monkeypatch.setattr(calibration.os, "kill", lambda pid, _sig: killed.append(pid))
    monkeypatch.setattr(calibration.os, "getpid", lambda: 1)
    monkeypatch.setattr(calibration.time, "sleep", lambda _s: None)
    monkeypatch.setattr(calibration, "_probe_process_groups", set())
    return tmp_path, killed


def _lane(root: Path, pid: int = 100) -> None:
    lane_env = {LANE_ENV_MARKER: "planner-qwen", "CUDA_VISIBLE_DEVICES": "0"}
    _process(root, pid, ["/opt/venv/bin/vllm", "serve", "Qwen/Qwen3.8-27B", "--port", "11436"], pgid=pid, env=lane_env)
    _process(root, pid + 1, ["VLLM::EngineCore"], pgid=pid, env=lane_env)


def test_only_the_probe_is_killed_while_a_lane_serves(proc_root):
    root, killed = proc_root
    _lane(root)
    probe_env = {PROBE_ENV_MARKER: "1", "CUDA_VISIBLE_DEVICES": "1,2"}
    _process(root, 200, ["/opt/venv/bin/vllm", "serve", "org/m", "--port", PROBE_PORT], pgid=200, env=probe_env)
    _process(root, 201, ["VLLM::Worker_TP0"], pgid=200, env=probe_env)

    calibration._kill_stale_vllm_workers()

    assert sorted(killed) == [200, 201]


def test_an_orphaned_probe_worker_is_still_killed(proc_root):
    root, killed = proc_root
    _lane(root)
    # The probe parent is gone; its worker was re-parented but keeps the marker.
    _process(root, 301, ["VLLM::Worker_TP1"], pgid=300, env={PROBE_ENV_MARKER: "1"})

    calibration._kill_stale_vllm_workers()

    assert killed == [301]


def test_a_spawned_probe_group_is_killed_even_without_the_marker(proc_root, monkeypatch):
    root, killed = proc_root
    _lane(root)
    monkeypatch.setattr(calibration, "_probe_process_groups", {400})
    _process(root, 401, ["VLLM::Worker_TP0"], pgid=400)

    calibration._kill_stale_vllm_workers()

    assert killed == [401]


def test_a_probe_from_an_older_build_is_found_by_its_port(proc_root):
    root, killed = proc_root
    _lane(root)
    _process(root, 500, ["python", "-m", "vllm", "serve", "org/m", f"--port={PROBE_PORT}"], pgid=500)
    _process(root, 501, ["VLLM::Worker_TP0"], pgid=500)
    # An unmarked vLLM process on another port is not a probe.
    _process(root, 600, ["/opt/venv/bin/vllm", "serve", "org/other", "--port", "11440"], pgid=600)

    calibration._kill_stale_vllm_workers()

    assert sorted(killed) == [500, 501]


def test_a_lane_on_the_calibration_port_is_never_killed(proc_root):
    root, killed = proc_root
    _process(
        root,
        700,
        ["/opt/venv/bin/vllm", "serve", "org/m", "--port", PROBE_PORT],
        pgid=700,
        env={LANE_ENV_MARKER: "planner-m"},
    )

    calibration._kill_stale_vllm_workers()

    assert killed == []


def test_probe_environment_is_marked_and_tracked(tmp_path, monkeypatch):
    seen: dict = {}

    class FakePopen:
        pid = 4242

        def __init__(self, cmd, env, **kwargs):
            seen["env"] = env
            seen["new_session"] = kwargs.get("start_new_session")

    monkeypatch.setenv(LANE_ENV_MARKER, "inherited")
    monkeypatch.setattr(calibration.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(calibration, "_probe_process_groups", set())
    calibration.spawn_vllm({"model": "org/m"}, "vllm", "127.0.0.1", 11499, tmp_path / "log", "1G")

    assert seen["env"][PROBE_ENV_MARKER] == "1"
    assert LANE_ENV_MARKER not in seen["env"]
    assert seen["new_session"] is True
    assert calibration._probe_process_groups == {4242}


def test_lane_environment_carries_the_lane_marker(tmp_path, monkeypatch):
    from logos_worker_node.models import LaneConfig, VllmConfig, WorkerConfig
    from logos_worker_node.vllm_process import VllmProcessHandle

    # Keep the caches the lane environment points at inside the test directory.
    monkeypatch.delenv("LOGOS_WORKER_CACHE_ROOT", raising=False)
    handle = VllmProcessHandle("planner-qwen", 19000, WorkerConfig(models_path=str(tmp_path)))
    monkeypatch.setattr(handle, "_resolve_hf_home", lambda root: f"{root}/.hf_cache")
    env = handle._build_env(LaneConfig(model="org/m", vllm=True, vllm_config=VllmConfig()))
    assert env[LANE_ENV_MARKER] == "planner-qwen"
    assert PROBE_ENV_MARKER not in env


def test_every_process_of_a_probe_is_killed_whatever_its_command_line(proc_root):
    root, killed = proc_root
    _lane(root)
    _process(
        root,
        800,
        ["python", "-c", "from multiprocessing.resource_tracker import main"],
        pgid=800,
        env={PROBE_ENV_MARKER: "1"},
    )
    # An unrelated process without vLLM in its command line stays.
    _process(root, 900, ["sleep", "100"], pgid=900)

    calibration._kill_stale_vllm_workers()

    assert killed == [800]
