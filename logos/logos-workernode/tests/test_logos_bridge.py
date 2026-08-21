from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from logos_worker_node.logos_bridge import LogosBridgeClient, _CalibrationSession
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
    assert (
        client._derive_ws_url("abc") == "ws://logos.example:8080/logosdb/providers/logosnode/session?token=abc"
    )  # noqa: SLF001


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

    monkeypatch.setattr(
        "logos_worker_node.logos_bridge.httpx.AsyncClient",
        lambda timeout=15.0: _HttpClient(),
    )
    auth = await client._authenticate()  # noqa: SLF001
    assert auth["ws_url"] == "wss://logos.example/ws"


@pytest.mark.asyncio
async def test_execute_infer_command_passthrough(monkeypatch):
    app = _DummyApp()
    lane_manager = type("LaneMgr", (), {})()
    lane_manager.get_lane_status = AsyncMock(return_value=_make_lane_status())
    # _execute_infer_command now atomically validates-and-counts via
    # acquire_lane_for_infer (replacing the separate resolve + increment).
    lane_manager.acquire_lane_for_infer = AsyncMock(return_value=_make_lane_status())
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

    monkeypatch.setattr(
        "logos_worker_node.logos_bridge.httpx.AsyncClient",
        lambda timeout=None: _HttpClient(),
    )
    result = await client._execute_infer_command(  # noqa: SLF001
        {
            "lane_id": "lane-a",
            "payload": {"messages": [{"role": "user", "content": "hi"}]},
        }
    )
    assert result["status_code"] == 200
    assert result["body"] == {"ok": True}
    lane_manager.acquire_lane_for_infer.assert_awaited_once_with("lane-a")
    lane_manager.decrement_active_requests.assert_awaited_once_with("lane-a")


@pytest.mark.asyncio
async def test_execute_infer_command_preserves_plain_text_that_is_valid_json(monkeypatch):
    app = _DummyApp()
    lane_manager = SimpleNamespace(
        acquire_lane_for_infer=AsyncMock(return_value=_make_lane_status()),
        decrement_active_requests=AsyncMock(return_value=None),
    )
    app.state.lane_manager = lane_manager

    client = LogosBridgeClient(
        app,
        LogosConfig(enabled=True, logos_url="https://logos.example", shared_key="secret"),
    )

    class _Resp:
        status_code = 200
        text = "null"

        def __init__(self):
            self.headers = {"content-type": "text/plain; charset=utf-8"}

        @staticmethod
        def json():
            return None

    class _HttpClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):  # noqa: ARG002
            return None

        async def post(self, url, headers=None, **kwargs):  # noqa: ARG002
            return _Resp()

    monkeypatch.setattr(
        "logos_worker_node.logos_bridge.httpx.AsyncClient",
        lambda timeout=None: _HttpClient(),
    )

    result = await client._execute_infer_command(  # noqa: SLF001
        {
            "lane_id": "lane-a",
            "request_path": "v1/audio/transcriptions",
            "payload": {
                "model": "whisper-1",
                "_logos_multipart": {
                    "fields": [["model", "whisper-1"]],
                    "files": [],
                },
            },
        }
    )

    assert result == {
        "status_code": 200,
        "body": "null",
        "headers": {"content-type": "text/plain; charset=utf-8"},
    }


@pytest.mark.asyncio
async def test_execute_infer_command_base64_encodes_binary_multipart_response(monkeypatch):
    app = _DummyApp()
    app.state.lane_manager = SimpleNamespace(
        acquire_lane_for_infer=AsyncMock(return_value=_make_lane_status()),
        decrement_active_requests=AsyncMock(return_value=None),
    )
    client = LogosBridgeClient(
        app,
        LogosConfig(enabled=True, logos_url="https://logos.example", shared_key="secret"),
    )

    class _Resp:
        status_code = 200
        content = b"\xff\x00ID3"
        text = "\ufffd\x00ID3"

        def __init__(self):
            self.headers = {"content-type": "audio/mpeg"}

        @staticmethod
        def json():
            raise ValueError("not JSON")

    class _HttpClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):  # noqa: ARG002
            return None

        async def post(self, url, headers=None, **kwargs):  # noqa: ARG002
            return _Resp()

    monkeypatch.setattr(
        "logos_worker_node.logos_bridge.httpx.AsyncClient",
        lambda timeout=None: _HttpClient(),
    )

    result = await client._execute_infer_command(  # noqa: SLF001
        {
            "lane_id": "lane-a",
            "request_path": "v1/audio/transcriptions",
            "payload": {
                "model": "audio-binary-model",
                "_logos_multipart": {
                    "fields": [["model", "audio-binary-model"]],
                    "files": [],
                },
            },
        }
    )

    assert result == {
        "status_code": 200,
        "body": None,
        "headers": {"content-type": "audio/mpeg"},
        "body_base64": "/wBJRDM=",
        "body_encoding": "base64",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("response_headers", [{}, {"content-type": "application/json"}])
async def test_execute_infer_command_preserves_binary_when_json_parsing_fails(monkeypatch, response_headers):
    app = _DummyApp()
    app.state.lane_manager = SimpleNamespace(
        acquire_lane_for_infer=AsyncMock(return_value=_make_lane_status()),
        decrement_active_requests=AsyncMock(return_value=None),
    )
    client = LogosBridgeClient(
        app,
        LogosConfig(enabled=True, logos_url="https://logos.example", shared_key="secret"),
    )

    class _Resp:
        status_code = 200
        headers = response_headers
        content = b"\xff\x00ID3"
        text = "\ufffd\x00ID3"

        @staticmethod
        def json():
            raise ValueError("not JSON")

    class _HttpClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):  # noqa: ARG002
            return None

        async def post(self, url, headers=None, **kwargs):  # noqa: ARG002
            return _Resp()

    monkeypatch.setattr(
        "logos_worker_node.logos_bridge.httpx.AsyncClient",
        lambda timeout=None: _HttpClient(),
    )

    result = await client._execute_infer_command(  # noqa: SLF001
        {
            "lane_id": "lane-a",
            "request_path": "v1/audio/transcriptions",
            "payload": {
                "model": "audio-binary-model",
                "_logos_multipart": {"fields": [], "files": []},
            },
        }
    )

    assert result["body"] is None
    assert result["body_base64"] == "/wBJRDM="
    assert result["body_encoding"] == "base64"


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


def test_lane_target_url_blocks_vllm_management_endpoints():
    """Ensure vLLM sleep/wake and other management endpoints cannot be reached
    through proxied inference requests."""
    lane_status = {"port": 11436, "inference_endpoint": "/v1/chat/completions"}

    for blocked_path in ("sleep", "wake_up", "is_sleeping", "pause", "resume"):
        with pytest.raises(ValueError, match="not allowed through the inference proxy"):
            LogosBridgeClient._lane_target_url(lane_status, request_path=blocked_path)

    # Normal inference paths should work fine
    url = LogosBridgeClient._lane_target_url(lane_status, request_path="v1/chat/completions")
    assert url == "http://127.0.0.1:11436/v1/chat/completions"

    url = LogosBridgeClient._lane_target_url(lane_status, request_path="v1/embeddings")
    assert url == "http://127.0.0.1:11436/v1/embeddings"


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


@pytest.mark.asyncio
async def test_status_refresh_loop_pushes_periodically_when_idle(monkeypatch):
    """Idle worker (no lane churn) must still resend runtime status periodically.

    Otherwise VRAM/host-memory telemetry only reaches the server on lane state
    changes, so a worker that recently freed VRAM keeps reporting the stale
    snapshot captured at the last lane transition.
    """
    cfg = LogosConfig(
        enabled=True,
        logos_url="https://logos.example",
        shared_key="secret",
        status_refresh_interval_seconds=5,
    )
    app = _DummyApp()

    class _StaticLaneManager:
        status_revision = 0

        async def wait_for_status_revision(self, last_revision, timeout=None):
            await asyncio.sleep(0)
            return last_revision  # never changes

    app.state.lane_manager = _StaticLaneManager()
    client = LogosBridgeClient(app, cfg)
    # _runtime_has_transient_lanes() reads _last_runtime_payload — keep it empty
    # so it returns False; the only thing that should drive a send is the timer.
    client._last_runtime_payload = {"lanes": []}  # noqa: SLF001

    send_calls: list[bool] = []

    async def _fake_send(_ws, force=False):
        send_calls.append(force)
        if len(send_calls) >= 3:
            client._stopping.set()
        return True

    client._send_runtime_status = _fake_send  # type: ignore[method-assign]  # noqa: SLF001

    # Advance the monotonic clock by more than the refresh interval on every
    # tick so the periodic branch fires.
    now = [0.0]
    fake_time = SimpleNamespace(monotonic=lambda: (now.__setitem__(0, now[0] + 10.0) or now[0]))
    monkeypatch.setattr("logos_worker_node.logos_bridge.time", fake_time)

    await asyncio.wait_for(client._status_refresh_loop(object()), timeout=1.0)  # noqa: SLF001

    assert len(send_calls) >= 3
    assert all(force is False for force in send_calls)


@pytest.mark.asyncio
async def test_status_refresh_loop_holds_off_before_interval_elapses(monkeypatch):
    """No lane churn + interval not elapsed → no runtime push."""
    cfg = LogosConfig(
        enabled=True,
        logos_url="https://logos.example",
        shared_key="secret",
        status_refresh_interval_seconds=60,
    )
    app = _DummyApp()

    iterations = [0]

    class _StaticLaneManager:
        status_revision = 0

        async def wait_for_status_revision(self, last_revision, timeout=None):
            await asyncio.sleep(0)
            iterations[0] += 1
            if iterations[0] >= 5:
                client._stopping.set()
            return last_revision

    app.state.lane_manager = _StaticLaneManager()
    client = LogosBridgeClient(app, cfg)
    client._last_runtime_payload = {"lanes": []}  # noqa: SLF001

    send_calls: list[bool] = []

    async def _fake_send(_ws, force=False):
        send_calls.append(force)
        return True

    client._send_runtime_status = _fake_send  # type: ignore[method-assign]  # noqa: SLF001

    # Monotonic stays constant → interval never elapses.
    fake_time = SimpleNamespace(monotonic=lambda: 0.0)
    monkeypatch.setattr("logos_worker_node.logos_bridge.time", fake_time)

    await asyncio.wait_for(client._status_refresh_loop(object()), timeout=1.0)  # noqa: SLF001

    assert send_calls == []


def test_runtime_has_transient_lanes_uses_last_payload():
    cfg = LogosConfig(enabled=True, logos_url="https://logos.example", shared_key="secret")
    client = LogosBridgeClient(_DummyApp(), cfg)

    client._last_runtime_payload = {"lanes": [{"lane_id": "lane-a", "runtime_state": "loaded"}]}  # noqa: SLF001
    assert client._runtime_has_transient_lanes() is False  # noqa: SLF001

    client._last_runtime_payload = {"lanes": [{"lane_id": "lane-a", "runtime_state": "starting"}]}  # noqa: SLF001
    assert client._runtime_has_transient_lanes() is True  # noqa: SLF001


def _make_app_for_calibration(tmp_path, *, vllm_disable_sleep=False, per_model_overrides=None):
    """Build a fake app.state for calibration-session tests."""
    from logos_worker_node.model_profiles import ModelProfileRegistry
    from logos_worker_node.models import AppConfig

    cfg_dict = {
        "engines": {
            "vllm": {
                "disable_sleep_mode": vllm_disable_sleep,
                "model_overrides": per_model_overrides or {},
            }
        },
    }
    cfg = AppConfig(**cfg_dict)
    app = _DummyApp()
    app.state.config = cfg
    app.state.model_profiles = ModelProfileRegistry(state_dir=tmp_path)
    app.state.model_cache = None
    # Minimal lane_manager stub: event_log + destroy_all + _mark_status_dirty.
    # The session driver records calibration_* events onto event_log directly
    # and marks status dirty after each model completes.
    lane_manager = type("LaneMgr", (), {})()
    lane_manager._event_log = []
    lane_manager._MAX_EVENT_LOG = 500
    lane_manager._mark_status_dirty = lambda: None
    lane_manager.destroy_all = AsyncMock(return_value=None)
    app.state.lane_manager = lane_manager
    return app


async def _drain_session(client) -> None:
    """Await the active session task, swallowing any cleanup exceptions."""
    session = client._active_calibration_session  # noqa: SLF001
    if session is None or session.task is None:
        return
    try:
        await session.task
    except Exception:
        pass


@pytest.mark.asyncio
async def test_start_calibration_session_returns_ok_and_runs_in_background(tmp_path, monkeypatch):
    """A normal session start: refuse only on node-unhealthy, otherwise
    return ok=True and let the background task walk the model list."""
    app = _make_app_for_calibration(tmp_path)
    cfg = LogosConfig(
        enabled=True,
        logos_url="https://logos.example",
        shared_key="secret",
        configured_models=[],  # empty list → session finishes as a no-op
    )
    client = LogosBridgeClient(app, cfg)

    response = await client._handle_start_calibration_session({"sleep_level": 1})  # noqa: SLF001
    assert response["ok"] is True
    assert response["sleep_level"] == 1
    assert "started_at" in response
    await _drain_session(client)

    events = [e.event for e in app.state.lane_manager._event_log]
    assert "calibration_session_started" in events
    assert "calibration_session_finished" in events
    # destroy_all is only called when there is at least one model to calibrate;
    # an empty configured_models list ends the session before that step.
    app.state.lane_manager.destroy_all.assert_not_awaited()


@pytest.mark.asyncio
async def test_start_calibration_session_refuses_when_node_unhealthy(tmp_path, monkeypatch):
    """Node-level degradation (GPU ERR, HF cache EIO, …) must bounce the
    session start RPC. The kv-cache search would fail the same way for
    every model in the session."""
    from logos_worker_node import node_health as _nh

    app = _make_app_for_calibration(tmp_path)
    cfg = LogosConfig(enabled=True, logos_url="https://logos.example", shared_key="secret")
    client = LogosBridgeClient(app, cfg)

    monkeypatch.setattr(
        _nh,
        "evaluate_node_health",
        lambda: _nh.NodeHealthStatus(
            healthy=False,
            checked_at="2026-06-05T00:00:00Z",
            reason_code="filesystem-eio",
            reason_detail="HF cache returned EIO",
        ),
    )

    response = await client._handle_start_calibration_session({"sleep_level": 1})  # noqa: SLF001
    assert response["ok"] is False
    assert response.get("node_unhealthy") is True
    assert response.get("reason_code") == "filesystem-eio"
    assert client._active_calibration_session is None  # noqa: SLF001


@pytest.mark.asyncio
async def test_start_calibration_session_refuses_when_one_in_progress(tmp_path):
    """A second start_calibration_session while the first is still running
    must be rejected. Caller is expected to stop_calibration_session first
    or wait for the terminal session event."""
    app = _make_app_for_calibration(tmp_path)
    cfg = LogosConfig(
        enabled=True,
        logos_url="https://logos.example",
        shared_key="secret",
        configured_models=[],
    )
    client = LogosBridgeClient(app, cfg)

    # Pre-claim the slot with a never-completing task so the second call
    # sees an active session.
    sentinel = asyncio.create_task(asyncio.sleep(60))
    from logos_worker_node.logos_bridge import _CalibrationSession

    session = _CalibrationSession(sleep_level=1)
    session.task = sentinel
    client._active_calibration_session = session  # noqa: SLF001
    try:
        response = await client._handle_start_calibration_session({"sleep_level": 1})  # noqa: SLF001
    finally:
        sentinel.cancel()
        try:
            await sentinel
        except asyncio.CancelledError:
            pass

    assert response["ok"] is False
    assert "already in progress" in response["error"]


@pytest.mark.asyncio
async def test_stop_calibration_session_sets_cancel_event(tmp_path):
    """stop_calibration_session must set the shared cancel_event so the
    calibration's wait_ready bails within ~2s instead of waiting out the
    full ready_timeout."""
    app = _make_app_for_calibration(tmp_path)
    cfg = LogosConfig(
        enabled=True,
        logos_url="https://logos.example",
        shared_key="secret",
        configured_models=[],
    )
    client = LogosBridgeClient(app, cfg)

    from logos_worker_node.logos_bridge import _CalibrationSession

    session = _CalibrationSession(sleep_level=1)
    session.current_model = "test/model"

    # The stop handler awaits the task with a 15s timeout. Use a task that
    # finishes immediately on cancel so the stop returns fast.
    async def _wait_then_finish():
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            raise

    session.task = asyncio.create_task(_wait_then_finish())
    client._active_calibration_session = session  # noqa: SLF001

    # We don't want to wait 15s for the test — cancel the task right after
    # the stop handler reads cancel_event, so wait_for returns.
    async def _force_complete():
        await asyncio.sleep(0.05)
        if not session.task.done():
            session.task.cancel()

    forcer = asyncio.create_task(_force_complete())
    response = await client._handle_stop_calibration_session()  # noqa: SLF001
    await forcer
    try:
        await session.task
    except (asyncio.CancelledError, Exception):
        pass

    assert response["ok"] is True
    assert response["was_active"] is True
    assert response["current_model"] == "test/model"
    assert session.cancel_event.is_set()


@pytest.mark.asyncio
async def test_stop_calibration_session_idempotent_when_no_session(tmp_path):
    """A stop with no active session is a no-op — important so the master
    can fire it on window close without worrying whether a session is
    actually running."""
    app = _make_app_for_calibration(tmp_path)
    cfg = LogosConfig(enabled=True, logos_url="https://logos.example", shared_key="secret")
    client = LogosBridgeClient(app, cfg)

    response = await client._handle_stop_calibration_session()  # noqa: SLF001
    assert response["ok"] is True
    assert response["was_active"] is False


def test_list_uncalibrated_skips_calibration_unsupported(tmp_path):
    """Models classified as permanently unsupported on this worker must not
    appear in the session's work list — every probe would fail the same
    way until ops removes the flag."""
    from logos_worker_node.model_profiles import ModelProfileRecord

    app = _make_app_for_calibration(tmp_path)
    cfg = LogosConfig(
        enabled=True,
        logos_url="https://logos.example",
        shared_key="secret",
        configured_models=["bad/repo", "good/model"],
    )
    client = LogosBridgeClient(app, cfg)
    app.state.model_profiles._profiles["bad/repo"] = ModelProfileRecord(
        calibration_unsupported=True,
        calibration_unsupported_reason="invalid-repo-id",
    )

    assert client._list_uncalibrated_models() == ["good/model"]  # noqa: SLF001


def test_list_uncalibrated_skips_sleep_disabled_models_already_measured(tmp_path):
    """A model whose worker config forbids sleep and that already has
    base_residency measured has nothing more to calibrate — the sleep
    fields are N/A by design."""
    from logos_worker_node.model_profiles import ModelProfileRecord

    app = _make_app_for_calibration(tmp_path, vllm_disable_sleep=True)
    cfg = LogosConfig(
        enabled=True,
        logos_url="https://logos.example",
        shared_key="secret",
        configured_models=["openai/gpt-oss-120b"],
    )
    client = LogosBridgeClient(app, cfg)
    app.state.model_profiles._profiles["openai/gpt-oss-120b"] = ModelProfileRecord(
        base_residency_mb=91203.0,
        sleep_mode_disabled=True,
    )

    assert client._list_uncalibrated_models() == []  # noqa: SLF001


def test_list_uncalibrated_flags_calibrated_profile_missing_pairs(tmp_path):
    """Profiles calibrated before the pair sweep must be recalibrated."""
    from logos_worker_node.model_profiles import ModelProfileRecord

    app = _make_app_for_calibration(tmp_path)
    cfg = LogosConfig(
        enabled=True,
        logos_url="https://logos.example",
        shared_key="secret",
        configured_models=["qwen/model"],
    )
    client = LogosBridgeClient(app, cfg)
    app.state.model_profiles._profiles["qwen/model"] = ModelProfileRecord(
        residency_source="calibrated",
        base_residency_mb=91203.0,
        sleeping_residual_mb=5000.0,
        sleep_l1_transient_host_ram_mb=4096.0,
        min_kv_cache_mb=1024.0,
        max_kv_cache_mb=8192.0,
        kv_cache_to_max_model_len_pairs=None,
    )

    assert client._list_uncalibrated_models() == ["qwen/model"]  # noqa: SLF001


@pytest.mark.asyncio
async def test_session_calibrates_sleep_disabled_model_without_sleep(tmp_path, monkeypatch):
    """A model that can't be slept on this worker is calibrated at
    sleep_level 0 rather than skipped: base_residency is measurable without
    sleep, and skipping left such a model permanently uncalibrated — and so
    never announced as a capability — with no way back."""
    from logos_worker_node import config as _wcfg
    from logos_worker_node.calibration import CalibrationResult

    monkeypatch.setattr(_wcfg, "STATE_DIR", tmp_path)
    app = _make_app_for_calibration(
        tmp_path,
        per_model_overrides={"openai/gpt-oss-120b": {"enable_sleep_mode": False}},
    )
    cfg = LogosConfig(
        enabled=True,
        logos_url="https://logos.example",
        shared_key="secret",
        configured_models=["openai/gpt-oss-120b", "microsoft/Phi-4-reasoning"],
    )
    client = LogosBridgeClient(app, cfg)

    # Mock the actual calibration so we don't spawn vLLM.
    seen_sleep_levels: dict[str, int] = {}

    def _fake_calibrate(plan, **kwargs):
        sleep_level = int(kwargs["sleep_level"])
        seen_sleep_levels[plan["model"]] = sleep_level
        return CalibrationResult(
            model=plan["model"],
            tensor_parallel_size=1,
            gpu_devices="0",
            kv_cache_sent_mb=2048.0,
            success=True,
            base_residency_mb=12345.0,
            sleeping_residual_mb=(512.0 if sleep_level > 0 else None),
            sleep_l1_transient_host_ram_mb=(4096.0 if sleep_level > 0 else None),
        )

    monkeypatch.setattr(
        "logos_worker_node.calibration.calibrate_with_tp_escalation",
        _fake_calibrate,
    )
    monkeypatch.setattr(
        "logos_worker_node.calibration.plans_from_config",
        lambda _p: [],
    )

    response = await client._handle_start_calibration_session({"sleep_level": 1})  # noqa: SLF001
    assert response["ok"] is True
    await _drain_session(client)

    events = [(e.event, e.model) for e in app.state.lane_manager._event_log]
    assert ("calibration_model_skipped", "openai/gpt-oss-120b") not in events
    assert ("calibration_model_completed", "openai/gpt-oss-120b") in events
    assert ("calibration_model_completed", "microsoft/Phi-4-reasoning") in events
    assert ("calibration_session_finished", "") in events
    # The nosleep model probed without sleep; the other one kept the session level.
    assert seen_sleep_levels == {"openai/gpt-oss-120b": 0, "microsoft/Phi-4-reasoning": 1}
    # sleep_mode_disabled persisted, and the measurement landed.
    nosleep_profile = app.state.model_profiles.get_profile("openai/gpt-oss-120b")
    assert nosleep_profile is not None
    assert nosleep_profile.sleep_mode_disabled is True
    assert nosleep_profile.base_residency_mb == 12345.0
    assert nosleep_profile.sleeping_residual_mb is None
    # The model is announced to Logos now that it has a profile.
    assert "openai/gpt-oss-120b" in client._cfg.capabilities_models  # noqa: SLF001


@pytest.mark.asyncio
async def test_nosleep_model_with_profile_is_not_recalibrated(tmp_path, monkeypatch):
    """A nosleep model calibrated at level 0 has null sleep fields by
    design. Those nulls must not read as "incomplete", or every session
    re-picks the model forever."""
    from logos_worker_node import config as _wcfg

    monkeypatch.setattr(_wcfg, "STATE_DIR", tmp_path)
    app = _make_app_for_calibration(
        tmp_path,
        per_model_overrides={"openai/gpt-oss-120b": {"enable_sleep_mode": False}},
    )
    app.state.model_profiles.seed_capabilities(["openai/gpt-oss-120b"])
    profile = app.state.model_profiles.get_profile("openai/gpt-oss-120b")
    profile.base_residency_mb = 98945.0
    profile.residency_source = "calibrated"
    profile.sleeping_residual_mb = None
    profile.sleep_l1_transient_host_ram_mb = None
    profile.sleep_mode_disabled = True
    profile.kv_cache_to_max_model_len_pairs = [{"kv_mb": 8192.0, "max_model_len": 32768}]

    cfg = LogosConfig(
        enabled=True,
        logos_url="https://logos.example",
        shared_key="secret",
        configured_models=["openai/gpt-oss-120b"],
    )
    client = LogosBridgeClient(app, cfg)

    assert client._list_uncalibrated_models() == []  # noqa: SLF001


@pytest.mark.asyncio
async def test_session_destroys_lanes_before_calibrating(tmp_path, monkeypatch):
    """Live lanes hold VRAM. The session must free everything up front or
    the kv-cache search OOMs and blacklists every probe size."""
    from logos_worker_node import config as _wcfg
    from logos_worker_node.calibration import CalibrationResult

    monkeypatch.setattr(_wcfg, "STATE_DIR", tmp_path)
    app = _make_app_for_calibration(tmp_path)
    cfg = LogosConfig(
        enabled=True,
        logos_url="https://logos.example",
        shared_key="secret",
        configured_models=["some/model"],
    )
    client = LogosBridgeClient(app, cfg)

    def _fake_calibrate(plan, **kwargs):
        return CalibrationResult(
            model=plan["model"],
            tensor_parallel_size=1,
            gpu_devices="0",
            kv_cache_sent_mb=2048.0,
            success=True,
            base_residency_mb=12345.0,
            sleeping_residual_mb=512.0,
            sleep_l1_transient_host_ram_mb=4096.0,
        )

    monkeypatch.setattr(
        "logos_worker_node.calibration.calibrate_with_tp_escalation",
        _fake_calibrate,
    )
    monkeypatch.setattr(
        "logos_worker_node.calibration.plans_from_config",
        lambda _p: [],
    )

    response = await client._handle_start_calibration_session({"sleep_level": 1})  # noqa: SLF001
    assert response["ok"] is True
    await _drain_session(client)

    app.state.lane_manager.destroy_all.assert_awaited_once()


# ── Streaming: defer stream_start until first token byte (wake-readiness fix) ──


class _CollectWS:
    def __init__(self) -> None:
        self.frames: list[dict] = []

    async def send(self, raw: str) -> None:
        self.frames.append(json.loads(raw))


class _FakeUpstream:
    def __init__(self, status_code: int, chunks: list[bytes]) -> None:
        self.status_code = status_code
        self.headers = {"content-type": "text/event-stream"}
        self._chunks = chunks

    async def aiter_bytes(self):
        for c in self._chunks:
            yield c

    async def aread(self) -> bytes:
        return b"".join(self._chunks)

    async def aclose(self) -> None:
        return None


class _FakeStreamClient:
    def __init__(self, upstream: _FakeUpstream) -> None:
        self._u = upstream

    def build_request(self, *a, **k):  # noqa: ANN002, ANN003
        return SimpleNamespace()

    async def send(self, request, stream=True):  # noqa: ARG002
        return self._u

    async def aclose(self) -> None:
        return None


async def _run_stream(monkeypatch, chunks: list[bytes], status_code: int = 200) -> list[dict]:
    app = _DummyApp()
    lane_manager = type("LaneMgr", (), {})()
    lane_manager.acquire_lane_for_infer = AsyncMock(return_value=_make_lane_status())
    lane_manager.decrement_active_requests = AsyncMock(return_value=None)
    app.state.lane_manager = lane_manager
    cfg = LogosConfig(enabled=True, logos_url="https://logos.example", shared_key="secret")
    client = LogosBridgeClient(app, cfg)
    upstream = _FakeUpstream(status_code, chunks)
    monkeypatch.setattr(
        "logos_worker_node.logos_bridge.httpx.AsyncClient",
        lambda timeout=None: _FakeStreamClient(upstream),
    )
    ws = _CollectWS()
    await client._execute_stream_command(  # noqa: SLF001
        ws, "cmd-1", {"lane_id": "lane-a", "payload": {"messages": []}}
    )
    return ws.frames


@pytest.mark.asyncio
async def test_stream_defers_start_until_first_byte(monkeypatch):
    frames = await _run_stream(monkeypatch, [b"tok1", b"tok2"])
    assert [f["type"] for f in frames] == ["stream_start", "stream_chunk", "stream_chunk", "stream_end"]
    assert frames[-1]["success"] is True


@pytest.mark.asyncio
async def test_stream_200_with_no_output_fails_clean_without_start(monkeypatch):
    # vLLM returns 200 headers but the (just-woken / re-slept) engine emits nothing:
    # must NOT send a client-visible stream_start, and must end as a clean failure
    # so the orchestrator can reroute instead of a 200-then-drop.
    frames = await _run_stream(monkeypatch, [])
    assert [f["type"] for f in frames] == ["stream_end"]
    assert frames[-1]["success"] is False
    assert "stream_start" not in [f["type"] for f in frames]


# ---------------------------------------------------------------------------
# VRAM-growing commands are refused while a calibration session holds the GPU
# ---------------------------------------------------------------------------


def _client_with_calibration_session(session_done: bool = False) -> LogosBridgeClient:
    app = _DummyApp()
    app.state.lane_manager = object()
    cfg = LogosConfig(enabled=True, logos_url="https://logos.example", shared_key="secret")
    client = LogosBridgeClient(app, cfg)

    session = _CalibrationSession(sleep_level=1)
    session.task = SimpleNamespace(done=lambda: session_done)
    client._active_calibration_session = session  # noqa: SLF001
    return client


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["add_lane", "apply_lanes", "wake_lane", "reconfigure_lane"])
async def test_vram_growing_commands_are_refused_during_calibration(action):
    """The session freed this node's VRAM for its probes. A lane placed now
    takes the memory they need and the kv-cache search fails at sizes that
    would otherwise fit — so the node refuses locally, whatever the server
    currently believes."""
    client = _client_with_calibration_session()

    result = await client._execute_command(action, {"lane_id": "lane-a"})  # noqa: SLF001

    assert result["ok"] is False
    assert result["calibrating"] is True
    assert action in result["error"]


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["delete_lane", "sleep_lane"])
async def test_vram_freeing_commands_are_still_accepted_during_calibration(action):
    """Only growth is refused — the guard must not block the server from
    freeing memory the session could use."""
    client = _client_with_calibration_session()
    calls: list[str] = []

    async def _remove_lane(lane_id):
        calls.append(f"remove:{lane_id}")

    async def _sleep_lane(lane_id, level=1, mode="wait"):  # noqa: ARG001
        calls.append(f"sleep:{lane_id}")
        return _make_lane_status()

    client._app.state.lane_manager = SimpleNamespace(  # noqa: SLF001
        remove_lane=_remove_lane,
        sleep_lane=_sleep_lane,
    )

    await client._execute_command(action, {"lane_id": "lane-a"})  # noqa: SLF001

    assert calls, f"{action} must reach the lane manager"


@pytest.mark.asyncio
async def test_a_finished_session_does_not_keep_refusing():
    """_active_calibration_session lingers until the next start clears it, so
    the task state is what decides — otherwise the node would refuse lanes
    forever after its first session."""
    client = _client_with_calibration_session(session_done=True)
    added: list[str] = []

    async def _add_lane(lane_config):
        added.append(lane_config.lane_id)
        return _make_lane_status()

    client._app.state.lane_manager = SimpleNamespace(add_lane=_add_lane)  # noqa: SLF001

    await client._execute_command(  # noqa: SLF001
        "add_lane",
        {"lane_id": "lane-a", "model": "qwen2.5-coder:32b"},
    )

    assert added == ["lane-a"]


def _event_stub(event_id: str, name: str):
    return SimpleNamespace(
        event_id=event_id,
        model_dump=lambda mode="json", _n=name: {"event": _n},
    )


def _bridge_client(app) -> LogosBridgeClient:
    cfg = LogosConfig(enabled=True, logos_url="https://logos.example", shared_key="secret")
    return LogosBridgeClient(app, cfg)


@pytest.mark.asyncio
async def test_event_loop_flags_only_the_backlog_that_existed_at_connect():
    """The first drain runs a second after the connect, so it carries both the
    backlog and anything created in that second. Only the backlog is history:
    a session ending inside that second produces a live terminal event, and
    dismissing it as backlog would leave the provider excluded from lane
    placement with no further event coming to release it."""
    app = _DummyApp()
    client = _bridge_client(app)

    log = [_event_stub("evt-1", "calibration_session_finished")]
    replay_ids = frozenset({"evt-1"})
    # The session ends between the connect and the drain.
    log.append(_event_stub("calib-9", "calibration_session_cancelled"))
    app.state.lane_manager = SimpleNamespace(event_log=log)

    sent: list[dict] = []

    async def _send_json(_ws, payload):
        sent.append(payload)
        if len(sent) == 2:
            client._stopping.set()  # noqa: SLF001

    client._send_json = _send_json  # type: ignore[method-assign]  # noqa: SLF001

    await client._event_loop(object(), replay_event_ids=replay_ids)  # noqa: SLF001

    assert [p["event"]["event"] for p in sent] == [
        "calibration_session_finished",
        "calibration_session_cancelled",
    ]
    assert [p["replay"] for p in sent] == [True, False]


@pytest.mark.asyncio
async def test_a_live_event_in_a_full_log_is_not_mistaken_for_backlog():
    """The log is capped and trims from the front, so on a full log a live event
    lands at a position the backlog used to occupy. Keyed on position it would
    be sent as replay, the server would ignore it, and a terminal event lost
    that way leaves the provider excluded with nothing left to release it."""
    app = _DummyApp()
    client = _bridge_client(app)

    cap = 500
    backlog = [_event_stub(f"evt-{n}", "lane_started") for n in range(1, cap + 1)]
    replay_ids = frozenset(event.event_id for event in backlog)

    # A live terminal event arrives; the append trims the oldest entry, so the
    # log length is unchanged and the new event sits at the last position.
    full_log = backlog[1:] + [_event_stub("calib-1", "calibration_session_finished")]
    assert len(full_log) == cap
    app.state.lane_manager = SimpleNamespace(event_log=full_log)

    sent: list[dict] = []

    async def _send_json(_ws, payload):
        sent.append(payload)
        if payload["event"]["event"] == "calibration_session_finished":
            client._stopping.set()  # noqa: SLF001

    client._send_json = _send_json  # type: ignore[method-assign]  # noqa: SLF001

    await client._event_loop(object(), replay_event_ids=replay_ids)  # noqa: SLF001

    terminal = [p for p in sent if p["event"]["event"] == "calibration_session_finished"]
    assert terminal, "the live terminal event must be forwarded"
    assert terminal[0]["replay"] is False


@pytest.mark.asyncio
async def test_event_loop_keeps_forwarding_once_the_log_is_full():
    """A positional cursor equals the log length once the log is full and never
    advances again, so no further event would reach the server at all."""
    app = _DummyApp()
    client = _bridge_client(app)

    cap = 500
    log = [_event_stub(f"evt-{n}", "lane_started") for n in range(1, cap + 1)]
    drains = {"count": 0}

    class _LaneManager:
        @property
        def event_log(self):
            drains["count"] += 1
            if drains["count"] == 1:
                return list(log)
            # Second drain: one new event, oldest trimmed — same length.
            return log[1:] + [_event_stub("evt-501", "lane_stopped")]

    app.state.lane_manager = _LaneManager()

    sent: list[dict] = []

    async def _send_json(_ws, payload):
        sent.append(payload)
        if payload["event"]["event"] == "lane_stopped":
            client._stopping.set()  # noqa: SLF001

    client._send_json = _send_json  # type: ignore[method-assign]  # noqa: SLF001

    await client._event_loop(object())  # noqa: SLF001

    assert len(sent) == cap + 1, "the event added to a full log must still be forwarded"
    assert sent[-1]["event"]["event"] == "lane_stopped"


@pytest.mark.asyncio
async def test_event_loop_does_not_resend_events_it_already_forwarded():
    app = _DummyApp()
    client = _bridge_client(app)

    log = [_event_stub("evt-1", "lane_started")]
    drains = {"count": 0}

    class _LaneManager:
        @property
        def event_log(self):
            drains["count"] += 1
            if drains["count"] >= 2:
                client._stopping.set()  # noqa: SLF001
            return list(log)

    app.state.lane_manager = _LaneManager()

    sent: list[dict] = []

    async def _send_json(_ws, payload):
        sent.append(payload)

    client._send_json = _send_json  # type: ignore[method-assign]  # noqa: SLF001

    await client._event_loop(object())  # noqa: SLF001

    assert len(sent) == 1


def test_current_event_ids_snapshots_the_log():
    app = _DummyApp()
    app.state.lane_manager = SimpleNamespace(
        event_log=[_event_stub("evt-1", "lane_started"), _event_stub("calib-1", "calibration_session_started")]
    )
    client = _bridge_client(app)

    assert client._current_event_ids() == frozenset({"evt-1", "calib-1"})  # noqa: SLF001

    app.state.lane_manager = None
    assert client._current_event_ids() == frozenset()  # noqa: SLF001


# ---------------------------------------------------------------------------
# The status carries the live calibration state
#
# The server excludes a calibrating worker from lane placement, and used to
# learn when that ended from a single lifecycle event. An event that never
# lands as a live one — dropped by the post-connect replay filter, belonging
# to a connection that is gone — left the worker excluded with nothing to
# release it. Observed in production as three workers holding no lanes for
# over seven hours, recovered only by restarting the container.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_reports_the_live_calibration_state(tmp_path, monkeypatch):
    app = _make_app_for_calibration(tmp_path)
    cfg = LogosConfig(enabled=True, logos_url="https://logos.example", shared_key="secret")
    client = LogosBridgeClient(app, cfg)

    monkeypatch.setattr(
        "logos_worker_node.logos_bridge.build_runtime_status",
        AsyncMock(return_value=SimpleNamespace(model_dump=lambda mode="json": {"lanes": []})),
    )
    sends: list[dict] = []

    async def _fake_send_json(_ws, payload):
        sends.append(payload)

    client._send_json = _fake_send_json  # type: ignore[method-assign]  # noqa: SLF001

    await client._send_runtime_status(object(), force=True)  # noqa: SLF001
    assert sends[-1]["calibrating"] is False

    client._active_calibration_session = _CalibrationSession(sleep_level=1)  # noqa: SLF001
    await client._send_runtime_status(object(), force=True)  # noqa: SLF001
    assert sends[-1]["calibrating"] is True


@pytest.mark.asyncio
async def test_a_session_ending_is_pushed_even_when_nothing_else_changed(tmp_path, monkeypatch):
    """A session that starts and ends without touching a lane changes nothing
    else in the payload. Left out of the dedupe signature, the status carrying
    calibrating=False would never be sent and the server would stay stuck."""
    app = _make_app_for_calibration(tmp_path)
    cfg = LogosConfig(enabled=True, logos_url="https://logos.example", shared_key="secret")
    client = LogosBridgeClient(app, cfg)

    monkeypatch.setattr(
        "logos_worker_node.logos_bridge.build_runtime_status",
        AsyncMock(return_value=SimpleNamespace(model_dump=lambda mode="json": {"lanes": []})),
    )
    sends: list[dict] = []

    async def _fake_send_json(_ws, payload):
        sends.append(payload)

    client._send_json = _fake_send_json  # type: ignore[method-assign]  # noqa: SLF001

    session = _CalibrationSession(sleep_level=1)
    client._active_calibration_session = session  # noqa: SLF001
    assert await client._send_runtime_status(object(), force=False) is True  # noqa: SLF001
    assert await client._send_runtime_status(object(), force=False) is False  # noqa: SLF001

    client._active_calibration_session = None  # noqa: SLF001
    assert await client._send_runtime_status(object(), force=False) is True  # noqa: SLF001
    assert [p["calibrating"] for p in sends] == [True, False]


@pytest.mark.asyncio
async def test_hello_reports_a_finished_session_as_not_calibrating(tmp_path, monkeypatch):
    """_active_calibration_session lingers until the next start clears it.
    Reporting that as live at connect would exclude the worker from placement
    for as long as no new session begins."""
    app = _make_app_for_calibration(tmp_path)
    app.state.lane_manager._static_lane_ids = set()
    cfg = LogosConfig(enabled=True, logos_url="https://logos.example", shared_key="secret")
    client = LogosBridgeClient(app, cfg)

    async def _already_done():
        return None

    done = _CalibrationSession(sleep_level=1)
    done.task = asyncio.create_task(_already_done())
    await done.task
    client._active_calibration_session = done  # noqa: SLF001

    sends: list[dict] = []

    async def _fake_send_json(_ws, payload):
        sends.append(payload)

    client._send_json = _fake_send_json  # type: ignore[method-assign]  # noqa: SLF001
    await client._send_hello(object())  # noqa: SLF001

    assert sends[-1]["calibrating"] is False


# ---------------------------------------------------------------------------
# A calibration result is merged into the store, never written over it
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_unreadable_profile_store_is_left_alone(tmp_path, monkeypatch):
    """load_existing_profiles used to answer an unreadable store with an empty
    dict, and saving that back replaced every profile on the node with this one
    result. One lost measurement is recoverable; the file is not."""
    from logos_worker_node import config as _wcfg
    from logos_worker_node.calibration import CalibrationResult

    monkeypatch.setattr(_wcfg, "STATE_DIR", tmp_path)
    app = _make_app_for_calibration(tmp_path)
    cfg = LogosConfig(
        enabled=True,
        logos_url="https://logos.example",
        shared_key="secret",
        configured_models=["org/model-a"],
    )
    client = LogosBridgeClient(app, cfg)

    profiles_path = tmp_path / "model_profiles.yml"
    profiles_path.write_text("model_profiles:\n  org/other: {unterminated\n")
    corrupt = profiles_path.read_text()

    monkeypatch.setattr(
        "logos_worker_node.calibration.calibrate_with_tp_escalation",
        lambda plan, **kwargs: CalibrationResult(
            model=plan["model"],
            tensor_parallel_size=1,
            gpu_devices="0",
            kv_cache_sent_mb=2048.0,
            success=True,
            base_residency_mb=12345.0,
            sleeping_residual_mb=512.0,
        ),
    )
    monkeypatch.setattr("logos_worker_node.calibration.plans_from_config", lambda _p: [])

    assert (await client._handle_start_calibration_session({"sleep_level": 1}))["ok"] is True  # noqa: SLF001
    await _drain_session(client)

    assert profiles_path.read_text() == corrupt
    events = [(e.event, e.details) for e in app.state.lane_manager._event_log]
    assert any(e == "calibration_model_failed" and "unreadable" in d for e, d in events)
    # The session still ends cleanly — the server must not be left waiting.
    assert ("calibration_session_finished", "sleep_level=1") in events


@pytest.mark.asyncio
async def test_a_result_merges_into_the_existing_entry(tmp_path, monkeypatch):
    """Fields the probe does not measure — here the sleep gate's flag and a
    disk size recorded elsewhere — survive the write."""
    from logos_worker_node import config as _wcfg
    from logos_worker_node.calibration import CalibrationResult, load_existing_profiles, save_profiles

    monkeypatch.setattr(_wcfg, "STATE_DIR", tmp_path)
    app = _make_app_for_calibration(tmp_path)
    cfg = LogosConfig(
        enabled=True,
        logos_url="https://logos.example",
        shared_key="secret",
        configured_models=["org/model-a"],
    )
    client = LogosBridgeClient(app, cfg)

    profiles_path = tmp_path / "model_profiles.yml"
    save_profiles(
        profiles_path,
        {
            "org/model-a": {"base_residency_mb": 1.0, "disk_size_bytes": 42, "sleep_mode_disabled": True},
            "org/untouched": {"base_residency_mb": 22545.0},
        },
    )

    monkeypatch.setattr(
        "logos_worker_node.calibration.calibrate_with_tp_escalation",
        lambda plan, **kwargs: CalibrationResult(
            model=plan["model"],
            tensor_parallel_size=1,
            gpu_devices="0",
            kv_cache_sent_mb=2048.0,
            success=True,
            base_residency_mb=12345.0,
            sleeping_residual_mb=512.0,
        ),
    )
    monkeypatch.setattr("logos_worker_node.calibration.plans_from_config", lambda _p: [])

    assert (await client._handle_start_calibration_session({"sleep_level": 1}))["ok"] is True  # noqa: SLF001
    await _drain_session(client)

    stored = load_existing_profiles(profiles_path)
    assert stored["org/model-a"]["base_residency_mb"] == 12345.0
    assert stored["org/model-a"]["disk_size_bytes"] == 42
    assert stored["org/model-a"]["sleep_mode_disabled"] is True
    assert stored["org/untouched"]["base_residency_mb"] == 22545.0, "other models must be untouched"
