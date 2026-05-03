"""Lane manager for LogosWorkerNode."""

from __future__ import annotations

import asyncio
from itertools import combinations
import logging
import socket
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Iterable

from logos_worker_node.models import (
    DeviceSummary,
    LaneAction,
    LaneApplyResult,
    LaneConfig,
    LaneEvent,
    LaneStatus,
    LoadedModel,
    OllamaConfig,
    ProcessState,
    VllmConfig,
    VllmEngineConfig,
)
from logos_worker_node.model_profiles import ModelProfileRegistry
from logos_worker_node.ollama_process import OllamaProcessHandle
from logos_worker_node import prometheus_metrics as prom
from logos_worker_node.vllm_process import VllmProcessHandle

logger = logging.getLogger("logos_worker_node.lane_manager")

# Union type for all supported backend handles
ProcessHandle = OllamaProcessHandle | VllmProcessHandle

_DEFAULT_PORT_START = 11436
_DEFAULT_PORT_END = 11499

_RESTART_TIMEOUT = 90  # seconds total for spawn + preload on new process
_MAX_EVENT_LOG = 500    # max events kept in memory
_HANDLE_DESTROY_TIMEOUT = 45
_HANDLE_CLOSE_TIMEOUT = 10
_GPU_PLACEMENT_HEADROOM_RATIO = 0.10
_GPU_PLACEMENT_MIN_HEADROOM_MB = 1024.0
_CRASH_RESTART_COOLDOWN_S = 30.0
_MAX_CRASH_RESTARTS = 5  # per lane; budget resets on confirmed successful restart


def _write_reboot_sentinel(path: str) -> None:
    """Write the reboot-requested sentinel file (sync helper for asyncio.to_thread)."""
    import os
    sentinel_dir = os.path.dirname(path)
    if sentinel_dir:
        os.makedirs(sentinel_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("reboot-requested\n")


class PortAllocator:
    """Assigns and tracks ports within a range."""

    def __init__(
        self,
        start: int = _DEFAULT_PORT_START,
        end: int = _DEFAULT_PORT_END,
        reserved_ports: Iterable[int] | None = None,
    ) -> None:
        if start > end:
            raise ValueError(f"Invalid port range: start={start} is greater than end={end}")
        self._start = start
        self._end = end
        self._reserved_ports = {
            int(p) for p in (reserved_ports or []) if start <= int(p) <= end
        }
        self._used: dict[str, int] = {}  # lane_id -> port

    def allocate(self, lane_id: str) -> int:
        """Allocate the next available port for a lane."""
        if lane_id in self._used:
            return self._used[lane_id]
        used_ports = set(self._used.values())
        for port in range(self._start, self._end + 1):
            if port in used_ports or port in self._reserved_ports:
                continue
            if not self._is_port_available(port):
                continue
            self._used[lane_id] = port
            return port
        raise RuntimeError(
            f"Port range exhausted ({self._start}–{self._end}): "
            f"{len(self._used)} lanes already allocated, "
            f"{len(self._reserved_ports)} reserved"
        )

    @staticmethod
    def _is_port_available(port: int) -> bool:
        """Return True when no process is currently bound to the port.

        In heavily sandboxed test environments socket creation may be blocked.
        In that case we cannot probe host occupancy, so return True and rely
        on process spawn failure to surface a real conflict.
        """
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        except OSError:
            logger.debug("Socket probe unavailable; skipping host port occupancy check")
            return True

        with sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                return False
        return True

    def release(self, lane_id: str) -> None:
        self._used.pop(lane_id, None)

    def get_port(self, lane_id: str) -> int | None:
        return self._used.get(lane_id)

    @property
    def allocated(self) -> dict[str, int]:
        return dict(self._used)


def _normalize_lane_id(raw: str) -> str:
    return raw.replace("/", "_").replace(":", "_")


def _lane_id_from_config(lane_config: LaneConfig) -> str:
    """Resolve lane_id from config (explicit override or model-derived fallback)."""
    if lane_config.lane_id:
        return _normalize_lane_id(lane_config.lane_id)
    return _normalize_lane_id(lane_config.model)


def _routing_inference_endpoint(vllm: bool) -> str:
    if vllm:
        return "/v1/chat/completions"
    return "/v1/chat/completions"


def _lane_needs_restart(current: LaneConfig, desired: LaneConfig) -> bool:
    """Check if the lane config change requires a process restart.

    Only compares fields that cannot be changed at runtime and truly require
    stopping and re-spawning the vLLM/Ollama process.  Fields like
    kv_cache_memory_bytes and enable_sleep_mode are set at spawn time but
    changing them should NOT trigger a restart of an already-loaded lane —
    the planner should use sleep/reconfigure for KV tuning instead.
    """
    if current.model != desired.model:
        return True
    if current.vllm != desired.vllm:
        return True
    # Ollama-specific fields
    if not current.vllm:
        return (
            current.num_parallel != desired.num_parallel
            or current.context_length != desired.context_length
            or current.kv_cache_type != desired.kv_cache_type
            or current.flash_attention != desired.flash_attention
            or current.gpu_devices != desired.gpu_devices
            or current.keep_alive != desired.keep_alive
        )
    # vLLM: only compare fields that require a process restart
    cv = current.vllm_config
    dv = desired.vllm_config
    if cv is None and dv is None:
        return False
    if cv is None or dv is None:
        return True
    return (
        cv.tensor_parallel_size != dv.tensor_parallel_size
        or cv.max_model_len != dv.max_model_len
        or cv.dtype != dv.dtype
        or cv.quantization != dv.quantization
        or cv.enforce_eager != dv.enforce_eager
        or cv.attention_backend != dv.attention_backend
        or cv.disable_custom_all_reduce != dv.disable_custom_all_reduce
        or cv.cpu_offload_gb != dv.cpu_offload_gb
        or cv.enable_auto_tool_choice != dv.enable_auto_tool_choice
        or cv.tool_call_parser != dv.tool_call_parser
        or cv.extra_args != dv.extra_args
        or current.gpu_devices != desired.gpu_devices
    )


def _create_handle(
    lane_id: str,
    port: int,
    global_config: OllamaConfig,
    vllm_engine_config: VllmEngineConfig,
    lane_config: LaneConfig,
) -> ProcessHandle:
    """Factory: create the correct process handle based on backend type."""
    if lane_config.vllm:
        return VllmProcessHandle(lane_id, port, global_config, vllm_engine_config)
    return OllamaProcessHandle(lane_id, port, global_config)


class _ApplyAbort(Exception):
    """Internal sentinel to trigger rollback in apply_lanes."""


class LaneManager:
    """Manages a pool of process handles (Ollama or vLLM), one per model lane."""

    def __init__(
        self,
        global_config: OllamaConfig,
        vllm_engine_config: VllmEngineConfig | None = None,
        lane_port_start: int = _DEFAULT_PORT_START,
        lane_port_end: int = _DEFAULT_PORT_END,
        reserved_ports: Iterable[int] | None = None,
        nvidia_smi_available: Callable[[], bool] | None = None,
        model_profiles: ModelProfileRegistry | None = None,
        gpu_device_count: Callable[[], int] | None = None,
        per_gpu_vram_mb: Callable[[], float] | None = None,
        gpu_snapshot: Callable[[], Awaitable[DeviceSummary]] | None = None,
        gpu_force_poll: Callable[[], Awaitable[None]] | None = None,
        max_lanes: int = 0,
        model_cache: Any | None = None,
        auto_reboot_on_stuck_gpu: bool = True,
        reboot_sentinel_path: str = "/host/reboot-requested",
    ) -> None:
        self._global_config = global_config
        self._vllm_engine_config = vllm_engine_config or VllmEngineConfig()
        self._nvidia_smi_available = nvidia_smi_available or (lambda: True)
        self._gpu_device_count = gpu_device_count or (lambda: 1)
        self._per_gpu_vram_mb = per_gpu_vram_mb or (lambda: 0.0)
        self._gpu_snapshot = gpu_snapshot
        self._gpu_force_poll = gpu_force_poll
        self._max_lanes = max_lanes
        self._model_cache = model_cache
        self._auto_reboot_on_stuck_gpu = auto_reboot_on_stuck_gpu
        self._reboot_sentinel_path = reboot_sentinel_path
        self._handles: dict[str, ProcessHandle] = {}
        self._port_alloc = PortAllocator(
            start=lane_port_start,
            end=lane_port_end,
            reserved_ports=reserved_ports,
        )
        self._lock = asyncio.Lock()
        self._event_log: list[LaneEvent] = []
        self._active_requests: dict[str, int] = {}
        self._event_seq = 0
        self._starting_deadlines: dict[str, float] = {}
        self._status_revision = 0
        self._status_event = asyncio.Event()
        self._model_profiles = model_profiles
        self._last_profile_state: dict[str, str] = {}
        # Stuck-inference detection: track generation_tokens_total per lane
        self._last_gen_tokens: dict[str, float] = {}
        self._stuck_polls: dict[str, int] = {}  # consecutive polls with no progress
        _STUCK_POLL_THRESHOLD = 6  # ~30s at 5s heartbeat
        self._stuck_poll_threshold = _STUCK_POLL_THRESHOLD
        self._last_crash_restart_attempt_at: dict[str, float] = {}
        self._crash_restart_counts: dict[str, int] = {}

    def validate_capabilities(self, capabilities_models: list[str]) -> list[str]:
        """Check which capabilities_models are available locally.

        For each model, checks if it exists in the HF cache or models path.
        Returns a list of models that could NOT be found (warnings only,
        doesn't block startup).
        """
        import os
        missing = []
        hf_home = os.environ.get("HF_HOME", os.path.join(self._global_config.models_path, ".hf"))
        models_path = self._global_config.models_path
        for model_name in capabilities_models:
            # Check HF cache (transformers style: models--org--name)
            hf_cache_dir = os.path.join(hf_home, "hub", f"models--{model_name.replace('/', '--')}")
            # Check direct model path
            direct_path = os.path.join(models_path, model_name)
            if not os.path.isdir(hf_cache_dir) and not os.path.isdir(direct_path):
                missing.append(model_name)
                logger.warning(
                    "Capability model '%s' not found locally (checked %s and %s). "
                    "Ensure the model is downloaded before it can be loaded.",
                    model_name, hf_cache_dir, direct_path,
                )
        if not missing:
            logger.info("All %d capability models verified as available locally", len(capabilities_models))
        return missing

    def _validate_vllm_runtime_requirements(self, lanes: Iterable[LaneConfig]) -> None:
        vllm_lane_ids = [
            _lane_id_from_config(lane)
            for lane in lanes
            if lane.vllm
        ]
        if not vllm_lane_ids:
            return
        if self._nvidia_smi_available():
            return
        lane_list = ", ".join(vllm_lane_ids)
        raise RuntimeError(
            "vLLM lanes require a working nvidia-smi setup on this worker. "
            "nvidia-smi is mandatory for vLLM startup because LogosWorkerNode uses it for "
            "GPU/VRAM accounting and safe scheduling. "
            f"Configure nvidia-smi correctly or disable vLLM for these lanes: {lane_list}"
        )

    # ------------------------------------------------------------------
    # Declarative API
    # ------------------------------------------------------------------

    async def apply_lanes(self, desired: list[LaneConfig]) -> LaneApplyResult:
        """
        Declarative: describe the desired set of lanes.

        The manager diffs current vs desired and executes minimal transitions:
          1. Remove stale lanes (frees VRAM first)
          2. Reconfigure changed lanes (stop-then-start)
          3. Add new lanes (uses freed VRAM)

        On failure mid-apply, already-completed transitions are rolled back
        to restore the prior state (best-effort atomic semantics).

        Returns a result with all actions taken and final lane statuses.
        """
        if self._max_lanes > 0 and len(desired) > self._max_lanes:
            raise ValueError(
                f"Desired lane count ({len(desired)}) exceeds MAX_LANES limit ({self._max_lanes})"
            )
        self._validate_vllm_runtime_requirements(desired)
        async with self._lock:
            actions: list[LaneAction] = []
            errors: list[str] = []
            rolled_back = False

            desired_map: dict[str, LaneConfig] = {}
            for lc in desired:
                lid = _lane_id_from_config(lc)
                if lid in desired_map:
                    raise ValueError(
                        f"Duplicate desired lane id '{lid}' (from model '{lc.model}'). "
                        "Use unique lanes[].lane_id for replicas."
                    )
                desired_map[lid] = lc

            current_ids = set(self._handles.keys())
            desired_ids = set(desired_map.keys())

            # Snapshot for rollback: lane_id -> (handle, lane_config, port)
            snapshot: dict[str, tuple[ProcessHandle, LaneConfig | None, int | None]] = {
                lid: (h, h.lane_config, self._port_alloc.get_port(lid))
                for lid, h in self._handles.items()
            }
            # Track completed operations for rollback
            removed_snapshots: dict[str, tuple[ProcessHandle, LaneConfig | None, int]] = {}
            added_ids: list[str] = []
            restarted_ids: list[str] = []  # lanes that were restarted (for rollback)

            try:
                # Phase 1: Remove stale lanes (free VRAM)
                to_remove = current_ids - desired_ids
                for lid in to_remove:
                    handle = self._handles[lid]
                    port = self._port_alloc.get_port(lid)
                    lc = handle.lane_config
                    # Save for potential rollback before removing
                    removed_snapshots[lid] = (handle, lc, port)
                    try:
                        await self._remove_lane_unlocked(lid)
                        # Refresh GPU snapshot BEFORE _record_event so the status-push
                        # triggered by _mark_status_dirty carries post-removal VRAM numbers.
                        # This mirrors the same pattern in sleep_lane/wake_lane and prevents
                        # the server from seeing the lane as gone but VRAM still occupied
                        # (causing the wake VRAM check to be denied on the next request).
                        if self._gpu_force_poll is not None:
                            await self._gpu_force_poll()
                        self._record_event(lid, "removed", model=lc.model if lc else "", port=port)
                        actions.append(LaneAction(
                            action="removed", lane_id=lid,
                            model=lc.model if lc else lid,
                            details="Lane removed — process stopped",
                        ))
                    except Exception as e:
                        msg = f"Failed to remove lane '{lid}': {e}"
                        logger.error(msg, exc_info=True)
                        errors.append(msg)
                        raise _ApplyAbort(msg)

                # Phase 2: Reconfigure changed lanes (stop-then-start)
                to_check = current_ids & desired_ids
                for lid in to_check:
                    handle = self._handles[lid]
                    desired_lc = desired_map[lid]
                    current_lc = handle.lane_config

                    if current_lc is not None and _lane_needs_restart(current_lc, desired_lc):
                        try:
                            await self._restart_lane_unlocked(lid, desired_lc)
                            restarted_ids.append(lid)
                            if desired_lc.vllm:
                                details = f"restart: backend=vllm, ctx={desired_lc.context_length}"
                            else:
                                details = (
                                    f"restart: num_parallel={desired_lc.num_parallel}, "
                                    f"ctx={desired_lc.context_length}"
                                )
                            actions.append(LaneAction(
                                action="reconfigured", lane_id=lid,
                                model=desired_lc.model,
                                details=details,
                            ))
                        except Exception as e:
                            msg = f"Failed to restart lane '{lid}': {e}"
                            logger.error(msg, exc_info=True)
                            errors.append(msg)
                            raise _ApplyAbort(msg)
                    else:
                        actions.append(LaneAction(
                            action="unchanged", lane_id=lid, model=desired_lc.model,
                        ))

                # Phase 3: Add new lanes, with staggered startup.
                # Temporarily sleep any existing vLLM lanes that support
                # sleep mode so the new model can load VRAM without competing
                # with active KV-cache allocations in running lanes.
                to_add = desired_ids - current_ids
                slept_lids: list[str] = []
                if to_add:
                    for existing_lid, existing_h in self._handles.items():
                        elc = existing_h.lane_config
                        if (
                            elc is not None
                            and elc.vllm
                            and elc.vllm_config is not None
                            and elc.vllm_config.enable_sleep_mode
                        ):
                            try:
                                await existing_h.sleep(level=2, mode="wait")
                                slept_lids.append(existing_lid)
                                logger.info(
                                    "Staggered startup: slept lane '%s' (level=2) "
                                    "to free VRAM for %d new lane(s)",
                                    existing_lid, len(to_add),
                                )
                            except Exception:
                                logger.warning(
                                    "Staggered startup: could not sleep lane '%s'; "
                                    "continuing without stagger for that lane",
                                    existing_lid,
                                    exc_info=True,
                                )
                try:
                    add_list = list(to_add)
                    for idx, lid in enumerate(add_list):
                        lc = desired_map[lid]
                        try:
                            await self._add_lane_unlocked(lid, lc)
                            added_ids.append(lid)
                            port = self._port_alloc.get_port(lid)
                            if lc.vllm:
                                details = f"port={port}, continuous_batching=true"
                            else:
                                details = f"port={port}, num_parallel={lc.num_parallel}"
                            actions.append(LaneAction(
                                action="added", lane_id=lid, model=lc.model,
                                details=details,
                            ))
                        except Exception as e:
                            msg = f"Failed to add lane '{lid}': {e}"
                            logger.error(msg, exc_info=True)
                            errors.append(msg)
                            raise _ApplyAbort(msg)

                        # Stagger: sleep the just-spawned lane before starting
                        # the next one, so VRAM is freed for the next model load.
                        if idx < len(add_list) - 1:
                            new_h = self._handles.get(lid)
                            nlc = new_h.lane_config if new_h else None
                            if (
                                new_h is not None
                                and nlc is not None
                                and nlc.vllm
                                and nlc.vllm_config is not None
                                and nlc.vllm_config.enable_sleep_mode
                            ):
                                try:
                                    await new_h.sleep(level=2, mode="wait")
                                    slept_lids.append(lid)
                                    logger.info(
                                        "Staggered startup: slept newly-added lane '%s' "
                                        "before spawning next lane",
                                        lid,
                                    )
                                except Exception:
                                    logger.warning(
                                        "Staggered startup: could not sleep newly-added "
                                        "lane '%s'; next spawn may compete for VRAM",
                                        lid,
                                        exc_info=True,
                                    )
                finally:
                    # Always wake staggered lanes — even if an add failed
                    for slept_lid in slept_lids:
                        try:
                            slept_h = self._handles.get(slept_lid)
                            if slept_h is not None:
                                await slept_h.wake_up()
                                logger.info(
                                    "Staggered startup: woke lane '%s' after adding new lanes",
                                    slept_lid,
                                )
                        except Exception:
                            logger.warning(
                                "Staggered startup: failed to wake lane '%s'",
                                slept_lid,
                                exc_info=True,
                            )

            except _ApplyAbort:
                # ---- Rollback: best-effort restore previous state ----
                logger.warning("apply_lanes failed mid-operation — rolling back")
                rolled_back = True
                await self._rollback_unlocked(
                    removed_snapshots, added_ids, restarted_ids, snapshot,
                )

            lane_statuses = await self._collect_statuses_unlocked()
            prom.LANE_TRANSITIONS_TOTAL.labels(action="apply").inc()

            return LaneApplyResult(
                success=len(errors) == 0,
                actions=actions,
                lanes=lane_statuses,
                errors=errors,
                rolled_back=rolled_back,
            )

    # ------------------------------------------------------------------
    # Imperative lane operations
    # ------------------------------------------------------------------

    async def add_lane(self, lane_config: LaneConfig) -> LaneStatus:
        """Add a single lane."""
        lid = _lane_id_from_config(lane_config)
        self._validate_vllm_runtime_requirements([lane_config])
        if self._max_lanes > 0 and len(self._handles) >= self._max_lanes:
            raise ValueError(
                f"MAX_LANES limit reached ({self._max_lanes})"
            )
        async with self._lock:
            if lid in self._handles:
                raise ValueError(f"Lane '{lid}' already exists")
            await self._add_lane_unlocked(lid, lane_config)
            return await self._get_status_unlocked(lid)

    async def remove_lane(self, lane_id: str) -> None:
        """Remove a single lane and free its port."""
        async with self._lock:
            if lane_id not in self._handles:
                raise KeyError(f"Lane '{lane_id}' not found")
            await self._remove_lane_unlocked(lane_id)
            # Refresh GPU snapshot immediately after the process exits so the next
            # status heartbeat to logos-server carries accurate free-VRAM numbers.
            # Without this the server-side planner would see phantom VRAM (lanes=0
            # but VRAM still reported as occupied) for up to the poll interval.
            if self._gpu_force_poll is not None:
                await self._gpu_force_poll()
            prom.LANE_TRANSITIONS_TOTAL.labels(action="delete").inc()

    async def reconfigure_lane(self, lane_id: str, updates: dict[str, Any]) -> LaneStatus:
        """Apply partial updates to an existing lane (stop-then-start if restart needed)."""
        async with self._lock:
            handle = self._handles.get(lane_id)
            if handle is None:
                raise KeyError(f"Lane '{lane_id}' not found")

            current = handle.lane_config
            if current is None:
                raise RuntimeError(f"Lane '{lane_id}' has no config (never spawned)")

            current_data = current.model_dump()
            changed = False
            for key, value in updates.items():
                if value is not None and key in current_data and current_data[key] != value:
                    current_data[key] = value
                    changed = True

            if not changed:
                return await self._get_status_unlocked(lane_id)

            new_lc = LaneConfig(**current_data)
            self._validate_vllm_runtime_requirements([new_lc])
            if _lane_needs_restart(current, new_lc):
                await self._restart_lane_unlocked(lane_id, new_lc)
            prom.LANE_TRANSITIONS_TOTAL.labels(action="reconfigure").inc()

            return await self._get_status_unlocked(lane_id)

    async def sleep_lane(self, lane_id: str, level: int = 1, mode: str = "wait") -> LaneStatus:
        """Put a running vLLM lane into sleep mode."""
        async with self._lock:
            if len(self._handles) == 1:
                logger.warning(
                    "Sleeping the only active lane '%s' — worker will have zero serving capacity",
                    lane_id,
                )
            handle = self._handles.get(lane_id)
            if handle is None:
                raise KeyError(f"Lane '{lane_id}' not found")
            lc = handle.lane_config
            if lc is None or not lc.vllm:
                raise ValueError(f"Lane '{lane_id}' is not a vLLM lane")
            await handle.sleep(level=level, mode=mode)
            # Refresh GPU snapshot BEFORE _record_event so that the status-push
            # triggered by _mark_status_dirty carries post-sleep GPU numbers.
            # Without this, _status_refresh_loop would race ahead with stale data,
            # causing the server to see the lane as sleeping but VRAM still full.
            if self._gpu_force_poll is not None:
                await self._gpu_force_poll()
            prom.LANE_TRANSITIONS_TOTAL.labels(action="sleep").inc()
            self._record_event(
                lane_id,
                "sleep",
                model=lc.model,
                details=f"level={level}, mode={mode}",
                port=handle.port,
            )
            return await self._get_status_unlocked(lane_id)

    async def wake_lane(self, lane_id: str) -> LaneStatus:
        """Wake a sleeping vLLM lane."""
        cleanup: tuple[ProcessHandle, int | None, str] | None = None
        async with self._lock:
            handle = self._handles.get(lane_id)
            if handle is None:
                raise KeyError(f"Lane '{lane_id}' not found")
            lc = handle.lane_config
            if lc is None or not lc.vllm:
                raise ValueError(f"Lane '{lane_id}' is not a vLLM lane")
            try:
                await handle.wake_up()
            except Exception as exc:
                if not self._is_probable_cuda_oom(exc):
                    raise
                logger.error(
                    "Wake of lane '%s' failed with CUDA OOM; detaching lane for cleanup",
                    lane_id,
                    exc_info=True,
                )
                persist_recent_logs = getattr(handle, "persist_recent_logs", None)
                if callable(persist_recent_logs):
                    try:
                        persist_recent_logs("wake_oom")
                    except Exception:
                        logger.debug(
                            "Could not persist recent logs for lane '%s' after wake OOM",
                            lane_id,
                            exc_info=True,
                        )
                self._record_event(
                    lane_id,
                    "wake_oom",
                    model=lc.model,
                    details=str(exc),
                    port=handle.port,
                )
                detached_handle, port = self._detach_lane_unlocked(lane_id)
                if detached_handle is not None:
                    cleanup = (detached_handle, port, str(exc))
                else:
                    cleanup = (handle, handle.port, str(exc))
            else:
                # Refresh GPU snapshot before _record_event for the same reason
                # as in sleep_lane: wake allocates VRAM and _status_refresh_loop
                # must carry post-wake numbers in the heartbeat it sends.
                if self._gpu_force_poll is not None:
                    await self._gpu_force_poll()
                prom.LANE_TRANSITIONS_TOTAL.labels(action="wake").inc()
                self._record_event(
                    lane_id,
                    "wake",
                    model=lc.model,
                    port=handle.port,
                )
                return await self._get_status_unlocked(lane_id)

        assert cleanup is not None
        detached_handle, port, details = cleanup
        await self._finalize_detached_lane(lane_id, detached_handle, port)
        raise RuntimeError(
            f"Lane '{lane_id}' wake failed with CUDA OOM and was removed for cleanup: {details}"
        )

    # ------------------------------------------------------------------
    # Status / queries
    # ------------------------------------------------------------------

    async def get_all_statuses(self) -> list[LaneStatus]:
        # Snapshot handles without the lock so status collection (which does
        # async I/O like nvidia-smi queries) doesn't block behind long-running
        # operations like apply_lanes / add_lane that hold self._lock during
        # vLLM process startup.
        handles = list(self._handles.values())
        pids = []
        for handle in handles:
            ps = handle.status()
            if ps.state == ProcessState.RUNNING and ps.pid is not None:
                pids.append(ps.pid)
        pid_vram_map = await self._query_process_vram_map(pids)

        statuses = []
        for handle in handles:
            status = await self._build_lane_status(handle, pid_vram_map)
            statuses.append(status)
            self._record_profile_from_status(status)
        await self._check_stuck_lanes(statuses)
        await self._recover_dead_lanes(statuses)
        return statuses

    async def _recover_dead_lanes(self, statuses: list[LaneStatus]) -> None:
        """Best-effort restart for lanes whose process died unexpectedly.

        Implements a circuit breaker (max _MAX_CRASH_RESTARTS attempts per lane)
        and skips restart when VRAM or GPU is in an unrecoverable state.
        After all dead lanes exhaust their restart budget and any has stuck VRAM,
        the worker triggers a host OS reboot (when auto_reboot_on_stuck_gpu is enabled).
        """
        now = asyncio.get_running_loop().time()
        exhausted_lids: list[str] = []   # lanes that hit the max retry budget
        stuck_vram_lids: list[str] = []  # lanes with uncleared VRAM

        for status in statuses:
            if status.runtime_state not in {"stopped", "error"}:
                continue
            lane_config = status.lane_config
            if lane_config is None:
                continue
            lid = status.lane_id
            handle = self._handles.get(lid)

            # Skip if the handle has fatal CUDA errors (GPU unrecoverable without reboot)
            if handle is not None and getattr(handle, "has_fatal_cuda_errors", False):
                logger.error(
                    "Lane '%s' has fatal CUDA errors in recent logs; skipping restart "
                    "(reboot required to recover GPU state)",
                    lid,
                )
                self._record_event(
                    lid, "crash_restart_skipped_fatal_cuda",
                    model=lane_config.model,
                    details="Fatal CUDA error patterns detected in process logs",
                    port=status.port,
                )
                exhausted_lids.append(lid)
                if getattr(handle, "has_stuck_vram", False):
                    stuck_vram_lids.append(lid)
                continue

            # Skip if VRAM is still held from the previous crash
            if handle is not None and getattr(handle, "has_stuck_vram", False):
                logger.error(
                    "Lane '%s' has stuck VRAM from previous crash; skipping restart "
                    "until GPU memory is released",
                    lid,
                )
                self._record_event(
                    lid, "crash_restart_skipped_stuck_vram",
                    model=lane_config.model,
                    details="VRAM still held by crashed process",
                    port=status.port,
                )
                stuck_vram_lids.append(lid)
                exhausted_lids.append(lid)
                continue

            # Circuit breaker: skip if restart budget exhausted
            restart_count = self._crash_restart_counts.get(lid, 0)
            if restart_count >= _MAX_CRASH_RESTARTS:
                logger.error(
                    "Lane '%s' has exhausted its crash-restart budget (%d/%d); "
                    "skipping automatic restart",
                    lid, restart_count, _MAX_CRASH_RESTARTS,
                )
                self._record_event(
                    lid, "crash_restart_budget_exhausted",
                    model=lane_config.model,
                    details=f"restart_count={restart_count}/{_MAX_CRASH_RESTARTS}",
                    port=status.port,
                )
                exhausted_lids.append(lid)
                continue

            # Cooldown check
            last_attempt = self._last_crash_restart_attempt_at.get(lid, 0.0)
            if now - last_attempt < _CRASH_RESTART_COOLDOWN_S:
                continue

            self._last_crash_restart_attempt_at[lid] = now
            new_count = restart_count + 1
            self._crash_restart_counts[lid] = new_count
            self._record_event(
                lid,
                "crash_restart_attempt",
                model=lane_config.model,
                details=(
                    f"runtime_state={status.runtime_state}, "
                    f"attempt={new_count}/{_MAX_CRASH_RESTARTS}"
                ),
                port=status.port,
            )
            logger.warning(
                "Lane '%s' process is %s; attempting automatic restart (%d/%d)",
                lid,
                status.runtime_state,
                new_count,
                _MAX_CRASH_RESTARTS,
            )
            try:
                async with self._lock:
                    handle = self._handles.get(lid)
                    if handle is None:
                        continue
                    current = handle.status()
                    if current.state not in {ProcessState.STOPPED, ProcessState.ERROR}:
                        continue
                    current_lc = handle.lane_config or lane_config
                    await self._restart_lane_unlocked(lid, current_lc)
                # Successful restart: reset the counter
                self._crash_restart_counts[lid] = 0
                self._record_event(lid, "crash_restart_ok", model=current_lc.model, port=status.port)
            except Exception:
                logger.error("Lane '%s' automatic crash recovery failed", lid, exc_info=True)
                self._record_event(lid, "crash_restart_failed", model=lane_config.model, port=status.port)

        # If all dead lanes are exhausted AND any has stuck VRAM → consider host reboot
        if (
            self._auto_reboot_on_stuck_gpu
            and stuck_vram_lids
            and exhausted_lids
            and all(
                s.runtime_state in {"stopped", "error"}
                for s in statuses
                if s.lane_id in exhausted_lids
            )
        ):
            logger.critical(
                "All crashed lanes have exhausted restart budgets and %d lane(s) have "
                "stuck VRAM (%s); initiating host OS reboot",
                len(stuck_vram_lids),
                stuck_vram_lids,
            )
            await self._initiate_reboot()

    async def _initiate_reboot(self) -> None:
        """Trigger a host OS reboot to recover from unrecoverable GPU state.

        Attempts ``sudo reboot`` first; falls back to writing a sentinel file at
        ``self._reboot_sentinel_path`` which a host-side watchdog can pick up.
        """
        logger.critical("Initiating host OS reboot due to unrecoverable GPU state")

        # Stop all lanes gracefully before rebooting
        for lid in list(self._handles.keys()):
            try:
                handle = self._handles[lid]
                await handle.destroy()
            except Exception:
                logger.warning("Failed to stop lane '%s' before reboot", lid, exc_info=True)

        # Brief pause so logs can flush before the host goes down
        await asyncio.sleep(5)

        try:
            proc = await asyncio.create_subprocess_exec(
                "sudo", "reboot",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=10.0)
            logger.critical("sudo reboot issued successfully")
            return
        except Exception:
            logger.error(
                "sudo reboot failed; writing sentinel file '%s'",
                self._reboot_sentinel_path,
                exc_info=True,
            )

        # Fallback: write sentinel file for a host-side watchdog
        try:
            await asyncio.to_thread(_write_reboot_sentinel, self._reboot_sentinel_path)
            logger.critical("Sentinel file written at '%s'", self._reboot_sentinel_path)
        except Exception:
            logger.error(
                "Failed to write reboot sentinel file '%s'",
                self._reboot_sentinel_path,
                exc_info=True,
            )

    async def get_lane_status(self, lane_id: str) -> LaneStatus:
        async with self._lock:
            return await self._get_status_unlocked(lane_id)

    def get_current_lane_configs(self) -> list[LaneConfig]:
        """Return the LaneConfig for every active lane (for state persistence)."""
        configs: list[LaneConfig] = []
        for handle in self._handles.values():
            if handle.lane_config is not None:
                configs.append(handle.lane_config)
        return configs

    def get_handle(self, lane_id: str) -> ProcessHandle | None:
        return self._handles.get(lane_id)

    def get_handle_for_model(self, model: str) -> ProcessHandle | None:
        """Find the process handle for a given model name."""
        matches: list[tuple[str, ProcessHandle]] = []
        for lane_id, handle in self._handles.items():
            lc = handle.lane_config
            if lc is not None and lc.model == model:
                matches.append((lane_id, handle))
        if not matches:
            return None
        # Prefer least-loaded replica for model-level lookup.
        matches.sort(key=lambda item: (self._active_requests.get(item[0], 0), item[0]))
        return matches[0][1]

    async def increment_active_requests(self, lane_id: str) -> None:
        async with self._lock:
            if lane_id not in self._handles:
                raise KeyError(f"Lane '{lane_id}' not found")
            self._active_requests[lane_id] = self._active_requests.get(lane_id, 0) + 1
            self._mark_status_dirty()

    async def decrement_active_requests(self, lane_id: str) -> None:
        async with self._lock:
            if lane_id not in self._handles:
                return
            current = self._active_requests.get(lane_id, 0)
            self._active_requests[lane_id] = max(0, current - 1)
            self._mark_status_dirty()

    @property
    def lane_ids(self) -> list[str]:
        return list(self._handles.keys())

    @property
    def is_multi_lane(self) -> bool:
        return len(self._handles) > 0

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    async def destroy_all(self) -> None:
        """Stop all lane processes and clean up."""
        async with self._lock:
            detached: list[tuple[str, ProcessHandle, int | None]] = []
            for lid in list(self._handles.keys()):
                handle, port = self._detach_lane_unlocked(lid)
                if handle is not None:
                    detached.append((lid, handle, port))

        if not detached:
            return

        logger.info("Destroying %d lane(s) during worker shutdown", len(detached))
        await asyncio.gather(
            *(self._finalize_detached_lane(lid, handle, port) for lid, handle, port in detached),
            return_exceptions=False,
        )

    async def close(self) -> None:
        """Release HTTP clients for all handles."""
        for handle in self._handles.values():
            await handle.close()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    # CPU offload is controlled per-lane via vllm_config.cpu_offload_gb.
    # No auto-injection — only applied when explicitly set on a lane's config.

    def _apply_model_vllm_overrides(self, lane_config: LaneConfig) -> LaneConfig:
        """Merge worker-local per-model vLLM overrides into an incoming lane config.

        Reads engines.vllm.model_overrides from config.yml and merges matching
        entries on top of the lane's vllm_config.  Lets this worker enforce
        SM-specific workarounds (e.g. disable_custom_all_reduce, quantization: awq
        on Turing) without requiring changes to the Logos server.
        """
        if not lane_config.vllm or lane_config.vllm_config is None:
            return lane_config
        overrides = self._vllm_engine_config.model_overrides.get(lane_config.model)
        if not overrides:
            return lane_config
        merged = {**lane_config.vllm_config.model_dump(), **overrides}
        new_vc = VllmConfig.model_validate(merged)
        logger.info("Applied local vLLM overrides for %s: %s", lane_config.model, list(overrides))
        return lane_config.model_copy(update={"vllm_config": new_vc})

    def _auto_tensor_parallel(self, lane_config: LaneConfig) -> LaneConfig:
        """Validate and optionally escalate tensor_parallel_size for vLLM lanes.

        Policy:
        - TP=1 is the safe default when the model fits on one GPU.
        - If TP is explicitly set > 1, respect the operator's choice.
        - If TP is at default (1) and the model **provably** does not fit on
          a single GPU (based on model profile vs actual per-GPU VRAM), auto-
          escalate to the minimum TP needed.  This avoids the previous
          "always use all GPUs" approach while still preventing guaranteed
          OOM failures.
        """
        if not lane_config.vllm or lane_config.vllm_config is None:
            return lane_config
        vc = lane_config.vllm_config
        gpu_count = self._gpu_device_count()

        # Explicit TP > 1: respect the operator's choice, just validate
        if vc.tensor_parallel_size > 1:
            if vc.tensor_parallel_size > gpu_count:
                logger.warning(
                    "Lane '%s' requests tensor_parallel_size=%d but only %d GPU(s) detected; "
                    "vLLM startup will likely fail",
                    lane_config.model, vc.tensor_parallel_size, gpu_count,
                )
            else:
                logger.info(
                    "\033[36mTP\033[0m lane '%s' model=%s: "
                    "tensor_parallel_size=%d (explicit), %d GPU(s) available",
                    lane_config.model, lane_config.model,
                    vc.tensor_parallel_size, gpu_count,
                )
            return lane_config

        # TP=1 (default): check if the model actually fits on one GPU
        if gpu_count <= 1:
            return lane_config

        per_gpu_mb = self._per_gpu_vram_mb()
        if per_gpu_mb <= 0 or self._model_profiles is None:
            # Can't determine GPU size — keep TP=1 (safe default)
            return lane_config

        profile = self._model_profiles.get_profile(lane_config.model)
        if profile is None:
            return lane_config

        base_mb = profile.estimate_base_residency_mb(lane_config.model)
        if base_mb is None or base_mb <= 0:
            return lane_config

        # Use 85% of GPU VRAM as the usable threshold (CUDA context + runtime overhead)
        usable_per_gpu_mb = per_gpu_mb * 0.85

        if base_mb <= usable_per_gpu_mb:
            # Model fits on one GPU — keep TP=1
            return lane_config

        # Model does NOT fit on one GPU — compute minimum TP needed
        import math
        needed_tp = math.ceil(base_mb / usable_per_gpu_mb)
        needed_tp = min(needed_tp, gpu_count)

        if needed_tp <= 1:
            return lane_config

        new_vc = vc.model_copy(update={"tensor_parallel_size": needed_tp})
        new_config = lane_config.model_copy(update={"vllm_config": new_vc})
        logger.info(
            "\033[36mAuto-TP\033[0m lane '%s' model=%s: "
            "model needs ~%.0f MB but single GPU has ~%.0f MB usable — "
            "auto-escalating tensor_parallel_size 1 → %d (%d GPU(s) available)",
            lane_config.model, lane_config.model,
            base_mb, usable_per_gpu_mb,
            needed_tp, gpu_count,
        )
        return new_config

    @staticmethod
    def _parse_gpu_selector(selector: str, allowed_indices: set[int] | None = None) -> list[int]:
        raw = (selector or "").strip().replace(" ", "")
        lowered = raw.lower()
        if lowered in {"", "all"}:
            if allowed_indices is None:
                return []
            return sorted(allowed_indices)
        if lowered == "none":
            return []

        result: list[int] = []
        for part in raw.split(","):
            if not part.isdigit():
                continue
            index = int(part)
            if allowed_indices is not None and index not in allowed_indices:
                continue
            result.append(index)
        return result

    def _estimate_lane_vram_mb(self, lane_config: LaneConfig) -> float:
        """Estimate total lane VRAM footprint for placement decisions."""
        if self._model_profiles is None:
            return 0.0

        profile = self._model_profiles.get_profile(lane_config.model)
        if profile is None:
            return 0.0

        if not lane_config.vllm:
            if profile.loaded_vram_mb and profile.loaded_vram_mb > 0:
                return float(profile.loaded_vram_mb)
            estimated = profile.estimate_vram_mb()
            return float(estimated) if estimated > 0 else 0.0

        base_mb = float(profile.base_residency_mb or profile.estimate_base_residency_mb(lane_config.model) or 0.0)
        kv_mb = 0.0
        if lane_config.vllm_config and lane_config.vllm_config.kv_cache_memory_bytes:
            kv_mb = self._parse_memory_to_mb(lane_config.vllm_config.kv_cache_memory_bytes)
        elif profile.kv_budget_mb and profile.kv_budget_mb > 0:
            kv_mb = float(profile.kv_budget_mb)
        elif profile.loaded_vram_mb and profile.loaded_vram_mb > 0 and base_mb > 0:
            kv_mb = max(float(profile.loaded_vram_mb) - base_mb, 0.0)
        elif base_mb > 0:
            kv_mb = base_mb * 0.35

        total_mb = base_mb + kv_mb
        if total_mb > 0:
            return total_mb
        if profile.loaded_vram_mb and profile.loaded_vram_mb > 0:
            return float(profile.loaded_vram_mb)
        return 0.0

    @staticmethod
    def _parse_memory_to_mb(value: str) -> float:
        raw = (value or "").strip().upper()
        if not raw:
            return 0.0
        if raw.endswith("G"):
            return float(raw[:-1]) * 1024.0
        if raw.endswith("M"):
            return float(raw[:-1])
        if raw.endswith("K"):
            return float(raw[:-1]) / 1024.0
        return float(raw) / (1024.0 * 1024.0)

    @staticmethod
    def _pick_best_gpu_subset(
        device_rows: list[dict[str, float]],
        tp_size: int,
        per_gpu_required_mb: float,
        headroom_mb: float,
    ) -> list[int] | None:
        feasible = [
            row for row in device_rows
            if float(row["free_mb"]) >= per_gpu_required_mb + headroom_mb
        ]
        if len(feasible) < tp_size:
            return None

        best_indices: list[int] | None = None
        best_score: tuple[float, float, float, tuple[int, ...]] | None = None
        for combo in combinations(feasible, tp_size):
            indices = tuple(sorted(int(row["index"]) for row in combo))
            leftover = sum(float(row["free_mb"]) - per_gpu_required_mb for row in combo)
            utilization = sum(float(row["utilization"]) for row in combo)
            widest_free = max(float(row["free_mb"]) for row in combo)
            score = (leftover, utilization, widest_free, indices)
            if best_score is None or score < best_score:
                best_score = score
                best_indices = list(indices)
        return best_indices

    async def _auto_place_gpu_devices(self, lane_id: str, lane_config: LaneConfig) -> LaneConfig:
        """Pick an explicit GPU set for auto-managed vLLM lanes.

        Strategy:
        - Respect explicit lane gpu_devices.
        - Preserve the current placement when it still fits.
        - Otherwise choose the smallest feasible GPU subset by free-memory
          leftover (best fit) within the worker's allowed GPU pool.
        """
        if not lane_config.vllm or lane_config.vllm_config is None:
            return lane_config
        if lane_config.gpu_devices:
            return lane_config
        if self._gpu_snapshot is None:
            return lane_config

        try:
            snapshot = await self._gpu_snapshot()
        except Exception:
            logger.debug("Auto-placement: failed to read GPU snapshot for lane '%s'", lane_id, exc_info=True)
            return lane_config

        if not snapshot.nvidia_smi_available:
            return lane_config

        device_rows: list[dict[str, float]] = []
        for fallback_index, device in enumerate(snapshot.devices):
            if device.kind != "nvidia":
                continue
            raw_index = device.extra.get("index", fallback_index)
            try:
                index = int(raw_index)
            except (TypeError, ValueError):
                index = fallback_index
            device_rows.append(
                {
                    "index": float(index),
                    "free_mb": float(device.memory_free_mb or 0.0),
                    "utilization": float(device.utilization_percent or 0.0),
                }
            )
        if not device_rows:
            return lane_config

        available_indices = {int(row["index"]) for row in device_rows}
        allowed_indices = self._parse_gpu_selector(self._global_config.gpu_devices, available_indices)
        if not allowed_indices:
            return lane_config

        allowed_rows = [row for row in device_rows if int(row["index"]) in set(allowed_indices)]
        tp_size = max(1, int(lane_config.vllm_config.tensor_parallel_size))
        if len(allowed_rows) < tp_size:
            logger.warning(
                "Auto-placement skipped for lane '%s': only %d allowed GPU(s) for tp=%d",
                lane_id, len(allowed_rows), tp_size,
            )
            return lane_config

        required_total_mb = self._estimate_lane_vram_mb(lane_config)
        if required_total_mb <= 0:
            logger.debug(
                "Auto-placement skipped for lane '%s' model=%s: no VRAM estimate available",
                lane_id, lane_config.model,
            )
            return lane_config

        per_gpu_required_mb = required_total_mb / float(tp_size)
        headroom_mb = max(
            _GPU_PLACEMENT_MIN_HEADROOM_MB,
            per_gpu_required_mb * _GPU_PLACEMENT_HEADROOM_RATIO,
        )

        current_handle = self._handles.get(lane_id)
        current_selector = ""
        if current_handle is not None and current_handle.lane_config is not None:
            current_selector = current_handle.lane_config.gpu_devices
        sticky_indices = self._parse_gpu_selector(current_selector, available_indices)
        selected_indices: list[int] | None = None
        if len(sticky_indices) == tp_size:
            sticky_rows = [
                row for row in allowed_rows if int(row["index"]) in set(sticky_indices)
            ]
            if len(sticky_rows) == tp_size and all(
                float(row["free_mb"]) >= per_gpu_required_mb + headroom_mb
                for row in sticky_rows
            ):
                selected_indices = sorted(sticky_indices)

        if selected_indices is None:
            selected_indices = self._pick_best_gpu_subset(
                allowed_rows,
                tp_size,
                per_gpu_required_mb,
                headroom_mb,
            )
        if selected_indices is None:
            logger.warning(
                "Auto-placement found no feasible GPU subset for lane '%s' model=%s "
                "(required≈%.0fMB total, tp=%d, headroom≈%.0fMB)",
                lane_id, lane_config.model, required_total_mb, tp_size, headroom_mb,
            )
            return lane_config

        selector = ",".join(str(index) for index in selected_indices)
        logger.info(
            "Auto-placement lane '%s' model=%s: gpu_devices=%s "
            "(required≈%.0fMB total, %.0fMB/GPU, tp=%d)",
            lane_id, lane_config.model, selector,
            required_total_mb, per_gpu_required_mb, tp_size,
        )
        return lane_config.model_copy(update={"gpu_devices": selector})

    async def _wait_for_vram_headroom(
        self, lane_id: str, lane_config: LaneConfig,
    ) -> None:
        """Poll GPU snapshot briefly to confirm enough VRAM is free before spawn.

        After a previous model is stopped, CUDA may take a moment to reclaim
        device memory.  This gate avoids the common first-attempt failure where
        vLLM rejects the launch because free memory is below its utilisation
        threshold.  Polls up to 3 times (force_poll + snapshot) at ~2 s
        intervals — at most ~6 s total — then proceeds regardless so the
        planner's own retry loop handles any remaining race.
        """
        if self._gpu_force_poll is None or self._gpu_snapshot is None:
            return
        if not lane_config.vllm:
            return

        total_needed_mb = self._estimate_lane_vram_mb(lane_config)
        if total_needed_mb <= 0:
            return  # unknown profile — skip gate, let vLLM decide

        tp_size = 1
        if lane_config.vllm_config:
            tp_size = max(1, int(lane_config.vllm_config.tensor_parallel_size))
        per_gpu_needed_mb = total_needed_mb / tp_size

        # Which GPU indices will this lane use?
        target_indices: set[int] | None = None
        if lane_config.gpu_devices:
            try:
                target_indices = {
                    int(s.strip())
                    for s in lane_config.gpu_devices.split(",")
                    if s.strip()
                }
            except ValueError:
                pass

        max_attempts = 3
        poll_interval = 2.0

        for attempt in range(max_attempts):
            try:
                await self._gpu_force_poll()
                snapshot = await self._gpu_snapshot()
            except Exception:
                logger.debug(
                    "VRAM headroom check: GPU poll failed (attempt %d/%d)",
                    attempt + 1, max_attempts, exc_info=True,
                )
                break  # can't check — proceed with spawn

            if not snapshot.nvidia_smi_available:
                break

            # Check free VRAM on target devices
            min_free_mb = float("inf")
            for fallback_idx, device in enumerate(snapshot.devices):
                if device.kind != "nvidia":
                    continue
                raw_idx = device.extra.get("index", fallback_idx)
                try:
                    idx = int(raw_idx)
                except (TypeError, ValueError):
                    idx = fallback_idx
                if target_indices is not None and idx not in target_indices:
                    continue
                free = float(device.memory_free_mb or 0.0)
                min_free_mb = min(min_free_mb, free)

            if min_free_mb == float("inf"):
                break  # no matching devices found — skip gate

            if min_free_mb >= per_gpu_needed_mb:
                logger.info(
                    "VRAM headroom OK for lane '%s' model=%s: "
                    "min_free=%.0f MB >= needed=%.0f MB/GPU (attempt %d)",
                    lane_id, lane_config.model,
                    min_free_mb, per_gpu_needed_mb, attempt + 1,
                )
                return

            logger.info(
                "VRAM headroom wait for lane '%s' model=%s: "
                "min_free=%.0f MB < needed=%.0f MB/GPU — "
                "waiting %.1fs (attempt %d/%d)",
                lane_id, lane_config.model,
                min_free_mb, per_gpu_needed_mb,
                poll_interval, attempt + 1, max_attempts,
            )
            if attempt < max_attempts - 1:
                await asyncio.sleep(poll_interval)

        logger.warning(
            "VRAM headroom not confirmed for lane '%s' model=%s after %d attempts "
            "— proceeding with spawn (planner will retry if needed)",
            lane_id, lane_config.model, max_attempts,
        )

    async def _add_lane_unlocked(self, lane_id: str, lane_config: LaneConfig) -> None:
        if self._max_lanes > 0 and len(self._handles) >= self._max_lanes:
            raise ValueError(
                f"MAX_LANES limit reached ({self._max_lanes})"
            )
        # Ensure model is in RAM cache if available
        hf_home_override: str | None = None
        if (
            self._model_cache is not None
            and getattr(self._model_cache, "enabled", False)
            and lane_config.vllm
        ):
            effective = await self._model_cache.ensure_cached(lane_config.model)
            if effective:
                hf_home_override = effective
                is_tmpfs = hasattr(self._model_cache, "_cache_hub") and effective == str(self._model_cache._cache_hub.parent)
                logger.info(
                    "Lane '%s' model=%s: HF_HOME=%s (%s)",
                    lane_id, lane_config.model, effective,
                    "tmpfs RAM cache" if is_tmpfs else "source filesystem",
                )
        lane_config = self._apply_model_vllm_overrides(lane_config)
        lane_config = self._auto_tensor_parallel(lane_config)
        lane_config = await self._auto_place_gpu_devices(lane_id, lane_config)
        await self._wait_for_vram_headroom(lane_id, lane_config)
        port = self._port_alloc.allocate(lane_id)
        handle = _create_handle(
            lane_id,
            port,
            self._global_config,
            self._vllm_engine_config,
            lane_config,
        )
        if hf_home_override and hasattr(handle, "hf_home_override"):
            handle.hf_home_override = hf_home_override
        try:
            await handle.init()
            status = await handle.spawn(lane_config)
            if status.state != ProcessState.RUNNING:
                raise RuntimeError(
                    f"process did not enter running state (state={status.state.value}, "
                    f"return_code={status.return_code})"
                )
        except Exception:
            # Keep apply_lanes transactional: failed startup must not leak ports
            # or dangling handles.
            self._port_alloc.release(lane_id)
            try:
                await handle.destroy()
            except Exception:
                logger.debug("Cleanup after failed lane add for '%s' had errors", lane_id, exc_info=True)
            await handle.close()
            raise
        self._handles[lane_id] = handle
        self._active_requests[lane_id] = 0
        self._starting_deadlines[lane_id] = asyncio.get_running_loop().time() + _RESTART_TIMEOUT
        self._record_event(lane_id, "spawned", model=lane_config.model,
                           port=port)
        logger.info("Lane '%s' added (vllm=%s, model=%s, port=%d)",
                     lane_id, lane_config.vllm, lane_config.model, port)

    async def _remove_lane_unlocked(self, lane_id: str) -> None:
        handle, port = self._detach_lane_unlocked(lane_id)
        if handle is None:
            return
        await self._finalize_detached_lane(lane_id, handle, port)

    async def _restart_lane_unlocked(
        self, lane_id: str, new_config: LaneConfig,
    ) -> None:
        """
        Reconfigure a lane by stopping the old process first, then spawning a
        new one on the same port.  No concurrent processes — avoids zombie VRAM.
        """
        new_config = self._auto_tensor_parallel(new_config)
        old_handle = self._handles[lane_id]
        port = self._port_alloc.get_port(lane_id)
        old_config = old_handle.lane_config

        self._record_event(
            lane_id, "restart_stop_old",
            model=old_config.model if old_config else new_config.model,
            port=port,
        )
        logger.info(
            "Restart '%s': stopping old %s process on port %d",
            lane_id, "vllm" if (old_config and old_config.vllm) else "ollama", port,
        )

        # Stop old process and release its resources
        try:
            await old_handle.destroy()
        except Exception:
            logger.warning("Restart '%s': failed to destroy old handle", lane_id, exc_info=True)
        await old_handle.close()

        new_config = await self._auto_place_gpu_devices(lane_id, new_config)

        # Spawn new process on the same port
        new_handle = _create_handle(
            lane_id,
            port,
            self._global_config,
            self._vllm_engine_config,
            new_config,
        )
        await new_handle.init()

        self._record_event(
            lane_id, "restart_spawn_new",
            model=new_config.model,
            port=port,
        )
        logger.info(
            "Restart '%s': spawning new %s process on port %d",
            lane_id, "vllm" if new_config.vllm else "ollama", port,
        )

        try:
            await new_handle.spawn(new_config)
        except Exception as exc:
            logger.error(
                "Restart '%s' failed during spawn: %s",
                lane_id, exc,
            )
            self._record_event(lane_id, "restart_failed",
                               model=new_config.model, details=str(exc))
            try:
                await new_handle.destroy()
            except Exception:
                pass
            await new_handle.close()
            # Lane is now dead — remove it from handles and release all
            # bookkeeping so the dead lane is not reported as active.
            self._handles.pop(lane_id, None)
            self._port_alloc.release(lane_id)
            self._active_requests.pop(lane_id, None)
            self._starting_deadlines.pop(lane_id, None)
            raise

        # Success
        self._handles[lane_id] = new_handle
        self._starting_deadlines[lane_id] = asyncio.get_running_loop().time() + _RESTART_TIMEOUT

        self._record_event(
            lane_id, "restart_ok",
            model=new_config.model,
            port=port,
        )
        logger.info(
            "Restart '%s' complete: port %d with num_parallel=%d",
            lane_id, port, new_config.num_parallel,
        )
    
    def _detach_lane_unlocked(self, lane_id: str) -> tuple[ProcessHandle | None, int | None]:
        handle = self._handles.pop(lane_id, None)
        if handle is None:
            return None, None
        port = self._port_alloc.get_port(lane_id)
        self._port_alloc.release(lane_id)
        self._active_requests.pop(lane_id, None)
        self._starting_deadlines.pop(lane_id, None)
        return handle, port

    async def _finalize_detached_lane(
        self,
        lane_id: str,
        handle: ProcessHandle,
        port: int | None,
    ) -> None:
        try:
            await asyncio.wait_for(handle.destroy(), timeout=_HANDLE_DESTROY_TIMEOUT)
        except asyncio.TimeoutError:
            logger.error(
                "Timed out destroying lane '%s' after %ss; continuing shutdown with the lane detached",
                lane_id,
                _HANDLE_DESTROY_TIMEOUT,
            )
        except Exception:
            logger.warning("Error destroying lane '%s'", lane_id, exc_info=True)

        try:
            await asyncio.wait_for(handle.close(), timeout=_HANDLE_CLOSE_TIMEOUT)
        except asyncio.TimeoutError:
            logger.error(
                "Timed out closing lane '%s' after %ss; continuing shutdown with the handle detached",
                lane_id,
                _HANDLE_CLOSE_TIMEOUT,
            )
        except Exception:
            logger.warning("Error closing lane '%s'", lane_id, exc_info=True)

        self._record_event(lane_id, "stopped", port=port)
        logger.info("Lane '%s' removed", lane_id)

    async def _rollback_unlocked(
        self,
        removed_snapshots: dict[str, tuple[ProcessHandle, LaneConfig | None, int]],
        added_ids: list[str],
        restarted_ids: list[str],
        original_snapshot: dict[str, tuple[ProcessHandle, LaneConfig | None, int | None]],
    ) -> None:
        """Best-effort rollback of a failed apply_lanes operation."""
        # 1. Remove newly added lanes
        for lid in added_ids:
            try:
                await self._remove_lane_unlocked(lid)
                self._record_event(lid, "rollback_removed")
            except Exception:
                logger.warning("Rollback: failed to remove added lane '%s'", lid, exc_info=True)

        # 2. Restore restarted lanes from original config
        for lid in restarted_ids:
            orig = original_snapshot.get(lid)
            if orig is not None:
                _, orig_lc, orig_port = orig
                if orig_lc is not None and orig_port is not None:
                    # Stop the new (possibly broken) process
                    new_handle = self._handles.get(lid)
                    if new_handle is not None:
                        try:
                            await new_handle.destroy()
                            await new_handle.close()
                        except Exception:
                            logger.warning("Rollback: failed to stop new handle for '%s'", lid, exc_info=True)
                    try:
                        restored = _create_handle(
                            lid,
                            orig_port,
                            self._global_config,
                            self._vllm_engine_config,
                            orig_lc,
                        )
                        await restored.init()
                        await restored.spawn(orig_lc)
                        self._handles[lid] = restored
                        self._port_alloc._used[lid] = orig_port
                        self._active_requests[lid] = 0
                        self._starting_deadlines[lid] = asyncio.get_running_loop().time() + _RESTART_TIMEOUT
                        self._record_event(lid, "rollback_restored", model=orig_lc.model, port=orig_port)
                    except Exception:
                        logger.error("Rollback: failed to restore lane '%s'", lid, exc_info=True)
                        self._handles.pop(lid, None)

        # 3. Re-add removed lanes that had snapshots
        for lid, (handle, lc, port) in removed_snapshots.items():
            if lid not in self._handles and lc is not None:
                try:
                    restored = _create_handle(
                        lid,
                        port,
                        self._global_config,
                        self._vllm_engine_config,
                        lc,
                    )
                    await restored.init()
                    await restored.spawn(lc)
                    self._handles[lid] = restored
                    self._port_alloc._used[lid] = port
                    self._active_requests[lid] = 0
                    self._starting_deadlines[lid] = asyncio.get_running_loop().time() + _RESTART_TIMEOUT
                    self._record_event(lid, "rollback_restored", model=lc.model, port=port)
                except Exception:
                    logger.error("Rollback: failed to re-add removed lane '%s'", lid, exc_info=True)

        logger.info("Rollback complete")

    # ------------------------------------------------------------------
    # Event log
    # ------------------------------------------------------------------

    def _record_event(
        self,
        lane_id: str,
        event: str,
        model: str = "",
        details: str = "",
        port: int | None = None,
        old_port: int | None = None,
    ) -> None:
        """Append a lane transition event to the in-memory log."""
        self._event_seq += 1
        self._event_log.append(LaneEvent(
            event_id=f"evt-{self._event_seq}",
            timestamp=datetime.now(timezone.utc),
            lane_id=lane_id,
            event=event,
            model=model,
            details=details,
            port=port,
            old_port=old_port,
        ))
        # Trim to max size
        if len(self._event_log) > _MAX_EVENT_LOG:
            self._event_log = self._event_log[-_MAX_EVENT_LOG:]
        self._mark_status_dirty()

    @property
    def event_log(self) -> list[LaneEvent]:
        return list(self._event_log)

    @property
    def status_revision(self) -> int:
        return self._status_revision

    async def wait_for_status_revision(self, last_revision: int, timeout: float | None = None) -> int:
        while True:
            if self._status_revision != last_revision:
                return self._status_revision
            self._status_event.clear()
            if self._status_revision != last_revision:
                continue
            try:
                if timeout is None:
                    await self._status_event.wait()
                else:
                    await asyncio.wait_for(self._status_event.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                return self._status_revision

    def _mark_status_dirty(self) -> None:
        self._status_revision += 1
        self._status_event.set()

    async def _get_status_unlocked(self, lane_id: str) -> LaneStatus:
        handle = self._handles.get(lane_id)
        if handle is None:
            raise KeyError(f"Lane '{lane_id}' not found")
        ps = handle.status()
        pid_vram_map = await self._query_process_vram_map(
            [ps.pid] if ps.state == ProcessState.RUNNING and ps.pid is not None else []
        )
        return await self._build_lane_status(handle, pid_vram_map)

    async def _collect_statuses_unlocked(self) -> list[LaneStatus]:
        handles = list(self._handles.values())
        pids = []
        for handle in handles:
            ps = handle.status()
            if ps.state == ProcessState.RUNNING and ps.pid is not None:
                pids.append(ps.pid)
        pid_vram_map = await self._query_process_vram_map(pids)

        statuses = []
        for handle in handles:
            status = await self._build_lane_status(handle, pid_vram_map)
            statuses.append(status)
            self._record_profile_from_status(status)

        # Check for stuck vLLM lanes (no token generation progress while requests active).
        # auto_restart=False because this method is called with self._lock held.
        await self._check_stuck_lanes(statuses, auto_restart=False)
        return statuses

    @staticmethod
    def _is_probable_cuda_oom(exc: BaseException) -> bool:
        text = str(exc).lower()
        return (
            "out of memory" in text
            and (
                "cuda" in text
                or "cuda error" in text
                or "cumem_allocator" in text
            )
        )

    async def _check_stuck_lanes(
        self,
        statuses: list[LaneStatus],
        *,
        auto_restart: bool = True,
    ) -> None:
        """Detect vLLM lanes that have stopped generating tokens while requests are active.

        If ``generation_tokens_total`` doesn't increase for several consecutive
        polls while ``requests_running > 0``, the lane is likely stuck in an
        NCCL deadlock or similar hang.  Kill and log the event.

        When *auto_restart* is True (the default), the lane is automatically
        restarted with its previous configuration.  Pass ``False`` when the
        caller already holds ``self._lock`` to avoid a deadlock.
        """
        for status in statuses:
            lid = status.lane_id
            if not status.vllm:
                continue
            metrics = status.backend_metrics or {}
            gen_tokens = metrics.get("generation_tokens_total")
            requests_running = metrics.get("requests_running")

            if gen_tokens is None or requests_running is None:
                # Metrics not available — can't detect stuck state
                self._stuck_polls.pop(lid, None)
                continue

            prev_tokens = self._last_gen_tokens.get(lid)
            self._last_gen_tokens[lid] = gen_tokens

            if prev_tokens is None:
                self._stuck_polls.pop(lid, None)
                continue

            if requests_running > 0 and gen_tokens <= prev_tokens:
                count = self._stuck_polls.get(lid, 0) + 1
                self._stuck_polls[lid] = count
                if count >= self._stuck_poll_threshold:
                    logger.error(
                        "Lane '%s' appears stuck: %d consecutive polls with "
                        "requests_running=%.0f but generation_tokens_total unchanged (%.0f). "
                        "Killing the lane process.",
                        lid, count, requests_running, gen_tokens,
                    )
                    self._record_event(lid, "stuck_detected",
                                       model=status.model,
                                       details=f"gen_tokens={gen_tokens}, running={requests_running}, polls={count}")
                    self._stuck_polls.pop(lid, None)
                    self._last_gen_tokens.pop(lid, None)
                    # Kill the stuck lane and attempt automatic restart
                    handle = self._handles.get(lid)
                    if handle is not None:
                        lane_config = handle.lane_config
                        try:
                            await handle.stop()
                            logger.info("Lane '%s' stopped after stuck detection", lid)
                        except Exception:
                            logger.warning("Failed to stop stuck lane '%s'", lid, exc_info=True)

                        # Attempt automatic restart with the same config
                        if auto_restart and lane_config is not None:
                            await self._restart_stuck_lane(lid, lane_config)
            else:
                self._stuck_polls.pop(lid, None)

    async def _restart_stuck_lane(self, lane_id: str, lane_config: LaneConfig) -> None:
        """Attempt to restart a lane that was killed by stuck detection."""
        logger.info("Lane '%s': attempting automatic restart after stuck detection", lane_id)
        self._record_event(lane_id, "stuck_restart_attempt", model=lane_config.model)
        try:
            async with self._lock:
                if lane_id not in self._handles:
                    logger.warning(
                        "Lane '%s' was removed before stuck restart could begin — skipping",
                        lane_id,
                    )
                    return
                await self._restart_lane_unlocked(lane_id, lane_config)
            logger.info("Lane '%s': automatic restart after stuck detection succeeded", lane_id)
            self._record_event(lane_id, "stuck_restart_ok", model=lane_config.model)
        except Exception:
            logger.error(
                "Lane '%s': automatic restart after stuck detection failed",
                lane_id,
                exc_info=True,
            )
            self._record_event(
                lane_id, "stuck_restart_failed", model=lane_config.model,
            )

    def _record_profile_from_status(self, status: LaneStatus) -> None:
        """Update model profile with VRAM measurements from lane status."""
        if self._model_profiles is None:
            return
        model = status.model
        if not model:
            return
        vram = float(status.effective_vram_mb or 0.0)
        if vram <= 0:
            return
        engine = "vllm" if status.vllm else "ollama"
        observed_gpu_memory_utilization = None
        tensor_parallel_size = None
        lane_config = status.lane_config
        if status.vllm and lane_config is not None and lane_config.vllm_config is not None:
            if lane_config.vllm_config.gpu_memory_utilization is not None:
                observed_gpu_memory_utilization = float(lane_config.vllm_config.gpu_memory_utilization)
            tensor_parallel_size = int(lane_config.vllm_config.tensor_parallel_size)
        previous_state = self._last_profile_state.get(status.lane_id)
        if status.runtime_state in ("loaded", "running"):
            kv_cache_sent_mb = 0.0
            if (
                status.vllm
                and lane_config is not None
                and lane_config.vllm_config is not None
                and lane_config.vllm_config.kv_cache_memory_bytes
            ):
                kv_cache_sent_mb = ModelProfileRegistry._parse_kv_cache_to_mb(
                    lane_config.vllm_config.kv_cache_memory_bytes,
                )
            self._model_profiles.record_loaded_vram(
                model,
                vram,
                engine=engine,
                observed_gpu_memory_utilization=observed_gpu_memory_utilization,
                tensor_parallel_size=tensor_parallel_size,
                kv_cache_sent_mb=kv_cache_sent_mb,
            )
            if (
                status.vllm
                and observed_gpu_memory_utilization is not None
                and previous_state not in {"loaded", "running", "sleeping"}
            ):
                self._model_profiles.record_successful_load_util(
                    model,
                    observed_gpu_memory_utilization,
                )
        elif status.runtime_state == "sleeping":
            self._model_profiles.record_sleeping_vram(
                model,
                vram,
                engine=engine,
                observed_gpu_memory_utilization=observed_gpu_memory_utilization,
                tensor_parallel_size=tensor_parallel_size,
            )
        self._last_profile_state[status.lane_id] = status.runtime_state

    async def _build_lane_status(
        self,
        handle: ProcessHandle,
        pid_vram_map: dict[int, float] | None = None,
    ) -> LaneStatus:
        ps = handle.status()
        lc = handle.lane_config
        loaded_models: list[LoadedModel] = []
        vram_reported_mb = 0.0
        vram_by_pid_mb = 0.0

        if ps.state == ProcessState.RUNNING:
            try:
                raw_models = await handle.get_loaded_models()
                for m in raw_models:
                    expires_at = None
                    if ea := m.get("expires_at"):
                        try:
                            expires_at = datetime.fromisoformat(ea.replace("Z", "+00:00"))
                        except (ValueError, TypeError):
                            pass
                    loaded_models.append(LoadedModel(
                        name=m.get("name", ""),
                        size=m.get("size", 0),
                        size_vram=m.get("size_vram", 0),
                        expires_at=expires_at,
                        digest=m.get("digest"),
                        details=m.get("details", {}),
                    ))
                    vram_reported_mb += m.get("size_vram", 0) / (1024 * 1024)
            except Exception:
                logger.debug("Could not query loaded models for lane '%s'", handle.lane_id)

        if ps.state == ProcessState.RUNNING and ps.pid is not None:
            if pid_vram_map is None:
                pid_vram_map = await self._query_process_vram_map([ps.pid])
            vram_by_pid_mb = float(pid_vram_map.get(ps.pid, 0.0))

        effective_gpu_devices = ""
        is_vllm = False
        routing_url = f"http://127.0.0.1:{handle.port}"
        inference_endpoint = "/v1/chat/completions"
        sleep_mode_enabled = False
        sleep_state: str = "unsupported"
        backend_metrics: dict[str, Any] = {}
        model = ""
        num_parallel = 0
        context_length = 0
        keep_alive = ""
        kv_cache_type = ""
        flash_attention = False
        gpu_devices = ""

        if lc is not None:
            is_vllm = lc.vllm
            model = lc.model
            if lc.vllm:
                # Use vLLM-reported max concurrency (KV-budget-derived) when available.
                vllm_max = getattr(handle, "max_concurrency", None)
                num_parallel = vllm_max if vllm_max and vllm_max > 0 else 0
            else:
                num_parallel = lc.num_parallel
            context_length = lc.context_length
            keep_alive = lc.keep_alive
            kv_cache_type = lc.kv_cache_type
            flash_attention = lc.flash_attention
            gpu_devices = lc.gpu_devices
            effective_gpu_devices = lc.gpu_devices or self._global_config.gpu_devices
            inference_endpoint = _routing_inference_endpoint(lc.vllm)
            if lc.vllm:
                sleep_mode_enabled = bool(lc.vllm_config and lc.vllm_config.enable_sleep_mode)
                backend_metrics = (lc.vllm_config.model_dump(mode="json") if lc.vllm_config else {})
            else:
                backend_metrics = {
                    "engine": "ollama",
                    "num_parallel": lc.num_parallel,
                    "keep_alive": lc.keep_alive,
                    "kv_cache_type": lc.kv_cache_type,
                    "flash_attention": lc.flash_attention,
                    "context_length": lc.context_length,
                }
        if hasattr(handle, "get_backend_metrics"):
            try:
                backend_metrics.update(await handle.get_backend_metrics())
            except Exception:
                logger.debug("Could not query backend metrics for lane '%s'", handle.lane_id, exc_info=True)

        if lc is not None and lc.vllm:
            if not sleep_mode_enabled:
                sleep_state = "unsupported"
            elif ps.state != ProcessState.RUNNING:
                sleep_state = "unknown"
            else:
                try:
                    sleeping = await handle.is_sleeping()
                except Exception:
                    sleeping = None
                if sleeping is True:
                    sleep_state = "sleeping"
                elif sleeping is False:
                    sleep_state = "awake"
                else:
                    sleep_state = "unknown"

        active_requests = self._active_requests.get(handle.lane_id, 0)
        runtime_state: str = "stopped"
        starting_deadline = self._starting_deadlines.get(handle.lane_id, 0.0)
        now = asyncio.get_running_loop().time()
        if ps.state == ProcessState.RUNNING:
            if lc is not None and lc.vllm and sleep_mode_enabled and sleep_state == "sleeping":
                runtime_state = "sleeping"
            elif not loaded_models and now < starting_deadline:
                runtime_state = "starting"
            elif active_requests > 0:
                runtime_state = "running"
            elif loaded_models:
                runtime_state = "loaded"
            else:
                runtime_state = "cold"
        elif ps.state == ProcessState.STOPPED:
            runtime_state = "stopped"
        elif ps.state == ProcessState.ERROR:
            runtime_state = "error"
        elif ps.state == ProcessState.STARTING:
            runtime_state = "starting"

        vram_device_mb = 0.0
        vram_source: str = "unknown"
        if vram_by_pid_mb > 0:
            effective_vram_mb = vram_by_pid_mb
            vram_source = "pid"
        elif vram_reported_mb > 0:
            effective_vram_mb = vram_reported_mb
            vram_source = "reported"
        elif vram_device_mb > 0:
            effective_vram_mb = vram_device_mb
            vram_source = "device"
        else:
            effective_vram_mb = 0.0

        return LaneStatus(
            lane_id=handle.lane_id,
            lane_uid=f"{'vllm' if is_vllm else 'ollama'}:{handle.lane_id}",
            model=model,
            port=handle.port,
            vllm=is_vllm,
            process=ps,
            runtime_state=runtime_state,
            routing_url=routing_url,
            inference_endpoint=inference_endpoint,
            num_parallel=num_parallel,
            context_length=context_length,
            keep_alive=keep_alive,
            kv_cache_type=kv_cache_type,
            flash_attention=flash_attention,
            gpu_devices=gpu_devices,
            effective_gpu_devices=effective_gpu_devices,
            sleep_mode_enabled=sleep_mode_enabled,
            sleep_state=sleep_state,
            active_requests=active_requests,
            loaded_models=loaded_models,
            lane_config=lc,
            backend_metrics=backend_metrics,
            reported_vram_mb=vram_reported_mb,
            pid_vram_mb=vram_by_pid_mb,
            vram_device_mb=vram_device_mb,
            vram_source=vram_source,
            effective_vram_mb=effective_vram_mb,
        )

    async def _query_process_vram_map(self, pids: list[int]) -> dict[int, float]:
        """Query per-process VRAM from nvidia-smi for the given PIDs."""
        unique_pids = {int(pid) for pid in pids if pid is not None}
        if not unique_pids:
            return {}

        cmd = [
            "nvidia-smi",
            "--query-compute-apps=pid,used_memory",
            "--format=csv,noheader,nounits",
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _stderr = await proc.communicate()
        except FileNotFoundError:
            return {}
        except Exception:
            logger.debug("Failed to query nvidia-smi process memory", exc_info=True)
            return {}

        if proc.returncode != 0:
            return {}

        # nvidia-smi often reports GPU worker child PIDs (for example vLLM
        # workers) instead of the lane root PID tracked by asyncio subprocess.
        # Map descendant worker memory back to the requested root PID.
        result: dict[int, float] = {pid: 0.0 for pid in unique_pids}
        parent_cache: dict[int, int | None] = {}
        text = stdout.decode("utf-8", errors="replace")
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or "," not in line:
                continue
            left, right = line.split(",", 1)
            pid_str = left.strip()
            mem_str = right.strip()
            if not pid_str.isdigit():
                continue
            pid = int(pid_str)
            try:
                mem_mb = float(mem_str)
            except ValueError:
                continue
            owner_pid = self._resolve_owner_pid(pid, unique_pids, parent_cache)
            if owner_pid is None:
                continue
            result[owner_pid] = result.get(owner_pid, 0.0) + mem_mb
        return result

    @staticmethod
    def _resolve_owner_pid(
        candidate_pid: int,
        roots: set[int],
        parent_cache: dict[int, int | None],
    ) -> int | None:
        """Resolve candidate PID to one of the tracked root PIDs via PPID chain."""
        if candidate_pid in roots:
            return candidate_pid

        visited: set[int] = set()
        current = candidate_pid
        while current > 1 and current not in visited:
            visited.add(current)
            parent = LaneManager._read_parent_pid(current, parent_cache)
            if parent is None or parent <= 0:
                return None
            if parent in roots:
                return parent
            if parent == current:
                return None
            current = parent
        return None

    @staticmethod
    def _read_parent_pid(pid: int, parent_cache: dict[int, int | None]) -> int | None:
        cached = parent_cache.get(pid, None)
        if pid in parent_cache:
            return cached

        stat_path = f"/proc/{pid}/stat"
        try:
            with open(stat_path, "r", encoding="utf-8") as f:
                data = f.read().strip()
        except OSError:
            parent_cache[pid] = None
            return None

        # /proc/<pid>/stat format:
        # pid (comm) state ppid ...
        # comm may contain spaces, so split at the final ')' first.
        rparen = data.rfind(")")
        if rparen == -1:
            parent_cache[pid] = None
            return None
        tail = data[rparen + 2 :].split()
        if len(tail) < 3:
            parent_cache[pid] = None
            return None
        # tail[0]=state, tail[1]=ppid
        try:
            ppid = int(tail[1])
        except ValueError:
            ppid = None
        parent_cache[pid] = ppid
        return ppid
