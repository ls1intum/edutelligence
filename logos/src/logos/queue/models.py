"""
Data models for the priority queue subsystem.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Any


class Priority(IntEnum):
    """
    Priority levels for request queuing.

    Higher numeric values = higher priority.
    Used for heap ordering (negated for max-heap behavior).
    """
    LOW = 1
    NORMAL = 5
    HIGH = 10

    @classmethod
    def from_int(cls, value: int) -> "Priority":
        """
        Convert integer priority to Priority enum.

        Maps:
        - 1 → LOW
        - 5 → NORMAL
        - 10 → HIGH
        - Other values → NORMAL (default)
        """
        try:
            return cls(value)
        except ValueError:
            # Default to NORMAL for unrecognized values
            return cls.NORMAL

    @classmethod
    def from_string(cls, value: str) -> "Priority":
        """
        Convert string priority to Priority enum.

        Maps (case-insensitive):
        - "low" → LOW
        - "normal", "medium", "mid" → NORMAL
        - "high", "critical" → HIGH
        """
        value_lower = value.lower().strip()

        if value_lower in ("low", "l"):
            return cls.LOW
        elif value_lower in ("normal", "medium", "mid", "n", "m"):
            return cls.NORMAL
        elif value_lower in ("high", "critical", "h", "c"):
            return cls.HIGH
        else:
            # Default to NORMAL
            return cls.NORMAL


@dataclass
class QueueEntry:
    """
    Metadata wrapper for a task in the priority queue.

    Tracks additional information beyond the task itself:
    - When it was enqueued
    - Original vs current priority (for escalation tracking)
    - Unique identifier for queue operations
    - How many times it has been escalated
    """

    entry_id: str
    """Unique identifier for this queue entry (e.g., 'qe-123-456')."""

    task: Any
    """The actual Task object from scheduler."""

    model_id: int
    """Which model this task is queued for."""

    original_priority: Priority
    """Priority when first enqueued."""

    current_priority: Priority
    """Current priority (may be escalated from original)."""

    enqueue_time: datetime = field(default_factory=datetime.now)
    """When this entry was added to the queue."""

    escalation_count: int = 0
    """Number of times this entry has been escalated."""

    last_escalation_time: datetime | None = None
    """When this entry was last escalated (None if never)."""

    @property
    def wait_time_seconds(self) -> float:
        """Calculate how long this entry has been waiting in queue."""
        return (datetime.now() - self.enqueue_time).total_seconds()

    @property
    def time_since_last_escalation_seconds(self) -> float | None:
        """
        Calculate time since last escalation.
        Returns None if never escalated.
        """
        if self.last_escalation_time is None:
            return None
        return (datetime.now() - self.last_escalation_time).total_seconds()

    def escalate(self, new_priority: Priority) -> None:
        """
        Record an escalation to a new priority level.

        Updates:
        - current_priority
        - escalation_count
        - last_escalation_time
        """
        self.current_priority = new_priority
        self.escalation_count += 1
        self.last_escalation_time = datetime.now()


@dataclass
class QueueStatePerPriority:
    """
    Queue depth breakdown by priority level for a specific model.

    Used by SDI to report queue state to schedulers.
    """

    low: int = 0
    """Number of LOW priority tasks queued."""

    normal: int = 0
    """Number of NORMAL priority tasks queued."""

    high: int = 0
    """Number of HIGH priority tasks queued."""

    @property
    def total(self) -> int:
        """Total number of tasks across all priority levels."""
        return self.low + self.normal + self.high

    def __repr__(self) -> str:
        return f"QueueState(low={self.low}, normal={self.normal}, high={self.high}, total={self.total})"
