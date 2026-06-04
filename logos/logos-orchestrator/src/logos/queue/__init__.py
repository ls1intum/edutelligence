"""
Priority Queue Subsystem for Logos Scheduling.

This subsystem provides priority-aware queue management for request scheduling.
It maintains separate queues per priority level (LOW, NORMAL, HIGH) for each model.

Key Components:
- PriorityQueueManager: Thread-safe queue operations
- QueueEntry: Metadata wrapper for queued tasks
- QueueStatePerPriority: Queue depth breakdown by priority
- Priority: Enum for priority levels

The queue manager is a pure data structure - it does NOT implement scheduling
policy or escalation logic. Those are the responsibility of the Scheduler.
"""

from logos.queue.models import Priority, QueueEntry, QueueStatePerPriority
from logos.queue.priority_queue import PriorityQueueManager

__all__ = [
    "Priority",
    "QueueEntry",
    "QueueStatePerPriority",
    "PriorityQueueManager",
]
