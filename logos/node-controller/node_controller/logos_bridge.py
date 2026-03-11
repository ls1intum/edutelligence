"""
Node-controller <-> Logos bridge client.

This client authenticates against Logos, opens a persistent websocket session,
publishes runtime status, and executes control commands from Logos.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
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

from node_controller.config import save_lanes_config
from node_controller.models import LaneConfig, LaneStatus, LogosConfig

logger = logging.getLogger("node_controller.logos_bridge")


class LogosBridgeClient:
    """Maintains a secure outbound control session to Logos."""

    def __init__(self, app: Any, config: LogosConfig) -> None:
        self._app = app
        self._cfg = config
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()
        self._send_lock = asyncio.Lock()

    async def start(self) -> None:
        if not self._cfg.enabled:
            logger.info("Logos bridge disabled in config")
            return
        if self._task is not None and not self._task.done():
            return
        self._stopping.clear()
        self._task = asyncio.create_task(self._run(), name="logos-bridge")
        logger.info(
            "Logos bridge started (provider_id=%s, node_id=%s)",
            self._cfg.provider_id,
            self._node_id(),
        )

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
        logger.info("Logos bridge stopped")

    def _node_id(self) -> str:
        return self._cfg.node_id or f"node-{self._cfg.provider_id}"

    async def _run(self) -> None:
        if websockets is None:
            raise RuntimeError("websockets dependency is required for Logos bridge")
        backoff = max(1, self._cfg.reconnect_backoff_seconds)
        while not self._stopping.is_set():
            try:
                auth = await self._authenticate()
                ws_url = str(auth.get("ws_url", "")).strip()
                if not ws_url:
                    raise RuntimeError("Logos /auth response missing ws_url")

                logger.info("Connecting Logos bridge websocket: %s", ws_url)
                async with websockets.connect(
                    ws_url,
                    ping_interval=None,
                    close_timeout=5,
                    max_size=2 * 1024 * 1024,
                ) as ws:
                    await self._send_status_update(ws)
                    heartbeat_task = asyncio.create_task(
                        self._heartbeat_loop(ws),
                        name="logos-bridge-heartbeat",
                    )
                    try:
                        while not self._stopping.is_set():
                            raw = await ws.recv()
                            if isinstance(raw, bytes):
                                raw = raw.decode("utf-8", errors="replace")
                            await self._handle_message(ws, raw)
                    finally:
                        heartbeat_task.cancel()
                        try:
                            await heartbeat_task
                        except asyncio.CancelledError:
                            pass
            except asyncio.CancelledError:
                raise
            except ConnectionClosed as exc:
                logger.warning("Logos websocket closed (%s)", exc)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Logos bridge cycle failed: %s", exc)

            if self._stopping.is_set():
                return
            await asyncio.sleep(backoff)

    async def _authenticate(self) -> dict[str, Any]:
        logos_url = (self._cfg.logos_url or "").rstrip("/")
        if not logos_url:
            raise RuntimeError("logos.logos_url must be configured when logos.enabled=true")
        parsed = urlparse(logos_url)
        if parsed.scheme not in {"https", "http"}:
            raise RuntimeError("logos.logos_url must use https (or http with logos.allow_insecure_http=true)")
        if parsed.scheme == "http" and not self._cfg.allow_insecure_http:
            raise RuntimeError("logos.logos_url uses http but logos.allow_insecure_http is false")
        if not self._cfg.provider_id:
            raise RuntimeError("logos.provider_id must be configured when logos.enabled=true")
        if not self._cfg.shared_key:
            raise RuntimeError("logos.shared_key must be configured when logos.enabled=true")

        auth_url = f"{logos_url}/logosdb/providers/node/auth"
        payload = {
            "provider_id": self._cfg.provider_id,
            "shared_key": self._cfg.shared_key,
            "node_id": self._node_id(),
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
                raise RuntimeError("Logos /auth response missing session token")
            ws_url = self._derive_ws_url(token)
            data["ws_url"] = ws_url
        ws_parsed = urlparse(ws_url)
        if ws_parsed.scheme not in {"wss", "ws"}:
            raise RuntimeError("Logos websocket URL must use wss (or ws in dev mode)")
        if ws_parsed.scheme == "ws" and not self._cfg.allow_insecure_http:
            raise RuntimeError("Logos websocket URL uses ws but logos.allow_insecure_http is false")
        return data

    def _derive_ws_url(self, token: str) -> str:
        parsed = urlparse(self._cfg.logos_url)
        if not parsed.scheme or not parsed.netloc:
            raise RuntimeError("logos.logos_url must be an absolute URL")
        if parsed.scheme not in {"https", "http"}:
            raise RuntimeError("logos.logos_url must use https (or http with logos.allow_insecure_http=true)")
        if parsed.scheme == "http":
            if not self._cfg.allow_insecure_http:
                raise RuntimeError("logos.logos_url uses http but logos.allow_insecure_http is false")
            ws_scheme = "ws"
        else:
            ws_scheme = "wss"
        return f"{ws_scheme}://{parsed.netloc}/logosdb/providers/node/session?token={token}"

    async def _heartbeat_loop(self, ws) -> None:
        interval = max(1, self._cfg.heartbeat_interval_seconds)
        while not self._stopping.is_set():
            await asyncio.sleep(interval)
            await self._send_status_update(ws)

    async def _send_status_update(self, ws) -> None:
        lane_manager = self._app.state.lane_manager
        gpu_collector = self._app.state.gpu_collector
        lanes = await lane_manager.get_all_statuses()
        gpu = await gpu_collector.get_snapshot()
        message = {
            "type": "status_update",
            "provider_id": self._cfg.provider_id,
            "node_id": self._node_id(),
            "capabilities_models": self._cfg.capabilities_models,
            "status": {
                "lanes": [lane.model_dump(mode="json") for lane in lanes],
                "gpu": gpu.model_dump(mode="json"),
            },
        }
        await self._send_json(ws, message)

    async def _send_json(self, ws, payload: dict[str, Any]) -> None:
        async with self._send_lock:
            await ws.send(json.dumps(payload))

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
            await self._execute_stream_command(ws, cmd_id, params)
            return

        try:
            result = await self._execute_command(action, params)
            response = {
                "type": "command_result",
                "cmd_id": cmd_id,
                "success": True,
                "result": result,
            }
        except Exception as exc:  # noqa: BLE001
            response = {
                "type": "command_result",
                "cmd_id": cmd_id,
                "success": False,
                "error": str(exc),
            }
        await self._send_json(ws, response)

    async def _execute_command(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        lane_manager = self._app.state.lane_manager
        gpu_collector = self._app.state.gpu_collector

        if action == "infer":
            return await self._execute_infer_command(params)

        if action == "get_status":
            lanes = await lane_manager.get_all_statuses()
            gpu = await gpu_collector.get_snapshot()
            return {
                "lanes": [lane.model_dump(mode="json") for lane in lanes],
                "gpu": gpu.model_dump(mode="json"),
            }

        if action == "get_gpu":
            gpu = await gpu_collector.get_snapshot()
            return gpu.model_dump(mode="json")

        if action == "get_lanes":
            lanes = await lane_manager.get_all_statuses()
            return {"lanes": [lane.model_dump(mode="json") for lane in lanes]}

        if action == "apply_lanes":
            raw_lanes = params.get("lanes") or []
            lanes = [LaneConfig(**item) for item in raw_lanes]
            result = await lane_manager.apply_lanes(lanes)
            if result.success:
                save_lanes_config(lanes)
            return result.model_dump(mode="json")

        lane_id = str(params.get("lane_id", "")).strip()
        if action == "delete_lane":
            if not lane_id:
                raise ValueError("lane_id is required")
            await lane_manager.remove_lane(lane_id)
            return {"ok": True, "lane_id": lane_id}

        if action == "sleep_lane":
            if not lane_id:
                raise ValueError("lane_id is required")
            status = await lane_manager.sleep_lane(
                lane_id,
                level=int(params.get("level", 1)),
                mode=str(params.get("mode", "wait")),
            )
            return status.model_dump(mode="json")

        if action == "wake_lane":
            if not lane_id:
                raise ValueError("lane_id is required")
            status = await lane_manager.wake_lane(lane_id)
            return status.model_dump(mode="json")

        if action == "reconfigure_lane":
            if not lane_id:
                raise ValueError("lane_id is required")
            updates = params.get("updates") or {}
            if not isinstance(updates, dict):
                raise ValueError("updates must be an object")
            status = await lane_manager.reconfigure_lane(lane_id, updates)
            return status.model_dump(mode="json")

        raise ValueError(f"Unsupported bridge command '{action}'")

    @staticmethod
    def _lane_target_url(lane: LaneStatus) -> str:
        endpoint = (lane.inference_endpoint or "/v1/chat/completions").lstrip("/")
        return f"http://127.0.0.1:{lane.port}/{endpoint}"

    async def _resolve_lane_for_infer(self, lane_id: str) -> LaneStatus:
        if not lane_id:
            raise ValueError("lane_id is required")
        lane_manager = self._app.state.lane_manager
        lane_status = await lane_manager.get_lane_status(lane_id)
        if lane_status.runtime_state != "running":
            raise RuntimeError(f"Lane '{lane_id}' is not running (state={lane_status.runtime_state})")
        return lane_status

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
            target_url = self._lane_target_url(lane_status)
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

            await self._send_json(
                ws,
                {
                    "type": "stream_end",
                    "cmd_id": cmd_id,
                    "success": True,
                },
            )
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
            if upstream is not None:
                try:
                    await upstream.aclose()
                except Exception:  # noqa: BLE001
                    pass
            await client.aclose()
            await lane_manager.decrement_active_requests(lane_id)
