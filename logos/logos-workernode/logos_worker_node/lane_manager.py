"""Lane manager for LogosWorkerNode."""

from __future__ import annotations

import asyncio
import logging
import socket
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from logos_worker_node.models import (
    LaneAction,
    LaneApplyResult,
    LaneConfig,
    LaneEvent,
    LaneStatus,
    LoadedModel,
    OllamaConfig,
    ProcessState,
)
from logos_worker_node.model_profiles import ModelProfileRegistry
from logos_worker_node.ollama_process import OllamaProcessHandle
from logos_worker_node.vllm_process import VllmProcessHandle

logger = logging.getLogger("logos_worker_node.lane_manager")

# Union type for all supported backend handles
ProcessHandle = OllamaProcessHandle | VllmProcessHandle

_DEFAULT_PORT_START = 11436
_DEFAULT_PORT_END = 11499

_HOT_SWAP_TIMEOUT = 90  # seconds total for spawn + preload on new process
_MAX_EVENT_LOG = 500    # max events kept in memory


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
    """Check if the lane config change requires a process restart."""
    if current.vllm != desired.vllm:
        return True
    return (
        current.num_parallel != desired.num_parallel
        or current.context_length != desired.context_length
        or current.kv_cache_type != desired.kv_cache_type
        or current.flash_attention != desired.flash_attention
        or current.gpu_devices != desired.gpu_devices
        or current.keep_alive != desired.keep_alive
        or current.vllm_config != desired.vllm_config
    )


def _create_handle(lane_id: str, port: int, global_config: OllamaConfig, lane_config: LaneConfig) -> ProcessHandle:
    """Factory: create the correct process handle based on backend type."""
    if lane_config.vllm:
        return VllmProcessHandle(lane_id, port, global_config)
    return OllamaProcessHandle(lane_id, port, global_config)


class _ApplyAbort(Exception):
    """Internal sentinel to trigger rollback in apply_lanes."""


class LaneManager:
    """Manages a pool of process handles (Ollama or vLLM), one per model lane."""

    def __init__(
        self,
        global_config: OllamaConfig,
        lane_port_start: int = _DEFAULT_PORT_START,
        lane_port_end: int = _DEFAULT_PORT_END,
        reserved_ports: Iterable[int] | None = None,
        nvidia_smi_available: Callable[[], bool] | None = None,
        model_profiles: ModelProfileRegistry | None = None,
    ) -> None:
        self._global_config = global_config
        self._nvidia_smi_available = nvidia_smi_available or (lambda: True)
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
          2. Reconfigure changed lanes via hot-swap (zero-downtime)
          3. Add new lanes (uses freed VRAM)

        On failure mid-apply, already-completed transitions are rolled back
        to restore the prior state (best-effort atomic semantics).

        Returns a result with all actions taken and final lane statuses.
        """
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
            swapped_old_handles: dict[str, ProcessHandle] = {}  # lid -> old handle to cleanup

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

                # Phase 2: Reconfigure changed lanes (hot-swap)
                to_check = current_ids & desired_ids
                for lid in to_check:
                    handle = self._handles[lid]
                    desired_lc = desired_map[lid]
                    current_lc = handle.lane_config

                    if current_lc is not None and _lane_needs_restart(current_lc, desired_lc):
                        try:
                            old_handle = await self._hot_swap_lane_unlocked(lid, desired_lc)
                            swapped_old_handles[lid] = old_handle
                            if desired_lc.vllm:
                                details = f"hot-swap: backend=vllm, ctx={desired_lc.context_length}"
                            else:
                                details = (
                                    f"hot-swap: num_parallel={desired_lc.num_parallel}, "
                                    f"ctx={desired_lc.context_length}"
                                )
                            actions.append(LaneAction(
                                action="reconfigured", lane_id=lid,
                                model=desired_lc.model,
                                details=details,
                            ))
                        except Exception as e:
                            msg = f"Failed to hot-swap lane '{lid}': {e}"
                            logger.error(msg, exc_info=True)
                            errors.append(msg)
                            raise _ApplyAbort(msg)
                    else:
                        actions.append(LaneAction(
                            action="unchanged", lane_id=lid, model=desired_lc.model,
                        ))

                # Phase 3: Add new lanes
                to_add = desired_ids - current_ids
                for lid in to_add:
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

            except _ApplyAbort:
                # ---- Rollback: best-effort restore previous state ----
                logger.warning("apply_lanes failed mid-operation — rolling back")
                rolled_back = True
                await self._rollback_unlocked(
                    removed_snapshots, added_ids, swapped_old_handles, snapshot,
                )

            # Cleanup old handles from successful hot-swaps (not rolled back)
            if not rolled_back:
                for old_handle in swapped_old_handles.values():
                    await old_handle.close()

            lane_statuses = await self._collect_statuses_unlocked()

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

    async def reconfigure_lane(self, lane_id: str, updates: dict[str, Any]) -> LaneStatus:
        """Apply partial updates to an existing lane via hot-swap."""
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
                old_handle = await self._hot_swap_lane_unlocked(lane_id, new_lc)
                await old_handle.close()

            return await self._get_status_unlocked(lane_id)

    async def sleep_lane(self, lane_id: str, level: int = 1, mode: str = "wait") -> LaneStatus:
        """Put a running vLLM lane into sleep mode."""
        async with self._lock:
            handle = self._handles.get(lane_id)
            if handle is None:
                raise KeyError(f"Lane '{lane_id}' not found")
            lc = handle.lane_config
            if lc is None or not lc.vllm:
                raise ValueError(f"Lane '{lane_id}' is not a vLLM lane")
            await handle.sleep(level=level, mode=mode)
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
        async with self._lock:
            handle = self._handles.get(lane_id)
            if handle is None:
                raise KeyError(f"Lane '{lane_id}' not found")
            lc = handle.lane_config
            if lc is None or not lc.vllm:
                raise ValueError(f"Lane '{lane_id}' is not a vLLM lane")
            await handle.wake_up()
            self._record_event(
                lane_id,
                "wake",
                model=lc.model,
                port=handle.port,
            )
            return await self._get_status_unlocked(lane_id)

    # ------------------------------------------------------------------
    # Status / queries
    # ------------------------------------------------------------------

    async def get_all_statuses(self) -> list[LaneStatus]:
        async with self._lock:
            return await self._collect_statuses_unlocked()

    async def get_lane_status(self, lane_id: str) -> LaneStatus:
        async with self._lock:
            return await self._get_status_unlocked(lane_id)

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
            for lid in list(self._handles.keys()):
                try:
                    await self._remove_lane_unlocked(lid)
                except Exception:
                    logger.warning("Error destroying lane '%s'", lid, exc_info=True)

    async def close(self) -> None:
        """Release HTTP clients for all handles."""
        for handle in self._handles.values():
            await handle.close()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _add_lane_unlocked(self, lane_id: str, lane_config: LaneConfig) -> None:
        port = self._port_alloc.allocate(lane_id)
        handle = _create_handle(lane_id, port, self._global_config, lane_config)
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
        self._starting_deadlines[lane_id] = asyncio.get_running_loop().time() + _HOT_SWAP_TIMEOUT
        self._record_event(lane_id, "spawned", model=lane_config.model,
                           port=port)
        logger.info("Lane '%s' added (vllm=%s, model=%s, port=%d)",
                     lane_id, lane_config.vllm, lane_config.model, port)

    async def _remove_lane_unlocked(self, lane_id: str) -> None:
        handle = self._handles.pop(lane_id, None)
        if handle is None:
            return
        await handle.destroy()
        await handle.close()
        self._port_alloc.release(lane_id)
        self._active_requests.pop(lane_id, None)
        self._starting_deadlines.pop(lane_id, None)
        self._record_event(lane_id, "stopped")
        logger.info("Lane '%s' removed", lane_id)

    async def _hot_swap_lane_unlocked(
        self, lane_id: str, new_config: LaneConfig,
    ) -> ProcessHandle:
        """
        Hot-swap reconfiguration: spawn new process on a temp port, preload
        the model, then atomically replace the old handle.  If the new
        process fails to come up, the old handle remains untouched (rollback).

        Returns the OLD handle (caller must close it after success).
        """
        old_handle = self._handles[lane_id]
        old_port = self._port_alloc.get_port(lane_id)

        # Allocate a temporary port for the new process
        temp_id = f"_swap_{lane_id}"
        temp_port = self._port_alloc.allocate(temp_id)

        self._record_event(
            lane_id, "hot_swap_start",
            model=new_config.model,
            port=temp_port,
            old_port=old_port,
        )
        logger.info(
            "Hot-swap '%s': new %s process on port %d (old port %d)",
            lane_id, "vllm" if new_config.vllm else "ollama", temp_port, old_port,
        )

        new_handle = _create_handle(lane_id, temp_port, self._global_config, new_config)
        await new_handle.init()

        try:
            await new_handle.spawn(new_config)

            # Verify the new process is healthy
            version = await new_handle.get_version()
            if version is None:
                raise RuntimeError("New process did not respond to version check")

        except Exception as exc:
            # Rollback: destroy new handle, release temp port, keep old handle
            logger.error(
                "Hot-swap '%s' failed during spawn: %s — keeping old process",
                lane_id, exc,
            )
            self._record_event(lane_id, "hot_swap_rollback",
                               model=new_config.model, details=str(exc))
            try:
                await new_handle.destroy()
            except Exception:
                pass
            await new_handle.close()
            self._port_alloc.release(temp_id)
            raise

        # Success: swap handles
        # Stop old process
        try:
            await old_handle.stop()
        except Exception:
            logger.warning("Could not stop old handle for lane '%s'", lane_id, exc_info=True)

        # Update port allocator: release old port, move new port from temp_id to lane_id
        self._port_alloc.release(lane_id)
        self._port_alloc.release(temp_id)
        self._port_alloc._used[lane_id] = temp_port

        # Replace handle in registry
        self._handles[lane_id] = new_handle
        self._starting_deadlines[lane_id] = asyncio.get_running_loop().time() + _HOT_SWAP_TIMEOUT

        self._record_event(
            lane_id, "hot_swap_ok",
            model=new_config.model,
            port=temp_port,
            old_port=old_port,
        )
        logger.info(
            "Hot-swap '%s' complete: now on port %d with num_parallel=%d",
            lane_id, temp_port, new_config.num_parallel,
        )
        return old_handle

    async def _rollback_unlocked(
        self,
        removed_snapshots: dict[str, tuple[ProcessHandle, LaneConfig | None, int]],
        added_ids: list[str],
        swapped_old_handles: dict[str, ProcessHandle],
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

        # 2. Restore hot-swapped lanes: stop new handle, restore old handle
        for lid, old_handle in swapped_old_handles.items():
            new_handle = self._handles.get(lid)
            if new_handle is not None:
                try:
                    await new_handle.destroy()
                    await new_handle.close()
                except Exception:
                    logger.warning("Rollback: failed to stop new handle for '%s'", lid, exc_info=True)
            # Restore old handle — it was stopped but may be restartable
            orig = original_snapshot.get(lid)
            if orig is not None:
                _, orig_lc, orig_port = orig
                if orig_lc is not None and orig_port is not None:
                    try:
                        restored = _create_handle(lid, orig_port, self._global_config, orig_lc)
                        await restored.init()
                        await restored.spawn(orig_lc)
                        self._handles[lid] = restored
                        self._port_alloc._used[lid] = orig_port
                        self._active_requests[lid] = 0
                        self._starting_deadlines[lid] = asyncio.get_running_loop().time() + _HOT_SWAP_TIMEOUT
                        self._record_event(lid, "rollback_restored", model=orig_lc.model, port=orig_port)
                    except Exception:
                        logger.error("Rollback: failed to restore lane '%s'", lid, exc_info=True)
                        self._handles.pop(lid, None)
                        await old_handle.close()

        # 3. Re-add removed lanes that had snapshots
        for lid, (handle, lc, port) in removed_snapshots.items():
            if lid not in self._handles and lc is not None:
                try:
                    restored = _create_handle(lid, port, self._global_config, lc)
                    await restored.init()
                    await restored.spawn(lc)
                    self._handles[lid] = restored
                    self._port_alloc._used[lid] = port
                    self._active_requests[lid] = 0
                    self._starting_deadlines[lid] = asyncio.get_running_loop().time() + _HOT_SWAP_TIMEOUT
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
        return statuses

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
        if status.runtime_state in ("loaded", "running"):
            self._model_profiles.record_loaded_vram(model, vram)
        elif status.runtime_state == "sleeping":
            self._model_profiles.record_sleeping_vram(model, vram)

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
            num_parallel = 0 if lc.vllm else lc.num_parallel
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
