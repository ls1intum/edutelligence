"""Tests for the model-only PriorityQueueManager (Phase 2).

The queue is now keyed solely by model_id; provider_id is accepted by every
public method but ignored. A request enqueued from one provider is visible
to (and dequeue-able by) any other provider serving the same model.
"""

from logos.queue import PriorityQueueManager
from logos.queue.models import Priority


class DummyTask:
    def __init__(self, tid):
        self._id = tid

    def get_id(self):
        return self._id


def test_enqueue_from_one_provider_dequeue_from_another():
    """Cross-provider dispatch: enqueue under provider_id=1 → dequeue while
    the calling provider claims provider_id=2. Both see the same queue."""
    mgr = PriorityQueueManager()
    mgr.enqueue(DummyTask(1), model_id=5, provider_id=1, priority=Priority.NORMAL)
    task = mgr.dequeue(model_id=5, provider_id=2)
    assert task is not None
    assert task.get_id() == 1


def test_state_is_model_wide_regardless_of_provider_arg():
    mgr = PriorityQueueManager()
    mgr.enqueue(DummyTask(1), model_id=5, provider_id=10, priority=Priority.NORMAL)
    mgr.enqueue(DummyTask(2), model_id=5, provider_id=20, priority=Priority.HIGH)
    s_a = mgr.get_state(5, provider_id=10)
    s_b = mgr.get_state(5, provider_id=999)
    assert s_a.total == 2 and s_b.total == 2
    assert s_a.normal == 1 and s_a.high == 1


def test_total_depth_by_deployment_shim_returns_model_total():
    mgr = PriorityQueueManager()
    mgr.enqueue(DummyTask(1), model_id=5, provider_id=10, priority=Priority.NORMAL)
    mgr.enqueue(DummyTask(2), model_id=5, provider_id=20, priority=Priority.NORMAL)
    # Both providers see the full model-level depth.
    assert mgr.get_total_depth_by_deployment(5, 10) == 2
    assert mgr.get_total_depth_by_deployment(5, 20) == 2


def test_get_total_depth_by_model_matches_aggregate():
    mgr = PriorityQueueManager()
    mgr.enqueue(DummyTask(1), model_id=5, provider_id=10, priority=Priority.NORMAL)
    mgr.enqueue(DummyTask(2), model_id=5, provider_id=20, priority=Priority.NORMAL)
    mgr.enqueue(DummyTask(3), model_id=6, provider_id=10, priority=Priority.NORMAL)
    assert mgr.get_total_depth_by_model(5) == 2
    assert mgr.get_total_depth_by_model(6) == 1
    assert mgr.get_total_depth_all() == 3


def test_priority_ordering_preserved_under_model_only():
    """High priority drains first regardless of which provider enqueued it."""
    mgr = PriorityQueueManager()
    mgr.enqueue(DummyTask("low-from-A"), model_id=5, provider_id=1, priority=Priority.LOW)
    mgr.enqueue(DummyTask("normal-from-B"), model_id=5, provider_id=2, priority=Priority.NORMAL)
    mgr.enqueue(DummyTask("high-from-C"), model_id=5, provider_id=3, priority=Priority.HIGH)

    # Any provider draining the queue gets HIGH first.
    assert mgr.dequeue(5, provider_id=99).get_id() == "high-from-C"
    assert mgr.dequeue(5, provider_id=99).get_id() == "normal-from-B"
    assert mgr.dequeue(5, provider_id=99).get_id() == "low-from-A"


def test_remove_works_regardless_of_provider_in_lookup():
    mgr = PriorityQueueManager()
    eid = mgr.enqueue(DummyTask(1), model_id=5, provider_id=1, priority=Priority.NORMAL)
    assert mgr.remove(eid) is True
    assert mgr.dequeue(5, provider_id=99) is None


def test_move_priority_works_under_model_only():
    mgr = PriorityQueueManager()
    eid = mgr.enqueue(DummyTask(1), model_id=5, provider_id=1, priority=Priority.LOW)
    assert mgr.move_priority(eid, Priority.HIGH) is True
    state = mgr.get_state(5)
    assert state.low == 0
    assert state.high == 1


def test_get_total_depth_by_provider_shim_returns_total():
    """Back-compat: get_total_depth_by_provider returns total across all
    models since per-provider depth has no meaning in model-only queue."""
    mgr = PriorityQueueManager()
    mgr.enqueue(DummyTask(1), model_id=5, provider_id=1, priority=Priority.NORMAL)
    mgr.enqueue(DummyTask(2), model_id=6, provider_id=1, priority=Priority.NORMAL)
    # Both providers see the full total — provider partition is gone.
    assert mgr.get_total_depth_by_provider(1) == 2
    assert mgr.get_total_depth_by_provider(99) == 2


def test_reassign_entries_no_longer_present():
    """Phase 2 deletes reassign_entries — there's nothing to reassign now."""
    mgr = PriorityQueueManager()
    assert not hasattr(mgr, "reassign_entries")
