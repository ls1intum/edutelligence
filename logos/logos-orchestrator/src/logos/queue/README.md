# Priority Queue Subsystem

## Overview

The Priority Queue subsystem provides multi-level priority queue management for request scheduling. It maintains separate queues for each priority level (LOW, NORMAL, HIGH) per model.

**Design Philosophy:** The queue is a **pure data structure** - it provides queue operations but does NOT implement scheduling policy or automatic escalation. Schedulers control when and how tasks are escalated.

### Key Features

- **Three Priority Levels**: LOW=1, NORMAL=5, HIGH=10
- **Thread-Safe**: All operations protected with RLock for concurrent access
- **Per-Model Queues**: Independent queues for each model
- **Escalation Support**: Methods to move tasks between priority levels
- **Metadata Tracking**: Enqueue time, escalation count, wait time

### Ordering

Inside the queue, entries are ordered by:

1. **Bucket** — the `Priority` level the entry's `raw_priority` maps to
   (`Priority.from_int`: 10→HIGH, 1→LOW, everything else→NORMAL). A HIGH
   entry always dequeues before any NORMAL entry, regardless of the values
   below.
2. **Raw priority** — the full-precision integer the request resolved to on
   the 1..10 scale (key override > team priority > policy priority, see
   `pipeline.resolve_queue_priority`). The raw value refines ordering *inside*
   a bucket: a team at priority 7 dequeues before a plain 5 in NORMAL.
3. **Role rank** — the caller's tiebreak rank from
   `pipeline.queue_role_rank`: application keys (2) before admin keys (1),
   before developer/service traffic (0). This is the default intra-team
   ordering *application > app admin > developer*; unknown callers rank 0.
4. **FIFO** — enqueue time breaks remaining ties.

`enqueue` takes `raw_priority` (defaults to the bucket's level) and
`role_rank` (default 0). `move_priority` keeps the entry's role rank across
the escalated bucket. Note that log/monitoring consumers report the *bucket*
name (low/normal/high), so a raw 7 is logged as "normal".

### Queue Metrics Logging

Queue depths and request priorities are **logged to the database** by the pipeline (not by the queue itself):
- `pipeline.py` records queue metrics at enqueue and schedule events via the monitoring module
- Data is written to `log_entry`
- This enables analysis of queueing behavior and scheduler performance

## Core Components

### Priority (Enum)
Three priority levels: `Priority.LOW` (1), `Priority.NORMAL` (5), `Priority.HIGH` (10)

### QueueEntry (Data Class)
Metadata wrapper for queued tasks with tracking of enqueue time, escalation
count, wait time, the entry's `raw_priority` (full-precision queue value) and
`role_rank` (caller tiebreak rank).

### QueueStatePerPriority (Data Class)
Queue depth breakdown: `low`, `normal`, `high` counts plus `total` property.

### PriorityQueueManager (Main Class)
Thread-safe queue manager providing:

```python
# Core Operations
entry_id = queue_mgr.enqueue(task, model_id, priority,
                             raw_priority=5, role_rank=0)
task = queue_mgr.dequeue(model_id)  # Highest priority
task, entry = queue_mgr.dequeue_with_entry(model_id)

# Escalation
queue_mgr.move_priority(entry_id, new_priority)
entries = queue_mgr.get_entries_for_priority(model_id, priority)

# State Queries
state = queue_mgr.get_state(model_id)  # QueueStatePerPriority
total = queue_mgr.get_total_depth_by_deployment(model_id)
is_empty = queue_mgr.is_empty()
```

## Usage Example

```python
from logos.queue import PriorityQueueManager, Priority

queue_mgr = PriorityQueueManager()

# Enqueue with different priorities
queue_mgr.enqueue(task1, model_id=1, priority=Priority.LOW)
queue_mgr.enqueue(task2, model_id=1, priority=Priority.NORMAL)
queue_mgr.enqueue(task3, model_id=1, priority=Priority.HIGH)

# Dequeue returns highest priority first
task = queue_mgr.dequeue(model_id=1)  # Returns task3 (HIGH)

# Escalation (scheduler's responsibility)
low_entries = queue_mgr.get_entries_for_priority(model_id=1, Priority.LOW)
for entry in low_entries:
    if entry.wait_time_seconds > 300:  # 5 minutes
        queue_mgr.move_priority(entry.entry_id, Priority.NORMAL)

# Monitor queue state
state = queue_mgr.get_state(model_id=1)
print(f"Queue: {state.low}/{state.normal}/{state.high} (total={state.total})")
```

## Integration

**Schedulers** (`../pipeline/`): Use queue manager for request queuing and escalation
**SDI Facades** (`../sdi/`): Query queue state for availability decisions
**Pipeline** (`../pipeline/pipeline.py`): Logs queue depths to database for analysis
