"""Outbound Logos control-plane bridge for LogosWorkerNode."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

try:
    import websockets
    from websockets.exceptions import ConnectionClosed
except Exception:  # noqa: BLE001
    websockets = None

    class ConnectionClosed(Exception):
        pass

from logos_worker_node.config import save_lanes_config
from logos_worker_node.models import LaneConfig, LogosConfig, WorkerTransportStatus
from logos_worker_node import prometheus_metrics as prom
from logos_worker_node.runtime import build_runtime_status

logger = logging.getLogger("logos_worker_node.logos_bridge")

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

    @property
    def worker_id(self) -> str:
        return self._cfg.worker_id or f"worker-{self._cfg.provider_id}"

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
        logger.info("Logos bridge started (provider_id=%s, worker_id=%s)", self._cfg.provider_id, self.worker_id)

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
                    max_size=4 * 1024 * 1024,
                ) as ws:
                    self._connected = True
                    self._last_connected_at = datetime.now(timezone.utc)
                    self._consecutive_failures = 0
                    self._last_event_seq = 0
                    self._last_runtime_signature = None
                    self._last_runtime_payload = {}
                    caps = list(self._cfg.capabilities_models) if self._cfg.capabilities_models else []
                    logger.info(
                        "%s══ BRIDGE CONNECTED ══%s provider_id=%s worker_id=%s "
                        "capabilities=%s url=%s",
                        _GREEN + _BOLD, _RESET,
                        self._cfg.provider_id, self.worker_id,
                        caps or "(none)", ws_url.split("?")[0],
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
                    "%s══ BRIDGE DISCONNECTED ══%s websocket closed: %s "
                    "(consecutive_failures=%d)",
                    _RED + _BOLD, _RESET, exc, self._consecutive_failures,
                )
            except Exception as exc:  # noqa: BLE001
                self._consecutive_failures += 1
                prom.BRIDGE_RECONNECTS_TOTAL.inc()
                prom.BRIDGE_ERRORS_TOTAL.inc()
                logger.warning(
                    "%s══ BRIDGE ERROR ══%s %s (consecutive_failures=%d, "
                    "retrying in %ds)",
                    _RED + _BOLD, _RESET, exc, self._consecutive_failures,
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
        if not self._cfg.provider_id or not self._cfg.shared_key:
            raise RuntimeError("logos.provider_id and logos.shared_key are required")

        auth_url = f"{logos_url}/logosdb/providers/logosnode/auth"
        payload = {
            "provider_id": self._cfg.provider_id,
            "shared_key": self._cfg.shared_key,
            "worker_id": self.worker_id,
            "capabilities_models": self._cfg.capabilities_models,
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(auth_url, json=payload)
        if resp.status_code >= 400:
            raise RuntimeError(f"/auth rejected with HTTP {resp.status_code}: {resp.text}")
        data = resp.json() if resp.content else {}
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
        while not self._stopping.is_set():
            next_revision = await lane_manager.wait_for_status_revision(revision, timeout=1.0)
            changed = next_revision != revision
            revision = next_revision
            if changed or self._runtime_has_transient_lanes():
                await self._send_runtime_status(ws, force=False)

    async def _event_loop(self, ws) -> None:
        while not self._stopping.is_set():
            await asyncio.sleep(1)
            events = self._app.state.lane_manager.event_log
            for event in events[self._last_event_seq:]:
                await self._send_json(
                    ws,
                    {
                        "type": "event",
                        "provider_id": self._cfg.provider_id,
                        "worker_id": self.worker_id,
                        "event": event.model_dump(mode="json"),
                    },
                )
            self._last_event_seq = len(events)

    async def _send_hello(self, ws) -> None:
        await self._send_json(
            ws,
            {
                "type": "hello",
                "provider_id": self._cfg.provider_id,
                "worker_id": self.worker_id,
                "capabilities_models": self._cfg.capabilities_models,
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
                "provider_id": self._cfg.provider_id,
                "worker_id": self.worker_id,
                "capabilities_models": self._cfg.capabilities_models,
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
                "provider_id": self._cfg.provider_id,
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
                    _RED, action, _RESET, cmd_id[:8], exc,
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
                logger.debug("Bridge background command task failed during shutdown", exc_info=True)
        self._command_tasks.clear()

    async def _execute_command_and_respond(self, ws, cmd_id: str, action: str, params: dict[str, Any]) -> None:
        if action != "infer":
            param_summary = ", ".join(f"{k}={v}" for k, v in params.items() if k != "messages")
            logger.info(
                "%s>> CMD %s%s cmd_id=%s %s",
                _CYAN + _BOLD, action, _RESET, cmd_id[:8], param_summary,
            )

        try:
            result = await self._execute_command(action, params)
            if action != "infer":
                logger.info(
                    "%s<< CMD %s OK%s cmd_id=%s",
                    _GREEN, action, _RESET, cmd_id[:8],
                )
            response = {"type": "command_result", "cmd_id": cmd_id, "success": True, "result": result}
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "%s<< CMD %s FAILED%s cmd_id=%s error=%s",
                _RED, action, _RESET, cmd_id[:8], exc,
            )
            response = {"type": "command_result", "cmd_id": cmd_id, "success": False, "error": str(exc)}
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
            if result.success:
                try:
                    save_lanes_config(lanes)
                except OSError:
                    logger.debug("Could not persist lane config (read-only filesystem)")
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

        raise ValueError(f"Unsupported bridge command '{action}'")

    @staticmethod
    def _lane_target_url(lane_status: dict[str, Any]) -> str:
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
        target_url = self._lane_target_url(lane_status)

        await lane_manager.increment_active_requests(lane_id)
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                upstream = await client.post(target_url, headers={"Content-Type": "application/json"}, json=payload)
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
        return {"status_code": int(upstream.status_code), "body": body, "headers": headers}

    async def _execute_stream_command(self, ws, cmd_id: str, params: dict[str, Any]) -> None:
        lane_manager = self._app.state.lane_manager
        lane_id = str(params.get("lane_id", "")).strip()
        payload = params.get("payload") or {}
        if not isinstance(payload, dict):
            await self._send_json(ws, {"type": "stream_end", "cmd_id": cmd_id, "success": False, "error": "payload must be an object"})
            return

        try:
            lane_status = await self._resolve_lane_for_infer(lane_id)
            target_url = self._lane_target_url(lane_status)
        except Exception as exc:  # noqa: BLE001
            await self._send_json(ws, {"type": "stream_end", "cmd_id": cmd_id, "success": False, "error": str(exc)})
            return

        await lane_manager.increment_active_requests(lane_id)
        client = httpx.AsyncClient(timeout=None)
        upstream = None
        try:
            request = client.build_request("POST", target_url, headers={"Content-Type": "application/json"}, json=payload)
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
                        {"type": "stream_chunk", "cmd_id": cmd_id, "chunk_b64": base64.b64encode(raw).decode("ascii")},
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
                    {"type": "stream_chunk", "cmd_id": cmd_id, "chunk_b64": base64.b64encode(chunk).decode("ascii")},
                )
            await self._send_json(ws, {"type": "stream_end", "cmd_id": cmd_id, "success": True})
        except Exception as exc:  # noqa: BLE001
            await self._send_json(ws, {"type": "stream_end", "cmd_id": cmd_id, "success": False, "error": str(exc)})
        finally:
            if upstream is not None:
                try:
                    await upstream.aclose()
                except Exception:  # noqa: BLE001
                    pass
            await client.aclose()
            await lane_manager.decrement_active_requests(lane_id)
