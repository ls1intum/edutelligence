# src/logos/pipeline/base_scheduler.py
"""
Shared scheduler implementation pieces.
"""

import asyncio
import logging
from typing import Dict

from logos.queue.priority_queue import Priority, PriorityQueueManager
from logos.sdi.azure_facade import AzureSchedulingDataFacade
from logos.sdi.logosnode_facade import LogosNodeSchedulingDataFacade

from .scheduler_interface import SchedulerInterface, SchedulingResult

logger = logging.getLogger(__name__)


class BaseScheduler(SchedulerInterface):
    """
    Base scheduler with shared queueing and SDI tracking logic.
    """

    def __init__(
        self,
        queue_manager: PriorityQueueManager,
        logosnode_facade: LogosNodeSchedulingDataFacade,
        azure_facade: AzureSchedulingDataFacade,
        model_registry: Dict[tuple[int, int], str] | None = None,
        on_capacity_needed=None,
    ):
        self._queue_mgr = queue_manager
        self._logosnode = logosnode_facade
        self._azure = azure_facade
        self._model_registry = model_registry or {}
        # Async callback: (provider_id, model_name) -> None
        # Fired when a request is queued for a sleeping/unloaded model
        # so the capacity planner can start waking/loading immediately.
        self._on_capacity_needed = on_capacity_needed
        self._logger = logging.getLogger(__name__)

    def _create_result(
        self,
        model_id: int,
        provider_id: int,
        provider_type: str,
        priority_int: int,
        request_id: str,
        was_queued: bool,
    ) -> SchedulingResult:
        """Helper to create SchedulingResult and update stats."""
        queue_depth = 0
        utilization = 0.0

        priority_str = Priority.from_int(priority_int).name.lower()
        is_cold_start = False

        if provider_type == "logosnode":
            priority = Priority.from_int(priority_int)
            queue_state = self._queue_mgr.get_state(model_id, provider_id)
            queue_depth = queue_state.total
            tracking_started = False

            try:
                status = self._logosnode.get_model_status(model_id, provider_id)
                utilization = float(status.active_requests)
                is_cold_start = not status.is_loaded
            except ValueError:
                utilization = 0.0
                is_cold_start = True

            try:
                self._logosnode.on_request_start(
                    request_id,
                    model_id=model_id,
                    provider_id=provider_id,
                    priority=priority.name.lower(),
                )
                tracking_started = True
            except (KeyError, ValueError) as exc:
                logger.warning(
                    "Skipping logosnode request tracking for model=%s worker=%s request=%s: %s",
                    self._logosnode.get_model_name(model_id, provider_id) or model_id,
                    self._logosnode.get_provider_name(provider_id) or provider_id,
                    request_id,
                    exc,
                )

            if tracking_started and not was_queued:
                try:
                    self._logosnode.on_request_begin_processing(
                        request_id,
                        increment_active=False,
                        provider_id=provider_id,
                    )
                except KeyError:
                    pass

        provider_metrics = {}

        if provider_type == "logosnode":
            try:
                cap = self._logosnode.get_capacity_info(provider_id)
                provider_metrics["available_vram_mb"] = cap.available_vram_mb
            except Exception:
                pass

        elif provider_type == "azure":
            try:
                cap = self._azure.get_model_capacity(model_id, provider_id)
                if cap:
                    provider_metrics["azure_rate_remaining_requests"] = cap.rate_limit_remaining_requests
                    provider_metrics["azure_rate_remaining_tokens"] = cap.rate_limit_remaining_tokens
            except Exception:
                pass

        return SchedulingResult(
            model_id=model_id,
            provider_id=provider_id,
            provider_type=provider_type,
            queue_entry_id=None,
            was_queued=was_queued,
            queue_depth_at_schedule=queue_depth,
            queue_depth_at_arrival=queue_depth,
            utilization_at_arrival=utilization,
            provider_metrics=provider_metrics,
            available_vram_mb=provider_metrics.get("available_vram_mb"),
            azure_rate_remaining_requests=provider_metrics.get("azure_rate_remaining_requests"),
            azure_rate_remaining_tokens=provider_metrics.get("azure_rate_remaining_tokens"),
            priority_when_scheduled=priority_str,
            is_cold_start=is_cold_start,
        )

    def release(self, model_id: int, provider_id: int, provider_type: str, request_id: str) -> None:
        """
        Called when a request completes.
        1. Notify SDI facade.
        2. Check starvation (priority aging).
        3. Wake up next queued request if any.
        """

        self._check_starvation(model_id, provider_id)

        depth_before = self._queue_mgr.get_total_depth_by_deployment(model_id, provider_id)

        next_task = None
        entry = None
        while True:
            next_task, entry = self._queue_mgr.dequeue_with_entry(model_id, provider_id)
            if not next_task:
                break
            if isinstance(next_task, asyncio.Future) and next_task.done():
                continue
            break

        has_waiters = next_task is not None

        # For logosnode: check lane readiness BEFORE deciding reuse_slot.
        # If the lane is sleeping/draining, we must NOT transfer the slot —
        # that would create a phantom active count.  Instead, release the
        # slot properly (reuse_slot=False) and re-enqueue the waiter so it
        # can be served once the model is available again.
        reuse_slot = has_waiters
        if provider_type == "logosnode" and has_waiters:
            try:
                lane_ready = self._logosnode.is_model_lane_ready(model_id, provider_id)
            except Exception:
                lane_ready = True  # optimistic if check fails
            if not lane_ready:
                logger.info(
                    "Request %s released model=%s but lane not ready — " "re-enqueuing waiter instead of slot transfer",
                    request_id,
                    self._logosnode.get_model_name(model_id, provider_id) or model_id,
                )
                reuse_slot = False
                # Put the waiter back in the queue
                if isinstance(next_task, asyncio.Future) and not next_task.done():
                    waiter_priority = entry.current_priority if entry else Priority.NORMAL
                    self._queue_mgr.enqueue(
                        next_task,
                        model_id,
                        provider_id,
                        waiter_priority,
                        is_cold_at_queue=(bool(entry.is_cold_at_queue) if entry else False),
                    )
                next_task = None
                has_waiters = False

        if provider_type == "logosnode":
            try:
                self._logosnode.on_request_complete(
                    request_id,
                    was_cold_start=False,
                    duration_ms=0,
                    reuse_slot=reuse_slot,
                    provider_id=provider_id,
                )
                logger.info(
                    "Request %s released model=%s. Reusing slot? %s",
                    request_id,
                    self._logosnode.get_model_name(model_id, provider_id) or model_id,
                    reuse_slot,
                )
            except KeyError:
                pass

        if next_task and isinstance(next_task, asyncio.Future):
            if not next_task.done():
                priority_str = entry.current_priority.name.lower() if entry else Priority.NORMAL.name.lower()
                entry.current_priority.value if entry else Priority.NORMAL.value

                provider_metrics = {}
                # Trust the cold flag captured at queue entry: by the time
                # we dispatch, the lane is loaded, so a fresh status check
                # would always say "not cold". The flag is what tells us
                # the request actually triggered a cold/wake load.
                is_cold_start = bool(entry.is_cold_at_queue) if entry else None

                if provider_type == "logosnode":

                    try:
                        cap = self._logosnode.get_capacity_info(provider_id)
                        provider_metrics["available_vram_mb"] = cap.available_vram_mb
                    except Exception:
                        pass
                elif provider_type == "azure":
                    try:
                        cap = self._azure.get_model_capacity(model_id, provider_id)
                        if cap:
                            provider_metrics["azure_rate_remaining_requests"] = cap.rate_limit_remaining_requests
                            provider_metrics["azure_rate_remaining_tokens"] = cap.rate_limit_remaining_tokens
                    except Exception:
                        pass

                result = SchedulingResult(
                    model_id=model_id,
                    provider_id=provider_id,
                    provider_type=provider_type,
                    queue_entry_id=None,
                    was_queued=True,
                    queue_depth_at_schedule=depth_before,
                    queue_depth_at_arrival=depth_before,
                    priority_when_scheduled=priority_str,
                    is_cold_start=is_cold_start,
                    provider_metrics=provider_metrics,
                    available_vram_mb=provider_metrics.get("available_vram_mb"),
                    azure_rate_remaining_requests=provider_metrics.get("azure_rate_remaining_requests"),
                    azure_rate_remaining_tokens=provider_metrics.get("azure_rate_remaining_tokens"),
                )

                logger.info(
                    "Waking up queued request for model=%s",
                    self._logosnode.get_model_name(model_id, provider_id) or model_id,
                )
                next_task.get_loop().call_soon_threadsafe(next_task.set_result, result)

    def _check_starvation(self, model_id: int, provider_id: int) -> None:
        # Priority promotion is intentionally disabled: low-priority requests
        # are expected to wait (or starve) when capacity is unavailable.
        pass

    def get_total_queue_depth(self) -> int:
        """Get total queued requests."""
        return self._queue_mgr.get_total_depth_all()

    def update_provider_stats(self, model_id: int, provider_id: int, headers: Dict[str, str]) -> None:
        """
        Update provider-specific statistics (e.g., rate limits) from response headers.
        Currently only Azure uses response headers for rate-limits; logosnode is no-op.
        """
        provider_type = self._model_registry.get((model_id, provider_id))
        if not provider_type:
            return

        if provider_type == "azure":
            try:
                self._azure.update_model_rate_limits(model_id, provider_id, headers)
            except Exception:
                logger.debug(
                    "Failed to update Azure rate limits for model=%s",
                    self._logosnode.get_model_name(model_id, provider_id) or model_id,
                    exc_info=False,
                )

    def reevaluate_model_queues(self, model_name: str) -> None:
        """Reevaluate queued requests for a model after state change (load/wake).

        When a provider state changes (e.g. a new lane becomes available),
        dispatches up to max_capacity queued futures immediately rather than
        drip-feeding one at a time. Results are created with slot_transferred=False
        so _queue_and_wait properly increments the active count.
        """
        for (model_id, provider_id), ptype in self._model_registry.items():
            if ptype != "logosnode":
                continue

            # Use lane readiness as the primary check — it reads the runtime
            # snapshot directly, bypassing the 5s refresh_interval cache in
            # _loaded_models that can be stale right after a cold load confirms.
            try:
                if not self._logosnode.is_model_lane_ready(model_id, provider_id):
                    continue
            except Exception:
                continue

            try:
                status = self._logosnode.get_model_status(model_id, provider_id)
            except (ValueError, KeyError):
                continue

            # Determine how many requests we can dispatch
            try:
                max_capacity, _ = self._logosnode.get_parallel_capacity(model_id, provider_id)
            except (KeyError, Exception):
                max_capacity = 1
            current_active = status.active_requests
            available_slots = max(0, max_capacity - current_active)

            dispatched = 0
            while dispatched < available_slots:
                task, entry = self._queue_mgr.dequeue_with_entry(model_id, provider_id)
                if task is None:
                    break
                if not isinstance(task, asyncio.Future) or task.done():
                    continue

                priority_str = entry.current_priority.name.lower() if entry else Priority.NORMAL.name.lower()
                queue_depth = self._queue_mgr.get_total_depth_by_deployment(model_id, provider_id)

                provider_metrics = {}
                try:
                    cap = self._logosnode.get_capacity_info(provider_id)
                    provider_metrics["available_vram_mb"] = cap.available_vram_mb
                except Exception:
                    pass

                result = SchedulingResult(
                    model_id=model_id,
                    provider_id=provider_id,
                    provider_type="logosnode",
                    queue_entry_id=None,
                    was_queued=True,
                    queue_depth_at_schedule=queue_depth,
                    queue_depth_at_arrival=queue_depth,
                    priority_when_scheduled=priority_str,
                    # Trust the cold flag captured at enqueue time — wakes
                    # from sleep aren't cold even though a state change
                    # triggered the dispatcher.
                    is_cold_start=bool(entry.is_cold_at_queue) if entry else None,
                    provider_metrics=provider_metrics,
                    available_vram_mb=provider_metrics.get("available_vram_mb"),
                    slot_transferred=False,
                )

                logger.info(
                    "Reevaluation: resolving queued request for model=%s "
                    "(worker=%s, dispatched=%d/%d) after state change",
                    model_name,
                    self._logosnode.get_provider_name(provider_id) or provider_id,
                    dispatched + 1,
                    available_slots,
                )
                task.get_loop().call_soon_threadsafe(task.set_result, result)
                dispatched += 1

            if dispatched > 0:
                logger.info(
                    "Reevaluation complete: dispatched %d queued requests for model=%s (worker=%s)",
                    dispatched,
                    model_name,
                    self._logosnode.get_provider_name(provider_id) or provider_id,
                )

    def update_model_registry(self, model_registry: Dict[tuple[int, int], str]) -> None:
        self._model_registry = dict(model_registry or {})
