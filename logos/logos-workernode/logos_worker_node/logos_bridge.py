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
from logos_worker_node.models import LaneConfig, LogosConfig, WorkerTransportStatus, model_can_sleep
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
        # Resolved by server during auth
        self._resolved_worker_id: str = ""
        # Active server-orchestrated calibration: (model_name, cancel_event, thread, started_at)
        self._active_calibration: tuple[str, threading.Event, threading.Thread, float] | None = None

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

        if action == "start_calibration":
            return self._handle_start_calibration(params)
        if action == "stop_calibration":
            return self._handle_stop_calibration()
        if action == "get_calibration_status":
            return self._handle_get_calibration_status()

        raise ValueError(f"Unsupported bridge command '{action}'")

    def _handle_start_calibration(self, params: dict[str, Any]) -> dict[str, Any]:
        """Start a background calibration for one model (server-orchestrated path)."""
        model_name = str(params.get("model_name", "")).strip()
        if not model_name:
            return {"ok": False, "error": "model_name is required"}
        sleep_level = int(params.get("sleep_level", 1))

        cfg = self._app.state.config
        model_profiles = self._app.state.model_profiles

        # Reject calibration requests that would measure sleep_l<N> transient
        # host-RAM for a model whose worker config forbids sleeping. The vLLM
        # lane would be spawned with enable_sleep_mode=False (worker kill
        # switch or per-model override), the POST /sleep call in Phase 4
        # would fail, and the orchestrator would keep retrying every
        # maintenance window. Persist the sleep_mode_disabled flag in the
        # model profile so the master's calibration orchestrator can stop
        # asking instead of relying on per-window deduping alone.
        if sleep_level > 0 and not model_can_sleep(cfg, model_name):
            model_profiles.mark_sleep_mode_disabled(model_name, True)
            err = (
                f"sleep mode disabled for model {model_name!r} on this worker "
                f"(engines.vllm.disable_sleep_mode or per-model "
                f"enable_sleep_mode=false override); cannot calibrate "
                f"sleep_l{sleep_level} transient host RAM"
            )
            logger.warning("[Calibration] refusing start_calibration: %s", err)
            return {"ok": False, "error": err, "sleep_mode_disabled": True}
        # Config now permits sleep — clear any stale "sleep_mode_disabled"
        # flag persisted by a prior rejection so a config flip
        # (false → true) is picked up immediately.
        if model_can_sleep(cfg, model_name):
            model_profiles.mark_sleep_mode_disabled(model_name, False)

        if self._active_calibration is not None:
            active_model = self._active_calibration[0]
            if self._active_calibration[2].is_alive():
                return {"ok": False, "error": f"calibration already in progress: {active_model}"}
            # Thread finished — clean up stale entry
            self._active_calibration = None

        cancel_event = threading.Event()
        started_at = time.time()

        model_cache = getattr(self._app.state, "model_cache", None)

        def _run_calibration() -> None:
            from pathlib import Path

            from logos_worker_node.calibration import load_existing_profiles, result_to_profile_dict, save_profiles
            from logos_worker_node.config import get_state_dir

            state_dir = get_state_dir()
            profiles_path = state_dir / "model_profiles.yml"
            nccl_p2p = cfg.engines.vllm.nccl_p2p_available if cfg.engines else False
            _mc = model_cache if (model_cache is not None and getattr(model_cache, "enabled", False)) else None

            # Find the config.yml path for plans_from_config
            import os

            config_path_str = os.environ.get("LOGOS_WORKER_NODE_CONFIG", "").strip()
            if config_path_str:
                config_path = Path(config_path_str)
            else:
                for candidate in [Path("/app/config.yml"), Path("config.yml")]:
                    if candidate.resolve().is_file():
                        config_path = candidate
                        break
                else:
                    config_path = Path("config.yml")

            try:
                logger.info(
                    "[Calibration] Starting server-orchestrated calibration: model=%s sleep_level=%d",
                    model_name,
                    sleep_level,
                )
                from logos_worker_node.calibration import calibrate_with_tp_escalation, plans_from_config

                all_plans = plans_from_config(config_path) if config_path.exists() else []
                plan_by_model = {p["model"]: p for p in all_plans}
                plan = plan_by_model.get(model_name) or {"model": model_name}

                from logos_worker_node.calibration import _CALIBRATION_PORT, _DEFAULT_VLLM, _READY_TIMEOUT_S

                log_dir = state_dir / "calibration_logs"
                log_dir.mkdir(parents=True, exist_ok=True)

                result = calibrate_with_tp_escalation(
                    plan,
                    vllm_binary=_DEFAULT_VLLM,
                    port=_CALIBRATION_PORT,
                    log_dir=log_dir,
                    sleep_level=sleep_level,
                    ready_timeout_s=_READY_TIMEOUT_S,
                    nccl_p2p_available=nccl_p2p,
                    model_cache=_mc,
                    cancel_event=cancel_event,
                )

                if result.success:
                    # Persist the new profile to model_profiles.yml and reload.
                    # Preserve any prior transient measurements that the current
                    # run did not produce (this calibration only measures one
                    # sleep level — the other field comes back as None from
                    # result_to_profile_dict and must not clobber an earlier
                    # value).
                    existing = load_existing_profiles(profiles_path)
                    prior = existing.get(model_name) or {}
                    new_profile = result_to_profile_dict(result)
                    for _carry in ("sleep_l1_transient_host_ram_mb", "sleep_l2_transient_host_ram_mb"):
                        if new_profile.get(_carry) is None and prior.get(_carry) is not None:
                            new_profile[_carry] = prior[_carry]
                    existing[model_name] = new_profile
                    save_profiles(profiles_path, existing)
                    model_profiles._load_persisted()
                    logger.info(
                        "[Calibration] Completed successfully: model=%s base_residency=%.0f MB",
                        model_name,
                        result.base_residency_mb,
                    )
                elif cancel_event.is_set():
                    logger.info("[Calibration] Cancelled by server: model=%s", model_name)
                else:
                    logger.warning(
                        "[Calibration] Failed: model=%s error=%s",
                        model_name,
                        result.error,
                    )
            except Exception:
                logger.exception("[Calibration] Unexpected error for model=%s", model_name)
            finally:
                # Clear active state when the thread exits
                if self._active_calibration is not None and self._active_calibration[0] == model_name:
                    self._active_calibration = None

        thread = threading.Thread(target=_run_calibration, name=f"calibration-{model_name}", daemon=True)
        self._active_calibration = (model_name, cancel_event, thread, started_at)
        thread.start()
        return {"ok": True, "model_name": model_name, "sleep_level": sleep_level, "started_at": started_at}

    def _handle_stop_calibration(self) -> dict[str, Any]:
        """Cancel any in-progress calibration (idempotent)."""
        if self._active_calibration is None:
            return {"ok": True, "was_active": False}

        model_name, cancel_event, thread, _started_at = self._active_calibration
        cancel_event.set()
        thread.join(timeout=10.0)
        self._active_calibration = None
        logger.info("[Calibration] stop_calibration received — cancelled model=%s", model_name)
        return {"ok": True, "was_active": True, "model_name": model_name}

    def _handle_get_calibration_status(self) -> dict[str, Any]:
        """Return whether a calibration is currently running."""
        if self._active_calibration is None:
            return {"active": False, "model_name": None, "started_at": None}
        model_name, _cancel, thread, started_at = self._active_calibration
        if not thread.is_alive():
            self._active_calibration = None
            return {"active": False, "model_name": None, "started_at": None}
        return {"active": True, "model_name": model_name, "started_at": started_at}

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
            if upstream is not None:
                try:
                    await upstream.aclose()
                except Exception:  # noqa: BLE001
                    pass
            await client.aclose()
            await lane_manager.decrement_active_requests(lane_id)
