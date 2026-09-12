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

        priority_str = Priority.from_resolved(priority_int).name.lower()
        is_cold_start = False

        if provider_type == "logosnode":
            priority = Priority.from_resolved(priority_int)
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
        """Called when a request completes: free its capacity, then re-dispatch.

        This used to hand the freed slot straight to the next waiter. That
        treats requests as interchangeable units, and they are not: a 200-token
        request finishing frees a sliver of KV cache, which says nothing about
        whether an 8000-token request waiting behind it will fit. Transferring
        the slot 1:1 over-commits in one direction and under-commits in the
        other, and it bypassed admission entirely — so under load the engine's
        own queue was built here rather than by the gate. Measured on dev, that
        was the dominant source of engine-side queueing: 0.12 average during
        the arrival ramp versus 0.78 while completions were recycling slots.

        Now the capacity is simply released and the queue re-evaluated through
        the normal gate, which reads what the engine can actually take. The
        re-evaluation happens right here, so nothing waits for the next worker
        report to make progress.
        """

        self._check_starvation(model_id, provider_id)

        if provider_type == "logosnode":
            try:
                self._logosnode.on_request_complete(
                    request_id,
                    was_cold_start=False,
                    duration_ms=0,
                    reuse_slot=False,
                    provider_id=provider_id,
                )
                logger.info(
                    "Request %s released model=%s",
                    request_id,
                    self._logosnode.get_model_name(model_id, provider_id) or model_id,
                )
            except KeyError:
                pass

        # Hand the freed capacity to the queue through the gate rather than
        # to one specific waiter. `reevaluate_model_queues` re-checks lane
        # readiness and admission, so a lane that has gone to sleep or filled
        # up simply dispatches nothing and the waiters stay queued.
        model_name = None
        if provider_type == "logosnode":
            try:
                model_name = self._logosnode.get_model_name(model_id, provider_id)
            except Exception:  # noqa: BLE001
                model_name = None
        self.reevaluate_model_queues(model_name or f"model-{model_id}")

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

    def on_worker_report(self, provider_id: int) -> None:
        """A worker's status landed — reconsider anything held against the old one.

        The forwarding gate spends a per-report budget (see
        ``AdmissionDecision``), so a fresh report is what restores it. Without
        this the budget would only be re-tested when something completes, and
        on a ramp from idle nothing has completed yet — the held requests
        would sit in the queue while the lane had room. Measured on dev, a
        report follows a forwarded request within ~0.9s, so this paces the
        ramp rather than stalling it.
        """
        self.reevaluate_model_queues(f"provider-{provider_id}")

    def reevaluate_model_queues(self, model_name: str) -> None:
        """Reevaluate queued requests for a model after state change (load/wake).

        When a provider state changes (e.g. a new lane becomes available),
        dispatches as many queued futures as the gate allows rather than
        drip-feeding one at a time.
        """
        for (model_id, provider_id), ptype in self._model_registry.items():
            if ptype != "logosnode":
                continue

            # Symmetric with the offline-worker gate in
            # `ClassificationCorrectingScheduler._compute_candidate_scores`:
            # `_model_registry` is DB-derived and includes every deployment
            # regardless of session state. Without this check, a queued
            # future could be dispatched onto a worker whose session was
            # popped after enqueue — the pipeline would then crash at
            # execution-context resolution with
            # LogosNodeOfflineError("No active logosnode worker session").
            try:
                if not self._logosnode.is_provider_online(provider_id):
                    continue
            except Exception:
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

            # Bound the batch by what the lane signals justify releasing in
            # one pass. Without this, a wake/load event drains the whole
            # orchestrator queue onto one worker at once — precisely the
            # forwarding we want to avoid, since a request sitting in the
            # engine's own queue can no longer be reordered by priority,
            # re-routed to a peer, or given up when the worker drains.
            batch_limit = self._admission_batch_limit(model_id, provider_id)
            if batch_limit is not None:
                available_slots = min(available_slots, batch_limit)

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

    def _admission_batch_limit(self, model_id: int, provider_id: int) -> int | None:
        """How many queued requests this worker may be handed in one pass.

        Zero when the lane signals say to hold off entirely. None means the
        worker gave no usable signal (older worker, no runtime snapshot yet)
        — callers then fall back to the capacity gate alone, which is the
        pre-existing behaviour.
        """
        try:
            decision = self._logosnode.evaluate_admission(model_id, provider_id)
        except Exception:  # noqa: BLE001 — facade may not know this deployment
            return None
        if not decision.can_admit:
            return 0
        return decision.batch_limit

    def update_model_registry(self, model_registry: Dict[tuple[int, int], str]) -> None:
        self._model_registry = dict(model_registry or {})
