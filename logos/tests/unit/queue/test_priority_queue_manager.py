import pytest

from logos.queue import PriorityQueueManager
from logos.queue.models import Priority


class DummyTask:
    def __init__(self, tid):
        self._id = tid

    def get_id(self):
        return self._id


def test_enqueue_updates_depth_and_peek_order():
    mgr = PriorityQueueManager()
    provider_id = 1
    mgr.enqueue(DummyTask(1), model_id=10, provider_id=provider_id, priority=Priority.NORMAL)
    mgr.enqueue(DummyTask(2), model_id=10, provider_id=provider_id, priority=Priority.HIGH)
    state = mgr.get_state(10, provider_id)
    assert state.high == 1
    assert state.normal == 1
    assert state.low == 0

    peek_task, peek_priority = mgr.peek(10, provider_id)
    assert peek_task.get_id() == 2
    assert peek_priority == Priority.HIGH


def test_dequeue_respects_priority_then_fifo():
    mgr = PriorityQueueManager()
    provider_id = 1
    # Two highs, one normal
    mgr.enqueue(DummyTask("h1"), model_id=1, provider_id=provider_id, priority=Priority.HIGH)
    mgr.enqueue(DummyTask("h2"), model_id=1, provider_id=provider_id, priority=Priority.HIGH)
    mgr.enqueue(DummyTask("n1"), model_id=1, provider_id=provider_id, priority=Priority.NORMAL)

    first = mgr.dequeue(1, provider_id)
    second = mgr.dequeue(1, provider_id)
    third = mgr.dequeue(1, provider_id)

    assert first.get_id() == "h1"
    assert second.get_id() == "h2"
    assert third.get_id() == "n1"
    assert mgr.dequeue(1, provider_id) is None


def test_dequeue_specific_priority():
    mgr = PriorityQueueManager()
    provider_id = 1
    mgr.enqueue(DummyTask("low"), model_id=2, provider_id=provider_id, priority=Priority.LOW)
    mgr.enqueue(DummyTask("hi"), model_id=2, provider_id=provider_id, priority=Priority.HIGH)

    normal_none = mgr.dequeue(2, provider_id, priority=Priority.NORMAL)
    assert normal_none is None

    high_task = mgr.dequeue(2, provider_id, priority=Priority.HIGH)
    assert high_task.get_id() == "hi"

    low_task = mgr.dequeue(2, provider_id, priority=Priority.LOW)
    assert low_task.get_id() == "low"


def test_move_priority_updates_state_and_lookup():
    mgr = PriorityQueueManager()
    provider_id = 1
    entry_id = mgr.enqueue(DummyTask(1), model_id=3, provider_id=provider_id, priority=Priority.LOW)
    moved = mgr.move_priority(entry_id, Priority.HIGH)
    assert moved is True
    state = mgr.get_state(3, provider_id)
    assert state.high == 1
    assert state.low == 0

    peek_task, peek_priority = mgr.peek(3, provider_id)
    assert peek_priority == Priority.HIGH
    assert peek_task.get_id() == 1


def test_remove_entry_decrements_depth():
    mgr = PriorityQueueManager()
    provider_id = 1
    entry_id = mgr.enqueue(DummyTask(1), model_id=4, provider_id=provider_id, priority=Priority.NORMAL)
    removed = mgr.remove(entry_id)
    assert removed is True
    state = mgr.get_state(4, provider_id)
    assert state.normal == 0
    assert mgr.dequeue(4, provider_id) is None
