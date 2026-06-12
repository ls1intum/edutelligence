from __future__ import annotations

import asyncio

import pytest

from logos_worker_node.models import LaneConfig, OllamaConfig
from logos_worker_node.ollama_process import OllamaProcessHandle


@pytest.mark.asyncio
async def test_spawn_uses_new_process_session(monkeypatch) -> None:
    handle = OllamaProcessHandle("lane-test", 19000, OllamaConfig())
    lane = LaneConfig(model="qwen2.5-coder:32b")

    class DummyProcess:
        pid = 4242
        returncode = None
        stdout = None

    captured: dict[str, object] = {}

    async def _fake_exec(*cmd, **kwargs):  # noqa: ANN001
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return DummyProcess()

    async def _fake_wait_for_ready(timeout):  # noqa: ANN001
        return True

    async def _fake_preload_model(_model: str) -> bool:
        return True

    monkeypatch.setattr(handle, "_build_env", lambda _lane: {})
    monkeypatch.setattr(handle, "_wait_for_ready", _fake_wait_for_ready)
    monkeypatch.setattr(handle, "_preload_model", _fake_preload_model)
    monkeypatch.setattr("logos_worker_node.ollama_process.asyncio.create_subprocess_exec", _fake_exec)

    try:
        status = await handle.spawn(lane)
    finally:
        await handle.close()

    assert status.pid == 4242
    assert captured["kwargs"]["start_new_session"] is True
    assert handle._process_group_id == 4242


@pytest.mark.asyncio
async def test_kill_process_does_not_wait_forever_after_sigkill(monkeypatch) -> None:
    handle = OllamaProcessHandle("lane-test", 19000, OllamaConfig())

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
    monkeypatch.setattr("logos_worker_node.ollama_process.os.killpg", _fake_killpg)
    monkeypatch.setattr("logos_worker_node.ollama_process.asyncio.wait_for", _fake_wait_for)

    await handle._kill_process()

    assert len(calls) == 2
    assert handle._process_group_id is None
