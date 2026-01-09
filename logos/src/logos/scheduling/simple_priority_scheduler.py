"""
Minimal Scheduler - Shows Queue and SDI Integration

This is a minimal reference showing how to:
1. Extract scheduling data from tasks
2. Use PriorityQueueManager for queue operations
3. Query SDI facades for capacity/state information
4. Implement custom scheduling logic

Customize the scoring and escalation logic for your specific needs.
"""

from typing import Dict, Optional, List, Tuple
from logos.scheduling.scheduler import Scheduler, Task
from logos.queue import PriorityQueueManager, Priority


class SimplePriorityScheduler(Scheduler):
    """Minimal scheduler demonstrating queue and SDI integration."""

    def __init__(self, queue_manager: PriorityQueueManager, sdi_facades: Optional[Dict] = None):
        """
        Args:
            queue_manager: PriorityQueueManager for queue operations
            sdi_facades: Dict of {provider_name: SDI facade} for capacity/state queries
        """
        super().__init__()
        self.queue_manager = queue_manager
        self.sdi_facades = sdi_facades or {}

    def enqueue(self, task: Task) -> None:
        """Add task to queue - extracts priority from task data."""
        if not task.models:
            return

        # EXTRACT: Task contains model tuples with scheduling data
        # Format: (model_id, weight, priority_int, parallel_capacity)
        model_id, weight, priority_int, parallel_capacity = task.models[0]

        # CONVERT: Integer priority to Priority enum (LOW=1, NORMAL=5, HIGH=10)
        priority = Priority.from_int(priority_int)

        # ENQUEUE: Add to priority queue
        self.queue_manager.enqueue(task, model_id, priority)

    def schedule(self, work_table: Dict[int, int]) -> Optional[Task]:
        """
        Select next task to execute.

        Args:
            work_table: {model_id: available_slots} - current capacity

        Returns:
            Task to execute, or None if no task available
        """
        # OPTIONAL: Check for escalations (time-based priority increases)
        # self._check_escalations()  # Your escalation logic here

        # QUERY: Find all models with queued tasks and available capacity
        candidates: List[Tuple[int, Task, Priority, float]] = []

        for model_id in self.queue_manager.get_all_models():
            # CHECK CAPACITY: Does this model have available slots?
            if work_table.get(model_id, 0) <= 0:
                continue

            # PEEK: Look at highest priority task without removing it
            peek_result = self.queue_manager.peek(model_id)
            if peek_result is None:
                continue

            task, priority = peek_result

            # SCORE: Your custom scoring logic here
            score = self._score_task(task, model_id, priority, work_table)
            candidates.append((model_id, task, priority, score))

        if not candidates:
            return None

        # SELECT: Choose highest-scoring task
        candidates.sort(key=lambda x: x[3], reverse=True)
        best_model_id = candidates[0][0]

        # DEQUEUE: Remove and return the selected task
        return self.queue_manager.dequeue(best_model_id)

    def _score_task(self, task: Task, model_id: int, priority: Priority, work_table: Dict[int, int]) -> float:
        """
        Score task for scheduling priority (higher = more urgent).

        CUSTOMIZE THIS: Different scheduling approaches use different factors:
        - Priority-only: Just use priority level
        - Load-balancing: Prefer models with fewer queued tasks
        - Cold-start aware: Penalize models that need loading
        - Deadline-based: Factor in task deadlines
        - Fair-share: Track per-user usage and balance
        """
        score = 0.0

        # Factor 1: Priority level (HIGH=10, NORMAL=5, LOW=1)
        score += int(priority) * 10

        # Factor 2: Queue depth - prefer less loaded models
        # QUERY SDI: Get current queue state
        queue_state = self.queue_manager.get_state(model_id)
        score -= queue_state.total * 0.1

        # Factor 3: Cold start prediction (requires SDI query)
        # if self.sdi_facades:
        #     facade = self.sdi_facades.get(provider_name)
        #     model_status = facade.get_model_status(model_id)
        #     if not model_status.is_loaded:
        #         score -= 5  # Penalize cold starts

        # Factor 4: Available capacity
        score += work_table.get(model_id, 0)

        return score

    def is_empty(self) -> bool:
        """Check if all queues are empty."""
        return self.queue_manager.is_empty()

    def get_depth_for_model(self, model_id: int) -> int:
        """Queue depth for a specific model (all priorities)."""
        return self.queue_manager.get_total_depth(model_id)
