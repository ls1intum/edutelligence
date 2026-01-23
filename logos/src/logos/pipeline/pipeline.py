# src/logos/pipeline/pipeline.py
"""
Main request pipeline orchestrating classification → scheduling → execution.
"""

import logging
import uuid
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Tuple

from logos.classification.classification_manager import ClassificationManager
from logos.classification.proxy_policy import ProxyPolicy
from logos.dbutils.types import Deployment
from logos.monitoring.recorder import MonitoringRecorder

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
    ):
        self._classifier = classifier
        self._scheduler = scheduler
        self._executor = executor
        self._context_resolver = context_resolver or ContextResolver()
        self._monitoring = monitoring or MonitoringRecorder()

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
        request_id = str(uuid.uuid4())
        
        # 1. Classification
        classification_result = self._classify(request)
        if not classification_result.candidates:
            return PipelineResult(
                success=False,
                model_id=None,
                provider_id=None,
                execution_context=None,
                classification_stats=classification_result.stats,
                scheduling_stats={},
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
                scheduling_stats={"error": "Queue wait timeout"},
                error=str(exc),
            )

        if not scheduling_result:
            logger.warning(f"Request {request_id} failed scheduling: All models unavailable")
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
                scheduling_stats={"error": "No available model"},
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
        
        # 3. Resolve execution context (with authorization check)
        exec_context = self._context_resolver.resolve_context(
                model_id=scheduling_result.model_id,
                provider_id=scheduling_result.provider_id,
                logos_key=request.logos_key,
                profile_id=request.profile_id,

        )

        if not exec_context:
            return PipelineResult(
                success=False,
                model_id=scheduling_result.model_id,
                provider_id=None,
                execution_context=None,
                classification_stats=classification_result.stats,
                scheduling_stats={"model_id": scheduling_result.model_id},
                error=f"Failed to resolve execution context for model {scheduling_result.model_id}",
            )
        
        # Record provider ID now that it's resolved
        self._monitoring.record_provider(request_id, exec_context.provider_id)

        
        return PipelineResult(
            success=True,
            model_id=scheduling_result.model_id,
            provider_id=exec_context.provider_id,
            execution_context=exec_context,
            classification_stats=classification_result.stats,
            scheduling_stats={
                "request_id": request_id,
                "model_id": scheduling_result.model_id,
                "provider_id": scheduling_result.provider_id,
                "provider_type": scheduling_result.provider_type,
                "queue_depth": scheduling_result.queue_depth_at_schedule,
                "queue_depth_at_arrival": scheduling_result.queue_depth_at_arrival,
                "utilization_at_arrival": scheduling_result.utilization_at_arrival,
                "is_cold_start": scheduling_result.is_cold_start,
            },
        )
    
    def _classify(self, request: PipelineRequest) -> "_ClassificationResult":
        """Run classification to get candidate models."""
        policy = request.policy or ProxyPolicy()
        
        # Extract prompts
        user_prompt, system_prompt = self._extract_prompts(request.payload)
        
        import time
        start = time.time()
        
        candidates = self._classifier.classify(
            user_prompt,
            policy,
            allowed=request.allowed_models,
            system=system_prompt,
        )
        
        elapsed = time.time() - start
        
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


@dataclass
class _ClassificationResult:
    candidates: List[Tuple[int, float, int, int]]
    stats: Dict[str, Any]
