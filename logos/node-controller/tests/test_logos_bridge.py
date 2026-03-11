from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from node_controller.logos_bridge import LogosBridgeClient
from node_controller.models import LaneStatus, LogosConfig, ProcessState, ProcessStatus


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
        backend="ollama",
        process=ProcessStatus(state=ProcessState.RUNNING, pid=1001),
        runtime_state="running",
        routing_url="http://127.0.0.1:19001",
        inference_endpoint="/v1/chat/completions",
        num_parallel=4,
        context_length=4096,
        kv_cache_type="q8_0",
        flash_attention=True,
    )


def test_derive_ws_url_uses_wss_for_https():
    cfg = LogosConfig(
        enabled=True,
        logos_url="https://logos.example:8080",
        provider_id=7,
        shared_key="secret",
    )
    client = LogosBridgeClient(_DummyApp(), cfg)
    ws_url = client._derive_ws_url("abc")  # noqa: SLF001
    assert ws_url == "wss://logos.example:8080/logosdb/providers/node/session?token=abc"


def test_derive_ws_url_rejects_http():
    cfg = LogosConfig(
        enabled=True,
        logos_url="http://logos.example:8080",
        provider_id=7,
        shared_key="secret",
    )
    client = LogosBridgeClient(_DummyApp(), cfg)
    with pytest.raises(RuntimeError):
        client._derive_ws_url("abc")  # noqa: SLF001


def test_derive_ws_url_allows_http_in_dev_mode():
    cfg = LogosConfig(
        enabled=True,
        logos_url="http://logos.example:8080",
        allow_insecure_http=True,
        provider_id=7,
        shared_key="secret",
    )
    client = LogosBridgeClient(_DummyApp(), cfg)
    ws_url = client._derive_ws_url("abc")  # noqa: SLF001
    assert ws_url == "ws://logos.example:8080/logosdb/providers/node/session?token=abc"


@pytest.mark.asyncio
async def test_authenticate_accepts_explicit_ws_url(monkeypatch):
    cfg = LogosConfig(
        enabled=True,
        logos_url="https://logos.example:8080",
        provider_id=9,
        shared_key="secret",
        node_id="node-9",
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
            assert url.endswith("/logosdb/providers/node/auth")
            return _Resp()

    monkeypatch.setattr("node_controller.logos_bridge.httpx.AsyncClient", lambda timeout=15.0: _HttpClient())
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

    cfg = LogosConfig(enabled=True, logos_url="https://logos.example", provider_id=1, shared_key="secret")
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

    monkeypatch.setattr("node_controller.logos_bridge.httpx.AsyncClient", lambda timeout=None: _HttpClient())
    result = await client._execute_infer_command(  # noqa: SLF001
        {"lane_id": "lane-a", "payload": {"messages": [{"role": "user", "content": "hi"}]}}
    )
    assert result["status_code"] == 200
    assert result["body"] == {"ok": True}
    lane_manager.increment_active_requests.assert_awaited_once_with("lane-a")
    lane_manager.decrement_active_requests.assert_awaited_once_with("lane-a")
