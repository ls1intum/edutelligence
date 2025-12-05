# src/logos/pipeline/scheduler_interface.py
"""
Abstract scheduler interface for model selection.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Tuple, Optional, Dict, Any

from logos.queue.priority_queue import PriorityQueueManager, Priority
from logos.sdi.ollama_facade import OllamaSchedulingDataFacade
from logos.sdi.azure_facade import AzureSchedulingDataFacade


import asyncio
import logging
from datetime import datetime, timedelta


@dataclass
class SchedulingResult:
    """Output from the scheduler."""
    model_id: int
    provider_type: str  # 'ollama' | 'azure'
    queue_entry_id: Optional[str]  # For local models with queue tracking
    was_queued: bool
    queue_depth_at_schedule: int
    queue_depth_at_arrival: Optional[int] = None
    utilization_at_arrival: Optional[float] = None


@dataclass
class SchedulingRequest:
    """Input for the scheduler."""
    request_id: str
    candidates: List[Tuple[int, float, int, int]]  # (model_id, weight, priority, parallel)
    payload: Dict[str, Any]
    timeout_s: Optional[float] = None


class SchedulerInterface(ABC):
    """Abstract interface for model scheduling."""
    
    @abstractmethod
    async def schedule(self, request: SchedulingRequest) -> Optional[SchedulingResult]:
        """
        Select a model from candidates based on weights and availability.
        If no model is immediately available, may queue the request and await availability.
        
        Returns None if no model is available and queuing failed/timed out.
        """
        pass
    
    @abstractmethod
    def release(self, model_id: int, request_id: str) -> None:
        """Called when a request completes to free capacity."""
        pass


class UtilizationAwareScheduler(SchedulerInterface):
    """
    Production scheduler that uses SDI data for scheduling decisions.
    
    Features:
    - Availability-aware selection
    - Async queuing when busy
    - Starvation prevention (priority aging)
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
        
    async def schedule(self, request: SchedulingRequest) -> Optional[SchedulingResult]:
        """
        Select a model from candidates based on weights and availability.
        
        Logic:
        1.  **Immediate Selection**: Iterates through candidates by weight. If a model is available (loaded, not rate-limited), it is selected immediately.
        2.  **Queuing**: If ALL candidates are unavailable, the request is queued against the highest-weighted candidate.
        3.  **Async Wait**: The method `await`s until the request is dequeued by a `release()` call from another request.
        
        Args:
            request: The scheduling request containing candidates and payload.
            
        Returns:
            `SchedulingResult` with the selected model ID, or `None` if queuing timed out or failed.
        """
        # 1. Try to find an immediately available model
        best_candidate = self._select_best_candidate(request.candidates)
        
        if best_candidate:
            model_id, provider_type, _, priority_int = best_candidate
            return self._create_result(model_id, provider_type, priority_int, request.request_id, was_queued=False)
            
        # 2. No model available -> Queue the request
        # We need to pick a "primary" model to queue against, or queue against multiple?
        # For simplicity, we pick the highest weighted candidate even if busy.
        # Or better: queue against the "best fit" model.
        
        if not request.candidates:
            return None
            
        # Sort candidates by raw weight (ignoring availability for now)
        sorted_candidates = sorted(request.candidates, key=lambda x: x[1], reverse=True)
        target_model_id, _, priority_int, _ = sorted_candidates[0]
        provider_type = self._model_registry.get(target_model_id)
        
        if not provider_type:
            return None
            
        priority = Priority.from_int(priority_int)
        
        # Create a Future to await
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        
        # Enqueue the Future
        entry_id = self._queue_mgr.enqueue(future, target_model_id, priority)
        
        try:
            # Wait for the future to be completed by release()
            timeout = request.timeout_s if request.timeout_s else 60
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self._queue_mgr.remove(entry_id)
            return None
            
    def _select_best_candidate(self, candidates: List[Tuple[int, float, int, int]]) -> Optional[Tuple[int, str, float, int]]:
        """Find the best immediately available model."""
        scored_candidates = []
        
        for model_id, weight, priority_int, parallel in candidates:
            provider_type = self._model_registry.get(model_id)
            if not provider_type:
                continue
                
            # Query SDI for availability
            availability_score = self._get_availability_score(model_id, provider_type)
            if availability_score is None:
                continue  # Model unavailable (rate-limited, cold, etc.)
            
            # Combined score: classification weight + availability bonus
            total_score = weight + availability_score
            scored_candidates.append((model_id, provider_type, total_score, priority_int))
        
        if not scored_candidates:
            return None
            
        # Select highest scoring
        scored_candidates.sort(key=lambda x: x[2], reverse=True)
        return scored_candidates[0]

    def _create_result(self, model_id: int, provider_type: str, priority_int: int, request_id: str, was_queued: bool) -> SchedulingResult:
        """Helper to create SchedulingResult and update stats."""
        queue_depth = 0
        utilization = 0.0
        
        if provider_type == 'ollama':
            priority = Priority.from_int(priority_int)
            queue_state = self._queue_mgr.get_state(model_id)
            queue_depth = queue_state.total
            
            # Get utilization (active requests)
            try:
                status = self._ollama.get_model_status(model_id)
                utilization = float(status.active_requests)
            except ValueError:
                utilization = 0.0
            
            self._ollama.on_request_start(
                request_id, 
                model_id=model_id,
                priority=priority.name.lower()
            )
            
        return SchedulingResult(
            model_id=model_id,
            provider_type=provider_type,
            queue_entry_id=None,
            was_queued=was_queued,
            queue_depth_at_schedule=queue_depth,
            queue_depth_at_arrival=queue_depth,
            utilization_at_arrival=utilization
        )
    
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
                return -20  # Cold start penalty (still available, just slow)
            
            # Bonus for warm, penalty for queue depth
            return 10 - (status.queue_depth * 0.5)
            
        elif provider_type == 'azure':
            try:
                status = self._azure.get_model_status(model_id)
                # Get deployment name from model registration
                # (This requires model_id -> deployment mapping)
                return 5 if status.is_loaded else None  # Azure always "loaded"
            except (ValueError, KeyError):
                return None
        
        return None
    
    def release(self, model_id: int, request_id: str) -> None:
        """
        Called when a request completes.
        1. Notify SDI facade.
        2. Check starvation (priority aging).
        3. Wake up next queued request if any.
        """
        provider_type = self._model_registry.get(model_id)
        
        # 1. Notify SDI
        if provider_type == 'ollama':
            try:
                self._ollama.on_request_complete(
                    request_id,
                    was_cold_start=False,
                    duration_ms=0
                )
            except KeyError:
                pass

        # 2. Check starvation
        self._check_starvation(model_id)

        # 3. Wake up next request
        # We dequeue the next task (which is a Future) and set its result
        next_task = self._queue_mgr.dequeue(model_id)
        if next_task and isinstance(next_task, asyncio.Future):
            if not next_task.done():
                # We need to construct a SchedulingResult for the woken request
                # We don't have the original request details here easily unless we stored them in the task
                # But we know the model_id and provider_type
                
                # NOTE: The Future expects a SchedulingResult.
                # We can assume priority was handled by the queue.
                # We'll use a default priority for the result metadata since we lost the original int.
                # Or we could have stored (Future, priority_int) in the queue.
                
                # For now, let's assume NORMAL priority for the result metadata or fetch from queue entry if possible.
                # But dequeue returns just the task.
                
                result = SchedulingResult(
                    model_id=model_id,
                    provider_type=provider_type,
                    queue_entry_id=None,
                    was_queued=True,
                    queue_depth_at_schedule=self._queue_mgr.get_total_depth(model_id)
                )
                
                # Schedule the callback to run safely
                next_task.get_loop().call_soon_threadsafe(next_task.set_result, result)

    def _check_starvation(self, model_id: int):
        """
        Check for starved requests and bump their priority.
        Rule: If waiting > 10s in LOW, move to NORMAL.
              If waiting > 30s in NORMAL, move to HIGH.
        """
        now = datetime.now()
        
        # Check LOW priority
        low_entries = self._queue_mgr.get_entries_for_priority(model_id, Priority.LOW)
        for entry in low_entries:
            if (now - entry.enqueue_time).total_seconds() > 10:
                self._queue_mgr.move_priority(entry.entry_id, Priority.NORMAL)
                
        # Check NORMAL priority
        normal_entries = self._queue_mgr.get_entries_for_priority(model_id, Priority.NORMAL)
        for entry in normal_entries:
            if (now - entry.enqueue_time).total_seconds() > 30:
                self._queue_mgr.move_priority(entry.entry_id, Priority.HIGH)
