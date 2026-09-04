"""Outbound Logos control-plane bridge for LogosWorkerNode."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
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
from logos_worker_node.metal import is_metal_backend
from logos_worker_node.models import LaneConfig, LaneEvent, LogosConfig, WorkerTransportStatus, model_can_sleep
from logos_worker_node.request_content import MULTIPART_PAYLOAD_KEY, httpx_request_parts
from logos_worker_node.runtime import build_runtime_status

logger = logging.getLogger("logos_worker_node.logos_bridge")

_INFERENCE_RELAY_TIMEOUT = httpx.Timeout(
    connect=10.0,
    read=3600.0,
    write=300.0,
    pool=10.0,
)

_MAX_CALIBRATION_LOG_TEXT_BYTES = 512 * 1024


# Commands that can grow this node's VRAM footprint. Refused while a
# calibration session holds the GPU — see _execute_command.
_VRAM_GROWING_ACTIONS = frozenset({"add_lane", "apply_lanes", "wake_lane", "reconfigure_lane"})


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
        # Keyed by cmd_id so a single in-flight command can be cancelled. An
        # unkeyed set only allowed "cancel everything on disconnect", which
        # left an abandoned request generating until it finished on its own.
        self._command_tasks: dict[str, asyncio.Task] = {}
        self._stopping = asyncio.Event()
        self._send_lock = asyncio.Lock()
        self._connected = False
        self._last_connected_at: datetime | None = None
        self._last_status_sent_at: datetime | None = None
        self._consecutive_failures = 0
        # Event ids already forwarded on the current connection. The log is
        # capped and trims from the front, so a list position is not a stable
        # cursor: once the log is full its length stops changing, and a
        # position-based cursor never advances past it again.
        self._forwarded_event_ids: set[str] = set()
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
                    # Resend the whole log to the new server session, and
                    # remember which events it already held: those are backlog,
                    # anything appended from here on is live. The first drain
                    # carries both and only this snapshot tells them apart.
                    self._forwarded_event_ids.clear()
                    replay_event_ids = self._current_event_ids()
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
                    event_task = asyncio.create_task(
                        self._event_loop(ws, replay_event_ids=replay_event_ids),
                        name="logos-bridge-events",
                    )
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

    async def _event_loop(self, ws, replay_event_ids: frozenset[str] = frozenset()) -> None:
        # Events named in *replay_event_ids* were already in the log when this
        # connection came up: a backlog that can hold lifecycle events from
        # sessions long finished, in an order that says nothing about what is
        # running now. They are flagged so the server keeps taking its
        # calibration state from the hello instead.
        #
        # Membership, not position. The log is capped at _MAX_EVENT_LOG and
        # trims from the front, so on a full log a live event lands at a
        # position the backlog used to occupy — a positional boundary would
        # send it as replay, the server would ignore it, and a terminal event
        # lost that way leaves the provider excluded from lane placement with
        # nothing left to release it. The same trimming is why what has already
        # been forwarded is tracked by id: a positional cursor equals the log
        # length once it is full and never advances again, so no further event
        # would reach the server at all.
        while not self._stopping.is_set():
            await asyncio.sleep(1)
            events = self._app.state.lane_manager.event_log
            for event in events:
                if event.event_id in self._forwarded_event_ids:
                    continue
                await self._send_json(
                    ws,
                    {
                        "type": "event",
                        "worker_id": self.worker_id,
                        "event": event.model_dump(mode="json"),
                        "replay": event.event_id in replay_event_ids,
                    },
                )
                self._forwarded_event_ids.add(event.event_id)
            # Forget ids the log has trimmed away, so this set stays bounded by
            # the log size rather than growing for the life of the connection.
            self._forwarded_event_ids &= {event.event_id for event in events}

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
                # Authoritative calibration state at connect time. The server
                # excludes calibrating workers from lane placement; it cannot
                # derive that from the replayed event log alone, because the
                # log is in-memory, capped, and only reaches the server a
                # moment after the first status has already made this worker
                # look plannable. Asks the task, not the slot: a finished
                # session lingers in _active_calibration_session until the next
                # start clears it, and reporting that as live would exclude this
                # worker from placement for as long as no new session begins.
                "calibrating": self._calibration_session_is_live(),
                "actions": [
                    "infer",
                    "infer_stream",
                    # The server only sends cancellations to a worker that
                    # lists this; an older worker keeps the previous
                    # behaviour instead of being sent a command it would
                    # answer with "Unsupported bridge command".
                    "cancel_command",
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
        # Every status repeats the live calibration state, so the server can
        # settle it without depending on a lifecycle event arriving. An event
        # is a one-shot signal: the one that ends a session can be dropped
        # (post-connect replay filter, a connection that no longer exists) and
        # the server is then left excluding this worker from lane placement
        # with nothing to release it. Part of the dedupe signature because a
        # session that starts and ends while the lanes are untouched changes
        # nothing else in the payload, and the status would not be sent at all.
        calibrating = self._calibration_session_is_live()
        signature = json.dumps(
            {"runtime": payload, "calibrating": calibrating},
            sort_keys=True,
            separators=(",", ":"),
        )
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
                "calibrating": calibrating,
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
        self._command_tasks[cmd_id] = task

        def _cleanup(done_task: asyncio.Task) -> None:
            # Only drop our own entry: a cmd_id is unique per command, but
            # clearing blindly would race a same-key re-registration.
            if self._command_tasks.get(cmd_id) is done_task:
                self._command_tasks.pop(cmd_id, None)
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
        tasks = tuple(self._command_tasks.values())
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

    def cancel_command(self, target_cmd_id: str) -> bool:
        """Cancel one in-flight command by its cmd_id.

        Returns whether a live task was found. Cancelling the task unwinds
        ``_execute_stream_command``'s ``finally``, which closes the httpx
        stream to the lane — that closed connection is what makes vLLM abort
        the sequence and free its KV blocks — and decrements the lane's
        in-flight count.
        """
        task = self._command_tasks.get(target_cmd_id)
        if task is None or task.done():
            return False
        task.cancel()
        return True

    async def _handle_cancel_command(self, ws, cmd_id: str, params: dict[str, Any]) -> None:
        """Abort the command named by ``params["target_cmd_id"]``.

        Sent when the client behind a request has gone away. Without it the
        lane keeps generating a response nobody will read: the relay holds a
        KV slot and burns GPU cycles for the full length of a generation that
        was abandoned, which under retry storms compounds the overload that
        caused the retries.

        Answers with a normal ``command_result`` so the server can tell an
        aborted stream from one that had already finished on its own.
        """
        target_cmd_id = str(params.get("target_cmd_id", "")).strip()
        cancelled = self.cancel_command(target_cmd_id) if target_cmd_id else False
        if cancelled:
            logger.info(
                "%s>> CMD cancel_command%s cmd_id=%s target=%s aborted",
                _CYAN + _BOLD,
                _RESET,
                cmd_id[:8],
                target_cmd_id[:8],
            )
        else:
            # Not an error: a cancel racing a completing stream is normal.
            logger.debug(
                "cancel_command cmd_id=%s target=%s: no in-flight command",
                cmd_id[:8],
                target_cmd_id[:8],
            )
        await self._send_json(
            ws,
            {
                "type": "command_result",
                "cmd_id": cmd_id,
                "success": True,
                "result": {"cancelled": cancelled, "target_cmd_id": target_cmd_id},
            },
        )

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

        # Cancellation must not queue behind the command it cancels — handle
        # it inline on the receive loop rather than spawning a task.
        if action == "cancel_command":
            await self._handle_cancel_command(ws, cmd_id, params)
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

        if action in _VRAM_GROWING_ACTIONS and self._calibration_session_is_live():
            # Last line of defence, at the resource itself. The server excludes
            # a calibrating worker from lane placement, but every mechanism it
            # has for knowing lags reality by some amount — an event in flight,
            # a plan made a moment ago — and a lane placed here takes the VRAM
            # the probes need, which fails the kv-cache search at sizes that
            # would otherwise fit. Refusing locally makes those races harmless.
            #
            # The session's own lane work does not come through here: it drives
            # the lane manager directly (destroy_all) and runs its probes on
            # _CALIBRATION_PORT. The server re-spawns lanes via apply_lanes once
            # the session ends, which is why that command in particular has to
            # be refused while it is still running.
            logger.warning(
                "[Calibration] refusing %s: a calibration session is running and holds this node's VRAM",
                action,
            )
            return {
                "ok": False,
                "error": (
                    f"'{action}' is refused while a calibration session is running: "
                    f"the session has freed this node's VRAM for its probes."
                ),
                "calibrating": True,
            }

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

    def _current_event_ids(self) -> frozenset[str]:
        lane_manager = getattr(self._app.state, "lane_manager", None)
        if lane_manager is None:
            return frozenset()
        try:
            return frozenset(event.event_id for event in lane_manager.event_log)
        except Exception:  # noqa: BLE001
            return frozenset()

    def _calibration_session_is_live(self) -> bool:
        """True while a calibration session is actually running.

        A finished session can linger in ``_active_calibration_session`` until
        the next start clears it, so the task state is what counts.
        """
        session = self._active_calibration_session
        if session is None:
            return False
        task = session.task
        return task is None or not task.done()

    async def _handle_start_calibration_session(self, params: dict[str, Any]) -> dict[str, Any]:
        """Start a worker-driven calibration session.

        The worker iterates its own list of uncalibrated configured models,
        runs each calibration sequentially, and emits ``calibration_*`` events
        back to the server. The server does not poll status and does not
        choose models; it only sends start/stop session RPCs.
        """
        # Refuse up front on the Metal backend: calibration.py measures
        # against nvidia-smi and samples /proc/meminfo, neither of which
        # exists on macOS, so no probe here can ever succeed. Capacity
        # profiles on this backend come from model_profile_overrides
        # (config.example.mlx.yml) — no flag is needed to keep the worker
        # away from a dead measurement path.
        if is_metal_backend():
            logger.info(
                "[Calibration] refusing start_calibration_session: calibration is "
                "unavailable on the Metal backend (nvidia-smi / /proc/meminfo "
                "do not exist on macOS) — profiles must come from "
                "model_profile_overrides"
            )
            return {
                "ok": False,
                "error": (
                    "calibration is unavailable on the Metal backend: it measures "
                    "against nvidia-smi and /proc/meminfo, which do not exist on "
                    "macOS. Supply capacity profiles via model_profile_overrides "
                    "instead."
                ),
                "calibration_unavailable": True,
                "reason_code": "metal-backend",
            }

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

    @staticmethod
    async def _read_calibration_log_text(
        model_name: str, log_dir: Path, max_bytes: int = _MAX_CALIBRATION_LOG_TEXT_BYTES
    ) -> str:
        log_path = log_dir / f"{model_name.replace('/', '__')}.log"
        try:
            return await asyncio.to_thread(LogosBridgeClient._read_calibration_log_tail, log_path, max_bytes)
        except OSError:
            return ""

    @staticmethod
    def _read_calibration_log_tail(log_path: Path, max_bytes: int) -> str:
        with log_path.open("rb") as f:
            file_size = f.seek(0, os.SEEK_END)
            if file_size <= max_bytes:
                f.seek(0)
                return f.read().decode("utf-8", errors="replace")

            omitted = file_size - max_bytes
            marker = f"... [truncated, {omitted} bytes omitted] ...\n"
            budget = max(0, max_bytes - len(marker.encode("utf-8")))

            f.seek(-budget, os.SEEK_END)
            tail = f.read().decode("utf-8", errors="ignore")
            return marker + tail

    @staticmethod
    def _truncate_calibration_log_text(text: str, max_bytes: int = _MAX_CALIBRATION_LOG_TEXT_BYTES) -> str:
        """Cap ``text`` to at most ``max_bytes`` UTF-8 bytes, trimming the head.

        The on-disk log is append-mode across every probe attempt in a
        session and can grow to several hundred KB (see
        ``_read_calibration_log_text``); without a cap the encoded
        ``calibration_probe_log`` event — and the DB row it lands in — would
        be unbounded. Keeps the tail (most recent output, where failures
        typically surface) and prefixes a truncation marker inside the limit.
        """
        encoded = text.encode("utf-8")
        if len(encoded) <= max_bytes:
            return text

        omitted = len(encoded) - max_bytes
        marker = f"... [truncated, {omitted} bytes omitted] ...\n"
        budget = max(0, max_bytes - len(marker.encode("utf-8")))
        tail = encoded[-budget:].decode("utf-8", errors="ignore")
        return marker + tail

    def _record_calibration_probe_log(self, model_name: str, result: Any, log_text: str) -> None:
        """Report the finalized per-model probe log to the orchestrator.

        Fires once per model after ``calibrate_with_tp_escalation`` returns
        (success or failure) — the model's ``{model}.log`` file is complete
        for this session's attempt at that point. Rides the same event
        channel as the other calibration events; the orchestrator upserts
        this into ``calibration_probe_logs``, keyed on (node, model).
        ``log_text`` is the caller's already-read file content (read off
        the event loop — see the call sites) so this stays a cheap,
        non-blocking, plain-sync call like the rest of the event helpers.
        """
        self._record_calibration_event(
            "calibration_probe_log",
            model=model_name,
            details=json.dumps(
                {
                    "success": result.success,
                    "probe_command": result.probe_command,
                    "error": result.error,
                    "unsupported_reason": result.unsupported_reason,
                    "node_unhealthy_reason": result.node_unhealthy_reason,
                    "tensor_parallel_size": result.tensor_parallel_size,
                    "gpu_devices": result.gpu_devices,
                    "kv_cache_sent_mb": round(result.kv_cache_sent_mb, 1),
                    "base_residency_mb": round(result.base_residency_mb, 1),
                    "loaded_vram_mb": round(result.loaded_vram_mb, 1),
                    "sleeping_residual_mb": (
                        round(result.sleeping_residual_mb, 1) if result.sleeping_residual_mb is not None else None
                    ),
                    "min_kv_cache_mb": round(result.min_kv_cache_mb, 1),
                    "max_kv_cache_mb": round(result.max_kv_cache_mb, 1),
                    "max_model_len": result.max_model_len,
                    "cold_load_time_s": (
                        round(result.cold_load_time_s, 1) if result.cold_load_time_s is not None else None
                    ),
                    "wake_from_sleep_time_s": (
                        round(result.wake_from_sleep_time_s, 1) if result.wake_from_sleep_time_s is not None else None
                    ),
                    "log_text": self._truncate_calibration_log_text(log_text),
                }
            ),
        )

    def _list_uncalibrated_models(self) -> list[str]:
        """Pick configured models that still need calibration.

        Mirrors the previous server-side selection logic so behaviour is
        unchanged — only the location of the decision moves to the worker.
        Models that cannot sleep on this worker are judged on their non-sleep
        fields alone, because their sleep fields stay null by design; models
        flagged calibration_unsupported are skipped entirely.
        """
        cfg = self._app.state.config
        model_profiles = self._app.state.model_profiles
        candidates = list(self._cfg.configured_models) or list(self._cfg.capabilities_models)

        # A session at level 0 measures no sleep field for any model, so those
        # fields must not count as missing — a run that cannot fill them would
        # otherwise re-pick the same models every time.
        session_sleep_level = (
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
            # session driver re-checks model_can_sleep before each model,
            # persists the new flag, and calibrates it at sleep_level 0. That
            # run leaves the sleep fields null by design, so they must not
            # count as missing here either. Mirrors
            # main.py::_auto_calibrate_if_needed.
            if session_sleep_level <= 0 or not model_can_sleep(cfg, model_name):
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
        # Push a status carrying calibrating=True right away. The server holds
        # its optimistic mark for a bounded window after dispatching the start,
        # and this is what confirms the session inside it.
        if lane_manager is not None:
            try:
                lane_manager._mark_status_dirty()  # noqa: SLF001
            except Exception:  # noqa: BLE001
                logger.debug("[Calibration] _mark_status_dirty failed", exc_info=True)
        try:
            from logos_worker_node.calibration import (  # noqa: PLC0415
                _CALIBRATION_PORT,
                _DEFAULT_VLLM,
                _READY_TIMEOUT_S,
                ProfileStoreUnreadableError,
                calibrate_with_tp_escalation,
                is_model_unsupported,
                load_existing_profiles,
                merge_profile,
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

            # Free the calibration's GPU slice up front — but only that slice
            # (issue #592). The probe is pinned to the slice (CUDA_VISIBLE_DEVICES),
            # so it only competes for the slice's VRAM; lanes on the leftover
            # GPUs keep serving for the rest of the session instead of sitting
            # idle. Without the pin the kv-cache search would start against an
            # already-loaded model on the measured GPUs and OOM at sizes that
            # would otherwise fit. The Logos server re-spawns the stopped slice
            # lanes via the normal apply_lanes path once the session ends.
            if lane_manager is not None:
                try:
                    calibration_gpus = lane_manager.begin_calibration_session()
                    stopped = await lane_manager.destroy_lanes_on_gpus(calibration_gpus)
                    logger.info(
                        "[Calibration] Calibration holds GPU(s) %s — stopped %d lane(s) on them; "
                        "leftover lanes kept serving",
                        sorted(calibration_gpus),
                        stopped,
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("[Calibration] calibration slice setup failed — continuing anyway")

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
                # for this model (worker kill switch or per-model override),
                # probing with sleep_level>0 would fail at the POST /sleep in
                # Phase 4 and waste the whole run. Calibrate it at level 0
                # instead: the sleep phases are skipped, sleeping_residual_mb
                # is recorded as null, and everything the planner places on —
                # base_residency_mb — is measured exactly as for any other
                # model. Skipping the model outright, as this used to, left it
                # permanently uncalibrated: a nosleep model is never reported
                # as a capability without a profile, and no later session could
                # ever produce one either.
                model_sleep_level = session.sleep_level
                if not model_can_sleep(cfg, model_name):
                    model_profiles.mark_sleep_mode_disabled(model_name, True)
                    model_sleep_level = 0
                    logger.info(
                        "[Calibration] %s cannot sleep on this worker — calibrating without the sleep phases",
                        model_name,
                    )
                else:
                    # Config now permits sleep — clear any stale flag so a
                    # config flip (true → false) is picked up immediately.
                    model_profiles.mark_sleep_mode_disabled(model_name, False)

                plan = plan_by_model.get(model_name) or {"model": model_name}
                self._record_calibration_event(
                    "calibration_model_started",
                    model=model_name,
                    details=f"sleep_level={model_sleep_level}",
                )
                logger.info(
                    "[Calibration] Starting model=%s sleep_level=%d",
                    model_name,
                    model_sleep_level,
                )

                # Blocking calibration runs in the default thread executor so
                # we keep the bridge's event loop responsive. The cancel_event
                # is the same instance the stop RPC sets — wait_ready polls
                # it every 2s and bails immediately.
                loop = asyncio.get_running_loop()
                try:
                    result = await loop.run_in_executor(
                        None,
                        lambda p=plan, sl=model_sleep_level: calibrate_with_tp_escalation(
                            p,
                            vllm_binary=_DEFAULT_VLLM,
                            port=_CALIBRATION_PORT,
                            log_dir=log_dir,
                            sleep_level=sl,
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
                    # An unreadable store aborts the write: load_existing_profiles
                    # used to answer with an empty dict, and saving that back
                    # replaced every profile on the node with this one result.
                    # Losing one measurement is recoverable; losing the file is
                    # not, because a model without base_residency_mb is never
                    # announced as a capability and a model that cannot sleep
                    # here would keep failing to be re-measured.
                    try:
                        existing = load_existing_profiles(profiles_path)
                    except ProfileStoreUnreadableError as exc:
                        logger.error(
                            "[Calibration] %s calibrated, but %s is unreadable (%s) — "
                            "keeping the file untouched. Fix or remove it; this model "
                            "re-calibrates on the next session.",
                            model_name,
                            profiles_path,
                            exc,
                        )
                        self._record_calibration_event(
                            "calibration_model_failed",
                            model=model_name,
                            details=f"profile store unreadable: {exc}",
                        )
                        continue
                    existing[model_name] = merge_profile(
                        existing.get(model_name),
                        result_to_profile_dict(result),
                    )
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
                    log_text = await self._read_calibration_log_text(model_name, log_dir)
                    self._record_calibration_probe_log(model_name, result, log_text)
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
                    log_text = await self._read_calibration_log_text(model_name, log_dir)
                    self._record_calibration_probe_log(model_name, result, log_text)

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
                    lane_manager.end_calibration_session()
                except Exception:  # noqa: BLE001
                    logger.debug("[Calibration] end_calibration_session failed", exc_info=True)
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

    async def _execute_infer_command(self, params: dict[str, Any]) -> dict[str, Any]:
        lane_manager = self._app.state.lane_manager
        lane_id = str(params.get("lane_id", "")).strip()
        payload = params.get("payload") or {}
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")

        # Atomically validate-and-count the lane (closes the dispatch-to-sleep
        # race: the lane cannot be slept/evicted between selection and counting).
        lane_status = (await lane_manager.acquire_lane_for_infer(lane_id)).model_dump(mode="json")
        try:
            request_path = params.get("request_path")
            target_url = self._lane_target_url(lane_status, payload, request_path=request_path)
            request_kwargs, request_headers = httpx_request_parts(payload)
            async with httpx.AsyncClient(timeout=_INFERENCE_RELAY_TIMEOUT) as client:
                upstream = await client.post(
                    target_url,
                    headers=request_headers,
                    **request_kwargs,
                )
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Lane relay request failed for '{lane_id}': {exc}") from exc
        finally:
            await lane_manager.decrement_active_requests(lane_id)

        content_type = upstream.headers.get("content-type")
        media_type = (content_type or "").partition(";")[0].strip().lower()
        is_json_response = not media_type or media_type == "application/json" or media_type.endswith("+json")
        is_successful_multipart = upstream.status_code < 400 and isinstance(payload.get(MULTIPART_PAYLOAD_KEY), dict)
        is_text_response = media_type.startswith("text/") or media_type == "application/x-subrip"
        body_base64 = None
        if is_successful_multipart:
            if is_text_response:
                body = upstream.text
            elif is_json_response:
                try:
                    body = upstream.json()
                except ValueError:
                    body = None
                    body_base64 = base64.b64encode(upstream.content).decode("ascii")
            else:
                body = None
                body_base64 = base64.b64encode(upstream.content).decode("ascii")
        else:
            try:
                body = upstream.json()
            except ValueError:
                body = upstream.text

        headers = {}
        if content_type:
            headers["content-type"] = content_type
        result = {
            "status_code": int(upstream.status_code),
            "body": body,
            "headers": headers,
        }
        if body_base64 is not None:
            result["body_base64"] = body_base64
            result["body_encoding"] = "base64"
        return result

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

        # Atomically validate-and-count the lane (closes the dispatch-to-sleep
        # race). On failure, emit a clean stream_end so the orchestrator reroutes
        # instead of the client seeing a severed stream. The increment is now part
        # of acquire; the finally below decrements it.
        try:
            lane_status = (await lane_manager.acquire_lane_for_infer(lane_id)).model_dump(mode="json")
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

        client = httpx.AsyncClient(timeout=_INFERENCE_RELAY_TIMEOUT)
        upstream = None
        try:
            request_path = params.get("request_path")
            target_url = self._lane_target_url(lane_status, payload, request_path=request_path)
            request_kwargs, request_headers = httpx_request_parts(payload)
            request = client.build_request(
                "POST",
                target_url,
                headers=request_headers,
                **request_kwargs,
            )
            upstream = await client.send(request, stream=True)

            def _start_frame() -> dict[str, Any]:
                return {
                    "type": "stream_start",
                    "cmd_id": cmd_id,
                    "status_code": int(upstream.status_code),
                    "content_type": upstream.headers.get("content-type", "text/event-stream"),
                }

            if upstream.status_code >= 400:
                # Error response: surface status + body immediately, then end.
                await self._send_json(ws, _start_frame())
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

            # 2xx: DEFER stream_start until the FIRST real token byte. vLLM returns
            # 200 headers before generating, so a lane that flipped to "awake" in
            # state but whose EngineCore is not yet serveable (just-woken / re-slept)
            # 200s the headers then emits nothing — which previously reached the
            # client as 200 + empty TTFT + a dropped body (RemoteProtocolError).
            # Withholding stream_start until the first byte turns that into a clean
            # pre-200 failure the orchestrator can reroute, with no client-visible
            # partial success. (A mid-stream drop after the first byte is unrelated
            # — the in-flight count protects an active lane from being slept.)
            started = False
            async for chunk in upstream.aiter_bytes():
                if not chunk:
                    continue
                if not started:
                    await self._send_json(ws, _start_frame())
                    started = True
                await self._send_json(
                    ws,
                    {
                        "type": "stream_chunk",
                        "cmd_id": cmd_id,
                        "chunk_b64": base64.b64encode(chunk).decode("ascii"),
                    },
                )
            if not started:
                # 2xx but the upstream produced ZERO bytes (engine not ready / lane
                # re-slept mid-request). Fail cleanly BEFORE any stream_start so the
                # request is reroutable rather than a client-visible 200-then-drop.
                await self._send_json(
                    ws,
                    {
                        "type": "stream_end",
                        "cmd_id": cmd_id,
                        "success": False,
                        "error": f"Lane '{lane_id}' returned 200 but produced no output (not ready / re-slept)",
                    },
                )
                return
            await self._send_json(ws, {"type": "stream_end", "cmd_id": cmd_id, "success": True})
        except asyncio.CancelledError:
            # The server cancelled this stream because its client went away.
            # No terminal frame: nobody is reading, and the server already
            # dropped the queue for this cmd_id. What matters is the `finally`
            # below — closing the httpx stream is what tells vLLM to abort the
            # sequence instead of generating into a socket nobody drains.
            # CancelledError is a BaseException, so the handler below does not
            # swallow it and no spurious stream_end is emitted.
            logger.info(
                "%s<< STREAM CANCELLED%s cmd_id=%s lane=%s — aborting generation",
                _YELLOW,
                _RESET,
                cmd_id[:8],
                lane_id,
            )
            raise
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
            #
            # Guarded so a lane-manager failure cannot skip the aclose below:
            # on the cancellation path that close is the whole point — it is
            # what makes vLLM abort the sequence and release its KV blocks.
            try:
                await lane_manager.decrement_active_requests(lane_id)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Failed to decrement in-flight count for lane=%s (cmd_id=%s)",
                    lane_id,
                    cmd_id[:8],
                    exc_info=True,
                )
            if upstream is not None:
                try:
                    await asyncio.wait_for(upstream.aclose(), timeout=5.0)
                except Exception:  # noqa: BLE001
                    pass
            try:
                await asyncio.wait_for(client.aclose(), timeout=5.0)
            except Exception:  # noqa: BLE001
                pass
