# src/logos/pipeline/utilization_scheduler.py
"""
Utilization-aware scheduler implementation.
"""

import asyncio
import logging
from typing import List, Tuple, Optional

from logos.queue.priority_queue import Priority

from .base_scheduler import BaseScheduler
from .scheduler_interface import SchedulingRequest, SchedulingResult


logger = logging.getLogger(__name__)


class UtilizationAwareScheduler(BaseScheduler):
    """
    Production scheduler that uses SDI data for scheduling decisions.

    Features:
    - Availability-aware selection
    - Async queuing when busy
    - Starvation prevention (priority aging)
    """

    def __init__(
        self,
        queue_manager,
        ollama_facade,
        azure_facade,
        model_registry,
    ):
        super().__init__(queue_manager, ollama_facade, azure_facade, model_registry)

    async def schedule(self, request: SchedulingRequest) -> Optional[SchedulingResult]:
        """
        Select a model from candidates based on weights and availability.

        Logic:
        1.  **Immediate Selection**: Iterates through candidates by weight. If a model is available
            (loaded, not rate-limited), it is selected immediately.
        2.  **Queuing**: If ALL candidates are unavailable, the request is queued against the
            highest-weighted candidate.
        3.  **Async Wait**: The method `await`s until the request is dequeued by a `release()`
            call from another request.
        """
        best_candidate = self._select_best_candidate(request.candidates)

        if best_candidate:
            model_id, provider_type, _, priority_int = best_candidate
            return self._create_result(
                model_id,
                provider_type,
                priority_int,
                request.request_id,
                was_queued=False,
            )

        if not request.candidates:
            return None

        sorted_candidates = sorted(request.candidates, key=lambda x: x[1], reverse=True)
        target_model_id, _, priority_int, _ = sorted_candidates[0]
        provider_type = self._model_registry.get(target_model_id)

        if not provider_type:
            return None

        priority = Priority.from_int(priority_int)

        loop = asyncio.get_running_loop()
        future = loop.create_future()

        entry_id = self._queue_mgr.enqueue(future, target_model_id, priority)
        logger.info(
            "Request %s queued for model %s (weight=%.2f, depth=%s)",
            request.request_id,
            target_model_id,
            sorted_candidates[0][1],
            self._queue_mgr.get_total_depth(target_model_id),
        )

        try:
            timeout = request.timeout_s if request.timeout_s else 300  # Increased to 5 minutes for queue wait
            result = await asyncio.wait_for(future, timeout=timeout)

            if provider_type == 'ollama':
                try:
                    self._ollama.on_request_begin_processing(
                        request.request_id,
                        increment_active=False,
                    )
                except KeyError:
                    pass

            return result
        except asyncio.TimeoutError:
            self._queue_mgr.remove(entry_id)
            return None

    def _select_best_candidate(
        self,
        candidates: List[Tuple[int, float, int, int]]
    ) -> Optional[Tuple[int, str, float, int]]:
        """Find the best immediately available model."""
        scored_candidates = []

        for model_id, weight, priority_int, parallel in candidates:
            provider_type = self._model_registry.get(model_id)
            if not provider_type:
                continue

            availability_score = self._get_availability_score(model_id, provider_type)
            if availability_score is None:
                continue

            total_score = weight + availability_score
            scored_candidates.append((model_id, provider_type, total_score, priority_int))

        if not scored_candidates:
            return None

        scored_candidates.sort(key=lambda x: x[2], reverse=True)

        for model_id, provider_type, score, priority_int in scored_candidates:
            if provider_type == 'ollama':
                if self._ollama.try_reserve_capacity(model_id):
                    logger.info(
                        "Reserved capacity on Ollama model %s (score=%.2f)",
                        model_id,
                        score,
                    )
                    return (model_id, provider_type, score, priority_int)
                logger.debug(
                    "Failed to reserve capacity on Ollama model %s, skipping",
                    model_id,
                )
            elif provider_type == 'azure':
                return (model_id, provider_type, score, priority_int)

        return None

    def _get_availability_score(self, model_id: int, provider_type: str) -> Optional[float]:
        """
        Returns availability bonus score, or None if model is unavailable.

        Scoring:
        - Ollama: +10 if loaded, -5 per queued request
        - Azure: +5 if has capacity, None if rate-limited
        """
        if provider_type == 'ollama':
            try:
                status = self._ollama.get_model_status(model_id)
            except ValueError:
                return None

            if not status.is_loaded:
                return -20

            return 10 - (status.queue_depth * 0.5)

        if provider_type == 'azure':
            try:
                status = self._azure.get_model_status(model_id)
                return 5 if status.is_loaded else None
            except (ValueError, KeyError):
                return None

        return None
