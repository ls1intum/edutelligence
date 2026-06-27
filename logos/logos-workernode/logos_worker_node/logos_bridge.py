"""Outbound Logos control-plane bridge for LogosWorkerNode."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, ClassVar
from urllib.parse import urlparse

import httpx

try:
    import websockets
    from websockets.exceptions import ConnectionClosed
except Exception:  # noqa: BLE001
    websockets = None

    class ConnectionClosed(Exception):
        pass


from logos_worker_node import prometheus_metrics as prom
from logos_worker_node.models import LaneConfig, LaneEvent, LogosConfig, WorkerTransportStatus, model_can_sleep
from logos_worker_node.runtime import build_runtime_status

logger = logging.getLogger("logos_worker_node.logos_bridge")


class _CalibrationSession:
    """Worker-driven calibration loop state.

    The worker owns the model-selection decision and walks its own list of
    uncalibrated models one at a time. Server only sends start/stop session
    RPCs and consumes calibration_* events back from the worker.
    """

    def __init__(self, sleep_level: int) -> None:
        self.sleep_level: int = sleep_level
        self.cancel_event: threading.Event = threading.Event()
        self.task: asyncio.Task | None = None
        self.started_at: float = time.time()
        # Updated by the session driver as it walks the model list — surfaced
        # so a future status RPC could inspect what's running without polling.
        self.current_model: str | None = None


# ANSI color codes for structured log output
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_CYAN = "\033[36m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RESET = "\033[0m"


class LogosBridgeClient:
    """Maintains the outbound control/data session to Logos."""

    def __init__(self, app: Any, config: LogosConfig) -> None:
        self._app = app
        self._cfg = config
        self._task: asyncio.Task | None = None
        self._command_tasks: set[asyncio.Task] = set()
        self._stopping = asyncio.Event()
        self._send_lock = asyncio.Lock()
        self._connected = False
        self._last_connected_at: datetime | None = None
        self._last_status_sent_at: datetime | None = None
        self._consecutive_failures = 0
        self._last_event_seq = 0
        self._last_runtime_signature: str | None = None
        self._last_runtime_payload: dict[str, Any] = {}
        # Resolved by server during auth
        self._resolved_worker_id: str = ""
        # Active worker-driven calibration session. The session task iterates
        # uncalibrated configured models and runs each calibration in a
        # thread executor. The cancel_event is threaded into the calibration
        # so a stop_calibration_session RPC kills the in-progress vLLM probe
        # within ~2s (wait_ready polls cancel_event).
        self._active_calibration_session: _CalibrationSession | None = None
        # Sequence counter for calibration event_id (independent of lane events).
        self._calibration_event_seq: int = 0

    @property
    def worker_id(self) -> str:
        return self._resolved_worker_id or "worker"

    def transport_status(self) -> WorkerTransportStatus:
        return WorkerTransportStatus(
            connected=self._connected,
            worker_id=self.worker_id,
            last_connected_at=self._last_connected_at,
            last_status_sent_at=self._last_status_sent_at,
            consecutive_failures=self._consecutive_failures,
        )

    async def start(self) -> None:
        if not self._cfg.enabled:
            logger.info("Logos bridge disabled in config")
            return
        if self._task is not None and not self._task.done():
            return
        self._stopping.clear()
        self._task = asyncio.create_task(self._run(), name="logos-bridge")
        logger.info("Logos bridge started (worker_id=%s)", self.worker_id)

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        self._connected = False
        logger.info("Logos bridge stopped")

    async def _run(self) -> None:
        if websockets is None:
            raise RuntimeError("websockets dependency is required for Logos bridge")
        backoff = max(1, self._cfg.reconnect_backoff_seconds)
        while not self._stopping.is_set():
            try:
                auth = await self._authenticate()
                ws_url = str(auth.get("ws_url", "")).strip()
                if not ws_url:
                    raise RuntimeError("Logos auth response missing ws_url")

                async with websockets.connect(
                    ws_url,
                    ping_interval=None,
                    close_timeout=5,
                    max_size=None,
                ) as ws:
                    self._connected = True
                    self._last_connected_at = datetime.now(timezone.utc)
                    self._consecutive_failures = 0
                    self._last_event_seq = 0
                    self._last_runtime_signature = None
                    self._last_runtime_payload = {}
                    caps = list(self._cfg.capabilities_models) if self._cfg.capabilities_models else []
                    logger.info(
                        "%s══ BRIDGE CONNECTED ══%s worker_id=%s " "capabilities=%s url=%s",
                        _GREEN + _BOLD,
                        _RESET,
                        self.worker_id,
                        caps or "(none)",
                        ws_url.split("?")[0],
                    )
                    await self._send_hello(ws)
                    await self._send_runtime_status(ws, force=True)
                    heartbeat_task = asyncio.create_task(self._heartbeat_loop(ws), name="logos-bridge-heartbeat")
                    status_task = asyncio.create_task(self._status_refresh_loop(ws), name="logos-bridge-status")
                    event_task = asyncio.create_task(self._event_loop(ws), name="logos-bridge-events")
                    try:
                        while not self._stopping.is_set():
                            raw = await ws.recv()
                            if isinstance(raw, bytes):
                                raw = raw.decode("utf-8", errors="replace")
                            await self._handle_message(ws, raw)
                    finally:
                        heartbeat_task.cancel()
                        status_task.cancel()
                        event_task.cancel()
                        for task in (heartbeat_task, status_task, event_task):
                            try:
                                await task
                            except asyncio.CancelledError:
                                pass
                        await self._cancel_command_tasks()
            except asyncio.CancelledError:
                raise
            except ConnectionClosed as exc:
                self._consecutive_failures += 1
                prom.BRIDGE_RECONNECTS_TOTAL.inc()
                prom.BRIDGE_ERRORS_TOTAL.inc()
                logger.warning(
                    "%s══ BRIDGE DISCONNECTED ══%s websocket closed: %s " "(consecutive_failures=%d)",
                    _RED + _BOLD,
                    _RESET,
                    exc,
                    self._consecutive_failures,
                )
            except Exception as exc:  # noqa: BLE001
                self._consecutive_failures += 1
                prom.BRIDGE_RECONNECTS_TOTAL.inc()
                prom.BRIDGE_ERRORS_TOTAL.inc()
                logger.warning(
                    "%s══ BRIDGE ERROR ══%s %s (consecutive_failures=%d, " "retrying in %ds)",
                    _RED + _BOLD,
                    _RESET,
                    exc,
                    self._consecutive_failures,
                    max(1, self._cfg.reconnect_backoff_seconds),
                )
            finally:
                self._connected = False

            if self._stopping.is_set():
                return
            await asyncio.sleep(backoff)

    async def _authenticate(self) -> dict[str, Any]:
        logos_url = (self._cfg.logos_url or "").rstrip("/")
        if not logos_url:
            raise RuntimeError("logos.logos_url must be configured when logos.enabled=true")
        parsed = urlparse(logos_url)
        if parsed.scheme not in {"https", "http"}:
            raise RuntimeError("logos.logos_url must use https or http")
        if parsed.scheme == "http" and not self._cfg.allow_insecure_http:
            raise RuntimeError("logos.logos_url uses http but logos.allow_insecure_http is false")
        if not self._cfg.shared_key:
            raise RuntimeError("logos.shared_key (LOGOS_API_KEY) is required")

        auth_url = f"{logos_url}/logosdb/providers/logosnode/auth"
        payload = {
            "shared_key": self._cfg.shared_key,
            "capabilities_models": self._cfg.capabilities_models,
            "configured_models": self._cfg.configured_models,
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(auth_url, json=payload)
        if resp.status_code >= 400:
            raise RuntimeError(f"/auth rejected with HTTP {resp.status_code}: {resp.text}")
        data = resp.json() if resp.content else {}

        # Pick up server-resolved worker identity
        if "worker_id" in data:
            self._resolved_worker_id = str(data["worker_id"])

        ws_url = str(data.get("ws_url", "")).strip()
        if not ws_url:
            token = str(data.get("session_token", "")).strip()
            if not token:
                raise RuntimeError("Logos auth response missing session token")
            ws_url = self._derive_ws_url(token)
        ws_url = self._normalize_ws_url(ws_url)
        data["ws_url"] = ws_url
        return data

    def _derive_ws_url(self, token: str) -> str:
        parsed = urlparse(self._cfg.logos_url)
        ws_scheme = "ws" if parsed.scheme == "http" else "wss"
        return f"{ws_scheme}://{parsed.netloc}/logosdb/providers/logosnode/session?token={token}"

    def _normalize_ws_url(self, ws_url: str) -> str:
        ws_url = (ws_url or "").strip()
        if not ws_url:
            return ws_url
        logos_scheme = urlparse(self._cfg.logos_url).scheme.lower()
        parsed_ws = urlparse(ws_url)
        ws_scheme = parsed_ws.scheme.lower()
        # Some deployments behind TLS-terminating proxies can still return ws://
        # even when logos_url is https://. Upgrade this automatically.
        if logos_scheme == "https" and ws_scheme == "ws":
            upgraded = parsed_ws._replace(scheme="wss").geturl()
            logger.warning(
                "Auth returned insecure websocket URL for HTTPS Logos URL; upgrading '%s' -> '%s'",
                ws_url,
                upgraded,
            )
            return upgraded
        return ws_url

    async def _heartbeat_loop(self, ws) -> None:
        interval = max(1, self._cfg.heartbeat_interval_seconds)
        while not self._stopping.is_set():
            await asyncio.sleep(interval)
            await self._send_heartbeat(ws)

    async def _status_refresh_loop(self, ws) -> None:
        lane_manager = self._app.state.lane_manager
        revision = getattr(lane_manager, "status_revision", 0)
        refresh_interval = max(1, self._cfg.status_refresh_interval_seconds)
        last_refresh = time.monotonic()
        while not self._stopping.is_set():
            next_revision = await lane_manager.wait_for_status_revision(revision, timeout=1.0)
            changed = next_revision != revision
            revision = next_revision
            now = time.monotonic()
            # Periodic refresh ensures VRAM/host-memory telemetry reaches the
            # server even on idle workers (no lane churn → revision never
            # bumps). The signature dedupe inside _send_runtime_status keeps
            # this cheap when nothing actually changed.
            interval_elapsed = (now - last_refresh) >= refresh_interval
            if changed or self._runtime_has_transient_lanes() or interval_elapsed:
                await self._send_runtime_status(ws, force=False)
                last_refresh = now

    async def _event_loop(self, ws) -> None:
        while not self._stopping.is_set():
            await asyncio.sleep(1)
            events = self._app.state.lane_manager.event_log
            for event in events[self._last_event_seq :]:
                await self._send_json(
                    ws,
                    {
                        "type": "event",
                        "worker_id": self.worker_id,
                        "event": event.model_dump(mode="json"),
                    },
                )
            self._last_event_seq = len(events)

    async def _send_hello(self, ws) -> None:
        max_lanes = 0
        static_lane_ids: list[str] = []
        if hasattr(self._app, "state") and hasattr(self._app.state, "config"):
            max_lanes = self._app.state.config.worker.max_lanes
        if hasattr(self._app, "state") and hasattr(self._app.state, "lane_manager"):
            static_lane_ids = sorted(self._app.state.lane_manager._static_lane_ids)
        await self._send_json(
            ws,
            {
                "type": "hello",
                "worker_id": self.worker_id,
                "capabilities_models": self._cfg.capabilities_models,
                "configured_models": self._cfg.configured_models,
                "max_lanes": max_lanes,
                "static_lane_ids": static_lane_ids,
                "actions": [
                    "infer",
                    "infer_stream",
                    "get_runtime",
                    "get_lanes",
                    "apply_lanes",
                    "add_lane",
                    "delete_lane",
                    "sleep_lane",
                    "wake_lane",
                    "reconfigure_lane",
                    "start_calibration_session",
                    "stop_calibration_session",
                ],
            },
        )

    def _runtime_has_transient_lanes(self) -> bool:
        lanes = self._last_runtime_payload.get("lanes") or []
        if not isinstance(lanes, list):
            return False
        transient_states = {"starting", "running"}
        for lane in lanes:
            if isinstance(lane, dict) and lane.get("runtime_state") in transient_states:
                return True
        return False

    async def _send_runtime_status(self, ws, force: bool = False) -> bool:
        runtime = await build_runtime_status(self._app)
        payload = runtime.model_dump(mode="json")
        signature = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        if not force and signature == self._last_runtime_signature:
            return False
        self._last_runtime_signature = signature
        self._last_runtime_payload = payload
        self._last_status_sent_at = datetime.now(timezone.utc)
        await self._send_json(
            ws,
            {
                "type": "status",
                "worker_id": self.worker_id,
                "capabilities_models": self._cfg.capabilities_models,
                "configured_models": self._cfg.configured_models,
                "runtime": payload,
            },
        )
        return True

    async def _send_heartbeat(self, ws) -> None:
        """Send a lightweight liveness heartbeat without runtime polling.

        Heartbeats must stay cheap so the server does not mark the worker
        session stale while expensive lane status collection is in progress,
        e.g. during TP startup, torch.compile, or backend warmup.
        """
        await self._send_json(
            ws,
            {
                "type": "heartbeat",
                "worker_id": self.worker_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )
        prom.BRIDGE_HEARTBEATS_TOTAL.inc()

    async def _send_json(self, ws, payload: dict[str, Any]) -> None:
        async with self._send_lock:
            await ws.send(json.dumps(payload))

    def _track_command_task(self, task: asyncio.Task, *, action: str, cmd_id: str) -> None:
        self._command_tasks.add(task)

        def _cleanup(done_task: asyncio.Task) -> None:
            self._command_tasks.discard(done_task)
            try:
                done_task.result()
            except asyncio.CancelledError:
                pass
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "%s<< CMD %s FAILED%s cmd_id=%s error=%s",
                    _RED,
                    action,
                    _RESET,
                    cmd_id[:8],
                    exc,
                )

        task.add_done_callback(_cleanup)

    async def _cancel_command_tasks(self) -> None:
        tasks = tuple(self._command_tasks)
        if not tasks:
            return

        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:  # noqa: BLE001
                logger.debug(
                    "Bridge background command task failed during shutdown",
                    exc_info=True,
                )
        self._command_tasks.clear()

    async def _execute_command_and_respond(self, ws, cmd_id: str, action: str, params: dict[str, Any]) -> None:
        if action != "infer":
            param_summary = ", ".join(f"{k}={v}" for k, v in params.items() if k != "messages")
            logger.info(
                "%s>> CMD %s%s cmd_id=%s %s",
                _CYAN + _BOLD,
                action,
                _RESET,
                cmd_id[:8],
                param_summary,
            )

        try:
            result = await self._execute_command(action, params)
            if action != "infer":
                logger.info(
                    "%s<< CMD %s OK%s cmd_id=%s",
                    _GREEN,
                    action,
                    _RESET,
                    cmd_id[:8],
                )
            response = {
                "type": "command_result",
                "cmd_id": cmd_id,
                "success": True,
                "result": result,
            }
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "%s<< CMD %s FAILED%s cmd_id=%s error=%s",
                _RED,
                action,
                _RESET,
                cmd_id[:8],
                exc,
            )
            response = {
                "type": "command_result",
                "cmd_id": cmd_id,
                "success": False,
                "error": str(exc),
            }
        await self._send_json(ws, response)

    async def _handle_message(self, ws, raw: str) -> None:
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            logger.debug("Ignoring non-JSON bridge message")
            return

        msg_type = message.get("type")
        if msg_type == "ping":
            await self._send_json(ws, {"type": "pong"})
            return
        if msg_type != "command":
            return

        cmd_id = str(message.get("cmd_id", "")).strip()
        action = str(message.get("action", "")).strip()
        params = message.get("params") or {}
        if not cmd_id or not action:
            return

        if action == "infer_stream":
            task = asyncio.create_task(
                self._execute_stream_command(ws, cmd_id, params),
                name=f"logos-bridge-{action}-{cmd_id[:8]}",
            )
            self._track_command_task(task, action=action, cmd_id=cmd_id)
            return

        if action == "infer":
            task = asyncio.create_task(
                self._execute_command_and_respond(ws, cmd_id, action, params),
                name=f"logos-bridge-{action}-{cmd_id[:8]}",
            )
            self._track_command_task(task, action=action, cmd_id=cmd_id)
            return

        await self._execute_command_and_respond(ws, cmd_id, action, params)

    async def _execute_command(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        lane_manager = self._app.state.lane_manager

        if action == "infer":
            return await self._execute_infer_command(params)
        if action == "get_runtime":
            runtime = await build_runtime_status(self._app)
            return runtime.model_dump(mode="json")
        if action == "get_lanes":
            lanes = await lane_manager.get_all_statuses()
            return {"lanes": [lane.model_dump(mode="json") for lane in lanes]}
        if action == "apply_lanes":
            lanes = [LaneConfig(**item) for item in (params.get("lanes") or [])]
            result = await lane_manager.apply_lanes(lanes)
            return result.model_dump(mode="json")

        if action == "add_lane":
            lane_config = LaneConfig(**params)
            status = await lane_manager.add_lane(lane_config)
            return status.model_dump(mode="json")

        lane_id = str(params.get("lane_id", "")).strip()
        if action == "delete_lane":
            await lane_manager.remove_lane(lane_id)
            return {"ok": True, "lane_id": lane_id}
        if action == "sleep_lane":
            status = await lane_manager.sleep_lane(
                lane_id,
                level=int(params.get("level", 1)),
                mode=str(params.get("mode", "wait")),
            )
            return status.model_dump(mode="json")
        if action == "wake_lane":
            status = await lane_manager.wake_lane(lane_id)
            return status.model_dump(mode="json")
        if action == "reconfigure_lane":
            updates = params.get("updates") or {}
            status = await lane_manager.reconfigure_lane(lane_id, updates)
            return status.model_dump(mode="json")

        if action == "start_calibration_session":
            return await self._handle_start_calibration_session(params)
        if action == "stop_calibration_session":
            return await self._handle_stop_calibration_session()

        raise ValueError(f"Unsupported bridge command '{action}'")

    async def _handle_start_calibration_session(self, params: dict[str, Any]) -> dict[str, Any]:
        """Start a worker-driven calibration session.

        The worker iterates its own list of uncalibrated configured models,
        runs each calibration sequentially, and emits ``calibration_*`` events
        back to the server. The server does not poll status and does not
        choose models; it only sends start/stop session RPCs.
        """
        sleep_level = int(params.get("sleep_level", 1))

        # Refuse start when a session is already running — caller should
        # have stopped the previous session first. The event channel told
        # them whether it finished.
        if self._active_calibration_session is not None:
            task = self._active_calibration_session.task
            if task is not None and not task.done():
                return {"ok": False, "error": "calibration session already in progress"}
            # Stale entry — drop it.
            self._active_calibration_session = None

        # Refuse when the node itself is in a degraded state (GPU ERR/N/A,
        # HF cache EIO, …). The kv-cache search would fail the same way
        # for every model in the session; better to bounce the request now
        # and let ops fix the underlying issue.
        try:
            from logos_worker_node.node_health import evaluate_node_health  # noqa: PLC0415

            _health = evaluate_node_health()
            if not _health.healthy:
                logger.error(
                    "[Calibration] refusing start_calibration_session: node unhealthy (reason=%s) — %s",
                    _health.reason_code,
                    _health.reason_detail,
                )
                return {
                    "ok": False,
                    "error": (
                        f"node is in a degraded state (reason={_health.reason_code}): "
                        f"{_health.reason_detail}. Calibration is suspended until "
                        f"the underlying issue is resolved."
                    ),
                    "node_unhealthy": True,
                    "reason_code": _health.reason_code,
                }
        except Exception:  # noqa: BLE001
            logger.debug("[Calibration] node_health evaluation failed", exc_info=True)

        session = _CalibrationSession(sleep_level=sleep_level)
        session.task = asyncio.create_task(
            self._run_calibration_session(session),
            name="calibration-session",
        )
        self._active_calibration_session = session
        logger.info(
            "[Calibration] Session started (sleep_level=%d) — worker drives model selection",
            sleep_level,
        )
        return {
            "ok": True,
            "sleep_level": sleep_level,
            "started_at": session.started_at,
        }

    async def _handle_stop_calibration_session(self) -> dict[str, Any]:
        """Cancel any in-progress calibration session.

        Sets the cancel_event so the calibration's wait_ready polling kills
        the running vLLM probe within ~2s, then awaits the session task
        briefly so the terminal ``calibration_session_cancelled`` event is
        emitted before the RPC reply.
        """
        session = self._active_calibration_session
        if session is None:
            return {"ok": True, "was_active": False}

        session.cancel_event.set()
        current_model = session.current_model
        if session.task is not None and not session.task.done():
            try:
                await asyncio.wait_for(asyncio.shield(session.task), timeout=15.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                # Session is still wrapping up (subprocess teardown). The
                # terminal event will arrive on the event channel when it
                # does. Don't block the RPC longer than 15s.
                pass
        logger.info(
            "[Calibration] stop_calibration_session received — cancelled (current_model=%s)",
            current_model or "<none>",
        )
        return {"ok": True, "was_active": True, "current_model": current_model}

    # ------------------------------------------------------------------
    # Calibration session driver
    # ------------------------------------------------------------------

    def _record_calibration_event(self, event: str, model: str = "", details: str = "") -> None:
        """Append a calibration event onto the lane manager's event log.

        Calibration events ride the same channel as lane events so the
        existing ``_event_loop`` forwards them to the server without any
        extra plumbing. ``lane_id`` is fixed to ``"calibration"`` so the
        server can distinguish them from real lane transitions.
        """
        lane_manager = getattr(self._app.state, "lane_manager", None)
        if lane_manager is None:
            return
        self._calibration_event_seq += 1
        lane_manager._event_log.append(  # noqa: SLF001
            LaneEvent(
                event_id=f"calib-{self._calibration_event_seq}",
                timestamp=datetime.now(timezone.utc),
                lane_id="calibration",
                event=event,
                model=model,
                details=details,
            )
        )
        # Cap log size like _record_event does.
        max_events = getattr(lane_manager, "_MAX_EVENT_LOG", 500)
        if len(lane_manager._event_log) > max_events:  # noqa: SLF001
            lane_manager._event_log = lane_manager._event_log[-max_events:]  # noqa: SLF001

    def _list_uncalibrated_models(self) -> list[str]:
        """Pick configured models that still need calibration.

        Mirrors the previous server-side selection logic so behaviour is
        unchanged — only the location of the decision moves to the worker.
        Skips models with sleep_mode_disabled (only the sleep field would
        be N/A) only when base_residency is already known, and models
        flagged calibration_unsupported.
        """
        cfg = self._app.state.config
        model_profiles = self._app.state.model_profiles
        candidates = list(self._cfg.configured_models) or list(self._cfg.capabilities_models)

        sleep_level = (
            self._active_calibration_session.sleep_level if self._active_calibration_session is not None else 1
        )

        ordered: list[str] = []
        for model_name in candidates:
            profile = model_profiles.get_profile(model_name)
            if profile is not None and profile.calibration_unsupported:
                continue
            sleep_na = bool(profile is not None and profile.sleep_mode_disabled)
            # Worker-side knowledge: if config now forbids sleep but profile
            # still claims it's possible, picking this model is fine — the
            # session driver re-checks model_can_sleep before each model
            # and persists the new flag.
            if sleep_level > 0 and not model_can_sleep(cfg, model_name):
                sleep_na = True
            collapsed_envelope = (
                profile is not None
                and profile.residency_source == "calibrated"
                and profile.min_kv_cache_mb is not None
                and profile.max_kv_cache_mb is not None
                and profile.min_kv_cache_mb > 0
                and profile.min_kv_cache_mb == profile.max_kv_cache_mb
            )
            needs_calib = (
                profile is None
                or profile.base_residency_mb is None
                or (not sleep_na and profile.sleeping_residual_mb is None)
                or (not sleep_na and profile.sleep_l1_transient_host_ram_mb is None)
                or (
                    profile is not None
                    and profile.residency_source == "calibrated"
                    and not profile.kv_cache_to_max_model_len_pairs
                )
                or collapsed_envelope
            )
            if needs_calib:
                ordered.append(model_name)
        return ordered

    async def _run_calibration_session(self, session: _CalibrationSession) -> None:
        """Async driver that walks uncalibrated models one at a time.

        Each model's blocking calibration runs on the default thread
        executor; the cancel_event is wired through to ``wait_ready`` so a
        stop_calibration_session RPC tears down the in-flight vLLM probe
        within ~2s instead of waiting out the full ready timeout.
        """
        # Emit the session_started event immediately, before anything that
        # could fail. The orchestrator relies on the terminal event in the
        # finally block to free its active-provider slot, so we must always
        # produce a session_started/session_finished pair on a normal start.
        models = self._list_uncalibrated_models()
        self._record_calibration_event(
            "calibration_session_started",
            details=f"models={len(models)} sleep_level={session.sleep_level}",
        )

        terminal_event = "calibration_session_finished"
        lane_manager = getattr(self._app.state, "lane_manager", None)
        try:
            from logos_worker_node.calibration import (  # noqa: PLC0415
                _CALIBRATION_PORT,
                _DEFAULT_VLLM,
                _READY_TIMEOUT_S,
                calibrate_with_tp_escalation,
                is_model_unsupported,
                load_existing_profiles,
                plans_from_config,
                result_to_profile_dict,
                save_profiles,
            )
            from logos_worker_node.config import get_state_dir  # noqa: PLC0415

            cfg = self._app.state.config
            model_profiles = self._app.state.model_profiles
            model_cache = getattr(self._app.state, "model_cache", None)

            if not models:
                logger.info("[Calibration] No uncalibrated models to process — session is a no-op")
                return

            state_dir = get_state_dir()
            profiles_path = state_dir / "model_profiles.yml"
            log_dir = state_dir / "calibration_logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            nccl_p2p = cfg.engines.vllm.nccl_p2p_available if cfg.engines else False
            _mc = model_cache if (model_cache is not None and getattr(model_cache, "enabled", False)) else None

            # Resolve plans once — the kv-cache ceilings come from config.yml.
            import os as _os  # noqa: PLC0415
            from pathlib import Path  # noqa: PLC0415

            config_path_str = _os.environ.get("LOGOS_WORKER_NODE_CONFIG", "").strip()
            if config_path_str:
                config_path = Path(config_path_str)
            else:
                for candidate in [Path("/app/config.yml"), Path("config.yml")]:
                    if candidate.resolve().is_file():
                        config_path = candidate
                        break
                else:
                    config_path = Path("config.yml")
            all_plans = plans_from_config(config_path) if config_path.exists() else []
            plan_by_model = {p["model"]: p for p in all_plans}

            # Free all VRAM up front. Live lanes compete with the calibration
            # probe for GPU memory: the kv-cache search starts against an
            # already-loaded model, every probe size OOMs, and the blacklist
            # fills up with bogus entries even though the model could have
            # calibrated on a clean GPU. The Logos server re-spawns lanes via
            # the normal apply_lanes path once the session ends.
            if lane_manager is not None:
                try:
                    await lane_manager.destroy_all()
                    logger.info("[Calibration] Stopped all lanes to free VRAM for calibration session")
                except Exception:  # noqa: BLE001
                    logger.exception("[Calibration] destroy_all failed — continuing anyway")

            for model_name in models:
                if session.cancel_event.is_set():
                    terminal_event = "calibration_session_cancelled"
                    break

                session.current_model = model_name

                # Pre-flight: persistent unsupported flag.
                _unsupported = None
                try:
                    _unsupported = is_model_unsupported(log_dir, model_name)
                except Exception:  # noqa: BLE001
                    logger.debug("[Calibration] unsupported-list lookup failed", exc_info=True)
                if _unsupported is not None:
                    model_profiles.mark_calibration_unsupported(model_name, True, _unsupported.reason_code)
                    logger.warning(
                        "[Calibration] Skipping %s — on unsupported list (reason=%s)",
                        model_name,
                        _unsupported.reason_code,
                    )
                    self._record_calibration_event(
                        "calibration_model_skipped",
                        model=model_name,
                        details=f"unsupported reason={_unsupported.reason_code}",
                    )
                    continue

                # Pre-flight: sleep gate. If the worker config forbids sleep
                # for this model (worker kill switch or per-model override)
                # there is no point spawning a vLLM lane with sleep_level>0 —
                # the POST /sleep at Phase 4 of calibration will fail and the
                # whole probe is wasted. Persist the flag and skip; the model
                # stays uncalibrated on this worker until config or sleep
                # level changes.
                if session.sleep_level > 0 and not model_can_sleep(cfg, model_name):
                    model_profiles.mark_sleep_mode_disabled(model_name, True)
                    logger.info(
                        "[Calibration] Skipping %s — sleep mode disabled on this worker",
                        model_name,
                    )
                    self._record_calibration_event(
                        "calibration_model_skipped",
                        model=model_name,
                        details="sleep_mode_disabled",
                    )
                    continue
                if model_can_sleep(cfg, model_name):
                    # Config now permits sleep — clear any stale flag so a
                    # config flip (true → false) is picked up immediately.
                    model_profiles.mark_sleep_mode_disabled(model_name, False)

                plan = plan_by_model.get(model_name) or {"model": model_name}
                self._record_calibration_event(
                    "calibration_model_started",
                    model=model_name,
                    details=f"sleep_level={session.sleep_level}",
                )
                logger.info(
                    "[Calibration] Starting model=%s sleep_level=%d",
                    model_name,
                    session.sleep_level,
                )

                # Blocking calibration runs in the default thread executor so
                # we keep the bridge's event loop responsive. The cancel_event
                # is the same instance the stop RPC sets — wait_ready polls
                # it every 2s and bails immediately.
                loop = asyncio.get_running_loop()
                try:
                    result = await loop.run_in_executor(
                        None,
                        lambda p=plan: calibrate_with_tp_escalation(
                            p,
                            vllm_binary=_DEFAULT_VLLM,
                            port=_CALIBRATION_PORT,
                            log_dir=log_dir,
                            sleep_level=session.sleep_level,
                            ready_timeout_s=_READY_TIMEOUT_S,
                            nccl_p2p_available=nccl_p2p,
                            model_cache=_mc,
                            cancel_event=session.cancel_event,
                        ),
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.exception("[Calibration] Unexpected error for model=%s", model_name)
                    self._record_calibration_event(
                        "calibration_model_failed",
                        model=model_name,
                        details=f"unexpected: {exc}",
                    )
                    continue

                # Cancellation may have fired during the calibration. We emit
                # the cancelled event and stop iterating; whether the result
                # is success or failure, we don't persist a half-baked profile.
                if session.cancel_event.is_set():
                    logger.info("[Calibration] Cancelled mid-model: %s", model_name)
                    self._record_calibration_event(
                        "calibration_model_cancelled",
                        model=model_name,
                    )
                    terminal_event = "calibration_session_cancelled"
                    break

                if result.success:
                    existing = load_existing_profiles(profiles_path)
                    prior = existing.get(model_name) or {}
                    new_profile = result_to_profile_dict(result)
                    for _carry in (
                        "sleep_l1_transient_host_ram_mb",
                        "sleep_l2_transient_host_ram_mb",
                    ):
                        if new_profile.get(_carry) is None and prior.get(_carry) is not None:
                            new_profile[_carry] = prior[_carry]
                    existing[model_name] = new_profile
                    save_profiles(profiles_path, existing)
                    model_profiles._load_persisted()  # noqa: SLF001
                    # Models that were pruned from capabilities at startup
                    # because they had no profile must be re-announced now
                    # that they're calibrated; otherwise the server never
                    # learns the worker can serve them.
                    if model_name not in self._cfg.capabilities_models:
                        self._cfg.capabilities_models = list(self._cfg.capabilities_models) + [model_name]
                        logger.info(
                            "[Calibration] Re-announcing %s to Logos (capabilities now: %d model(s))",
                            model_name,
                            len(self._cfg.capabilities_models),
                        )
                    logger.info(
                        "[Calibration] Completed model=%s base_residency=%.0f MB",
                        model_name,
                        result.base_residency_mb,
                    )
                    self._record_calibration_event(
                        "calibration_model_completed",
                        model=model_name,
                        details=f"base_residency_mb={result.base_residency_mb:.0f}",
                    )
                    # Dirty the lane manager's status revision so the next
                    # status push includes the updated model_profiles right
                    # away (instead of waiting the full status_refresh
                    # interval). Safe to call from the asyncio task because
                    # we're on the event loop.
                    if lane_manager is not None:
                        try:
                            lane_manager._mark_status_dirty()  # noqa: SLF001
                        except Exception:  # noqa: BLE001
                            logger.debug("[Calibration] _mark_status_dirty failed", exc_info=True)

                    # Issue #615: when the calibrated TP is >1, pre-shard the
                    # checkpoint now while the GPU is free, so the lane that
                    # serves this model later loads each rank's shard directly
                    # instead of every rank re-reading the full checkpoint.
                    await self._maybe_convert_sharded_checkpoint(model_name, result, plan, session, cfg, log_dir)
                else:
                    logger.warning(
                        "[Calibration] Failed model=%s error=%s",
                        model_name,
                        result.error,
                    )
                    if getattr(result, "unsupported_reason", None):
                        model_profiles.mark_calibration_unsupported(model_name, True, result.unsupported_reason)
                        logger.warning(
                            "[Calibration] %s marked calibration_unsupported (reason=%s)",
                            model_name,
                            result.unsupported_reason,
                        )
                    self._record_calibration_event(
                        "calibration_model_failed",
                        model=model_name,
                        details=f"error={result.error}"
                        + (
                            f" unsupported={result.unsupported_reason}"
                            if getattr(result, "unsupported_reason", None)
                            else ""
                        ),
                    )

                session.current_model = None
        except asyncio.CancelledError:
            terminal_event = "calibration_session_cancelled"
            raise
        except Exception:  # noqa: BLE001
            # Anything else — bad state dir, bad config — must not escape
            # silently because we still need to emit the terminal event so
            # the orchestrator frees its active-provider slot.
            logger.exception("[Calibration] Session aborted with unexpected error")
            terminal_event = "calibration_session_cancelled"
        finally:
            session.current_model = None
            self._record_calibration_event(
                terminal_event,
                details=f"sleep_level={session.sleep_level}",
            )
            if lane_manager is not None:
                try:
                    lane_manager._mark_status_dirty()  # noqa: SLF001
                except Exception:  # noqa: BLE001
                    pass
            if self._active_calibration_session is session:
                self._active_calibration_session = None
            logger.info("[Calibration] Session ended (%s)", terminal_event)

    async def _maybe_convert_sharded_checkpoint(
        self,
        model_name: str,
        result: Any,
        plan: dict[str, Any],
        session: _CalibrationSession,
        cfg: Any,
        log_dir: Any,
    ) -> None:
        """Pre-shard a model's checkpoint after calibration when its TP is >1.

        Runs the (blocking, GPU-loading) conversion on the thread executor with
        the session's cancel_event wired through, so stop_calibration_session
        tears it down within ~2s. Best-effort: any failure is logged and the
        model still serves from its full checkpoint. See issue #615.
        """
        try:
            from pathlib import Path  # noqa: PLC0415

            from logos_worker_node import sharded_checkpoint as sc  # noqa: PLC0415
            from logos_worker_node.calibration import _DEFAULT_VLLM  # noqa: PLC0415

            vc_engine = cfg.engines.vllm if cfg.engines else None
            if vc_engine is None or not getattr(vc_engine, "sharded_checkpoint_enabled", True):
                return
            tp = int(getattr(result, "tensor_parallel_size", 1) or 1)
            min_tp = max(2, int(getattr(vc_engine, "sharded_checkpoint_min_tensor_parallel_size", 2)))
            if tp < min_tp:
                return

            models_path = cfg.engines.ollama.models_path if cfg.engines else ""
            cache_root = sc.resolve_cache_root(models_path)
            if not cache_root:
                return
            target = sc.sharded_checkpoint_dir(cache_root, model_name, tp)
            if sc.is_sharded_checkpoint_ready(target):
                return

            import os as _os  # noqa: PLC0415

            hf_home = _os.environ.get("HF_HOME", "").strip() or str(Path(cache_root) / ".hf_cache")
            gpu_devices = str(getattr(result, "gpu_devices", "") or plan.get("gpu_devices") or "")
            dtype = str(plan.get("dtype", "auto") or "auto")
            quant = str(plan.get("quantization") or "")
            trust = "--trust-remote-code" in (plan.get("extra_args") or [])

            self._record_calibration_event("sharded_conversion_started", model=model_name, details=f"tp={tp}")
            logger.info("[Calibration] Converting %s to sharded checkpoint (tp=%d)", model_name, tp)

            loop = asyncio.get_running_loop()
            out = await loop.run_in_executor(
                None,
                lambda: sc.ensure_sharded_checkpoint(
                    model=model_name,
                    tensor_parallel_size=tp,
                    cache_root=cache_root,
                    vllm_binary=_DEFAULT_VLLM,
                    hf_home=hf_home,
                    gpu_devices=gpu_devices,
                    dtype=dtype,
                    quantization=quant,
                    trust_remote_code=trust,
                    nccl_p2p_available=vc_engine.nccl_p2p_available,
                    max_file_size_bytes=int(
                        getattr(vc_engine, "sharded_checkpoint_max_file_size_bytes", sc.DEFAULT_MAX_FILE_SIZE_BYTES)
                    ),
                    log_path=log_dir / f"sharded_{model_name.replace('/', '__')}_tp{tp}.log",
                    cancel_event=session.cancel_event,
                ),
            )
            if out is not None:
                self._record_calibration_event(
                    "sharded_conversion_completed", model=model_name, details=f"tp={tp} path={out}"
                )
                logger.info("[Calibration] Sharded checkpoint ready for %s: %s", model_name, out)
            else:
                self._record_calibration_event("sharded_conversion_failed", model=model_name, details=f"tp={tp}")
                logger.warning("[Calibration] Sharded conversion failed/skipped for %s (tp=%d)", model_name, tp)
        except Exception:  # noqa: BLE001
            logger.exception("[Calibration] Sharded conversion errored for %s", model_name)

    # vLLM endpoints that must never be reachable through proxied inference
    # requests.  These are internal management endpoints (sleep/wake, cache
    # reset, weight updates, etc.) that should only be triggered by the
    # lane manager or capacity planner, not by external API clients.
    _BLOCKED_REQUEST_PATHS: ClassVar[frozenset[str]] = frozenset(
        {
            "sleep",
            "wake_up",
            "is_sleeping",
            "pause",
            "resume",
            "is_paused",
            "reset_prefix_cache",
            "reset_mm_cache",
            "reset_encoder_cache",
            "update_weights",
            "init_weight_transfer_engine",
            "scale_elastic_ep",
            "is_scaling_elastic_ep",
            "collective_rpc",
        }
    )

    @staticmethod
    def _lane_target_url(
        lane_status: dict[str, Any],
        payload: dict[str, Any] | None = None,
        request_path: str | None = None,
    ) -> str:
        # If the caller forwarded the original API path (e.g. "v1/embeddings",
        # "v2/embed", "tokenize"), use it directly so vLLM decides what it supports.
        if request_path:
            endpoint = request_path.strip("/")
            # Block internal vLLM management endpoints from being reached
            # through proxied inference requests.
            if endpoint in LogosBridgeClient._BLOCKED_REQUEST_PATHS:
                raise ValueError(f"Request path '/{endpoint}' is not allowed through the inference proxy")
        else:
            endpoint = str(lane_status.get("inference_endpoint") or "/v1/chat/completions").lstrip("/")
        return f"http://127.0.0.1:{lane_status['port']}/{endpoint}"

    async def _resolve_lane_for_infer(self, lane_id: str) -> dict[str, Any]:
        if not lane_id:
            raise ValueError("lane_id is required")
        lane_status = await self._app.state.lane_manager.get_lane_status(lane_id)
        if lane_status.runtime_state not in {"loaded", "running", "cold", "starting"}:
            raise RuntimeError(f"Lane '{lane_id}' is not routable (state={lane_status.runtime_state})")
        return lane_status.model_dump(mode="json")

    async def _execute_infer_command(self, params: dict[str, Any]) -> dict[str, Any]:
        lane_manager = self._app.state.lane_manager
        lane_id = str(params.get("lane_id", "")).strip()
        payload = params.get("payload") or {}
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")

        lane_status = await self._resolve_lane_for_infer(lane_id)
        request_path = params.get("request_path")
        target_url = self._lane_target_url(lane_status, payload, request_path=request_path)

        await lane_manager.increment_active_requests(lane_id)
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                upstream = await client.post(
                    target_url,
                    headers={"Content-Type": "application/json"},
                    json=payload,
                )
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Lane relay request failed for '{lane_id}': {exc}") from exc
        finally:
            await lane_manager.decrement_active_requests(lane_id)

        try:
            body = upstream.json()
        except ValueError:
            body = upstream.text

        headers = {}
        content_type = upstream.headers.get("content-type")
        if content_type:
            headers["content-type"] = content_type
        return {
            "status_code": int(upstream.status_code),
            "body": body,
            "headers": headers,
        }

    async def _execute_stream_command(self, ws, cmd_id: str, params: dict[str, Any]) -> None:
        lane_manager = self._app.state.lane_manager
        lane_id = str(params.get("lane_id", "")).strip()
        payload = params.get("payload") or {}
        if not isinstance(payload, dict):
            await self._send_json(
                ws,
                {
                    "type": "stream_end",
                    "cmd_id": cmd_id,
                    "success": False,
                    "error": "payload must be an object",
                },
            )
            return

        try:
            lane_status = await self._resolve_lane_for_infer(lane_id)
            request_path = params.get("request_path")
            target_url = self._lane_target_url(lane_status, payload, request_path=request_path)
        except Exception as exc:  # noqa: BLE001
            await self._send_json(
                ws,
                {
                    "type": "stream_end",
                    "cmd_id": cmd_id,
                    "success": False,
                    "error": str(exc),
                },
            )
            return

        await lane_manager.increment_active_requests(lane_id)
        client = httpx.AsyncClient(timeout=None)
        upstream = None
        try:
            request = client.build_request(
                "POST",
                target_url,
                headers={"Content-Type": "application/json"},
                json=payload,
            )
            upstream = await client.send(request, stream=True)
            await self._send_json(
                ws,
                {
                    "type": "stream_start",
                    "cmd_id": cmd_id,
                    "status_code": int(upstream.status_code),
                    "content_type": upstream.headers.get("content-type", "text/event-stream"),
                },
            )
            if upstream.status_code >= 400:
                raw = await upstream.aread()
                if raw:
                    await self._send_json(
                        ws,
                        {
                            "type": "stream_chunk",
                            "cmd_id": cmd_id,
                            "chunk_b64": base64.b64encode(raw).decode("ascii"),
                        },
                    )
                await self._send_json(
                    ws,
                    {
                        "type": "stream_end",
                        "cmd_id": cmd_id,
                        "success": False,
                        "error": f"Lane '{lane_id}' returned HTTP {upstream.status_code}",
                    },
                )
                return

            async for chunk in upstream.aiter_bytes():
                if not chunk:
                    continue
                await self._send_json(
                    ws,
                    {
                        "type": "stream_chunk",
                        "cmd_id": cmd_id,
                        "chunk_b64": base64.b64encode(chunk).decode("ascii"),
                    },
                )
            await self._send_json(ws, {"type": "stream_end", "cmd_id": cmd_id, "success": True})
        except Exception as exc:  # noqa: BLE001
            await self._send_json(
                ws,
                {
                    "type": "stream_end",
                    "cmd_id": cmd_id,
                    "success": False,
                    "error": str(exc),
                },
            )
        finally:
            # Decrement before aclose() so that a client-side disconnect that
            # leaves httpx draining the upstream stream does not keep
            # worker_active > 0 and falsely trigger proxy_stuck detection.
            await lane_manager.decrement_active_requests(lane_id)
            if upstream is not None:
                try:
                    await asyncio.wait_for(upstream.aclose(), timeout=5.0)
                except Exception:  # noqa: BLE001
                    pass
            try:
                await asyncio.wait_for(client.aclose(), timeout=5.0)
            except Exception:  # noqa: BLE001
                pass
