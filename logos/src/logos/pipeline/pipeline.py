# src/logos/pipeline/pipeline.py
"""
Main request pipeline orchestrating classification → scheduling → execution.
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Tuple

from logos.classification.classification_manager import ClassificationManager
from logos.classification.proxy_policy import ProxyPolicy
from logos.dbutils.types import Deployment
from logos.monitoring.recorder import MonitoringRecorder
from logos.monitoring import prometheus_metrics as prom

from logos.queue.models import Priority

from .scheduler_interface import (
    SchedulerInterface,
    SchedulingRequest,
    SchedulingResult,
    QueueTimeoutError,
)
from .executor import Executor, ExecutionResult
from .context_resolver import ContextResolver, ExecutionContext


logger = logging.getLogger(__name__)


@dataclass
class PipelineRequest:
    """Input to the pipeline."""
    logos_key: str
    payload: Dict[str, Any]
    headers: Dict[str, str]
    allowed_models: List[int]
    deployments: list[Deployment]
    policy: Optional[Dict[str, Any]] = None
    profile_id: Optional[int] = None  # NEW: Profile ID for authorization
    request_id: Optional[str] = None


@dataclass
class PipelineResult:
    """Output from the pipeline."""
    success: bool
    model_id: Optional[int]
    provider_id: Optional[int]
    execution_context: Optional[ExecutionContext]
    classification_stats: Dict[str, Any]
    scheduling_stats: Dict[str, Any]
    error: Optional[str] = None


class RequestPipeline:
    """
    Orchestrates the full request flow:
    
    1. Classification - rank candidate models
    2. Scheduling - select best available model
    3. Execution - make backend call
    
    Decouples these concerns for testability and flexibility.
    """
    
    def __init__(
        self,
        classifier: ClassificationManager,
        scheduler: SchedulerInterface,
        executor: Executor,
        context_resolver: Optional[ContextResolver] = None,
        monitoring: Optional[MonitoringRecorder] = None,
        demand_tracker=None,
    ):
        self._classifier = classifier
        self._scheduler = scheduler
        self._executor = executor
        self._context_resolver = context_resolver or ContextResolver()
        self._monitoring = monitoring or MonitoringRecorder()
        self._demand_tracker = demand_tracker

    @property
    def classifier(self) -> ClassificationManager:
        """Expose classifier for read-only access."""
        return self._classifier

    def update_classifier(self, classifier: ClassificationManager) -> None:
        """Replace classifier instance after model changes."""
        self._classifier = classifier

    @property
    def executor(self) -> Executor:
        """Expose executor for helper functions."""
        return self._executor

    @property
    def scheduler(self) -> SchedulerInterface:
        """Expose scheduler for helper functions."""
        return self._scheduler
    
    async def process(self, request: PipelineRequest) -> PipelineResult:
        """
        Process a request through the full pipeline.
        
        This method orchestrates the entire lifecycle:
        1.  **Classification**: Determines which models are suitable candidates.
        2.  **Scheduling**: Selects the best available model, potentially queuing if all are busy.
        3.  **Execution Context**: Resolves the necessary DB information to perform the call.
        
        Args:
            request: The `PipelineRequest` containing payload, headers, and policy.
            
        Returns:
            `PipelineResult` containing the execution context (if successful) or error details.
            The result also includes classification and scheduling statistics for logging.
        """
        request_id = request.request_id or str(uuid.uuid4())
        
        # 1. Classification
        classification_result = self._classify(request)
        if not classification_result.candidates:
            self.record_completion(
                request_id=request_id,
                result_status="error",
                error_message="No models passed classification",
            )
            return PipelineResult(
                success=False,
                model_id=None,
                provider_id=None,
                execution_context=None,
                classification_stats=classification_result.stats,
                scheduling_stats={"request_id": request_id},
                error="No models passed classification",
            )
        
        sorted_candidates = sorted(
            classification_result.candidates, key=lambda x: x[1], reverse=True
        )
        target_model_id, _, priority_int, _ = sorted_candidates[0]
        target_deployment = next(
            (d for d in request.deployments if d["model_id"] == target_model_id),
            None,
        )

        # 2. Scheduling
        scheduling_request = SchedulingRequest(
            request_id=request_id,
            classified_models=classification_result.candidates,
            deployments=request.deployments,
            payload=request.payload,
            timeout_s=request.payload.get("timeout_s"),
        )
        
        # Record enqueue
        self._monitoring.record_enqueue(
            request_id=request_id,
            model_id=target_deployment["model_id"] if target_deployment else None,
            provider_id=target_deployment["provider_id"] if target_deployment else None,
            initial_priority=Priority.from_int(priority_int).name.lower(),
            queue_depth=self._scheduler.get_total_queue_depth(),
            timeout_s=request.payload.get("timeout_s"),
        )
        
        try:
            scheduling_result = await self._scheduler.schedule(scheduling_request)
        except QueueTimeoutError as exc:
            logger.warning("Request %s timed out waiting in queue", request_id)
            prom.SCHEDULING_DECISIONS_TOTAL.labels(result="timeout").inc()
            self.record_completion(
                request_id=request_id,
                result_status="timeout",
                error_message=str(exc),
            )
            return PipelineResult(
                success=False,
                model_id=exc.model_id,
                provider_id=exc.provider_id,
                execution_context=None,
                classification_stats=classification_result.stats,
                scheduling_stats={
                    "request_id": request_id,
                    "model_id": exc.model_id,
                    "provider_id": exc.provider_id,
                    "error": "Queue wait timeout",
                },
                error=str(exc),
            )

        if not scheduling_result:
            logger.warning(f"Request {request_id} failed scheduling: All models unavailable")
            prom.SCHEDULING_DECISIONS_TOTAL.labels(result="no_capacity").inc()
            self.record_completion(
                request_id=request_id,
                result_status="error",
                error_message="All candidate models unavailable (rate-limited or no capacity)",
            )
            return PipelineResult(
                success=False,
                model_id=None,
                provider_id=None,
                execution_context=None,
                classification_stats=classification_result.stats,
                scheduling_stats={"request_id": request_id, "error": "No available model"},
                error="All candidate models unavailable (rate-limited or no capacity)",
            )
        
        # Record scheduled
        self._monitoring.record_scheduled(
            request_id=request_id,
            model_id=scheduling_result.model_id,
            provider_id=scheduling_result.provider_id,
            priority_when_scheduled=scheduling_result.priority_when_scheduled,
            queue_depth_at_schedule=scheduling_result.queue_depth_at_schedule,
            provider_metrics=scheduling_result.provider_metrics
        )

        # Record demand for capacity planner
        self._record_demand(scheduling_result, sorted_candidates)

        # 3. Resolve execution context (with authorization check)
        #    For logosnode providers, the lane may be starting (not yet ready to
        #    accept requests). Retry with backoff instead of failing immediately.
        ctx_result = await self._resolve_context_with_retry(
            scheduling_result=scheduling_result,
            classification_result=classification_result,
            request=request,
            request_id=request_id,
        )
        if not ctx_result.success:
            return ctx_result

        # Record provider ID now that it's resolved
        self._monitoring.record_provider(request_id, ctx_result.execution_context.provider_id)

        return ctx_result

    def _record_demand(self, scheduling_result, sorted_candidates: list) -> None:
        if not self._demand_tracker:
            return
        model_name = self._resolve_model_name(scheduling_result.model_id)
        if model_name:
            self._demand_tracker.record_request(model_name)
        # Record latent demand when the scheduler overrides classification's top
        # choice due to availability (e.g. ETTFT penalties). This lets the
        # capacity planner see that users want the unloaded model, so it can
        # drain/wake it before it starves in resource mode.
        if sorted_candidates and scheduling_result.model_id != sorted_candidates[0][0]:
            top_model_name = self._resolve_model_name(sorted_candidates[0][0])
            if top_model_name:
                self._demand_tracker.record_latent_demand(top_model_name)
                prom.DEMAND_LATENT_TOTAL.labels(model=top_model_name).inc()

    _CONTEXT_RESOLVE_TIMEOUT_S = 180.0
    _CONTEXT_RESOLVE_INTERVAL_S = 2.0

    async def _resolve_context_with_retry(
        self,
        scheduling_result,
        classification_result: "_ClassificationResult",
        request: "PipelineRequest",
        request_id: str,
    ) -> "PipelineResult":
        """Resolve execution context, retrying for logosnode providers whose lane may still be starting."""
        deadline = time.monotonic() + self._CONTEXT_RESOLVE_TIMEOUT_S
        first_attempt = True

        while True:
            try:
                exec_context = await self._context_resolver.resolve_context(
                    model_id=scheduling_result.model_id,
                    provider_id=scheduling_result.provider_id,
                    logos_key=request.logos_key,
                    profile_id=request.profile_id,
                )
            except Exception as exc:  # noqa: BLE001
                self._release_scheduler_safe(scheduling_result, request_id, "exception")
                logger.warning(
                    "Execution context resolution raised for request %s (model_id=%s, provider_id=%s): %s",
                    request_id, scheduling_result.model_id, scheduling_result.provider_id, exc,
                )
                return self._context_failure(
                    scheduling_result, classification_result, request_id,
                    error=f"Failed to resolve execution context for model {scheduling_result.model_id}: {exc}",
                )

            if exec_context is not None:
                return PipelineResult(
                    success=True,
                    model_id=scheduling_result.model_id,
                    provider_id=scheduling_result.provider_id,
                    execution_context=exec_context,
                    classification_stats=classification_result.stats,
                    scheduling_stats=self._scheduling_stats(scheduling_result, request_id),
                )

            # For cloud providers or after timeout, fail immediately
            if scheduling_result.provider_type != "logosnode" or time.monotonic() >= deadline:
                self._release_scheduler_safe(scheduling_result, request_id, "failure")
                return self._context_failure(
                    scheduling_result, classification_result, request_id,
                    error=f"Failed to resolve execution context for model {scheduling_result.model_id}",
                )

            if first_attempt:
                logger.info(
                    "No lane ready yet for request %s (model=%s, provider=%s); "
                    "waiting up to %.0fs for lane to become available",
                    request_id, scheduling_result.model_id, scheduling_result.provider_id,
                    self._CONTEXT_RESOLVE_TIMEOUT_S,
                )
                first_attempt = False

            await asyncio.sleep(self._CONTEXT_RESOLVE_INTERVAL_S)

    def _release_scheduler_safe(self, scheduling_result, request_id: str, reason: str) -> None:
        try:
            self._scheduler.release(
                scheduling_result.model_id,
                scheduling_result.provider_id,
                scheduling_result.provider_type,
                request_id,
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "Failed to release scheduler reservation after context resolution %s "
                "(request_id=%s, model_id=%s, provider_id=%s)",
                reason, request_id, scheduling_result.model_id, scheduling_result.provider_id,
            )

    def _scheduling_stats(self, scheduling_result, request_id: str) -> dict:
        return {
            "request_id": request_id,
            "model_id": scheduling_result.model_id,
            "provider_id": scheduling_result.provider_id,
            "provider_type": scheduling_result.provider_type,
            "queue_depth": scheduling_result.queue_depth_at_schedule,
            "queue_depth_at_arrival": scheduling_result.queue_depth_at_arrival,
            "utilization_at_arrival": scheduling_result.utilization_at_arrival,
            "is_cold_start": scheduling_result.is_cold_start,
        }

    def _context_failure(
        self, scheduling_result, classification_result: "_ClassificationResult",
        request_id: str, *, error: str,
    ) -> "PipelineResult":
        return PipelineResult(
            success=False,
            model_id=scheduling_result.model_id,
            provider_id=scheduling_result.provider_id,
            execution_context=None,
            classification_stats=classification_result.stats,
            scheduling_stats=self._scheduling_stats(scheduling_result, request_id),
            error=error,
        )

    def _classify(self, request: PipelineRequest) -> "_ClassificationResult":
        """Run classification to get candidate models."""
        policy = request.policy or ProxyPolicy()
        
        # Extract prompts
        user_prompt, system_prompt = self._extract_prompts(request.payload)
        
        start = time.time()
        
        candidates = self._classifier.classify(
            user_prompt,
            policy,
            allowed=request.allowed_models,
            system=system_prompt,
        )
        
        elapsed = time.time() - start

        prom.CLASSIFICATION_DURATION_SECONDS.observe(elapsed)
        prom.CLASSIFICATION_CANDIDATES.observe(len(candidates))

        # Build classification stats
        stats = {
            "classification_time": elapsed,
            "candidate_count": len(candidates),
            "candidates": [
                {"model_id": m, "weight": w, "priority": p}
                for m, w, p, _ in candidates[:5]  # Top 5 for logging
            ],
        }
        
        return _ClassificationResult(candidates=candidates, stats=stats)
    
    def _extract_prompts(self, payload: Dict[str, Any]) -> Tuple[str, str]:
        """Extract user and system prompts from payload."""
        messages = payload.get("messages", [])
        user_prompt = ""
        system_prompt = ""
        
        for msg in messages:
            role = msg.get("role", "").lower()
            content = msg.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    p.get("text", "") for p in content 
                    if isinstance(p, dict) and p.get("type") == "text"
                )
            
            if role == "user":
                user_prompt = content
            elif role == "system":
                system_prompt = content
        
        return user_prompt, system_prompt

    def record_completion(self, request_id: str, result_status: str, error_message: Optional[str] = None, cold_start: Optional[bool] = None):
        """Record request completion."""
        self._monitoring.record_complete(
            request_id=request_id,
            result_status=result_status,
            error_message=error_message,
            cold_start=cold_start
        )

    def update_provider_stats(self, model_id: int, provider_id: int, headers: Dict[str, str]) -> None:
        """
        Update provider statistics (e.g. rate limits) from response headers.
        
        Args:
            model_id: The model that generated the response.
            provider_id: The provider that served the request.
            headers: Response headers containing rate limit info.
        """
        if not headers:
            return
            
        self._scheduler.update_provider_stats(model_id, provider_id, headers)

    def record_provider_metrics(self, request_id: str, provider_metrics: Dict[str, Any]) -> None:
        """Record provider metrics (e.g. Azure rate limits) for a request."""
        self._monitoring.record_provider_metrics(request_id, provider_metrics)

    def _resolve_model_name(self, model_id: int) -> Optional[str]:
        """Look up model name from scheduler's model registry."""
        if hasattr(self._scheduler, '_model_registry') and self._scheduler._model_registry:
            for (mid, pid), name in self._scheduler._model_registry.items():
                if mid == model_id:
                    return name
        return None


@dataclass
class _ClassificationResult:
    candidates: List[Tuple[int, float, int, int]]
    stats: Dict[str, Any]
