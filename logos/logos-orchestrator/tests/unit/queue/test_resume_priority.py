"""Priority.RESUME (#815): the stream-resume level sits above every other
queued priority and round-trips through the integer encoding."""

from logos.queue.models import Priority, QueueStatePerPriority
from logos.queue.priority_queue import PriorityQueueManager


def _task(name: str) -> dict:
    return {"id": name}


def test_resume_is_above_high():
    assert int(Priority.RESUME) > int(Priority.HIGH)
    assert Priority.from_int(int(Priority.RESUME)) is Priority.RESUME


def test_resume_jumps_every_other_priority():
    q = PriorityQueueManager()
    model = 7

    # Enqueued in the "wrong" order on purpose: a resume landing late must
    # still be served before anything already waiting.
    low_id = q.enqueue(_task("low"), model, priority=Priority.LOW)
    normal_id = q.enqueue(_task("normal"), model, priority=Priority.NORMAL)
    high_id = q.enqueue(_task("high"), model, priority=Priority.HIGH)
    resume_id = q.enqueue(_task("resume"), model, priority=Priority.RESUME)
    assert {low_id, normal_id, high_id, resume_id}

    assert q.dequeue(model)["id"] == "resume"
    assert q.dequeue(model)["id"] == "high"
    assert q.dequeue(model)["id"] == "normal"
    assert q.dequeue(model)["id"] == "low"
    assert q.dequeue(model) is None


def test_resume_orders_across_models_independently():
    q = PriorityQueueManager()
    q.enqueue(_task("a-low"), 1, priority=Priority.LOW)
    q.enqueue(_task("b-resume"), 2, priority=Priority.RESUME)

    # A resume on one model never preempts traffic on another model.
    assert q.dequeue(1)["id"] == "a-low"
    assert q.dequeue(2)["id"] == "b-resume"


def test_peek_prefers_resume():
    q = PriorityQueueManager()
    q.enqueue(_task("normal"), 3, priority=Priority.NORMAL)
    q.enqueue(_task("resume"), 3, priority=Priority.RESUME)

    task, priority = q.peek(3)
    assert task["id"] == "resume"
    assert priority is Priority.RESUME


def test_get_state_reports_resume_level():
    q = PriorityQueueManager()
    q.enqueue(_task("resume"), 4, priority=Priority.RESUME)
    q.enqueue(_task("high"), 4, priority=Priority.HIGH)

    state = q.get_state(4)
    assert state.resume == 1
    assert state.high == 1
    assert state.total == 2


def test_state_total_includes_resume():
    state = QueueStatePerPriority(low=1, normal=2, high=3, resume=4)
    assert state.total == 10
