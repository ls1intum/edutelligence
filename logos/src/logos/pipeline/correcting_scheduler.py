# src/logos/pipeline/correcting_scheduler.py
"""
Classification-correcting scheduler that re-ranks candidates using ETTFT penalties.

corrected_score = classification_weight - latency_penalty(ETTFT)

Invariant: never promotes models not in the classification candidate list.
"""

import asyncio
import logging
from typing import List, Tuple, Optional

from logos.queue.priority_queue import Priority

from .base_scheduler import BaseScheduler
from .scheduler_interface import SchedulingRequest, SchedulingResult, QueueTimeoutError
from .ettft_estimator import (
    EttftEstimate,
    ReadinessTier,
    TIER_THRESHOLDS,
    _DEFAULT_COLD_MS,
    estimate_ettft_local,
    estimate_ettft_azure,
    compute_corrected_score,
)

logger = logging.getLogger(__name__)


class ClassificationCorrectingScheduler(BaseScheduler):
    """
    Re-ranks classification candidates using ETTFT penalties.

    When ettft_enabled=True (default): corrected_score = weight - penalty(ETTFT)
    When ettft_enabled=False: corrected_score = weight (pure classification ordering)

    This enables ablation for thesis evaluation.
    """

    def __init__(
        self,
        queue_manager,
        logosnode_facade,
        azure_facade,
        model_registry=None,
        ettft_enabled: bool = True,
    ):
        super().__init__(queue_manager, logosnode_facade, azure_facade, model_registry)
        self._ettft_enabled = ettft_enabled

    async def schedule(self, request: SchedulingRequest) -> Optional[SchedulingResult]:
        """
        Select a model from candidates based on ETTFT-corrected scores.

        1. For each candidate, get ModelSchedulerView (logosnode) or AzureCapacity (azure)
        2. Compute EttftEstimate
        3. Compute corrected_score = weight - penalty (or raw weight if ettft_enabled=False)
        4. Sort by corrected_score descending
        5. Try try_reserve_capacity on each logosnode candidate in order
        6. Azure candidates: accept if not UNAVAILABLE
        7. If none immediately available: queue on highest corrected_score candidate
        """
        scored = self._compute_candidate_scores(
            request.classified_models or [],
            request.deployments,
        )

        # Try immediate selection
        best = self._try_immediate_select(scored, request.request_id)
        if best is not None:
            model_id, provider_id, provider_type, score, priority_int, ettft = best
            result = self._create_result(
                model_id, provider_id, provider_type,
                priority_int, request.request_id, was_queued=False,
            )
            result.ettft_estimate_ms = ettft.ettft_ms
            result.ettft_tier = ettft.tier.value
            return result

        # No immediate candidate — queue on the best scored one
        if not scored:
            return None

        return await self._queue_and_wait(scored[0], request)

    def _compute_candidate_scores(
        self,
        candidates: List[Tuple[int, float, int, int]],
        deployments: list,
    ) -> list:
        """Build scored list with ETTFT annotations.

        Returns list of (model_id, provider_id, provider_type, corrected_score, priority_int, ettft)
        sorted by corrected_score descending.
        """
        scored = []
        for model_id, weight, priority_int, parallel in candidates:
            deployment = next((d for d in deployments if d["model_id"] == model_id), None)
            if not deployment:
                continue

            provider_type = deployment["type"]
            provider_id = deployment["provider_id"]

            ettft = self._estimate_ettft(model_id, provider_id, provider_type)

            if ettft.tier == ReadinessTier.UNAVAILABLE:
                logger.debug(
                    "Model %s unavailable: %s", model_id, ettft.reasoning,
                )
                continue

            penalty = ettft.penalty if self._ettft_enabled else 0.0
            corrected = compute_corrected_score(weight, penalty)

            scored.append((model_id, provider_id, provider_type, corrected, priority_int, ettft))

        scored.sort(key=lambda x: x[3], reverse=True)

        if scored and self._ettft_enabled:
            logger.info(
                "ETTFT ranking: %s",
                ", ".join(
                    f"model={m} score={s:.2f} tier={e.tier.value} ettft={e.ettft_ms:.0f}ms"
                    for m, _, _, s, _, e in scored[:5]
                ),
            )

        return scored

    def _estimate_ettft(self, model_id: int, provider_id: int, provider_type: str) -> EttftEstimate:
        """Get ETTFT estimate for a model using the appropriate provider facade."""
        if provider_type == "logosnode":
            try:
                view = self._logosnode.get_model_scheduler_view(model_id, provider_id)
            except (KeyError, Exception):
                view = None
            if view is None:
                # No lanes visible — treat as COLD (capacity planner can cold-load
                # during context resolution) rather than UNAVAILABLE
                return EttftEstimate(
                    ettft_ms=_DEFAULT_COLD_MS,
                    tier=ReadinessTier.COLD,
                    penalty=TIER_THRESHOLDS[ReadinessTier.COLD]["penalty"],
                    reasoning=f"No lanes for logosnode model {model_id}, cold-load required",
                )
            return estimate_ettft_local(view)

        if provider_type == "azure":
            try:
                capacity = self._azure.get_model_capacity(model_id, provider_id)
            except (ValueError, KeyError):
                capacity = None
            return estimate_ettft_azure(capacity)

        return EttftEstimate(
            ettft_ms=float("inf"),
            tier=ReadinessTier.UNAVAILABLE,
            penalty=float("inf"),
            reasoning=f"Unknown provider type: {provider_type}",
        )

    def _try_immediate_select(self, scored: list, request_id: str):
        """Try to reserve capacity on the best available candidate.

        Returns the winning tuple or None if no candidate can be reserved immediately.
        """
        for model_id, provider_id, provider_type, score, priority_int, ettft in scored:
            if provider_type == "logosnode":
                try:
                    reserved = self._logosnode.try_reserve_capacity(model_id, provider_id, request_id)
                except (KeyError, Exception):
                    logger.debug("Provider %s unavailable for model %s, skipping", provider_id, model_id)
                    continue
                if reserved:
                    logger.info(
                        "Reserved logosnode model %s (score=%.2f, tier=%s, ettft=%.0fms)",
                        model_id, score, ettft.tier.value, ettft.ettft_ms,
                    )
                    return (model_id, provider_id, provider_type, score, priority_int, ettft)
                logger.debug("Failed to reserve logosnode model %s, trying next", model_id)
            elif provider_type == "azure":
                logger.info(
                    "Selected Azure model %s (score=%.2f, tier=%s, ettft=%.0fms)",
                    model_id, score, ettft.tier.value, ettft.ettft_ms,
                )
                return (model_id, provider_id, provider_type, score, priority_int, ettft)

        return None

    async def _queue_and_wait(self, best_scored: tuple, request: SchedulingRequest) -> Optional[SchedulingResult]:
        """Queue on the best-scored candidate and wait for release."""
        model_id, provider_id, provider_type, score, priority_int, ettft = best_scored
        priority = Priority.from_int(priority_int)

        loop = asyncio.get_running_loop()
        future = loop.create_future()

        entry_id = self._queue_mgr.enqueue(future, model_id, provider_id, priority)
        logger.info(
            "Request %s queued for model %s (corrected_score=%.2f, tier=%s, depth=%s)",
            request.request_id, model_id, score, ettft.tier.value,
            self._queue_mgr.get_total_depth_by_deployment(model_id, provider_id),
        )

        try:
            timeout = request.timeout_s if request.timeout_s else 300
            result = await asyncio.wait_for(future, timeout=timeout)

            # Attach ETTFT info to the dequeued result
            result.ettft_estimate_ms = ettft.ettft_ms
            result.ettft_tier = ettft.tier.value

            if provider_type == "logosnode":
                try:
                    if result.was_queued:
                        self._logosnode.on_request_start(
                            request.request_id,
                            model_id=result.model_id,
                            provider_id=provider_id,
                            priority=priority.name.lower(),
                        )
                    self._logosnode.on_request_begin_processing(
                        request.request_id,
                        increment_active=False,
                        provider_id=provider_id,
                    )
                except KeyError:
                    pass

            return result
        except asyncio.TimeoutError:
            self._queue_mgr.remove(entry_id)
            raise QueueTimeoutError(
                request_id=request.request_id,
                model_id=model_id,
                provider_id=provider_id,
                timeout_s=timeout,
            )
        except asyncio.CancelledError:
            self._queue_mgr.remove(entry_id)
            raise
