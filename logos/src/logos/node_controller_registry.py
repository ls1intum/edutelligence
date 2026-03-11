"""
Runtime registry for connected node provider sessions.
"""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import secrets
from typing import Any, AsyncIterator
import uuid

from fastapi import WebSocket


class NodeControllerOfflineError(RuntimeError):
    """Raised when a provider has no active websocket session."""


class NodeControllerCommandError(RuntimeError):
    """Raised when a command RPC returns an error."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class AuthTicket:
    provider_id: int
    node_id: str
    capabilities_models: set[str]
    expires_at: datetime


@dataclass
class ProviderSession:
    provider_id: int
    node_id: str
    websocket: WebSocket
    capabilities_models: set[str] = field(default_factory=set)
    last_heartbeat: datetime = field(default_factory=_utc_now)
    latest_status: dict[str, Any] = field(default_factory=dict)
    pending_commands: dict[str, asyncio.Future] = field(default_factory=dict)
    pending_streams: dict[str, asyncio.Queue] = field(default_factory=dict)
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def is_stale(self, stale_after_seconds: int) -> bool:
        return (_utc_now() - self.last_heartbeat) > timedelta(seconds=stale_after_seconds)


class NodeControllerRuntimeRegistry:
    """Tracks auth tickets, active provider sessions, and lane runtime data."""

    def __init__(self) -> None:
        self._tickets: dict[str, AuthTicket] = {}
        self._sessions: dict[int, ProviderSession] = {}
        self._lock = asyncio.Lock()

    async def issue_ticket(
        self,
        provider_id: int,
        node_id: str,
        capabilities_models: list[str],
        ttl_seconds: int = 60,
    ) -> str:
        token = secrets.token_urlsafe(32)
        expires_at = _utc_now() + timedelta(seconds=max(5, ttl_seconds))
        ticket = AuthTicket(
            provider_id=int(provider_id),
            node_id=node_id,
            capabilities_models={m for m in capabilities_models if isinstance(m, str) and m.strip()},
            expires_at=expires_at,
        )
        async with self._lock:
            self._tickets[token] = ticket
        return token

    async def consume_ticket(self, token: str) -> AuthTicket | None:
        async with self._lock:
            ticket = self._tickets.pop(token, None)
        if ticket is None:
            return None
        if ticket.expires_at < _utc_now():
            return None
        return ticket

    async def attach_session(self, ticket: AuthTicket, websocket: WebSocket) -> ProviderSession:
        session = ProviderSession(
            provider_id=ticket.provider_id,
            node_id=ticket.node_id,
            websocket=websocket,
            capabilities_models=set(ticket.capabilities_models),
        )
        async with self._lock:
            old = self._sessions.get(ticket.provider_id)
            self._sessions[ticket.provider_id] = session
        if old is not None:
            await self._close_session(old)
        return session

    async def detach_session(self, provider_id: int, websocket: WebSocket | None = None) -> None:
        async with self._lock:
            session = self._sessions.get(provider_id)
            if session is None:
                return
            if websocket is not None and session.websocket is not websocket:
                return
            self._sessions.pop(provider_id, None)
        for fut in list(session.pending_commands.values()):
            if not fut.done():
                fut.set_exception(NodeControllerOfflineError("Provider disconnected"))
        for queue in list(session.pending_streams.values()):
            try:
                queue.put_nowait(
                    {
                        "type": "stream_end",
                        "success": False,
                        "error": "Provider disconnected",
                    }
                )
            except Exception:  # noqa: BLE001
                pass
        session.pending_streams.clear()
        await self._close_session(session)

    async def _close_session(self, session: ProviderSession) -> None:
        try:
            await session.websocket.close()
        except Exception:  # noqa: BLE001
            pass

    async def update_status(
        self,
        provider_id: int,
        status: dict[str, Any],
        capabilities_models: list[str] | None = None,
    ) -> None:
        session = await self._get_session(provider_id)
        if session is None:
            return
        session.latest_status = status if isinstance(status, dict) else {}
        session.last_heartbeat = _utc_now()
        if capabilities_models is not None:
            session.capabilities_models = {
                m for m in capabilities_models if isinstance(m, str) and m.strip()
            }

    async def mark_heartbeat(self, provider_id: int) -> None:
        session = await self._get_session(provider_id)
        if session is not None:
            session.last_heartbeat = _utc_now()

    async def on_command_result(self, provider_id: int, payload: dict[str, Any]) -> None:
        session = await self._get_session(provider_id)
        if session is None:
            return
        cmd_id = str(payload.get("cmd_id", "")).strip()
        if not cmd_id:
            return
        fut = session.pending_commands.pop(cmd_id, None)
        if fut is not None and not fut.done():
            fut.set_result(payload)

    async def on_stream_start(self, provider_id: int, payload: dict[str, Any]) -> None:
        session = await self._get_session(provider_id)
        if session is None:
            return
        session.last_heartbeat = _utc_now()
        cmd_id = str(payload.get("cmd_id", "")).strip()
        if not cmd_id:
            return
        queue = session.pending_streams.get(cmd_id)
        if queue is not None:
            await queue.put({"type": "stream_start", **payload})

    async def on_stream_chunk(self, provider_id: int, payload: dict[str, Any]) -> None:
        session = await self._get_session(provider_id)
        if session is None:
            return
        session.last_heartbeat = _utc_now()
        cmd_id = str(payload.get("cmd_id", "")).strip()
        if not cmd_id:
            return
        queue = session.pending_streams.get(cmd_id)
        if queue is None:
            return
        encoded = payload.get("chunk_b64")
        if not isinstance(encoded, str):
            return
        try:
            chunk = base64.b64decode(encoded)
        except Exception:  # noqa: BLE001
            chunk = b""
        await queue.put({"type": "stream_chunk", "chunk": chunk})

    async def on_stream_end(self, provider_id: int, payload: dict[str, Any]) -> None:
        session = await self._get_session(provider_id)
        if session is None:
            return
        session.last_heartbeat = _utc_now()
        cmd_id = str(payload.get("cmd_id", "")).strip()
        if not cmd_id:
            return
        queue = session.pending_streams.get(cmd_id)
        if queue is not None:
            await queue.put(
                {
                    "type": "stream_end",
                    "success": bool(payload.get("success", False)),
                    "error": payload.get("error"),
                }
            )

    async def send_command(
        self,
        provider_id: int,
        action: str,
        params: dict[str, Any] | None = None,
        timeout_seconds: int = 20,
        stale_after_seconds: int = 30,
    ) -> dict[str, Any]:
        session = await self._get_active_session(provider_id, stale_after_seconds=stale_after_seconds)
        loop = asyncio.get_running_loop()
        cmd_id = str(uuid.uuid4())
        fut: asyncio.Future = loop.create_future()
        session.pending_commands[cmd_id] = fut

        message = {
            "type": "command",
            "cmd_id": cmd_id,
            "action": action,
            "params": params or {},
        }

        try:
            async with session.send_lock:
                await session.websocket.send_json(message)
        except Exception as exc:  # noqa: BLE001
            session.pending_commands.pop(cmd_id, None)
            raise NodeControllerOfflineError(f"Failed to send command: {exc}") from exc

        try:
            result = await asyncio.wait_for(fut, timeout=max(1, timeout_seconds))
        except asyncio.TimeoutError as exc:
            session.pending_commands.pop(cmd_id, None)
            raise NodeControllerOfflineError("Command timeout waiting for node response") from exc

        if not bool(result.get("success", False)):
            error = str(result.get("error", "unknown node command error"))
            raise NodeControllerCommandError(error)

        return result.get("result", {})

    async def send_stream_command(
        self,
        provider_id: int,
        action: str,
        params: dict[str, Any] | None = None,
        timeout_seconds: int = 20,
        stale_after_seconds: int = 30,
    ) -> AsyncIterator[bytes]:
        session = await self._get_active_session(provider_id, stale_after_seconds=stale_after_seconds)
        cmd_id = str(uuid.uuid4())
        stream_queue: asyncio.Queue = asyncio.Queue()
        session.pending_streams[cmd_id] = stream_queue

        message = {
            "type": "command",
            "cmd_id": cmd_id,
            "action": action,
            "params": params or {},
        }
        try:
            async with session.send_lock:
                await session.websocket.send_json(message)
        except Exception as exc:  # noqa: BLE001
            session.pending_streams.pop(cmd_id, None)
            raise NodeControllerOfflineError(f"Failed to send command: {exc}") from exc

        try:
            while True:
                try:
                    event = await asyncio.wait_for(stream_queue.get(), timeout=max(1, timeout_seconds))
                except asyncio.TimeoutError as exc:
                    raise NodeControllerOfflineError(
                        "Stream timeout waiting for node response"
                    ) from exc

                event_type = event.get("type")
                if event_type == "stream_start":
                    continue
                if event_type == "stream_chunk":
                    chunk = event.get("chunk")
                    if isinstance(chunk, bytes):
                        yield chunk
                    elif isinstance(chunk, str):
                        yield chunk.encode("utf-8")
                    continue
                if event_type == "stream_end":
                    if not bool(event.get("success", False)):
                        error = str(event.get("error", "unknown node stream error"))
                        raise NodeControllerCommandError(error)
                    break
        finally:
            session.pending_streams.pop(cmd_id, None)

    async def get_runtime_snapshot(
        self,
        provider_id: int,
        stale_after_seconds: int = 30,
    ) -> dict[str, Any]:
        session = await self._get_active_session(provider_id, stale_after_seconds=stale_after_seconds)
        status = session.latest_status or {}
        return {
            "provider_id": session.provider_id,
            "node_id": session.node_id,
            "capabilities_models": sorted(session.capabilities_models),
            "last_heartbeat": session.last_heartbeat.isoformat(),
            "status": status,
        }

    async def get_lanes(self, provider_id: int, stale_after_seconds: int = 30) -> list[dict[str, Any]]:
        snap = await self.get_runtime_snapshot(provider_id, stale_after_seconds=stale_after_seconds)
        lanes = snap.get("status", {}).get("lanes") or []
        return lanes if isinstance(lanes, list) else []

    async def get_gpu(self, provider_id: int, stale_after_seconds: int = 30) -> dict[str, Any]:
        snap = await self.get_runtime_snapshot(provider_id, stale_after_seconds=stale_after_seconds)
        gpu = snap.get("status", {}).get("gpu") or {}
        return gpu if isinstance(gpu, dict) else {}

    async def is_model_allowed(self, provider_id: int, model_name: str) -> bool:
        session = await self._get_session(provider_id)
        if session is None:
            return True
        if not session.capabilities_models:
            return True
        return model_name in session.capabilities_models

    async def select_lane_for_model(
        self,
        provider_id: int,
        model_name: str,
        stale_after_seconds: int = 30,
    ) -> dict[str, Any] | None:
        session = await self._get_active_session(provider_id, stale_after_seconds=stale_after_seconds)
        if session.capabilities_models and model_name not in session.capabilities_models:
            return None
        lanes = (session.latest_status or {}).get("lanes") or []
        if not isinstance(lanes, list):
            return None
        candidates: list[dict[str, Any]] = []
        for lane in lanes:
            if not isinstance(lane, dict):
                continue
            if lane.get("model") != model_name:
                continue
            if lane.get("runtime_state") != "running":
                continue
            candidates.append(lane)
        if not candidates:
            return None
        candidates.sort(
            key=lambda item: (
                int(item.get("active_requests", 0) or 0),
                str(item.get("lane_id", "")),
            )
        )
        return candidates[0]

    async def _get_session(self, provider_id: int) -> ProviderSession | None:
        async with self._lock:
            return self._sessions.get(int(provider_id))

    async def _get_active_session(
        self,
        provider_id: int,
        stale_after_seconds: int = 30,
    ) -> ProviderSession:
        session = await self._get_session(provider_id)
        if session is None:
            raise NodeControllerOfflineError("No node session for provider")
        if session.is_stale(stale_after_seconds):
            raise NodeControllerOfflineError("Node session is stale")
        return session
