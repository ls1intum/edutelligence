from datetime import datetime, timedelta

from logos.queue import Priority, PriorityQueueManager
from logos.queue import priority_queue as priority_queue_module


class DummyTask:
    def __init__(self, tid):
        self._id = tid

    def get_id(self):
        return self._id


class _FakeDateTime(datetime):
    """Deterministic, strictly increasing now() for FIFO assertions."""

    counter = 0

    @classmethod
    def now(cls, tz=None):  # noqa: ARG003
        cls.counter += 1
        return datetime(2026, 1, 1) + timedelta(seconds=cls.counter)

    @classmethod
    def reset(cls):
        cls.counter = 0


def test_backward_compat_provider_id_kwarg_ignored():
    """provider_id kwarg is accepted and silently ignored (backward compat)."""
    mgr = PriorityQueueManager()
    mgr.enqueue(DummyTask(1), model_id=5, provider_id=99, priority=Priority.NORMAL)
    state = mgr.get_state(5, provider_id=99)
    assert state.normal == 1
    task = mgr.dequeue(5, provider_id=99)
    assert task.get_id() == 1


def test_has_cold_queued_entries_false_when_no_cold_flag():
    mgr = PriorityQueueManager()
    mgr.enqueue(DummyTask(1), model_id=5, provider_id=1, priority=Priority.NORMAL)
    assert mgr.has_cold_queued_entries(5, 1) is False


def test_has_cold_queued_entries_true_when_any_entry_flagged():
    mgr = PriorityQueueManager()
    mgr.enqueue(DummyTask(1), model_id=5, provider_id=1, priority=Priority.NORMAL)
    mgr.enqueue(
        DummyTask(2),
        model_id=5,
        provider_id=1,
        priority=Priority.HIGH,
        is_cold_at_queue=True,
    )
    assert mgr.has_cold_queued_entries(5, 1) is True


def test_has_cold_queued_entries_provider_id_ignored():
    """Model-only queue: provider_id arg is accepted but ignored. Any cold-
    flagged entry on the model is visible regardless of which provider_id the
    caller passes (queue is shared across providers)."""
    mgr = PriorityQueueManager()
    mgr.enqueue(
        DummyTask(1),
        model_id=5,
        provider_id=1,
        priority=Priority.NORMAL,
        is_cold_at_queue=True,
    )
    assert mgr.has_cold_queued_entries(5, 1) is True
    # provider_id=2 still sees the same cold-queued entry.
    assert mgr.has_cold_queued_entries(5, 2) is True


def test_has_cold_queued_entries_scoped_to_model():
    mgr = PriorityQueueManager()
    mgr.enqueue(
        DummyTask(1),
        model_id=5,
        provider_id=1,
        priority=Priority.NORMAL,
        is_cold_at_queue=True,
    )
    # Different model on the same provider: no cold-queued entries.
    assert mgr.has_cold_queued_entries(6, 1) is False


def test_has_cold_queued_entries_clears_after_dequeue():
    mgr = PriorityQueueManager()
    mgr.enqueue(
        DummyTask(1),
        model_id=5,
        provider_id=1,
        priority=Priority.NORMAL,
        is_cold_at_queue=True,
    )
    assert mgr.has_cold_queued_entries(5, 1) is True
    mgr.dequeue(5, provider_id=1)
    assert mgr.has_cold_queued_entries(5, 1) is False


def test_role_rank_orders_within_equal_priority():
    """Within one priority, application keys (rank 2) dequeue before admin
    keys (rank 1), which dequeue before developer traffic (rank 0) — the
    default intra-team ordering application > app admin > developer."""
    mgr = PriorityQueueManager()
    for tid, rank in ((1, 0), (2, 1), (3, 2)):
        mgr.enqueue(DummyTask(tid), model_id=5, priority=Priority.NORMAL, role_rank=rank)

    assert mgr.dequeue(5).get_id() == 3
    assert mgr.dequeue(5).get_id() == 2
    assert mgr.dequeue(5).get_id() == 1


def test_role_rank_default_zero_waits_behind_ranked_traffic():
    """Callers that do not set a rank (benchmarks, internal jobs) queue at
    rank 0 and wait behind interactive traffic of the same priority."""
    mgr = PriorityQueueManager()
    mgr.enqueue(DummyTask(1), model_id=5, priority=Priority.NORMAL)  # no rank → 0
    mgr.enqueue(DummyTask(2), model_id=5, priority=Priority.NORMAL, role_rank=1)

    assert mgr.dequeue(5).get_id() == 2
    assert mgr.dequeue(5).get_id() == 1


def test_fifo_within_equal_priority_and_rank(monkeypatch):
    _FakeDateTime.reset()
    monkeypatch.setattr(priority_queue_module, "datetime", _FakeDateTime)
    mgr = PriorityQueueManager()
    for tid in (1, 2, 3):
        mgr.enqueue(DummyTask(tid), model_id=5, priority=Priority.NORMAL, role_rank=1)

    assert mgr.dequeue(5).get_id() == 1
    assert mgr.dequeue(5).get_id() == 2
    assert mgr.dequeue(5).get_id() == 3


def test_raw_priority_refines_ordering_inside_a_bucket():
    """Team priorities between the 1/5/10 buckets keep their exact value: a
    team at 7 dequeues before a plain 5 inside NORMAL."""
    mgr = PriorityQueueManager()
    mgr.enqueue(DummyTask(1), model_id=5, priority=Priority.NORMAL, raw_priority=5, role_rank=0)
    mgr.enqueue(DummyTask(2), model_id=5, priority=Priority.NORMAL, raw_priority=7, role_rank=0)

    assert mgr.dequeue(5).get_id() == 2
    assert mgr.dequeue(5).get_id() == 1


def test_bucket_still_dominates_raw_priority_and_role():
    """A HIGH entry (raw 10) dequeues before any NORMAL entry, whatever its
    raw value or role rank; the bucket comes first."""
    mgr = PriorityQueueManager()
    mgr.enqueue(DummyTask(1), model_id=5, priority=Priority.NORMAL, raw_priority=7, role_rank=2)
    mgr.enqueue(DummyTask(2), model_id=5, priority=Priority.HIGH, raw_priority=10, role_rank=0)

    assert mgr.dequeue(5).get_id() == 2
    assert mgr.dequeue(5).get_id() == 1


def test_role_rank_beats_raw_priority_only_inside_the_same_bucket():
    """Across buckets the raw priority decides; a rank-0 HIGH entry still
    beats a rank-2 NORMAL entry."""
    mgr = PriorityQueueManager()
    mgr.enqueue(DummyTask(1), model_id=5, priority=Priority.NORMAL, raw_priority=5, role_rank=2)
    mgr.enqueue(DummyTask(2), model_id=5, priority=Priority.HIGH, raw_priority=10, role_rank=0)

    assert mgr.dequeue(5).get_id() == 2


def test_move_priority_preserves_role_rank():
    """Escalation changes the bucket, not the caller's tiebreak rank: a rank-2
    entry escalated to HIGH still dequeues before a rank-0 HIGH entry."""
    mgr = PriorityQueueManager()
    low = mgr.enqueue(DummyTask(1), model_id=5, priority=Priority.HIGH, role_rank=0)
    normal_app = mgr.enqueue(DummyTask(2), model_id=5, priority=Priority.NORMAL, role_rank=2)

    assert mgr.move_priority(normal_app, Priority.HIGH) is True

    assert mgr.dequeue(5).get_id() == 2  # escalated app key, rank preserved
    assert mgr.dequeue(5).get_id() == 1
    assert mgr.get_entry_info(low) is None
