# src/logos/pipeline/base_scheduler.py
"""
Shared scheduler implementation pieces.
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict

from logos.queue.priority_queue import PriorityQueueManager, Priority
from logos.sdi.ollama_facade import OllamaSchedulingDataFacade
from logos.sdi.azure_facade import AzureSchedulingDataFacade

from .scheduler_interface import SchedulerInterface, SchedulingResult


logger = logging.getLogger(__name__)


class BaseScheduler(SchedulerInterface):
    """
    Base scheduler with shared queueing and SDI tracking logic.
    """

    def __init__(
        self,
        queue_manager: PriorityQueueManager,
        ollama_facade: OllamaSchedulingDataFacade,
        azure_facade: AzureSchedulingDataFacade,
        model_registry: Dict[int, str],  # model_id -> provider_type
    ):
        self._queue_mgr = queue_manager
        self._ollama = ollama_facade
        self._azure = azure_facade
        self._model_registry = model_registry
        self._logger = logging.getLogger(__name__)

    def _create_result(
        self,
        model_id: int,
        provider_type: str,
        priority_int: int,
        request_id: str,
        was_queued: bool
    ) -> SchedulingResult:
        """Helper to create SchedulingResult and update stats."""
        queue_depth = 0
        utilization = 0.0

        priority_str = Priority.from_int(priority_int).name.lower()
        is_cold_start = False

        if provider_type == 'ollama':
            priority = Priority.from_int(priority_int)
            queue_state = self._queue_mgr.get_state(model_id)
            queue_depth = queue_state.total

            try:
                status = self._ollama.get_model_status(model_id)
                utilization = float(status.active_requests)
                is_cold_start = not status.is_loaded
            except ValueError:
                utilization = 0.0
                is_cold_start = True

            self._ollama.on_request_start(
                request_id,
                model_id=model_id,
                priority=priority.name.lower(),
            )

            if not was_queued:
                try:
                    self._ollama.on_request_begin_processing(
                        request_id,
                        increment_active=False,
                    )
                except KeyError:
                    pass

        provider_metrics = {}

        if provider_type == 'ollama':
            try:
                cap = self._ollama.get_capacity_info(
                    self._ollama._model_to_provider.get(model_id)
                )
                provider_metrics['available_vram_mb'] = cap.available_vram_mb
            except Exception:
                pass

        elif provider_type == 'azure':
            try:
                cap = self._azure.get_model_capacity(model_id)
                if cap:
                    provider_metrics['azure_rate_remaining_requests'] = cap.rate_limit_remaining_requests
                    provider_metrics['azure_rate_remaining_tokens'] = cap.rate_limit_remaining_tokens
            except Exception:
                pass

        return SchedulingResult(
            model_id=model_id,
            provider_type=provider_type,
            queue_entry_id=None,
            was_queued=was_queued,
            queue_depth_at_schedule=queue_depth,
            queue_depth_at_arrival=queue_depth,
            utilization_at_arrival=utilization,
            provider_metrics=provider_metrics,
            available_vram_mb=provider_metrics.get('available_vram_mb'),
            azure_rate_remaining_requests=provider_metrics.get('azure_rate_remaining_requests'),
            azure_rate_remaining_tokens=provider_metrics.get('azure_rate_remaining_tokens'),
            priority_when_scheduled=priority_str,
            is_cold_start=is_cold_start,
        )

    def release(self, model_id: int, request_id: str) -> None:
        """
        Called when a request completes.
        1. Notify SDI facade.
        2. Check starvation (priority aging).
        3. Wake up next queued request if any.
        """
        provider_type = self._model_registry.get(model_id)

        self._check_starvation(model_id)

        has_waiters = (self._queue_mgr.get_total_depth(model_id) > 0)

        if provider_type == 'ollama':
            try:
                self._ollama.on_request_complete(
                    request_id,
                    was_cold_start=False,
                    duration_ms=0,
                    reuse_slot=has_waiters,
                )
                logger.info(
                    "Request %s released model %s. Reusing slot? %s",
                    request_id,
                    model_id,
                    has_waiters,
                )
            except KeyError:
                pass

        next_task = self._queue_mgr.dequeue(model_id)
        if next_task and isinstance(next_task, asyncio.Future):
            if not next_task.done():
                result = SchedulingResult(
                    model_id=model_id,
                    provider_type=provider_type,
                    queue_entry_id=None,
                    was_queued=True,
                    queue_depth_at_schedule=self._queue_mgr.get_total_depth(model_id),
                )

                logger.info("Waking up queued request for model %s", model_id)
                next_task.get_loop().call_soon_threadsafe(next_task.set_result, result)

    def _check_starvation(self, model_id: int) -> None:
        """
        Check for starved requests and bump their priority.
        Rule: If waiting > 10s in LOW, move to NORMAL.
              If waiting > 30s in NORMAL, move to HIGH.
        """
        now = datetime.now()

        low_entries = self._queue_mgr.get_entries_for_priority(model_id, Priority.LOW)
        for entry in low_entries:
            if (now - entry.enqueue_time).total_seconds() > 10:
                self._queue_mgr.move_priority(entry.entry_id, Priority.NORMAL)

            if (now - entry.enqueue_time).total_seconds() > 30:
                self._queue_mgr.move_priority(entry.entry_id, Priority.HIGH)

    def get_total_queue_depth(self) -> int:
        """Get total queued requests."""
        total = 0
        for model_id in self._model_registry.keys():
            total += self._queue_mgr.get_total_depth(model_id)
        return total

    def update_provider_stats(self, model_id: int, headers: Dict[str, str]) -> None:
        """
        Update provider statistics (e.g. rate limits) from response headers.
        """
        provider_type = self._model_registry.get(model_id)
        if provider_type == 'azure':
            self._azure.update_model_rate_limits(model_id, headers)
