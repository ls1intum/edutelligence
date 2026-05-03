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
    mgr.enqueue(DummyTask(1), model_id=10, priority=Priority.NORMAL)
    mgr.enqueue(DummyTask(2), model_id=10, priority=Priority.HIGH)
    state = mgr.get_state(10)
    assert state.high == 1
    assert state.normal == 1
    assert state.low == 0

    peek_task, peek_priority = mgr.peek(10)
    assert peek_task.get_id() == 2
    assert peek_priority == Priority.HIGH


def test_dequeue_respects_priority_then_fifo():
    mgr = PriorityQueueManager()
    mgr.enqueue(DummyTask("h1"), model_id=1, priority=Priority.HIGH)
    mgr.enqueue(DummyTask("h2"), model_id=1, priority=Priority.HIGH)
    mgr.enqueue(DummyTask("n1"), model_id=1, priority=Priority.NORMAL)

    first = mgr.dequeue(1)
    second = mgr.dequeue(1)
    third = mgr.dequeue(1)

    assert first.get_id() == "h1"
    assert second.get_id() == "h2"
    assert third.get_id() == "n1"
    assert mgr.dequeue(1) is None


def test_dequeue_specific_priority():
    mgr = PriorityQueueManager()
    mgr.enqueue(DummyTask("low"), model_id=2, priority=Priority.LOW)
    mgr.enqueue(DummyTask("hi"), model_id=2, priority=Priority.HIGH)

    normal_none = mgr.dequeue(2, priority=Priority.NORMAL)
    assert normal_none is None

    high_task = mgr.dequeue(2, priority=Priority.HIGH)
    assert high_task.get_id() == "hi"

    low_task = mgr.dequeue(2, priority=Priority.LOW)
    assert low_task.get_id() == "low"


def test_move_priority_updates_state_and_lookup():
    mgr = PriorityQueueManager()
    entry_id = mgr.enqueue(DummyTask(1), model_id=3, priority=Priority.LOW)
    moved = mgr.move_priority(entry_id, Priority.HIGH)
    assert moved is True
    state = mgr.get_state(3)
    assert state.high == 1
    assert state.low == 0

    peek_task, peek_priority = mgr.peek(3)
    assert peek_priority == Priority.HIGH
    assert peek_task.get_id() == 1


def test_remove_entry_decrements_depth():
    mgr = PriorityQueueManager()
    entry_id = mgr.enqueue(DummyTask(1), model_id=4, priority=Priority.NORMAL)
    removed = mgr.remove(entry_id)
    assert removed is True
    state = mgr.get_state(4)
    assert state.normal == 0
    assert mgr.dequeue(4) is None


def test_get_total_depth_by_model():
    mgr = PriorityQueueManager()
    mgr.enqueue(DummyTask("a"), model_id=10, priority=Priority.HIGH)
    mgr.enqueue(DummyTask("b"), model_id=10, priority=Priority.NORMAL)
    mgr.enqueue(DummyTask("c"), model_id=20, priority=Priority.LOW)

    assert mgr.get_total_depth_by_model(10) == 2
    assert mgr.get_total_depth_by_model(20) == 1
    assert mgr.get_total_depth_by_model(99) == 0


def test_get_total_depth_all():
    mgr = PriorityQueueManager()
    mgr.enqueue(DummyTask("a"), model_id=10, priority=Priority.HIGH)
    mgr.enqueue(DummyTask("b"), model_id=20, priority=Priority.LOW)

    assert mgr.get_total_depth_all() == 2


def test_backward_compat_provider_id_kwarg_ignored():
    """provider_id kwarg is accepted and silently ignored (backward compat)."""
    mgr = PriorityQueueManager()
    mgr.enqueue(DummyTask(1), model_id=5, provider_id=99, priority=Priority.NORMAL)
    state = mgr.get_state(5, provider_id=99)
    assert state.normal == 1
    task = mgr.dequeue(5, provider_id=99)
    assert task.get_id() == 1


def test_two_models_isolated():
    """Tasks for different model_ids do not interfere."""
    mgr = PriorityQueueManager()
    mgr.enqueue(DummyTask("m1"), model_id=100, priority=Priority.HIGH)
    mgr.enqueue(DummyTask("m2"), model_id=200, priority=Priority.HIGH)

    assert mgr.dequeue(100).get_id() == "m1"
    assert mgr.dequeue(200).get_id() == "m2"
    assert mgr.dequeue(100) is None
    assert mgr.dequeue(200) is None
