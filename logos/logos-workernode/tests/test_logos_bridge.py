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
    """Build a fake app.state for _handle_start_calibration tests."""
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
    return app


@pytest.mark.asyncio
async def test_start_calibration_rejected_when_worker_kill_switch_disables_sleep(tmp_path):
    """Regression for prod 2026-06-04: when engines.vllm.disable_sleep_mode is
    True, lanes spawn with enable_sleep_mode=False and cannot satisfy a
    sleep_l<N> calibration. The worker must refuse the request immediately
    instead of spawning a vLLM lane that will fail at Phase 4 (POST /sleep).
    """
    app = _make_app_for_calibration(tmp_path, vllm_disable_sleep=True)
    cfg = LogosConfig(enabled=True, logos_url="https://logos.example", shared_key="secret")
    client = LogosBridgeClient(app, cfg)

    response = await client._handle_start_calibration(
        {"model_name": "openai/gpt-oss-120b", "sleep_level": 1}
    )  # noqa: SLF001

    assert response["ok"] is False
    assert response.get("sleep_mode_disabled") is True
    assert "sleep mode disabled" in response["error"]
    assert client._active_calibration is None  # noqa: SLF001
    # Flag persisted so the master orchestrator stops asking
    profile = app.state.model_profiles.get_profile("openai/gpt-oss-120b")
    assert profile is not None
    assert profile.sleep_mode_disabled is True


@pytest.mark.asyncio
async def test_start_calibration_rejected_for_per_model_override(tmp_path):
    """Per-model enable_sleep_mode=false override under
    engines.vllm.model_overrides must also block sleep_l<N> calibration."""
    app = _make_app_for_calibration(
        tmp_path,
        per_model_overrides={"openai/gpt-oss-120b": {"enable_sleep_mode": False}},
    )
    cfg = LogosConfig(enabled=True, logos_url="https://logos.example", shared_key="secret")
    client = LogosBridgeClient(app, cfg)

    response = await client._handle_start_calibration(
        {"model_name": "openai/gpt-oss-120b", "sleep_level": 1}
    )  # noqa: SLF001

    assert response["ok"] is False
    assert response.get("sleep_mode_disabled") is True
    profile = app.state.model_profiles.get_profile("openai/gpt-oss-120b")
    assert profile is not None and profile.sleep_mode_disabled is True


@pytest.mark.asyncio
async def test_start_calibration_sleep_level_zero_skips_sleep_gate(tmp_path):
    """sleep_level=0 means "no sleep phase" — the gate must not refuse on
    enable_sleep_mode=False because no sleep call will happen."""
    app = _make_app_for_calibration(tmp_path, vllm_disable_sleep=True)
    cfg = LogosConfig(enabled=True, logos_url="https://logos.example", shared_key="secret")
    client = LogosBridgeClient(app, cfg)

    # Block the background thread from actually starting by pre-claiming the
    # active-calibration slot — this lets us exercise the gate without
    # depending on vLLM being available.
    import threading

    sentinel_event = threading.Event()
    sentinel_thread = threading.Thread(target=sentinel_event.wait, daemon=True)
    sentinel_thread.start()
    try:
        client._active_calibration = (  # noqa: SLF001
            "sentinel-model",
            sentinel_event,
            sentinel_thread,
            0.0,
        )

        response = await client._handle_start_calibration(
            {"model_name": "openai/gpt-oss-120b", "sleep_level": 0}
        )  # noqa: SLF001
    finally:
        sentinel_event.set()
        sentinel_thread.join(timeout=1.0)

    # Gate did not fire (no sleep_mode_disabled marker), but we got the
    # "calibration already in progress" message from the sentinel block.
    assert response["ok"] is False
    assert response.get("sleep_mode_disabled") is None
    assert "already in progress" in response["error"]


@pytest.mark.asyncio
async def test_start_calibration_stops_all_lanes_before_spawning(tmp_path, monkeypatch):
    """Live lanes hold VRAM. Calibration must free everything first or the
    kv-cache search OOMs and blacklists every probe size (deioma 2026-06-04)."""
    app = _make_app_for_calibration(tmp_path)
    lane_manager = type("LaneMgr", (), {})()
    lane_manager.destroy_all = AsyncMock(return_value=None)
    app.state.lane_manager = lane_manager
    cfg = LogosConfig(enabled=True, logos_url="https://logos.example", shared_key="secret")
    client = LogosBridgeClient(app, cfg)

    # Prevent the calibration thread from actually starting vLLM — we only
    # care that destroy_all ran by the time start_calibration returns.
    import threading as _threading

    real_thread_cls = _threading.Thread

    class _NoopThread(real_thread_cls):
        def start(self) -> None:  # noqa: D401
            return  # don't actually run _run_calibration

    monkeypatch.setattr("logos_worker_node.logos_bridge.threading.Thread", _NoopThread)

    response = await client._handle_start_calibration(  # noqa: SLF001
        {"model_name": "openai/gpt-oss-120b", "sleep_level": 0}
    )

    assert response["ok"] is True
    lane_manager.destroy_all.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_calibration_does_not_stop_lanes_on_rejection(tmp_path):
    """Rejection paths (sleep-mode-disabled, etc.) must return before destroy_all
    so we don't kill live lanes just to refuse the request seconds later."""
    app = _make_app_for_calibration(tmp_path, vllm_disable_sleep=True)
    lane_manager = type("LaneMgr", (), {})()
    lane_manager.destroy_all = AsyncMock(return_value=None)
    app.state.lane_manager = lane_manager
    cfg = LogosConfig(enabled=True, logos_url="https://logos.example", shared_key="secret")
    client = LogosBridgeClient(app, cfg)

    response = await client._handle_start_calibration(  # noqa: SLF001
        {"model_name": "openai/gpt-oss-120b", "sleep_level": 1}
    )

    assert response["ok"] is False
    lane_manager.destroy_all.assert_not_awaited()
