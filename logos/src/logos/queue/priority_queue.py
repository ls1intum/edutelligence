"""
Priority Queue Manager for multi-level request queuing.

This module provides thread-safe priority queue operations for scheduling.
Maintains separate heaps per model per priority level.

Queue key: model_id only (provider_id was dropped so queued requests can
re-route across workers as they become ready).
"""

import heapq
import logging
import uuid
from collections import defaultdict
from datetime import datetime
from threading import RLock
from typing import Dict, List, Tuple, Optional

from logos.queue.models import Priority, QueueEntry, QueueStatePerPriority


class PriorityQueueManager:
    """
    Thread-safe priority queue manager for request scheduling.

    Maintains separate priority queues (heaps) for each model:
        queues[model_id][Priority.HIGH] = [(priority, timestamp, entry_id, QueueEntry), ...]
        queues[model_id][Priority.NORMAL] = [...]
        queues[model_id][Priority.LOW] = [...]

    Design principles:
    - Pure queue operations - no scheduling policy
    - Thread-safe with RLock
    - No automatic escalation - that's the scheduler's job
    - Exposes methods for external escalation control
    """

    def __init__(self):
        """Initialize the priority queue manager."""
        # queues[model_id][priority] = heap of entries
        # Heap entries: (negative_priority, timestamp, entry_id, QueueEntry)
        # Using negative priority for max-heap behavior
        self._queues: Dict[int, Dict[Priority, List[Tuple[int, float, str, QueueEntry]]]] = defaultdict(
            lambda: {
                Priority.LOW: [],
                Priority.NORMAL: [],
                Priority.HIGH: [],
            }
        )

        # Fast lookup: entry_id -> (model_id, priority)
        self._entry_lookup: Dict[str, Tuple[int, Priority]] = {}

        # Lock for thread safety
        self._lock = RLock()

        # Counter for generating unique entry IDs
        self._entry_counter = 0

        logging.info("PriorityQueueManager initialized")

    def enqueue(
        self,
        task: any,
        model_id: int,
        provider_id: int,
        priority: Priority,
        is_cold_at_queue: bool = False,
    ) -> str:
        """
        Add a task to the appropriate priority queue.

        Args:
            task: The Task object to enqueue
            model_id: Which model this task is for
            priority: Priority level (LOW, NORMAL, HIGH)
            is_cold_at_queue: True if the lane was sleeping/cold/starting
                at the moment of queueing. Captured at enqueue time
                because by dispatch the lane is already loaded.

        Returns:
            Unique entry_id for this queued task

        Thread-safe.
        """
        with self._lock:
            # Generate unique entry ID
            self._entry_counter += 1
            entry_id = f"qe-{model_id}-{self._entry_counter}-{uuid.uuid4().hex[:8]}"

            # Create queue entry
            entry = QueueEntry(
                entry_id=entry_id,
                task=task,
                model_id=model_id,
                original_priority=priority,
                current_priority=priority,
                enqueue_time=datetime.now(),
                is_cold_at_queue=is_cold_at_queue,
            )

            # Add to appropriate heap
            heap_entry = (
                -int(priority),          # Negative for max-heap
                datetime.now().timestamp(),  # Tie-breaker (FIFO within priority)
                entry_id,                # Unique identifier
                entry,                   # The actual QueueEntry
            )

            heapq.heappush(self._queues[model_id][priority], heap_entry)

            # Update lookup table
            self._entry_lookup[entry_id] = (model_id, priority)

            logging.debug(
                f"Enqueued task {task.get_id() if hasattr(task, 'get_id') else 'unknown'} "
                f"to model {model_id} with priority {priority.name} (entry_id={entry_id})"
            )

            return entry_id

    def dequeue(self, model_id: int, priority: Optional[Priority] = None, **_kwargs) -> Optional[any]:
        """
        Remove and return the highest priority task for a model.

        Args:
            model_id: Which model to dequeue from
            priority: If specified, only dequeue from this priority level.
                     If None, dequeue from highest available priority.

        Returns:
            The Task object, or None if no tasks available

        Thread-safe.
        """
        with self._lock:
            if priority is not None:
                task, _ = self._dequeue_from_priority(model_id, priority)
                return task
            else:
                for p in [Priority.HIGH, Priority.NORMAL, Priority.LOW]:
                    task, _ = self._dequeue_from_priority(model_id, p)
                    if task is not None:
                        return task
                return None

    def dequeue_with_entry(self, model_id: int, priority: Optional[Priority] = None, **_kwargs) -> Tuple[Optional[any], Optional[QueueEntry]]:
        """
        Dequeue and return both the task and its QueueEntry metadata.

        Args:
            model_id: Which model to dequeue from
            priority: If specified, only dequeue from this priority level.
                     If None, dequeue from highest available priority.

        Returns:
            (task, QueueEntry) or (None, None)

        Thread-safe.
        """
        with self._lock:
            if priority is not None:
                return self._dequeue_from_priority(model_id, priority)
            for p in [Priority.HIGH, Priority.NORMAL, Priority.LOW]:
                task, entry = self._dequeue_from_priority(model_id, p)
                if task is not None:
                    return task, entry
            return None, None

    def _dequeue_from_priority(self, model_id: int, priority: Priority) -> Tuple[Optional[any], Optional[QueueEntry]]:
        """
        Internal helper to dequeue from a specific priority queue.

        Assumes lock is already held.
        """
        queue = self._queues[model_id][priority]

        if not queue:
            return None, None

        # Pop from heap
        _, _, entry_id, entry = heapq.heappop(queue)

        # Remove from lookup
        del self._entry_lookup[entry_id]

        logging.debug(
            f"Dequeued task {entry.task.get_id() if hasattr(entry.task, 'get_id') else 'unknown'} "
            f"from model {model_id} priority {priority.name} (entry_id={entry_id})"
        )

        return entry.task, entry

    def peek(self, model_id: int, **_kwargs) -> Optional[Tuple[any, Priority]]:
        """
        Look at the highest priority task without removing it.

        Returns:
            Tuple of (task, priority) or None if no tasks

        Thread-safe.
        """
        with self._lock:
            for priority in [Priority.HIGH, Priority.NORMAL, Priority.LOW]:
                queue = self._queues[model_id][priority]
                if queue:
                    _, _, _, entry = queue[0]
                    return entry.task, priority
            return None

    def move_priority(self, entry_id: str, new_priority: Priority) -> bool:
        """
        Move a queued entry to a different priority level.

        Args:
            entry_id: The unique entry ID to move
            new_priority: New priority level

        Returns:
            True if moved successfully, False if entry not found

        Thread-safe.
        """
        with self._lock:
            if entry_id not in self._entry_lookup:
                logging.warning(f"Cannot move entry {entry_id}: not found in queue")
                return False

            model_id, current_priority = self._entry_lookup[entry_id]

            if current_priority == new_priority:
                return True

            current_queue = self._queues[model_id][current_priority]
            entry_to_move = None

            for i, (_, _, eid, entry) in enumerate(current_queue):
                if eid == entry_id:
                    entry_to_move = entry
                    del current_queue[i]
                    heapq.heapify(current_queue)
                    break

            if entry_to_move is None:
                logging.error(f"Entry {entry_id} found in lookup but not in queue!")
                del self._entry_lookup[entry_id]
                return False

            entry_to_move.escalate(new_priority)

            heap_entry = (
                -int(new_priority),
                datetime.now().timestamp(),
                entry_id,
                entry_to_move,
            )
            heapq.heappush(self._queues[model_id][new_priority], heap_entry)

            self._entry_lookup[entry_id] = (model_id, new_priority)

            logging.info(
                f"Moved entry {entry_id} from {current_priority.name} to {new_priority.name} "
                f"(escalation count: {entry_to_move.escalation_count})"
            )

            return True

    def get_state(self, model_id: int, **_kwargs) -> QueueStatePerPriority:
        """
        Get queue depth breakdown by priority for a model.

        Args:
            model_id: Which model to query

        Returns:
            QueueStatePerPriority with counts per priority level

        Thread-safe.
        """
        with self._lock:
            return QueueStatePerPriority(
                low=len(self._queues[model_id][Priority.LOW]),
                normal=len(self._queues[model_id][Priority.NORMAL]),
                high=len(self._queues[model_id][Priority.HIGH]),
            )

    def get_entries_for_priority(self, model_id: int, priority: Priority, **_kwargs) -> List[QueueEntry]:
        """
        Get all queue entries for a specific model and priority.

        Args:
            model_id: Which model to query
            priority: Which priority level to query

        Returns:
            List of QueueEntry objects (sorted by wait time, oldest first)

        Thread-safe.
        """
        with self._lock:
            queue = self._queues[model_id][priority]
            entries = [entry for (_, _, _, entry) in queue]
            entries.sort(key=lambda e: e.enqueue_time)
            return entries

    def get_entry_info(self, entry_id: str) -> Optional[QueueEntry]:
        """
        Get metadata about a specific queue entry.

        Thread-safe.
        """
        with self._lock:
            if entry_id not in self._entry_lookup:
                return None

            model_id, priority = self._entry_lookup[entry_id]
            queue = self._queues[model_id][priority]

            for _, _, eid, entry in queue:
                if eid == entry_id:
                    return entry

            return None

    def remove(self, entry_id: str) -> bool:
        """
        Remove a specific entry from the queue (cancellation).

        Returns:
            True if removed, False if not found

        Thread-safe.
        """
        with self._lock:
            if entry_id not in self._entry_lookup:
                return False

            model_id, priority = self._entry_lookup[entry_id]
            queue = self._queues[model_id][priority]

            for i, (_, _, eid, _) in enumerate(queue):
                if eid == entry_id:
                    del queue[i]
                    heapq.heapify(queue)
                    del self._entry_lookup[entry_id]
                    logging.info(f"Removed entry {entry_id} from queue")
                    return True

            return False

    def is_empty(self) -> bool:
        """
        Check if all queues are empty.

        Thread-safe.
        """
        with self._lock:
            return all(
                len(queue) == 0
                for model_queues in self._queues.values()
                for queue in model_queues.values()
            )

    def get_total_depth_by_model(self, model_id: int) -> int:
        """
        Get total queue depth for a model (all priorities combined).

        Thread-safe.
        """
        state = self.get_state(model_id)
        return state.total

    # Backward-compat alias used in tests and base_scheduler
    def get_total_depth_by_deployment(self, model_id: int, *_args, **_kwargs) -> int:
        return self.get_total_depth_by_model(model_id)

    def get_total_depth_by_provider(self, provider_id: int) -> int:
        """
        Legacy: returns total depth summed across all models (provider_id ignored).

        Thread-safe.
        """
        with self._lock:
            return sum(
                len(queue)
                for model_queues in self._queues.values()
                for queue in model_queues.values()
            )

    def get_total_depth_all(self) -> int:
        """
        Get total queued tasks across all models.
        """
        with self._lock:
            return sum(
                len(queue)
                for model_queues in self._queues.values()
                for queue in model_queues.values()
            )
