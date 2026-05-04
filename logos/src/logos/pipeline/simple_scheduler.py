# src/logos/pipeline/simple_scheduler.py
"""
Simple scheduler that trusts vLLM queue signals.

Forward immediately when any worker has queue_waiting == 0.
Queue locally only when every viable worker is itself queueing in vLLM.
"""

import asyncio
import hashlib
import logging
from typing import List, Optional, Tuple

from logos.queue.priority_queue import Priority
from logos.terminal_logging import (
    model_name_cache,
    style_model,
    style_request_id,
    MAGENTA,
    YELLOW,
    paint,
)

from .base_scheduler import BaseScheduler
from .scheduler_interface import SchedulingRequest, SchedulingResult, QueueTimeoutError
from .ettft_estimator import (
    ReadinessTier,
    ReadinessSignal,
    classify_local,
    classify_azure,
    classify_peer,
)

logger = logging.getLogger(__name__)

# Tier preference order for queuing (best to worst among non-READY candidates)
_TIER_QUEUE_PREFERENCE = [
    ReadinessTier.QUEUEING,
    ReadinessTier.SLEEPING,
    ReadinessTier.COLD,
]

# Prefix-cache affinity: how much of a load discount the affinity-preferred
# deployment receives in the load tiebreak. Tuned to be "slight" — keeps a
# caller pinned to the same provider when load differs by ≤ 1 active request,
# but still spreads to alternatives once the preferred one gets noticeably
# busier. Issue #530.
_AFFINITY_LOAD_DISCOUNT = 1.0


def _affinity_score(affinity_key: str, model_id: int, provider_id: int) -> int:
    """Stable cross-process hash for rendezvous-style affinity scoring.

    Python's built-in `hash()` is salted per process, so we use blake2b for a
    deterministic value that stays consistent across replicas.
    """
    digest = hashlib.blake2b(
        f"{affinity_key}|{model_id}|{provider_id}".encode("utf-8"),
        digest_size=8,
    ).digest()
    return int.from_bytes(digest, "big")


def _preferred_provider_id(
    affinity_key: str,
    model_id: int,
    candidates_for_model: List[tuple],
) -> Optional[int]:
    """Return the provider_id with the highest affinity score for this caller+model."""
    if not candidates_for_model:
        return None
    best = max(
        candidates_for_model,
        key=lambda c: _affinity_score(affinity_key, model_id, c[1]),
    )
    return best[1]


class SimpleScheduler(BaseScheduler):
    """
    Scheduler that forwards immediately when vLLM has free capacity.

    Schedule logic:
    1. For each classified candidate, gather all (model_id, provider_id) pairs.
    2. Classify each (model_id, provider_id) via classify_local / classify_azure.
    3. Among READY candidates: pick highest classification weight, tiebreak on
       lowest requests_running. Forward immediately (no capacity check, no counter).
    4. If no READY: queue locally on the highest-weight QUEUEING/SLEEPING/COLD
       candidate. Await the future.
    5. On wake (release or snapshot reevaluation): the simple_scheduler re-classifies
       all candidates; the result already carries provider_id from base_scheduler.
    """

    async def schedule(self, request: SchedulingRequest) -> Optional[SchedulingResult]:
        scored = self._score_candidates(
            request.classified_models or [],
            request.deployments,
        )

        # Try to find a READY candidate
        ready = [c for c in scored if c[3] == ReadinessTier.READY]
        if ready:
            # Best weight, tiebreak on lowest requests_running, with a slight
            # prefix-cache affinity discount so repeat callers stick to the
            # same provider when load is comparable. (Issue #530.)
            best = sorted(
                ready,
                key=lambda c: (-c[2], self._adjusted_load(c, ready, request.affinity_key)),
            )[0]
            model_id, provider_id, weight, tier, priority_int, _requests_running, _signal = best
            provider_name = self._logosnode.get_provider_name(provider_id) or str(provider_id)
            logger.info(
                "%s accepted -> %s (provider=%s score=%.2f tier=%s)",
                style_request_id(request.request_id),
                style_model(model_name_cache.get(model_id)),
                provider_name,
                weight,
                paint(tier.value, MAGENTA),
            )
            actual_type = self._get_provider_type(model_id, provider_id, request.deployments)
            return self._create_result(
                model_id,
                provider_id,
                actual_type if actual_type == "logos_peer" else (
                    "logosnode" if tier != ReadinessTier.UNAVAILABLE else actual_type
                ),
                priority_int,
                request.request_id,
                was_queued=False,
            )

        # No READY candidates — queue on best available
        if not scored:
            return None

        # Filter out UNAVAILABLE
        viable = [c for c in scored if c[3] != ReadinessTier.UNAVAILABLE]
        if not viable:
            return None

        # Pick best by tier preference, then by weight
        def _queue_rank(c):
            tier = c[3]
            try:
                tier_order = _TIER_QUEUE_PREFERENCE.index(tier)
            except ValueError:
                tier_order = len(_TIER_QUEUE_PREFERENCE)
            return (tier_order, -c[2])  # lower tier_order = better; higher weight = better

        best_viable = sorted(viable, key=_queue_rank)[0]

        return await self._queue_and_wait(best_viable, request)

    def _score_candidates(
        self,
        candidates: list,
        deployments: list,
    ) -> list:
        """Build scored list with readiness annotations.

        Returns list of:
            (model_id, provider_id, weight, tier, priority_int, requests_running, signal)
        """
        scored = []
        for model_id, weight, priority_int, _parallel in candidates:
            # Find all (model_id, provider_id) deployments for this model
            model_deployments = [d for d in deployments if d["model_id"] == model_id]
            if not model_deployments:
                continue

            for deployment in model_deployments:
                provider_id = deployment["provider_id"]
                provider_type = deployment["type"]

                signal, requests_running = self._classify_candidate(
                    model_id, provider_id, provider_type
                )

                if signal.tier == ReadinessTier.UNAVAILABLE:
                    logger.debug(
                        "Model %s provider %s unavailable: %s",
                        model_id, provider_id, signal.reasoning,
                    )
                    continue

                scored.append((model_id, provider_id, weight, signal.tier, priority_int, requests_running, signal))

        # Sort by weight descending for consistent ordering
        scored.sort(key=lambda c: -c[2])
        return scored

    def _classify_candidate(
        self,
        model_id: int,
        provider_id: int,
        provider_type: str,
    ) -> Tuple[ReadinessSignal, float]:
        """Return (ReadinessSignal, requests_running) for one (model, provider) pair."""
        if provider_type == "logosnode":
            try:
                view = self._logosnode.get_model_scheduler_view(model_id, provider_id)
            except Exception:  # noqa: BLE001
                view = None
            if view is None:
                # No snapshot yet — treat as COLD (capacity planner will load it)
                return ReadinessSignal(
                    tier=ReadinessTier.COLD,
                    reasoning=f"No snapshot for logosnode model {model_id} provider {provider_id}",
                ), 0.0
            requests_running = sum(s.requests_running for s in view.lanes)
            return classify_local(view), requests_running

        if provider_type == "azure":
            try:
                capacity = self._azure.get_model_capacity(model_id, provider_id)
            except (ValueError, KeyError):
                capacity = None
            return classify_azure(capacity), 0.0

        if provider_type == "logos_peer":
            capacity = None
            if self._peer is not None:
                try:
                    capacity = self._peer.get_model_capacity(model_id, provider_id)
                except (ValueError, KeyError):
                    capacity = None
            # Use the peer's reported queue_depth as the requests_running tiebreak
            # so the scheduler prefers a less-loaded local deployment when both
            # local and peer are READY.
            requests_running = float(capacity.queue_depth) if capacity else 0.0
            return classify_peer(capacity), requests_running

        return ReadinessSignal(
            tier=ReadinessTier.UNAVAILABLE,
            reasoning=f"Unknown provider type: {provider_type}",
        ), 0.0

    def _adjusted_load(
        self,
        candidate: tuple,
        ready: list,
        affinity_key: Optional[str],
    ) -> float:
        """Apply prefix-cache affinity discount to the load tiebreak.

        Picks one preferred provider per (caller, model) via rendezvous
        hashing and gives it a `_AFFINITY_LOAD_DISCOUNT`-sized head start in
        the load-based tiebreak.
        """
        model_id, provider_id, _, _, _, requests_running, _ = candidate
        if not affinity_key:
            return float(requests_running)
        same_model = [c for c in ready if c[0] == model_id]
        if len(same_model) <= 1:
            return float(requests_running)
        preferred_id = _preferred_provider_id(affinity_key, model_id, same_model)
        if preferred_id is not None and preferred_id == provider_id:
            return float(requests_running) - _AFFINITY_LOAD_DISCOUNT
        return float(requests_running)

    def _get_provider_type(self, model_id: int, provider_id: int, deployments: list) -> str:
        for d in deployments:
            if d["model_id"] == model_id and d["provider_id"] == provider_id:
                return d.get("type", "logosnode")
        return "logosnode"

    async def _queue_and_wait(
        self, best_scored: tuple, request: SchedulingRequest
    ) -> Optional[SchedulingResult]:
        """Queue on the best-scored candidate and wait for release or reevaluation."""
        model_id, provider_id, weight, tier, priority_int, _requests_running, _signal = best_scored
        priority = Priority.from_int(priority_int)

        loop = asyncio.get_running_loop()
        future = loop.create_future()

        entry_id = self._queue_mgr.enqueue(future, model_id, priority)
        provider_name = self._logosnode.get_provider_name(provider_id) or str(provider_id)
        logger.info(
            "%s %s -> %s (provider=%s weight=%.2f tier=%s depth=%s)",
            paint("queued", YELLOW),
            style_request_id(request.request_id),
            style_model(model_name_cache.get(model_id)),
            provider_name,
            weight,
            paint(tier.value, MAGENTA),
            self._queue_mgr.get_total_depth_by_model(model_id),
        )

        try:
            timeout = request.timeout_s if request.timeout_s else 300
            result = await asyncio.wait_for(future, timeout=timeout)

            provider_type = self._get_provider_type(model_id, result.provider_id, request.deployments)
            if provider_type == "logosnode":
                try:
                    if result.was_queued:
                        self._logosnode.on_request_start(
                            request.request_id,
                            model_id=result.model_id,
                            provider_id=result.provider_id,
                            priority=priority.name.lower(),
                        )
                    self._logosnode.on_request_begin_processing(
                        request.request_id,
                        increment_active=False,
                        provider_id=result.provider_id,
                    )
                except KeyError:
                    pass

            return result
        except asyncio.TimeoutError as exc:
            self._queue_mgr.remove(entry_id)
            raise QueueTimeoutError(
                request_id=request.request_id,
                model_id=model_id,
                provider_id=provider_id,
                timeout_s=float(timeout),
            ) from exc
