from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from logos_worker_node.logos_bridge import LogosBridgeClient
from logos_worker_node.models import LaneStatus, LogosConfig, ProcessState, ProcessStatus


class _DummyState:
    pass


class _DummyApp:
    def __init__(self) -> None:
        self.state = _DummyState()


def _make_lane_status() -> LaneStatus:
    return LaneStatus(
        lane_id="lane-a",
        lane_uid="ollama:lane-a",
        model="qwen2.5-coder:32b",
        port=19001,
        vllm=False,
        process=ProcessStatus(state=ProcessState.RUNNING, pid=1001),
        runtime_state="running",
        routing_url="http://127.0.0.1:19001",
        inference_endpoint="/v1/chat/completions",
        num_parallel=4,
        context_length=4096,
        keep_alive="5m",
        kv_cache_type="q8_0",
        flash_attention=True,
    )


def test_derive_ws_url_uses_wss_for_https():
    cfg = LogosConfig(
        enabled=True,
        logos_url="https://logos.example:8080",
        shared_key="secret",
    )
    client = LogosBridgeClient(_DummyApp(), cfg)
    ws_url = client._derive_ws_url("abc")  # noqa: SLF001
    assert ws_url == "wss://logos.example:8080/logosdb/providers/logosnode/session?token=abc"


def test_derive_ws_url_uses_ws_for_http():
    cfg = LogosConfig(
        enabled=True,
        logos_url="http://logos.example:8080",
        shared_key="secret",
    )
    client = LogosBridgeClient(_DummyApp(), cfg)
    assert client._derive_ws_url("abc") == "ws://logos.example:8080/logosdb/providers/logosnode/session?token=abc"  # noqa: SLF001


def test_derive_ws_url_allows_http_in_dev_mode():
    cfg = LogosConfig(
        enabled=True,
        logos_url="http://logos.example:8080",
        allow_insecure_http=True,
        shared_key="secret",
    )
    client = LogosBridgeClient(_DummyApp(), cfg)
    ws_url = client._derive_ws_url("abc")  # noqa: SLF001
    assert ws_url == "ws://logos.example:8080/logosdb/providers/logosnode/session?token=abc"


@pytest.mark.asyncio
async def test_authenticate_accepts_explicit_ws_url(monkeypatch):
    cfg = LogosConfig(
        enabled=True,
        logos_url="https://logos.example:8080",
        shared_key="secret",
        capabilities_models=["model-a"],
    )
    client = LogosBridgeClient(_DummyApp(), cfg)

    class _Resp:
        status_code = 200
        content = b'{"ws_url":"wss://logos.example/ws","session_token":"tok"}'

        @staticmethod
        def json():
            return {"ws_url": "wss://logos.example/ws", "session_token": "tok"}

        text = '{"ws_url":"wss://logos.example/ws","session_token":"tok"}'

    class _HttpClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):  # noqa: ARG002
            return None

        async def post(self, url: str, json=None):  # noqa: ARG002
            assert url.endswith("/logosdb/providers/logosnode/auth")
            return _Resp()

    monkeypatch.setattr("logos_worker_node.logos_bridge.httpx.AsyncClient", lambda timeout=15.0: _HttpClient())
    auth = await client._authenticate()  # noqa: SLF001
    assert auth["ws_url"] == "wss://logos.example/ws"


@pytest.mark.asyncio
async def test_execute_infer_command_passthrough(monkeypatch):
    app = _DummyApp()
    lane_manager = type("LaneMgr", (), {})()
    lane_manager.get_lane_status = AsyncMock(return_value=_make_lane_status())
    lane_manager.increment_active_requests = AsyncMock(return_value=None)
    lane_manager.decrement_active_requests = AsyncMock(return_value=None)
    app.state.lane_manager = lane_manager
    app.state.gpu_collector = object()

    cfg = LogosConfig(enabled=True, logos_url="https://logos.example", shared_key="secret")
    client = LogosBridgeClient(app, cfg)

    class _Resp:
        status_code = 200
        headers = {"content-type": "application/json"}
        text = '{"ok": true}'

        @staticmethod
        def json():
            return {"ok": True}

    class _HttpClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):  # noqa: ARG002
            return None

        async def post(self, url, headers=None, json=None):  # noqa: ARG002
            assert url.endswith("/v1/chat/completions")
            return _Resp()

    monkeypatch.setattr("logos_worker_node.logos_bridge.httpx.AsyncClient", lambda timeout=None: _HttpClient())
    result = await client._execute_infer_command(  # noqa: SLF001
        {"lane_id": "lane-a", "payload": {"messages": [{"role": "user", "content": "hi"}]}}
    )
    assert result["status_code"] == 200
    assert result["body"] == {"ok": True}
    lane_manager.increment_active_requests.assert_awaited_once_with("lane-a")
    lane_manager.decrement_active_requests.assert_awaited_once_with("lane-a")


@pytest.mark.asyncio
async def test_handle_message_runs_stream_command_in_background():
    app = _DummyApp()
    app.state.lane_manager = object()
    app.state.gpu_collector = object()

    cfg = LogosConfig(enabled=True, logos_url="https://logos.example", shared_key="secret")
    client = LogosBridgeClient(app, cfg)

    started = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()

    async def _fake_execute_stream_command(ws, cmd_id, params):  # noqa: ARG001
        assert cmd_id == "cmd-stream"
        assert params == {"lane_id": "lane-a"}
        started.set()
        await release.wait()
        finished.set()

    client._execute_stream_command = _fake_execute_stream_command  # type: ignore[method-assign]  # noqa: SLF001

    handle_task = asyncio.create_task(
        client._handle_message(  # noqa: SLF001
            object(),
            json.dumps(
                {
                    "type": "command",
                    "cmd_id": "cmd-stream",
                    "action": "infer_stream",
                    "params": {"lane_id": "lane-a"},
                }
            ),
        )
    )

    await started.wait()
    await asyncio.sleep(0)

    assert handle_task.done()
    assert len(client._command_tasks) == 1  # noqa: SLF001
    assert not finished.is_set()

    background_tasks = tuple(client._command_tasks)  # noqa: SLF001
    release.set()
    await asyncio.gather(*background_tasks)

    assert finished.is_set()


@pytest.mark.asyncio
async def test_handle_message_runs_infer_command_in_background():
    app = _DummyApp()
    app.state.lane_manager = object()
    app.state.gpu_collector = object()

    cfg = LogosConfig(enabled=True, logos_url="https://logos.example", shared_key="secret")
    client = LogosBridgeClient(app, cfg)

    started = asyncio.Event()
    release = asyncio.Event()
    sent_payloads: list[dict] = []

    async def _fake_execute_command(action, params):
        assert action == "infer"
        assert params == {"lane_id": "lane-a"}
        started.set()
        await release.wait()
        return {"ok": True}

    async def _fake_send_json(_ws, payload):
        sent_payloads.append(payload)

    client._execute_command = _fake_execute_command  # type: ignore[method-assign]  # noqa: SLF001
    client._send_json = _fake_send_json  # type: ignore[method-assign]  # noqa: SLF001

    handle_task = asyncio.create_task(
        client._handle_message(  # noqa: SLF001
            object(),
            json.dumps(
                {
                    "type": "command",
                    "cmd_id": "cmd-infer",
                    "action": "infer",
                    "params": {"lane_id": "lane-a"},
                }
            ),
        )
    )

    await started.wait()
    await asyncio.sleep(0)

    assert handle_task.done()
    assert len(client._command_tasks) == 1  # noqa: SLF001
    assert sent_payloads == []

    background_tasks = tuple(client._command_tasks)  # noqa: SLF001
    release.set()
    await asyncio.gather(*background_tasks)

    assert sent_payloads == [
        {
            "type": "command_result",
            "cmd_id": "cmd-infer",
            "success": True,
            "result": {"ok": True},
        }
    ]


@pytest.mark.asyncio
async def test_send_runtime_status_skips_unchanged_payload(monkeypatch):
    app = _DummyApp()
    app.state.lane_manager = object()
    app.state.gpu_collector = object()

    cfg = LogosConfig(enabled=True, logos_url="https://logos.example", shared_key="secret")
    client = LogosBridgeClient(app, cfg)

    runtime_payload = {
        "worker_id": "worker-1",
        "lanes": [{"lane_id": "lane-a", "runtime_state": "loaded"}],
    }

    monkeypatch.setattr(
        "logos_worker_node.logos_bridge.build_runtime_status",
        AsyncMock(return_value=SimpleNamespace(model_dump=lambda mode="json": runtime_payload)),
    )

    sends: list[dict] = []

    async def _fake_send_json(_ws, payload):
        sends.append(payload)

    client._send_json = _fake_send_json  # type: ignore[method-assign]  # noqa: SLF001

    sent_first = await client._send_runtime_status(object(), force=False)  # noqa: SLF001
    sent_second = await client._send_runtime_status(object(), force=False)  # noqa: SLF001
    sent_forced = await client._send_runtime_status(object(), force=True)  # noqa: SLF001

    assert sent_first is True
    assert sent_second is False
    assert sent_forced is True
    assert [payload["type"] for payload in sends] == ["status", "status"]


@pytest.mark.asyncio
async def test_send_heartbeat_uses_lightweight_payload():
    cfg = LogosConfig(enabled=True, logos_url="https://logos.example", shared_key="secret")
    client = LogosBridgeClient(_DummyApp(), cfg)

    sends: list[dict] = []

    async def _fake_send_json(_ws, payload):
        sends.append(payload)

    client._send_json = _fake_send_json  # type: ignore[method-assign]  # noqa: SLF001

    await client._send_heartbeat(object())  # noqa: SLF001

    assert len(sends) == 1
    payload = sends[0]
    assert payload["type"] == "heartbeat"
    assert "provider_id" not in payload
    assert payload["worker_id"] == client.worker_id
    assert isinstance(payload.get("timestamp"), str)


@pytest.mark.asyncio
async def test_heartbeat_loop_does_not_build_runtime_status(monkeypatch):
    cfg = LogosConfig(
        enabled=True,
        logos_url="https://logos.example",
        shared_key="secret",
        heartbeat_interval_seconds=1,
    )
    client = LogosBridgeClient(_DummyApp(), cfg)

    runtime_status = AsyncMock(side_effect=AssertionError("heartbeat should not build runtime status"))
    monkeypatch.setattr("logos_worker_node.logos_bridge.build_runtime_status", runtime_status)

    sends: list[dict] = []

    async def _fake_send_json(_ws, payload):
        sends.append(payload)
        client._stopping.set()

    async def _fake_sleep(_seconds):
        return None

    client._send_json = _fake_send_json  # type: ignore[method-assign]  # noqa: SLF001
    monkeypatch.setattr("logos_worker_node.logos_bridge.asyncio.sleep", _fake_sleep)

    await client._heartbeat_loop(object())  # noqa: SLF001

    assert [payload["type"] for payload in sends] == ["heartbeat"]
    runtime_status.assert_not_awaited()


def test_runtime_has_transient_lanes_uses_last_payload():
    cfg = LogosConfig(enabled=True, logos_url="https://logos.example", shared_key="secret")
    client = LogosBridgeClient(_DummyApp(), cfg)

    client._last_runtime_payload = {"lanes": [{"lane_id": "lane-a", "runtime_state": "loaded"}]}  # noqa: SLF001
    assert client._runtime_has_transient_lanes() is False  # noqa: SLF001

    client._last_runtime_payload = {"lanes": [{"lane_id": "lane-a", "runtime_state": "starting"}]}  # noqa: SLF001
    assert client._runtime_has_transient_lanes() is True  # noqa: SLF001
