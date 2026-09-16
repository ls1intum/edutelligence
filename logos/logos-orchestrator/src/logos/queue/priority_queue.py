"""
Priority Queue Manager for multi-level request queuing.

Phase 2: model-only queue. Queues are keyed solely by ``model_id`` so a
normal queued request can be served by any provider with capability for that
model. Individual internal requests may carry a provider affinity when their
result must be attributable to one exact worker.

For backward compatibility every public method that previously took a
``provider_id`` still accepts it. Enqueue and aggregate metrics ignore it;
dequeue uses it only to keep provider-affine entries on their required worker.
"""

import heapq
import logging
import uuid
from collections import defaultdict
from datetime import datetime
from threading import RLock
from typing import Dict, List, Optional, Tuple, Union

from logos.queue.models import Priority, QueueEntry, QueueStatePerPriority


class PriorityQueueManager:
    """Thread-safe priority queue manager keyed by ``model_id``.

    Maintains separate priority heaps per model:
        queues[model_id][Priority.HIGH] = [(-raw_priority, -role_rank, ts, entry_id, QueueEntry), ...]
        queues[model_id][Priority.NORMAL] = [...]
        queues[model_id][Priority.LOW] = [...]

    Ordering inside the queue:
    1. ``-raw_priority``: the full-precision priority the request resolved to
       (team > key > policy scale, 1..10). Bucket choice (LOW/NORMAL/HIGH)
       still comes from ``Priority.from_int(raw_priority)``; the raw value
       refines ordering *within* a bucket, so a team priority of 7 dequeues
       before a plain 5 in NORMAL.
    2. ``-role_rank``: the caller's queue tiebreak rank (application keys
       before admin keys before developer traffic, see
       pipeline.queue_role_rank) — the default intra-team ordering
       application > app admin > developer.
    3. ``ts``: FIFO for equal priority and rank.

    Design principles:
    - Pure queue operations — no scheduling policy.
    - Thread-safe via ``RLock``.
    - No provider partition: any provider that serves the model can dispatch
      normal requests from the same queue (release path picks via
      lane_comparator).
    - Optional per-entry affinity: benchmark requests can be restricted to one
      provider without splitting the model-wide queue.
    - Backward-compatible: every method that previously accepted
      ``provider_id`` still accepts it; unpinned behavior stays model-wide.
    """

    def __init__(self):
        # queues[model_id][priority] = heap of
        # (-raw_priority, -role_rank, ts, entry_id, QueueEntry)
        self._queues: Dict[int, Dict[Priority, List[Tuple[int, int, float, str, QueueEntry]]]] = defaultdict(
            lambda: {
                Priority.LOW: [],
                Priority.NORMAL: [],
                Priority.HIGH: [],
            }
        )

        # Fast lookup: entry_id → (model_id, priority)
        self._entry_lookup: Dict[str, Tuple[int, Priority]] = {}

        self._lock = RLock()
        self._entry_counter = 0

        logging.info("PriorityQueueManager initialized (model-only queue)")

    def enqueue(
        self,
        task: any,
        model_id: int,
        provider_id: int = None,  # Ignored — kept for back-compat.
        priority: Priority = Priority.NORMAL,
        is_cold_at_queue: bool = False,
        provider_affinity: int | None = None,
        raw_priority: int | None = None,
        role_rank: int = 0,
    ) -> str:
        """Add a task to the priority queue for ``model_id``.

        ``provider_id`` is accepted but ignored (back-compat). Unless
        ``provider_affinity`` is set, any provider with capability for
        ``model_id`` can later dispatch this task.

        ``raw_priority`` is the full-precision priority the request resolved
        to (1..10 scale); it refines the ordering inside the bucket that
        ``priority`` (``Priority.from_int(raw_priority)``) selects. Defaults
        to ``int(priority)``. ``role_rank`` is the caller's tiebreak rank
        within equal priority (see pipeline.queue_role_rank); 0 = unknown
        caller, which waits behind interactive traffic.
        """
        with self._lock:
            self._entry_counter += 1
            entry_id = f"qe-{model_id}-{self._entry_counter}-{uuid.uuid4().hex[:8]}"

            entry = QueueEntry(
                entry_id=entry_id,
                task=task,
                model_id=model_id,
                original_priority=priority,
                current_priority=priority,
                raw_priority=int(raw_priority if raw_priority is not None else priority),
                role_rank=role_rank,
                enqueue_time=datetime.now(),
                is_cold_at_queue=is_cold_at_queue,
                provider_affinity=provider_affinity,
            )

            heap_entry = (
                -entry.raw_priority,
                -entry.role_rank,
                datetime.now().timestamp(),
                entry_id,
                entry,
            )
            heapq.heappush(self._queues[model_id][priority], heap_entry)
            self._entry_lookup[entry_id] = (model_id, priority)

            logging.debug(
                f"Enqueued task {task.get_id() if hasattr(task, 'get_id') else 'unknown'} "
                f"to model {model_id} priority {priority.name} (entry_id={entry_id})"
            )
            return entry_id

    def dequeue(
        self,
        model_id: int,
        provider_id: int = None,  # Ignored — kept for back-compat.
        priority: Optional[Priority] = None,
    ) -> Optional[any]:
        """Remove and return the highest-priority task for ``model_id``.

        ``provider_id`` selects entries eligible for that provider. Unpinned
        entries remain eligible for every provider.
        """
        with self._lock:
            if priority is not None:
                task, _ = self._dequeue_from_priority(model_id, priority, provider_id)
                return task
            for p in [Priority.HIGH, Priority.NORMAL, Priority.LOW]:
                task, _ = self._dequeue_from_priority(model_id, p, provider_id)
                if task is not None:
                    return task
            return None

    def dequeue_with_entry(
        self,
        model_id: int,
        provider_id: int = None,  # Ignored — kept for back-compat.
        priority: Optional[Priority] = None,
    ) -> Tuple[Optional[any], Optional[QueueEntry]]:
        """Dequeue and return both the task and its QueueEntry metadata."""
        with self._lock:
            if priority is not None:
                return self._dequeue_from_priority(model_id, priority, provider_id)
            for p in [Priority.HIGH, Priority.NORMAL, Priority.LOW]:
                task, entry = self._dequeue_from_priority(model_id, p, provider_id)
                if task is not None:
                    return task, entry
            return None, None

    def _dequeue_from_priority(
        self,
        model_id: int,
        priority: Priority,
        provider_id: int | None = None,
    ) -> Tuple[Optional[any], Optional[QueueEntry]]:
        """Dequeue from a specific priority heap. Caller must hold ``_lock``."""
        queue = self._queues[model_id][priority]
        if not queue:
            return None, None

        eligible_index = next(
            (
                index
                for index, (*_ordering, candidate) in sorted(
                    # Order by the heap's leading keys:
                    # (-raw_priority, -role_rank, ts, entry_id).
                    enumerate(queue), key=lambda item: item[1][:4]
                )
                if provider_id is None or candidate.provider_affinity in (None, provider_id)
            ),
            None,
        )
        if eligible_index is None:
            return None, None

        _, _, _, entry_id, entry = queue[eligible_index]
        if eligible_index == 0:
            heapq.heappop(queue)
        else:
            del queue[eligible_index]
            heapq.heapify(queue)
        del self._entry_lookup[entry_id]

        logging.debug(
            f"Dequeued task {entry.task.get_id() if hasattr(entry.task, 'get_id') else 'unknown'} "
            f"from model {model_id} priority {priority.name} (entry_id={entry_id})"
        )
        return entry.task, entry

    def peek(
        self,
        model_id: int,
        provider_id: int = None,
    ) -> Optional[Tuple[any, Priority]]:
        """Peek at the highest-priority queued task without removing it.

        ``provider_id`` is accepted but ignored.
        """
        with self._lock:
            for priority in [Priority.HIGH, Priority.NORMAL, Priority.LOW]:
                queue = self._queues[model_id][priority]
                if queue:
                    _, _, _, _, entry = queue[0]
                    return entry.task, priority
            return None

    def move_priority(self, entry_id: str, new_priority: Priority) -> bool:
        """Move a queued entry to a different priority level (escalation)."""
        with self._lock:
            if entry_id not in self._entry_lookup:
                logging.warning(f"Cannot move entry {entry_id}: not found in queue")
                return False

            model_id, current_priority = self._entry_lookup[entry_id]
            if current_priority == new_priority:
                return True

            current_queue = self._queues[model_id][current_priority]
            entry_to_move = None
            for i, (_, _, _, eid, entry) in enumerate(current_queue):
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
            # Escalation changes the bucket, not the caller: keep the entry's
            # raw priority and role rank so its position inside the new
            # bucket matches where it would have sat.
            entry_to_move.raw_priority = int(new_priority)

            heap_entry = (
                -entry_to_move.raw_priority,
                -entry_to_move.role_rank,
                datetime.now().timestamp(),
                entry_id,
                entry_to_move,
            )
            heapq.heappush(self._queues[model_id][new_priority], heap_entry)
            self._entry_lookup[entry_id] = (model_id, new_priority)

            logging.info(
                f"Moved entry {entry_id} from {current_priority.name} to "
                f"{new_priority.name} (escalation count: {entry_to_move.escalation_count})"
            )
            return True

    def get_state(
        self,
        model_id: int,
        provider_id: int = None,
    ) -> QueueStatePerPriority:
        """Queue depth breakdown by priority for a model.

        ``provider_id`` is accepted but ignored.
        """
        with self._lock:
            return QueueStatePerPriority(
                low=len(self._queues[model_id][Priority.LOW]),
                normal=len(self._queues[model_id][Priority.NORMAL]),
                high=len(self._queues[model_id][Priority.HIGH]),
            )

    def get_entries_for_priority(
        self,
        model_id: int,
        provider_id: Optional[Union[int, Priority]] = None,
        priority: Optional[Priority] = None,
    ) -> List[QueueEntry]:
        """Get all queue entries for a specific model and priority.

        Back-compat: callers that pass ``(model_id, provider_id, priority)``
        positionally — or supply ``provider_id=...`` as a keyword — keep
        working; the provider id is ignored under model-only queueing.
        Two-arg model-only callers ``(model_id, priority)`` also work: when
        the third argument is omitted, the second positional value is
        re-interpreted as the priority.
        """
        if priority is None:
            # Two-positional-arg model-only style: (model_id, priority).
            priority = provider_id
        # else: legacy three-arg style or provider_id= kwarg — middle value is
        # the (now-ignored) provider id; trust the explicit `priority` kwarg.
        if not isinstance(priority, Priority):
            raise TypeError("get_entries_for_priority requires a Priority value")

        with self._lock:
            queue = self._queues[model_id][priority]
            entries = [entry for (*_, entry) in queue]
            entries.sort(key=lambda e: e.enqueue_time)
            return entries

    def get_entry_info(self, entry_id: str) -> Optional[QueueEntry]:
        """Metadata about a specific queue entry."""
        with self._lock:
            if entry_id not in self._entry_lookup:
                return None
            model_id, priority = self._entry_lookup[entry_id]
            queue = self._queues[model_id][priority]
            for (*_, entry) in queue:
                if entry.entry_id == entry_id:
                    return entry
            return None

    def remove(self, entry_id: str) -> bool:
        """Remove a specific entry from the queue (cancellation)."""
        with self._lock:
            if entry_id not in self._entry_lookup:
                return False
            model_id, priority = self._entry_lookup[entry_id]
            queue = self._queues[model_id][priority]
            for i, (_, _, _, eid, _) in enumerate(queue):
                if eid == entry_id:
                    del queue[i]
                    heapq.heapify(queue)
                    del self._entry_lookup[entry_id]
                    logging.info(f"Removed entry {entry_id} from queue")
                    return True
            return False

    def is_empty(self) -> bool:
        """True if no tasks are queued across all models/priorities."""
        with self._lock:
            return all(len(queue) == 0 for model_queues in self._queues.values() for queue in model_queues.values())

    def get_total_depth_by_model(self, model_id: int) -> int:
        """Total queue depth for a model (all priorities combined)."""
        state = self.get_state(model_id)
        return state.total

    def get_total_depth_by_deployment(self, model_id: int, provider_id: int = None) -> int:
        """Back-compat alias for ``get_total_depth_by_model``.

        ``provider_id`` is accepted but ignored — with model-only queues every
        provider serving the model sees the same queue depth.
        """
        return self.get_total_depth_by_model(model_id)

    def has_cold_queued_entries(self, model_id: int, provider_id: int = None) -> bool:
        """Return True if any queued entry for ``model_id`` was flagged
        ``is_cold_at_queue`` at enqueue.

        Unpinned entries count for every provider; pinned entries count only
        for their required provider.
        """
        with self._lock:
            model_queues = self._queues.get(model_id)
            if not model_queues:
                return False
            for queue in model_queues.values():
                for (*_, entry) in queue:
                    eligible = provider_id is None or entry.provider_affinity in (None, provider_id)
                    if eligible and entry.is_cold_at_queue:
                        return True
            return False

    def get_total_depth_by_provider(self, provider_id: int = None) -> int:
        """Back-compat: total queued tasks. With model-only queues "per
        provider" no longer carries information, so this returns the total
        across all models.
        """
        return self.get_total_depth_all()

    def get_total_depth_all(self) -> int:
        """Total queued tasks across all models/priorities."""
        with self._lock:
            return len(self._entry_lookup)
