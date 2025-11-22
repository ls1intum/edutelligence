# Priority Queue Subsystem

## Overview

The Priority Queue subsystem provides multi-level priority queue management for request scheduling. It maintains separate queues for each priority level (LOW, NORMAL, HIGH) per model.

### Key Features

- **Multi-level Priority Queues**: Three priority levels (LOW=1, NORMAL=5, HIGH=10)
- **Thread-Safe**: All operations protected with RLock for concurrent access
- **Escalation Support**: Methods to move tasks between priority levels
- **Per-Model Queues**: Independent queues for each model
- **Metadata Tracking**: Enqueue time, escalation count, wait time
- **Pure Data Structure**: No scheduling policy - that's the scheduler's job

### Design Philosophy

The queue subsystem is a **pure data structure** - it provides queue operations but does NOT implement scheduling policy or automatic escalation. Schedulers control when and how tasks are escalated using the exposed methods.

## Components

### 1. Priority Enum

```python
from logos.queue import Priority

# Three priority levels
Priority.LOW     # value = 1
Priority.NORMAL  # value = 5
Priority.HIGH    # value = 10

# Convert from various sources
priority = Priority.from_int(10)          # → Priority.HIGH
priority = Priority.from_string("high")   # → Priority.HIGH
priority = Priority.from_string("medium") # → Priority.NORMAL
```

### 2. QueueEntry

Metadata wrapper for queued tasks:

```python
@dataclass
class QueueEntry:
    entry_id: str                       # Unique identifier
    task: Any                           # The actual Task object
    model_id: int                       # Which model this task is for
    original_priority: Priority         # Priority when first enqueued
    current_priority: Priority          # Current priority (after escalations)
    enqueue_time: datetime             # When added to queue
    escalation_count: int = 0          # Number of escalations
    last_escalation_time: datetime | None = None

    @property
    def wait_time_seconds(self) -> float:
        """How long this entry has been waiting."""

    @property
    def time_since_last_escalation_seconds(self) -> float | None:
        """Time since last escalation (None if never escalated)."""
```

### 3. QueueStatePerPriority

Queue depth breakdown by priority level:

```python
@dataclass
class QueueStatePerPriority:
    low: int = 0        # Number of LOW priority tasks
    normal: int = 0     # Number of NORMAL priority tasks
    high: int = 0       # Number of HIGH priority tasks

    @property
    def total(self) -> int:
        """Total tasks across all priorities."""
        return self.low + self.normal + self.high
```

### 4. PriorityQueueManager

Thread-safe queue manager:

```python
from logos.queue import PriorityQueueManager, Priority

queue_mgr = PriorityQueueManager()

# Core Operations
entry_id = queue_mgr.enqueue(task, model_id=1, priority=Priority.HIGH)
task = queue_mgr.dequeue(model_id=1)  # Returns highest priority task
task, priority = queue_mgr.peek(model_id=1)  # Look without removing

# Escalation Support
queue_mgr.move_priority(entry_id, Priority.HIGH)  # Escalate to HIGH
entries = queue_mgr.get_entries_for_priority(model_id=1, Priority.LOW)

# State Queries
state = queue_mgr.get_state(model_id=1)  # QueueStatePerPriority
print(f"Queue: low={state.low}, normal={state.normal}, high={state.high}")

# Utility
models = queue_mgr.get_all_models()  # Models with queued tasks
is_empty = queue_mgr.is_empty()      # True if no tasks anywhere
```

## Usage Examples

### Basic Enqueueing and Dequeueing

```python
from logos.queue import PriorityQueueManager, Priority
from logos.scheduling.scheduler import Task

queue_mgr = PriorityQueueManager()

# Enqueue tasks with different priorities
task1 = Task(data={'prompt': '...'}, models=[(1, 1.0, 1, 2)], task_id=1)
task2 = Task(data={'prompt': '...'}, models=[(1, 1.0, 5, 2)], task_id=2)
task3 = Task(data={'prompt': '...'}, models=[(1, 1.0, 10, 2)], task_id=3)

queue_mgr.enqueue(task1, model_id=1, priority=Priority.LOW)
queue_mgr.enqueue(task2, model_id=1, priority=Priority.NORMAL)
queue_mgr.enqueue(task3, model_id=1, priority=Priority.HIGH)

# Dequeue returns highest priority first
task = queue_mgr.dequeue(model_id=1)  # Returns task3 (HIGH priority)
task = queue_mgr.dequeue(model_id=1)  # Returns task2 (NORMAL priority)
task = queue_mgr.dequeue(model_id=1)  # Returns task1 (LOW priority)
```

### Time-Based Escalation (Scheduler Responsibility)

```python
import time
from datetime import datetime

# Get all LOW priority entries that need escalation
low_entries = queue_mgr.get_entries_for_priority(model_id=1, priority=Priority.LOW)

for entry in low_entries:
    # Check if entry has been waiting > 5 minutes
    if entry.wait_time_seconds > 300:
        print(f"Escalating task {entry.task.get_id()} from LOW to NORMAL")
        queue_mgr.move_priority(entry.entry_id, Priority.NORMAL)
```

### Monitoring Queue State

```python
# Get queue state for SDI reporting
state = queue_mgr.get_state(model_id=1)

print(f"Model 1 Queue State:")
print(f"  LOW priority:    {state.low} tasks")
print(f"  NORMAL priority: {state.normal} tasks")
print(f"  HIGH priority:   {state.high} tasks")
print(f"  Total:           {state.total} tasks")

# Use in scheduling decisions
if state.total > 10:
    print("Model 1 is heavily loaded")
```

### Canceling Requests

```python
# Enqueue a task
entry_id = queue_mgr.enqueue(task, model_id=1, priority=Priority.NORMAL)

# Later, cancel it
success = queue_mgr.remove(entry_id)
if success:
    print(f"Request {entry_id} canceled")
```

## Integration with Scheduler

The SimplePriorityScheduler (reference implementation) demonstrates how schedulers use the queue manager:

```python
from logos.scheduling.simple_priority_scheduler import SimplePriorityScheduler
from logos.queue import PriorityQueueManager

queue_mgr = PriorityQueueManager()
scheduler = SimplePriorityScheduler(
    queue_manager=queue_mgr,
    escalation_check_interval=30.0  # Check escalations every 30 seconds
)

# SimplePriorityScheduler is a reference implementation showing integration patterns
# Custom schedulers can use the same queue manager with different scheduling logic
# See src/logos/scheduling/simple_priority_scheduler.py for implementation details
```

## Integration with SDI

SDI facades query the queue manager for queue state:

```python
from logos.sdi.ollama_facade import OllamaSchedulingDataFacade
from logos.queue import PriorityQueueManager

queue_mgr = PriorityQueueManager()

# Queue manager is REQUIRED for Ollama facade
facade = OllamaSchedulingDataFacade(queue_mgr, db_manager=None)

# SDI reports queue state per priority level
status = facade.get_model_status(model_id=1)
print(f"Queue state: {status.queue_state.low}/{status.queue_state.normal}/{status.queue_state.high}")
```

## Testing

Comprehensive integration tests in `tests/scheduling_data/`:

```bash
./tests/scheduling_data/test_scheduling_data.sh
```

Tests cover:
- Queue + SDI + Scheduler integration
- Request lifecycle (enqueue → execute → complete → queue drain)
- Priority ordering with real execution
- Mixed Azure + Ollama workloads
- Rate limit handling and cold start scenarios
- Thread safety and concurrent execution

## FAQs

**Q: Why separate queue subsystem from scheduler?**
A: Clean separation of concerns. Queue = data structure, Scheduler = policy. Different schedulers can use the same queue with different escalation strategies.

## Support

For issues or questions:
- Check integration tests: `tests/scheduling_data/`
- See examples: `src/logos/scheduling/simple_priority_scheduler.py`
- Read SDI docs: `src/logos/sdi/README.md`
