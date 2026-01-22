# src/logos/pipeline/fcfs_scheduler.py
"""
FCFS scheduler implementation that always picks the top-ranked candidate.
"""

import asyncio
import logging
from typing import Optional

from logos.queue.priority_queue import Priority

from .scheduler_interface import SchedulingRequest, SchedulingResult
from .base_scheduler import BaseScheduler


logger = logging.getLogger(__name__)


class FcfScheduler(BaseScheduler):
    """
    First-come-first-serve scheduler that always selects the top-ranked
    classification candidate and queues if that model is busy.

    Uses SDI only for tracking and capacity reservation, not for selection.
    """

    async def schedule(self, request: SchedulingRequest) -> Optional[SchedulingResult]:
        if not request.classified_models:
            return None

        sorted_candidates = sorted(request.classified_models, key=lambda x: x[1], reverse=True)
        target_model_id, weight, priority_int, _ = sorted_candidates[0]
        
        # Find the first deployment matching target_model_id
        deployment = next(
            (d for d in request.deployments if d["model_id"] == target_model_id),
            None
        )
        
        if not deployment:
            logger.warning("No deployment found for model_id=%s", target_model_id)
            return None

        provider_type = deployment["type"]
        provider_id = deployment["provider_id"]
        
        if not provider_type:
            logger.warning("No provider type found for provider_id=%s", provider_id)
            return None

        if provider_type == 'ollama':
            if self._ollama.try_reserve_capacity(target_model_id, provider_id):
                logger.info(
                    "Reserved capacity on Ollama model %s (weight=%.2f)",
                    target_model_id,
                    weight,
                )
                return self._create_result(
                    target_model_id,
                    provider_id,
                    provider_type,
                    priority_int,
                    request.request_id,
                    was_queued=False,
                )
        else:
            return self._create_result(
                target_model_id,
                provider_id,
                provider_type,
                priority_int,
                request.request_id,
                was_queued=False,
            )

        priority = Priority.from_int(priority_int)
        loop = asyncio.get_running_loop()
        future = loop.create_future()

        entry_id = self._queue_mgr.enqueue(future, target_model_id, provider_id, priority)
        logger.info(
            "Request %s queued for model %s (weight=%.2f, depth=%s)",
            request.request_id,
            target_model_id,
            weight,
            self._queue_mgr.get_total_depth_by_deployment(target_model_id, provider_id),
        )

        try:
            timeout = request.timeout_s if request.timeout_s else 300  # Increased to 5 minutes for queue wait
            result = await asyncio.wait_for(future, timeout=timeout)

            if provider_type == 'ollama':
                try:
                    self._ollama.on_request_begin_processing(
                        request.request_id,
                        increment_active=False,
                        provider_id=provider_id,
                    )
                except KeyError:
                    pass

            return result
        except asyncio.TimeoutError:
            self._queue_mgr.remove(entry_id)
            return None
