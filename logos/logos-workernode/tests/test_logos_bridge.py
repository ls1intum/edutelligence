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
async def test_session_skips_sleep_disabled_model_and_continues(tmp_path, monkeypatch):
    """Inside the session loop, a model that can't be slept on this worker
    is recorded as skipped (with sleep_mode_disabled persisted on the
    profile) and the loop moves on to the next model. The session must
    not refuse the whole batch over one bad model."""
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

    events = [(e.event, e.model) for e in app.state.lane_manager._event_log]
    # gpt-oss skipped, phi-4 attempted and completed.
    assert ("calibration_model_skipped", "openai/gpt-oss-120b") in events
    assert ("calibration_model_completed", "microsoft/Phi-4-reasoning") in events
    assert ("calibration_session_finished", "") in events
    # sleep_mode_disabled persisted for the skipped model.
    skipped_profile = app.state.model_profiles.get_profile("openai/gpt-oss-120b")
    assert skipped_profile is not None
    assert skipped_profile.sleep_mode_disabled is True


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
