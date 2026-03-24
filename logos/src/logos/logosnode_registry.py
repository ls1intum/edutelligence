"""Runtime registry for connected logosnode worker sessions."""

from __future__ import annotations

import asyncio
import base64
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import logging
import secrets
from typing import Any, AsyncIterator
import uuid

from fastapi import WebSocket
from logos.terminal_logging import (
    BOLD,
    CYAN,
    DIM,
    GREEN,
    RED,
    YELLOW,
    format_state,
    paint,
    render_section,
    wrap_plain,
)

logger = logging.getLogger(__name__)


class LogosNodeOfflineError(RuntimeError):
    """Raised when a provider has no active worker session."""


class LogosNodeCommandError(RuntimeError):
    """Raised when a worker command RPC returns an error."""


class LogosNodeSessionConflictError(RuntimeError):
    """Raised when a different worker tries to claim an active provider session."""


def _lane_metric_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _lane_ttft_p95_seconds(metrics: dict[str, Any]) -> float:
    histogram = metrics.get("ttft_histogram")
    if not isinstance(histogram, dict) or not histogram:
        return 0.0

    buckets: list[tuple[float, float]] = []
    for raw_bucket, raw_count in histogram.items():
        count = _lane_metric_float(raw_count)
        if count < 0:
            continue
        bucket_label = str(raw_bucket).strip()
        if not bucket_label:
            continue
        if bucket_label == "+Inf":
            upper = float("inf")
        else:
            try:
                upper = float(bucket_label)
            except ValueError:
                continue
        buckets.append((upper, count))

    if not buckets:
        return 0.0

    buckets.sort(key=lambda item: item[0])
    total = max(count for _bucket, count in buckets)
    if total <= 0:
        return 0.0

    target = total * 0.95
    for upper, count in buckets:
        if count >= target:
            return 0.0 if upper == float("inf") else upper
    last_upper = buckets[-1][0]
    return 0.0 if last_upper == float("inf") else last_upper


def _lane_sort_key(lane: dict[str, Any]) -> tuple[Any, ...]:
    backend_metrics = lane.get("backend_metrics") if isinstance(lane.get("backend_metrics"), dict) else {}
    queue_waiting = _lane_metric_float(backend_metrics.get("queue_waiting"))
    requests_running = _lane_metric_float(backend_metrics.get("requests_running"))
    if requests_running <= 0:
        requests_running = _lane_metric_float(lane.get("active_requests"))
    ttft_p95_seconds = _lane_ttft_p95_seconds(backend_metrics)

    return (
        lane.get("runtime_state") == "cold",
        lane.get("runtime_state") == "starting",
        queue_waiting,
        requests_running,
        int(lane.get("active_requests", 0) or 0),
        ttft_p95_seconds,
        -float(lane.get("effective_vram_mb", 0.0) or 0.0),
        str(lane.get("lane_id", "")),
    )


def _lane_gpu_devices(lane: dict[str, Any]) -> str:
    lane_config = lane.get("lane_config") if isinstance(lane.get("lane_config"), dict) else {}
    return str(
        lane_config.get("gpu_devices")
        or lane.get("gpu_devices")
        or lane.get("effective_gpu_devices")
        or "-"
    )


def _lane_log_snapshot(lane: dict[str, Any]) -> dict[str, Any]:
    backend_metrics = lane.get("backend_metrics") if isinstance(lane.get("backend_metrics"), dict) else {}
    queue_waiting = _lane_metric_float(backend_metrics.get("queue_waiting"))
    requests_running = _lane_metric_float(backend_metrics.get("requests_running"))
    if requests_running <= 0:
        requests_running = _lane_metric_float(lane.get("active_requests"))
    cache_pressure = backend_metrics.get("gpu_cache_usage_percent")
    if cache_pressure is None:
        cache_pressure = backend_metrics.get("gpu_cache_usage_perc")
    prefix_hit = _lane_metric_float(backend_metrics.get("prefix_cache_hit_rate"))
    ttft_p95 = _lane_ttft_p95_seconds(backend_metrics)

    return {
        "lane_id": str(lane.get("lane_id") or "?"),
        "model": str(lane.get("model") or "?"),
        "runtime_state": str(lane.get("runtime_state") or "?"),
        "sleep_state": str(lane.get("sleep_state") or "?"),
        "active_requests": int(lane.get("active_requests", 0) or 0),
        "effective_vram_mb": round(float(lane.get("effective_vram_mb", 0.0) or 0.0), 1),
        "queue_waiting": round(queue_waiting, 1),
        "requests_running": round(requests_running, 1),
        "gpu_cache_usage_percent": (
            round(float(cache_pressure), 1) if cache_pressure is not None else None
        ),
        "prefix_cache_hit_rate": round(prefix_hit, 3) if prefix_hit is not None else None,
        "ttft_p95_seconds": round(ttft_p95, 3) if ttft_p95 is not None else None,
        "gpu_devices": _lane_gpu_devices(lane),
    }


def _format_optional_float(value: Any, suffix: str = "") -> str:
    if value is None:
        return "--"
    return f"{value}{suffix}"


def _render_lane_summary(snapshot: dict[str, Any], *, indent: str = "    ") -> list[str]:
    state_text = format_state(snapshot["runtime_state"], snapshot["sleep_state"])
    queue_text = _format_optional_float(snapshot.get("queue_waiting"))
    running_text = _format_optional_float(snapshot.get("requests_running"))
    cache_text = _format_optional_float(snapshot.get("gpu_cache_usage_percent"), "%")
    ttft_text = _format_optional_float(snapshot.get("ttft_p95_seconds"), "s")
    prefix_text = _format_optional_float(snapshot.get("prefix_cache_hit_rate"))

    lines = wrap_plain(f"model: {snapshot['model']}", indent=indent)
    lines.append(
        f"{indent}state={state_text} mem={snapshot['effective_vram_mb']:.0f}MB gpus={snapshot['gpu_devices']}"
    )
    lines.append(
        f"{indent}active={snapshot['active_requests']} run={running_text} "
        f"queue={queue_text} kv_cache={cache_text} ttft_p95={ttft_text} prefix_hit={prefix_text}"
    )
    return lines


def _render_lane_diff(old: dict[str, Any], new: dict[str, Any], *, indent: str = "    ") -> list[str]:
    lines: list[str] = []

    def _append_change(label: str, old_value: str, new_value: str) -> None:
        lines.append(f"{indent}{paint(label, DIM)}: {old_value} {paint('→', YELLOW)} {new_value}")

    if old.get("model") != new.get("model"):
        _append_change("model", str(old.get("model")), str(new.get("model")))

    old_state = f"{old.get('runtime_state')} / {old.get('sleep_state')}"
    new_state = format_state(str(new.get("runtime_state")), str(new.get("sleep_state")))
    if (old.get("runtime_state"), old.get("sleep_state")) != (
        new.get("runtime_state"), new.get("sleep_state")
    ):
        _append_change("state", old_state, new_state)

    if old.get("active_requests") != new.get("active_requests"):
        _append_change("active", str(old.get("active_requests")), str(new.get("active_requests")))
    if old.get("effective_vram_mb") != new.get("effective_vram_mb"):
        _append_change(
            "mem",
            f"{old.get('effective_vram_mb', 0):.0f}MB",
            f"{new.get('effective_vram_mb', 0):.0f}MB",
        )
    if old.get("queue_waiting") != new.get("queue_waiting"):
        _append_change(
            "queue",
            _format_optional_float(old.get("queue_waiting")),
            _format_optional_float(new.get("queue_waiting")),
        )
    if old.get("requests_running") != new.get("requests_running"):
        _append_change(
            "running",
            _format_optional_float(old.get("requests_running")),
            _format_optional_float(new.get("requests_running")),
        )
    if old.get("gpu_cache_usage_percent") != new.get("gpu_cache_usage_percent"):
        _append_change(
            "kv_cache",
            _format_optional_float(old.get("gpu_cache_usage_percent"), "%"),
            _format_optional_float(new.get("gpu_cache_usage_percent"), "%"),
        )
    if old.get("ttft_p95_seconds") != new.get("ttft_p95_seconds"):
        _append_change(
            "ttft_p95",
            _format_optional_float(old.get("ttft_p95_seconds"), "s"),
            _format_optional_float(new.get("ttft_p95_seconds"), "s"),
        )
    if old.get("gpu_devices") != new.get("gpu_devices"):
        _append_change("gpus", str(old.get("gpu_devices")), str(new.get("gpu_devices")))

    if not lines:
        lines.append(f"{indent}{paint('no tracked field changes', DIM)}")
    return lines



def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class AuthTicket:
    provider_id: int
    worker_id: str
    capabilities_models: set[str]
    expires_at: datetime


@dataclass
class ProviderSession:
    provider_id: int
    worker_id: str
    websocket: WebSocket
    capabilities_models: set[str] = field(default_factory=set)
    last_heartbeat: datetime = field(default_factory=_utc_now)
    first_status_received: bool = False
    latest_runtime: dict[str, Any] = field(default_factory=dict)
    latest_events: list[dict[str, Any]] = field(default_factory=list)
    recent_samples: deque[dict[str, Any]] = field(default_factory=deque)
    pending_commands: dict[str, asyncio.Future] = field(default_factory=dict)
    pending_streams: dict[str, asyncio.Queue] = field(default_factory=dict)
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def is_stale(self, stale_after_seconds: int) -> bool:
        return (_utc_now() - self.last_heartbeat) > timedelta(seconds=stale_after_seconds)


class LogosNodeRuntimeRegistry:
    """Tracks auth tickets, active worker sessions, and latest runtime state."""

    def __init__(self) -> None:
        self._tickets: dict[str, AuthTicket] = {}
        self._sessions: dict[int, ProviderSession] = {}
        self._lock = asyncio.Lock()
        self._recent_sample_window = timedelta(hours=1)
        self._recent_sample_max = 5000
        self._diag_log_cooldowns: dict[tuple[str, int], datetime] = {}

    def _session_diagnostic_lines(
        self,
        session: ProviderSession,
        *,
        headline: str,
        stale_after_seconds: int | None = None,
        command_action: str | None = None,
        timeout_seconds: int | None = None,
    ) -> list[str]:
        now = _utc_now()
        heartbeat_age_s = max(0.0, (now - session.last_heartbeat).total_seconds())
        status = "stale" if stale_after_seconds is not None and heartbeat_age_s > stale_after_seconds else "active"
        status_color = RED if status == "stale" else GREEN

        lines = [
            f"provider={session.provider_id} worker={paint(session.worker_id, BOLD)} status={paint(status, status_color, BOLD)}",
            f"  reason: {headline}",
            f"  heartbeat_age={heartbeat_age_s:.1f}s last_heartbeat={session.last_heartbeat.isoformat()}",
            f"  pending_commands={len(session.pending_commands)} pending_streams={len(session.pending_streams)}",
        ]
        if stale_after_seconds is not None:
            lines.append(f"  stale_after={stale_after_seconds}s")
        if command_action is not None:
            timeout_text = f" timeout={timeout_seconds}s" if timeout_seconds is not None else ""
            lines.append(f"  command={command_action}{timeout_text}")

        runtime = session.latest_runtime if isinstance(session.latest_runtime, dict) else {}
        lanes = runtime.get("lanes") if isinstance(runtime.get("lanes"), list) else []
        capacity = runtime.get("capacity") if isinstance(runtime.get("capacity"), dict) else {}
        lane_count = len(lanes)
        loaded_count = int(capacity.get("loaded_lane_count", 0) or 0)
        sleeping_count = int(capacity.get("sleeping_lane_count", 0) or 0)
        active_requests = int(capacity.get("active_requests", 0) or 0)
        lines.append(
            f"  lanes={lane_count} loaded={loaded_count} sleeping={sleeping_count} active_requests={active_requests}"
        )

        if session.capabilities_models:
            capabilities_text = ", ".join(sorted(session.capabilities_models))
            lines.extend(wrap_plain(f"capabilities: {capabilities_text}", indent="  "))

        for lane in sorted(
            (
                _lane_log_snapshot(lane)
                for lane in lanes
                if isinstance(lane, dict)
            ),
            key=_lane_sort_key,
        )[:3]:
            lines.append(f"  ▸ {paint(lane['lane_id'], BOLD)}")
            lines.extend(_render_lane_summary(lane, indent="    "))

        if lane_count > 3:
            lines.append(f"  {paint(f'+{lane_count - 3} more lane(s)', DIM)}")
        return lines

    def _emit_session_diagnostic(
        self,
        *,
        kind: str,
        session: ProviderSession,
        title: str,
        headline: str,
        accent: str,
        level: int = logging.WARNING,
        stale_after_seconds: int | None = None,
        command_action: str | None = None,
        timeout_seconds: int | None = None,
        cooldown_seconds: float = 15.0,
    ) -> None:
        now = _utc_now()
        key = (kind, session.provider_id)
        last = self._diag_log_cooldowns.get(key)
        if last is not None and (now - last).total_seconds() < cooldown_seconds:
            return
        self._diag_log_cooldowns[key] = now
        logger.log(
            level,
            render_section(
                title,
                self._session_diagnostic_lines(
                    session,
                    headline=headline,
                    stale_after_seconds=stale_after_seconds,
                    command_action=command_action,
                    timeout_seconds=timeout_seconds,
                ),
                accent=accent,
            ),
        )

    async def issue_ticket(
        self,
        provider_id: int,
        worker_id: str,
        capabilities_models: list[str],
        ttl_seconds: int = 60,
    ) -> str:
        token = secrets.token_urlsafe(32)
        expires_at = _utc_now() + timedelta(seconds=max(5, ttl_seconds))
        ticket = AuthTicket(
            provider_id=int(provider_id),
            worker_id=worker_id,
            capabilities_models={m for m in capabilities_models if isinstance(m, str) and m.strip()},
            expires_at=expires_at,
        )
        async with self._lock:
            self._tickets[token] = ticket
        return token

    async def consume_ticket(self, token: str) -> AuthTicket | None:
        async with self._lock:
            ticket = self._tickets.pop(token, None)
        if ticket is None or ticket.expires_at < _utc_now():
            return None
        return ticket

    async def attach_session(self, ticket: AuthTicket, websocket: WebSocket) -> ProviderSession:
        session = ProviderSession(
            provider_id=ticket.provider_id,
            worker_id=ticket.worker_id,
            websocket=websocket,
            capabilities_models=set(ticket.capabilities_models),
        )
        async with self._lock:
            old = self._sessions.get(ticket.provider_id)
            if (
                old is not None
                and old.worker_id != ticket.worker_id
                and not old.is_stale(30)
            ):
                raise LogosNodeSessionConflictError(
                    f"provider {ticket.provider_id} is already connected as worker '{old.worker_id}'"
                )
            self._sessions[ticket.provider_id] = session
        if old is not None:
            body_lines = [
                f"provider={ticket.provider_id} worker={paint(ticket.worker_id, BOLD)} status={paint('reconnected', YELLOW, BOLD)}",
                *wrap_plain(
                    "capabilities: " + (", ".join(sorted(ticket.capabilities_models)) or "none"),
                    indent="  ",
                ),
                "  previous session replaced",
                f"  {paint(f'active sessions: {len(self._sessions)}', DIM)}",
            ]
            logger.info(
                render_section(
                    "Worker Session Update",
                    body_lines,
                    accent=YELLOW,
                )
            )
            await self._close_session(old)
        else:
            body_lines = [
                f"provider={ticket.provider_id} worker={paint(ticket.worker_id, BOLD)} status={paint('connected', GREEN, BOLD)}",
                *wrap_plain(
                    "capabilities: " + (", ".join(sorted(ticket.capabilities_models)) or "none"),
                    indent="  ",
                ),
                f"  {paint(f'active sessions: {len(self._sessions)}', DIM)}",
            ]
            logger.info(
                render_section(
                    "Worker Session Update",
                    body_lines,
                    accent=GREEN,
                )
            )
        return session

    async def get_conflicting_session(
        self,
        provider_id: int,
        worker_id: str,
        *,
        stale_after_seconds: int = 30,
    ) -> ProviderSession | None:
        session = await self._get_session(provider_id)
        if session is None:
            return None
        if session.worker_id == worker_id:
            return None
        if session.is_stale(stale_after_seconds):
            return None
        return session

    async def detach_session(self, provider_id: int, websocket: WebSocket | None = None) -> None:
        async with self._lock:
            session = self._sessions.get(provider_id)
            if session is None:
                return
            if websocket is not None and session.websocket is not websocket:
                return
            self._sessions.pop(provider_id, None)
        pending_cmds = len(session.pending_commands)
        pending_streams = len(session.pending_streams)
        logger.warning(
            render_section(
                "Worker Session Update",
                [
                    f"provider={provider_id} worker={paint(session.worker_id, BOLD)} status={paint('disconnected', RED, BOLD)}",
                    f"  pending_commands={pending_cmds} pending_streams={pending_streams}",
                    f"  {paint(f'remaining sessions: {len(self._sessions)}', DIM)}",
                ],
                accent=RED,
            )
        )
        for fut in list(session.pending_commands.values()):
            if not fut.done():
                fut.set_exception(LogosNodeOfflineError("Worker disconnected"))
        for queue in list(session.pending_streams.values()):
            try:
                queue.put_nowait({"type": "stream_end", "success": False, "error": "Worker disconnected"})
            except Exception:  # noqa: BLE001
                pass
        session.pending_streams.clear()
        await self._close_session(session)

    async def _close_session(self, session: ProviderSession) -> None:
        try:
            await session.websocket.close()
        except Exception:  # noqa: BLE001
            pass

    async def on_hello(
        self,
        provider_id: int,
        worker_id: str,
        capabilities_models: list[str] | None = None,
    ) -> None:
        session = await self._get_session(provider_id)
        if session is None:
            return
        session.worker_id = worker_id or session.worker_id
        session.last_heartbeat = _utc_now()
        if capabilities_models is not None:
            session.capabilities_models = {m for m in capabilities_models if isinstance(m, str) and m.strip()}

    async def update_runtime(
        self,
        provider_id: int,
        runtime: dict[str, Any],
        capabilities_models: list[str] | None = None,
    ) -> None:
        session = await self._get_session(provider_id)
        if session is None:
            return
        old_runtime = session.latest_runtime
        session.latest_runtime = runtime if isinstance(runtime, dict) else {}
        session.first_status_received = True
        session.last_heartbeat = _utc_now()
        if capabilities_models is not None:
            session.capabilities_models = {m for m in capabilities_models if isinstance(m, str) and m.strip()}

        # Detect lane state and metric changes and log them as structured blocks.
        old_lanes = {
            snapshot["lane_id"]: snapshot
            for snapshot in (
                _lane_log_snapshot(l)
                for l in (old_runtime.get("lanes") or [])
                if isinstance(l, dict)
            )
        }
        new_lanes = {
            snapshot["lane_id"]: snapshot
            for snapshot in (
                _lane_log_snapshot(l)
                for l in (runtime.get("lanes") or [])
                if isinstance(runtime, dict) and isinstance(l, dict)
            )
        }
        if old_lanes != new_lanes:
            added = sorted(set(new_lanes) - set(old_lanes))
            removed = sorted(set(old_lanes) - set(new_lanes))
            changed = sorted(
                lid for lid in set(old_lanes) & set(new_lanes)
                if old_lanes[lid] != new_lanes[lid]
            )

            body_lines: list[str] = [
                f"provider={provider_id} worker={paint(session.worker_id, BOLD)} lanes={len(new_lanes)}"
            ]
            for lid in added:
                snapshot = new_lanes[lid]
                body_lines.append(f"{paint('+', GREEN, BOLD)} {paint(lid, BOLD)} added")
                body_lines.extend(_render_lane_summary(snapshot))
            for lid in removed:
                snapshot = old_lanes[lid]
                body_lines.append(f"{paint('-', RED, BOLD)} {paint(lid, BOLD)} removed")
                body_lines.extend(_render_lane_summary(snapshot))
            for lid in changed:
                old_snapshot = old_lanes[lid]
                new_snapshot = new_lanes[lid]
                body_lines.append(f"{paint('~', YELLOW, BOLD)} {paint(lid, BOLD)} changed")
                body_lines.extend(_render_lane_diff(old_snapshot, new_snapshot))
                body_lines.extend(_render_lane_summary(new_snapshot))

            logger.info(
                render_section(
                    "Lane Change",
                    body_lines,
                    accent=CYAN,
                )
            )

    async def record_runtime_sample(self, provider_id: int, sample: dict[str, Any]) -> None:
        session = await self._get_session(provider_id)
        if session is None or not isinstance(sample, dict):
            return
        session.recent_samples.append(dict(sample))
        self._trim_recent_samples(session)

    def peek_recent_samples(
        self,
        provider_id: int,
        *,
        after_snapshot_id: int = 0,
    ) -> list[dict[str, Any]]:
        session = self._sessions.get(int(provider_id))
        if session is None:
            return []
        self._trim_recent_samples(session)
        cursor = int(after_snapshot_id or 0)
        result: list[dict[str, Any]] = []
        for sample in session.recent_samples:
            if not isinstance(sample, dict):
                continue
            snapshot_id = int(sample.get("snapshot_id") or 0)
            if snapshot_id and snapshot_id <= cursor:
                continue
            result.append(dict(sample))
        return result

    async def append_event(self, provider_id: int, event: dict[str, Any]) -> None:
        session = await self._get_session(provider_id)
        if session is None:
            return
        session.last_heartbeat = _utc_now()
        if isinstance(event, dict):
            session.latest_events.append(event)
            session.latest_events = session.latest_events[-500:]

    async def mark_heartbeat(self, provider_id: int) -> None:
        session = await self._get_session(provider_id)
        if session is not None:
            session.last_heartbeat = _utc_now()

    async def on_command_result(self, provider_id: int, payload: dict[str, Any]) -> None:
        session = await self._get_session(provider_id)
        if session is None:
            return
        session.last_heartbeat = _utc_now()
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
            await queue.put({
                "type": "stream_end",
                "success": bool(payload.get("success", False)),
                "error": payload.get("error"),
            })

    async def send_command(
        self,
        provider_id: int,
        action: str,
        params: dict[str, Any] | None = None,
        timeout_seconds: int = 20,
        stale_after_seconds: int = 30,
    ) -> dict[str, Any]:
        session = await self._get_active_session(provider_id, stale_after_seconds)
        loop = asyncio.get_running_loop()
        cmd_id = str(uuid.uuid4())
        fut: asyncio.Future = loop.create_future()
        session.pending_commands[cmd_id] = fut

        message = {"type": "command", "cmd_id": cmd_id, "action": action, "params": params or {}}
        try:
            async with session.send_lock:
                await session.websocket.send_json(message)
        except Exception as exc:  # noqa: BLE001
            session.pending_commands.pop(cmd_id, None)
            raise LogosNodeOfflineError(f"Failed to send command: {exc}") from exc

        try:
            result = await asyncio.wait_for(fut, timeout=max(1, timeout_seconds))
        except asyncio.TimeoutError as exc:
            session.pending_commands.pop(cmd_id, None)
            self._emit_session_diagnostic(
                kind="command-timeout",
                session=session,
                title="Worker Command Timeout",
                headline="worker did not answer before command timeout",
                accent=RED,
                level=logging.ERROR,
                command_action=action,
                timeout_seconds=int(max(1, timeout_seconds)),
                cooldown_seconds=5.0,
            )
            raise LogosNodeOfflineError("Command timeout waiting for worker response") from exc

        if not bool(result.get("success", False)):
            raise LogosNodeCommandError(str(result.get("error", "unknown worker command error")))
        return result.get("result", {})

    async def send_stream_command(
        self,
        provider_id: int,
        action: str,
        params: dict[str, Any] | None = None,
        timeout_seconds: int = 20,
        stale_after_seconds: int = 30,
    ) -> AsyncIterator[bytes]:
        session = await self._get_active_session(provider_id, stale_after_seconds)
        cmd_id = str(uuid.uuid4())
        stream_queue: asyncio.Queue = asyncio.Queue()
        session.pending_streams[cmd_id] = stream_queue

        message = {"type": "command", "cmd_id": cmd_id, "action": action, "params": params or {}}
        try:
            async with session.send_lock:
                await session.websocket.send_json(message)
        except Exception as exc:  # noqa: BLE001
            session.pending_streams.pop(cmd_id, None)
            raise LogosNodeOfflineError(f"Failed to send command: {exc}") from exc

        try:
            while True:
                try:
                    event = await asyncio.wait_for(stream_queue.get(), timeout=max(1, timeout_seconds))
                except asyncio.TimeoutError as exc:
                    raise LogosNodeOfflineError("Stream timeout waiting for worker response") from exc
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
                        raise LogosNodeCommandError(str(event.get("error", "unknown worker stream error")))
                    break
        finally:
            session.pending_streams.pop(cmd_id, None)

    async def get_runtime_snapshot(self, provider_id: int, stale_after_seconds: int = 30) -> dict[str, Any]:
        session = await self._get_active_session(provider_id, stale_after_seconds)
        return {
            "provider_id": session.provider_id,
            "worker_id": session.worker_id,
            "capabilities_models": sorted(session.capabilities_models),
            "first_status_received": session.first_status_received,
            "last_heartbeat": session.last_heartbeat.isoformat(),
            "runtime": session.latest_runtime,
            "events": list(session.latest_events),
        }

    def peek_runtime_snapshot(self, provider_id: int) -> dict[str, Any] | None:
        session = self._sessions.get(int(provider_id))
        if session is None:
            return None
        return {
            "provider_id": session.provider_id,
            "worker_id": session.worker_id,
            "capabilities_models": sorted(session.capabilities_models),
            "first_status_received": session.first_status_received,
            "last_heartbeat": session.last_heartbeat.isoformat(),
            "runtime": session.latest_runtime,
            "events": list(session.latest_events),
        }

    def has_received_first_status(self, provider_id: int) -> bool:
        """Check if a provider has sent at least one status update since connecting."""
        session = self._sessions.get(int(provider_id))
        return session is not None and session.first_status_received

    async def get_lanes(self, provider_id: int, stale_after_seconds: int = 30) -> list[dict[str, Any]]:
        snap = await self.get_runtime_snapshot(provider_id, stale_after_seconds)
        lanes = snap.get("runtime", {}).get("lanes") or []
        return lanes if isinstance(lanes, list) else []

    async def get_devices(self, provider_id: int, stale_after_seconds: int = 30) -> dict[str, Any]:
        snap = await self.get_runtime_snapshot(provider_id, stale_after_seconds)
        devices = snap.get("runtime", {}).get("devices") or {}
        return devices if isinstance(devices, dict) else {}

    async def is_model_allowed(self, provider_id: int, model_name: str) -> bool:
        session = await self._get_session(provider_id)
        if session is None or not session.capabilities_models:
            return True
        return model_name in session.capabilities_models

    async def select_lane_for_model(
        self,
        provider_id: int,
        model_name: str,
        stale_after_seconds: int = 30,
    ) -> dict[str, Any] | None:
        session = await self._get_active_session(provider_id, stale_after_seconds)
        if session.capabilities_models and model_name not in session.capabilities_models:
            return None
        lanes = (session.latest_runtime or {}).get("lanes") or []
        if not isinstance(lanes, list):
            return None
        candidates: list[dict[str, Any]] = []
        for lane in lanes:
            if not isinstance(lane, dict):
                continue
            if lane.get("model") != model_name:
                continue
            if lane.get("runtime_state") not in {"loaded", "running", "cold", "starting"}:
                continue
            candidates.append(lane)
        if not candidates:
            return None
        candidates.sort(key=_lane_sort_key)
        return candidates[0]

    async def _get_session(self, provider_id: int) -> ProviderSession | None:
        async with self._lock:
            return self._sessions.get(int(provider_id))

    async def _get_active_session(self, provider_id: int, stale_after_seconds: int = 30) -> ProviderSession:
        session = await self._get_session(provider_id)
        if session is None:
            raise LogosNodeOfflineError("No active logosnode worker session")
        if session.is_stale(stale_after_seconds):
            self._emit_session_diagnostic(
                kind="session-stale",
                session=session,
                title="Worker Session Stale",
                headline="server has not received a heartbeat in time",
                accent=YELLOW,
                stale_after_seconds=stale_after_seconds,
            )
            raise LogosNodeOfflineError("logosnode worker session is stale")
        return session

    def _trim_recent_samples(self, session: ProviderSession) -> None:
        cutoff = _utc_now() - self._recent_sample_window
        while session.recent_samples:
            first = session.recent_samples[0]
            timestamp = self._sample_timestamp(first)
            if timestamp is None or timestamp >= cutoff:
                break
            session.recent_samples.popleft()
        while len(session.recent_samples) > self._recent_sample_max:
            session.recent_samples.popleft()

    @staticmethod
    def _sample_timestamp(sample: dict[str, Any]) -> datetime | None:
        raw = sample.get("timestamp")
        if not isinstance(raw, str) or not raw.strip():
            return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
