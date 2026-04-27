# src/logos/pipeline/correcting_scheduler.py
"""
Classification-correcting scheduler that re-ranks candidates using ETTFT penalties.

corrected_score = classification_weight - range_scaled_penalty(expected_wait)

Invariant: never promotes models not in the classification candidate list.
Multi-provider: expands all deployments per model_id so the same model on
logosnode + Azure (or two logosnode providers) produces separate scored candidates.
"""

import asyncio
import json
import logging
import os
import time
from typing import List, Tuple, Optional

from logos.queue.priority_queue import Priority

from .base_scheduler import BaseScheduler
from .scheduler_interface import SchedulingRequest, SchedulingResult, QueueTimeoutError
from .ettft_estimator import (
    EttftEstimate,
    ReadinessTier,
    OVERHEAD_COLD_S,
    DEFAULT_GENERATION_TIME_S,
    estimate_ettft_local,
    estimate_ettft_azure,
    compute_corrected_score,
    compute_weight_span,
)

logger = logging.getLogger(__name__)


class ClassificationCorrectingScheduler(BaseScheduler):
    """
    Re-ranks classification candidates using range-scaled ETTFT penalties.

    When ettft_enabled=True (default):
        corrected = weight - (wait/horizon × span × strength)
    When ettft_enabled=False:
        corrected = weight (pure classification ordering, ablation baseline)
    """

    def __init__(
        self,
        queue_manager,
        logosnode_facade,
        azure_facade,
        model_registry=None,
        ettft_enabled: bool = True,
        on_capacity_needed=None,
    ):
        super().__init__(queue_manager, logosnode_facade, azure_facade, model_registry, on_capacity_needed)
        self._ettft_enabled = ettft_enabled

        # Decision logging (JSON-lines): set ECCS_DECISION_LOG=/path/to/log.jsonl
        self._decision_log_path = os.environ.get("ECCS_DECISION_LOG")

        # Weight override for ablation benchmarks: ECCS_WEIGHT_OVERRIDE={"model_id": weight}
        self._weight_overrides: dict[int, float] = {}
        _override_raw = os.environ.get("ECCS_WEIGHT_OVERRIDE")
        if _override_raw:
            try:
                parsed = json.loads(_override_raw)
                self._weight_overrides = {int(k): float(v) for k, v in parsed.items()}
                logger.info("ECCS weight overrides: %s", self._weight_overrides)
            except (json.JSONDecodeError, ValueError, TypeError):
                logger.warning("Invalid ECCS_WEIGHT_OVERRIDE, ignoring: %s", _override_raw)

    def _log_decision(
        self,
        request_id: str,
        scored: list,
        original_candidates: list,
        selected: Optional[tuple],
        was_queued: bool,
    ) -> None:
        """Write one JSON-lines entry per scheduling decision (if ECCS_DECISION_LOG is set)."""
        if not self._decision_log_path:
            return

        cls_weights = {mid: w for mid, w, _, _ in original_candidates}
        cls_top = max(original_candidates, key=lambda x: x[1])[0] if original_candidates else None

        candidates_log = []
        for model_id, provider_id, provider_type, corrected, _prio, ettft in scored:
            cls_w = cls_weights.get(model_id, 0.0)
            eff_w = self._weight_overrides.get(model_id, cls_w) if self._weight_overrides else cls_w
            candidates_log.append({
                "model_id": model_id,
                "provider_id": provider_id,
                "provider_type": provider_type,
                "classification_weight": round(cls_w, 4),
                "effective_weight": round(eff_w, 4),
                "corrected_score": round(corrected, 4),
                "tier": ettft.tier.value,
                "expected_wait_s": round(ettft.expected_wait_s, 2),
            })

        sel_model = selected[0] if selected else None
        sel_provider = selected[1] if selected else None

        record = {
            "ts": time.time(),
            "request_id": request_id,
            "ettft_enabled": self._ettft_enabled,
            "weight_overrides_active": bool(self._weight_overrides),
            "candidates": candidates_log,
            "selected_model_id": sel_model,
            "selected_provider_id": sel_provider,
            "classification_top_model_id": cls_top,
            "correction_changed": sel_model is not None and sel_model != cls_top,
            "was_queued": was_queued,
        }

        try:
            with open(self._decision_log_path, "a") as f:
                f.write(json.dumps(record, separators=(",", ":")) + "\n")
        except OSError:
            logger.debug("Failed to write ECCS decision log", exc_info=True)

    async def schedule(self, request: SchedulingRequest) -> Optional[SchedulingResult]:
        """
        Select a model from candidates based on ETTFT-corrected scores.

        1. For each candidate × each deployment, compute EttftEstimate
        2. Compute corrected_score using range-scaled penalty
        3. Sort by corrected_score descending
        4. Try try_reserve_capacity on each logosnode candidate in order
        5. Azure candidates: accept if not UNAVAILABLE
        6. If none immediately available: queue on best logosnode candidate
        """
        scored = self._compute_candidate_scores(
            request.classified_models or [],
            request.deployments,
        )

        # Try immediate selection
        best = self._try_immediate_select(scored, request.request_id)
        if best is not None:
            model_id, provider_id, provider_type, score, priority_int, ettft = best
            self._log_decision(request.request_id, scored, request.classified_models or [], best, False)
            result = self._create_result(
                model_id, provider_id, provider_type,
                priority_int, request.request_id, was_queued=False,
            )
            result.ettft_estimate_ms = ettft.ettft_ms
            result.ettft_tier = ettft.tier.value
            return result

        # No immediate candidate — queue on the best logosnode candidate.
        # Cloud providers don't queue (accept or reject immediately).
        if not scored:
            self._log_decision(request.request_id, [], request.classified_models or [], None, False)
            return None

        logosnode_candidate = next((s for s in scored if s[2] == "logosnode"), None)
        if logosnode_candidate is None:
            self._log_decision(request.request_id, scored, request.classified_models or [], None, False)
            return None  # All cloud, none accepted → caller returns 503

        self._log_decision(request.request_id, scored, request.classified_models or [], logosnode_candidate, True)
        return await self._queue_and_wait(logosnode_candidate, request)

    def _compute_candidate_scores(
        self,
        candidates: List[Tuple[int, float, int, int]],
        deployments: list,
    ) -> list:
        """Build scored list with ETTFT annotations.

        Expands each (model_id, weight) across ALL matching deployments,
        producing one scored entry per (model_id, provider_id) pair.

        Returns list of (model_id, provider_id, provider_type,
                         corrected_score, priority_int, ettft)
        sorted by corrected_score descending.
        """
        scored = []
        unavailable_fallbacks = []

        # Apply weight overrides for controlled ablation experiments
        if self._weight_overrides:
            candidates = [
                (mid, self._weight_overrides.get(mid, w), pint, par)
                for mid, w, pint, par in candidates
            ]

        # Compute weight span across all (possibly overridden) weights
        all_weights = [weight for _, weight, _, _ in candidates]
        weight_span = compute_weight_span(all_weights)

        for model_id, weight, priority_int, parallel in candidates:
            # Multi-provider expansion: find ALL deployments for this model
            matching_deployments = [d for d in deployments if d["model_id"] == model_id]
            if not matching_deployments:
                continue

            for deployment in matching_deployments:
                provider_type = deployment["type"]
                provider_id = deployment["provider_id"]

                ettft = self._estimate_ettft(model_id, provider_id, provider_type)

                if ettft.tier == ReadinessTier.UNAVAILABLE:
                    logger.debug(
                        "Model %s provider %s unavailable: %s",
                        model_id, provider_id, ettft.reasoning,
                    )
                    # Only logosnode gets fallback queueing — model may be
                    # transitioning (sleep→wake) and will become available.
                    # Cloud unavailable means truly rate-limited → skip.
                    if provider_type == "logosnode":
                        fallback_ettft = EttftEstimate(
                            expected_wait_s=OVERHEAD_COLD_S,
                            tier=ReadinessTier.COLD,
                            reasoning=f"Fallback: {ettft.reasoning} — queueing as cold",
                            state_overhead_s=OVERHEAD_COLD_S,
                        )
                        corrected = compute_corrected_score(
                            weight,
                            fallback_ettft.expected_wait_s if self._ettft_enabled else 0.0,
                            weight_span,
                        )
                        unavailable_fallbacks.append(
                            (model_id, provider_id, provider_type, corrected, priority_int, fallback_ettft)
                        )
                    continue

                corrected = compute_corrected_score(
                    weight,
                    ettft.expected_wait_s if self._ettft_enabled else 0.0,
                    weight_span,
                )

                scored.append((model_id, provider_id, provider_type, corrected, priority_int, ettft))

        scored.sort(key=lambda x: x[3], reverse=True)

        # If all candidates were UNAVAILABLE, use logosnode fallbacks so we
        # queue instead of returning 503.
        if not scored and unavailable_fallbacks:
            unavailable_fallbacks.sort(key=lambda x: x[3], reverse=True)
            scored = unavailable_fallbacks
            logger.info(
                "All candidates unavailable — using %d fallback(s) for queueing",
                len(scored),
            )

        if scored and self._ettft_enabled:
            logger.info(
                "ETTFT ranking: %s",
                ", ".join(
                    f"model={m} provider={p} score={s:.2f} "
                    f"tier={e.tier.value} wait={e.expected_wait_s:.1f}s"
                    for m, p, _, s, _, e in scored[:5]
                ),
            )

        return scored

    def _estimate_ettft(self, model_id: int, provider_id: int, provider_type: str) -> EttftEstimate:
        """Get ETTFT estimate for a model using the appropriate provider facade."""
        if provider_type == "logosnode":
            try:
                view = self._logosnode.get_model_scheduler_view(model_id, provider_id)
            except KeyError:
                view = None
            except Exception:
                logger.warning(
                    "Unexpected error getting scheduler view for model %s provider %s",
                    model_id, provider_id, exc_info=True,
                )
                view = None

            if view is None:
                # No lanes visible — treat as COLD (capacity planner can
                # cold-load during context resolution)
                return EttftEstimate(
                    expected_wait_s=OVERHEAD_COLD_S,
                    tier=ReadinessTier.COLD,
                    reasoning=f"No lanes for logosnode model {model_id}, cold-load required",
                    state_overhead_s=OVERHEAD_COLD_S,
                )

            # Gather infrastructure data for VRAM-aware estimation
            effective_parallel = 1
            try:
                effective_parallel, _ = self._logosnode.get_parallel_capacity(model_id, provider_id)
            except (KeyError, Exception):
                pass

            available_vram_mb = float("inf")
            try:
                cap = self._logosnode.get_capacity_info(provider_id)
                available_vram_mb = float(cap.available_vram_mb)
            except (KeyError, Exception):
                pass

            model_vram_mb = 0.0
            kv_budget_mb = 0.0
            try:
                model_name = self._logosnode.get_model_name(model_id, provider_id)
                if model_name:
                    profiles = self._logosnode.get_model_profiles(provider_id)
                    if model_name in profiles:
                        profile = profiles[model_name]
                        model_vram_mb = profile.estimate_vram_mb()
                        kv_budget_mb = float(profile.kv_budget_mb or 0)
            except (KeyError, Exception):
                pass

            scheduler_queue_depth = self._queue_mgr.get_total_depth_by_deployment(
                model_id, provider_id,
            )

            # Observed e2e latency p50 for queue wait estimation
            observed_e2e_p50_s = view.warmest_e2e_latency_p50_seconds

            # All lanes on this provider for reclaim context
            all_provider_lanes = None
            try:
                all_provider_lanes = self._logosnode.get_all_lane_signals(provider_id)
            except (KeyError, Exception):
                pass

            return estimate_ettft_local(
                view,
                effective_parallel=effective_parallel,
                generation_time_s=DEFAULT_GENERATION_TIME_S,
                available_vram_mb=available_vram_mb,
                model_vram_mb=model_vram_mb,
                kv_budget_mb=kv_budget_mb,
                scheduler_queue_depth=scheduler_queue_depth,
                observed_e2e_p50_s=observed_e2e_p50_s,
                all_provider_lanes=all_provider_lanes,
            )

        if provider_type == "azure":
            try:
                capacity = self._azure.get_model_capacity(model_id, provider_id)
            except (ValueError, KeyError):
                capacity = None
            return estimate_ettft_azure(capacity)

        return EttftEstimate(
            expected_wait_s=float("inf"),
            tier=ReadinessTier.UNAVAILABLE,
            reasoning=f"Unknown provider type: {provider_type}",
        )

    # Tiers where the model lane is NOT loaded/running — try_reserve_capacity
    # will always fail for these because _is_model_lane_ready() requires
    # "loaded" or "running".  When ECCS is enabled and the best-scored
    # candidate is in one of these tiers, we should queue for it (let the
    # capacity planner wake/load it) rather than falling through to a
    # lower-scored warm model.
    _NOT_READY_TIERS = frozenset({
        ReadinessTier.SLEEPING,
        ReadinessTier.SLEEPING_RECLAIM,
        ReadinessTier.COLD,
        ReadinessTier.COLD_RECLAIM,
    })

    def _try_immediate_select(self, scored: list, request_id: str):
        """Try to reserve capacity on the best available candidate.

        Returns the winning tuple or None if no candidate can be reserved
        immediately.

        When ECCS is enabled and the highest-scored candidate is sleeping or
        cold, returns None so the caller queues for that candidate — the
        corrected score already accounts for the wake/load cost, so the
        capacity planner should handle it rather than silently downgrading
        to a lower-scored warm model.
        """
        for idx, (model_id, provider_id, provider_type, score, priority_int, ettft) in enumerate(scored):
            if provider_type == "logosnode":
                # If the top-scored candidate is not ready (sleeping/cold),
                # queue for it rather than falling through to a lower-scored
                # warm model.  This applies regardless of ETTFT — the scoring
                # system already determined this is the best model; its
                # sleeping state is temporary and the capacity planner will
                # wake it.
                if (
                    ettft.tier in self._NOT_READY_TIERS
                    and idx == 0
                ):
                    logger.info(
                        "Queue-for-best: top candidate model %s provider %s "
                        "is %s (score=%.2f, wait=%.1fs) — deferring to queue path "
                        "instead of downgrading to a lower-scored warm model",
                        model_id, provider_id, ettft.tier.value,
                        score, ettft.expected_wait_s,
                    )
                    return None

                try:
                    reserved = self._logosnode.try_reserve_capacity(model_id, provider_id, request_id)
                except (KeyError, Exception):
                    logger.debug("Provider %s unavailable for model %s, skipping", provider_id, model_id)
                    continue
                if reserved:
                    logger.info(
                        "Reserved logosnode model %s provider %s "
                        "(score=%.2f, tier=%s, wait=%.1fs)",
                        model_id, provider_id, score,
                        ettft.tier.value, ettft.expected_wait_s,
                    )
                    return (model_id, provider_id, provider_type, score, priority_int, ettft)
                logger.debug("Failed to reserve logosnode model %s, trying next", model_id)
            elif provider_type == "azure":
                logger.info(
                    "Selected Azure model %s provider %s "
                    "(score=%.2f, tier=%s, wait=%.1fs)",
                    model_id, provider_id, score,
                    ettft.tier.value, ettft.expected_wait_s,
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
        queue_depth = self._queue_mgr.get_total_depth_by_deployment(model_id, provider_id)
        logger.info(
            "Request %s queued for model %s provider %s "
            "(corrected_score=%.2f, tier=%s, depth=%s)",
            request.request_id, model_id, provider_id,
            score, ettft.tier.value, queue_depth,
        )

        # Fire-and-forget: signal capacity planner to wake/load the model
        # so queued requests don't wait for the 30s background cycle.
        if self._on_capacity_needed and provider_type == "logosnode":
            model_name = self._logosnode.get_model_name(model_id, provider_id)
            if model_name:
                asyncio.create_task(
                    self._on_capacity_needed(provider_id, model_name),
                    name=f"capacity-needed-{model_name}-{provider_id}",
                )

        try:
            timeout = request.timeout_s if request.timeout_s else 1200  # 20 minutes for queue wait
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
                    # slot_transferred=True means a completing request kept its
                    # slot for us (release path) — don't double-count.
                    # slot_transferred=False means fresh dispatch from
                    # reevaluate_model_queues — must increment active count.
                    self._logosnode.on_request_begin_processing(
                        request.request_id,
                        increment_active=not result.slot_transferred,
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
