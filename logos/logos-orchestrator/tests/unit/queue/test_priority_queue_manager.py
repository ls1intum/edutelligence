from logos.queue import Priority, PriorityQueueManager


class DummyTask:
    def __init__(self, tid):
        self._id = tid

    def get_id(self):
        return self._id


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


class TestWorkAwareOrdering:
    """Within one priority level, shorter estimated work dispatches first.

    This is what keeps a small latency-sensitive request from waiting for
    every long-running request that arrived before it when the queue fills
    under load — the failure mode behind Claude Code auto-classifier
    timeouts (#828).
    """

    def test_short_request_dequeues_before_long_one_within_same_priority(self):
        mgr = PriorityQueueManager()
        mgr.enqueue(DummyTask("long"), model_id=5, priority=Priority.NORMAL, work_estimate=50_000)
        mgr.enqueue(DummyTask("short"), model_id=5, priority=Priority.NORMAL, work_estimate=2_000)
        assert mgr.dequeue(5).get_id() == "short"
        assert mgr.dequeue(5).get_id() == "long"

    def test_fifo_is_kept_for_equal_work_estimates(self):
        mgr = PriorityQueueManager()
        mgr.enqueue(DummyTask("first"), model_id=5, priority=Priority.NORMAL, work_estimate=100)
        mgr.enqueue(DummyTask("second"), model_id=5, priority=Priority.NORMAL, work_estimate=100)
        assert mgr.dequeue(5).get_id() == "first"
        assert mgr.dequeue(5).get_id() == "second"

    def test_priority_still_dominates_the_work_estimate(self):
        mgr = PriorityQueueManager()
        mgr.enqueue(DummyTask("big-high"), model_id=5, priority=Priority.HIGH, work_estimate=100_000)
        mgr.enqueue(DummyTask("small-normal"), model_id=5, priority=Priority.NORMAL, work_estimate=10)
        assert mgr.dequeue(5).get_id() == "big-high"
        assert mgr.dequeue(5).get_id() == "small-normal"

    def test_unknown_work_sorts_after_estimated_work(self):
        """0 = could not estimate: the request is never assumed short."""
        mgr = PriorityQueueManager()
        mgr.enqueue(DummyTask("unknown"), model_id=5, priority=Priority.NORMAL)
        mgr.enqueue(DummyTask("known"), model_id=5, priority=Priority.NORMAL, work_estimate=100)
        assert mgr.dequeue(5).get_id() == "known"
        assert mgr.dequeue(5).get_id() == "unknown"

    def test_unknown_work_keeps_fifo_among_itself(self):
        mgr = PriorityQueueManager()
        mgr.enqueue(DummyTask("u1"), model_id=5, priority=Priority.NORMAL)
        mgr.enqueue(DummyTask("u2"), model_id=5, priority=Priority.NORMAL)
        assert mgr.dequeue(5).get_id() == "u1"
        assert mgr.dequeue(5).get_id() == "u2"

    def test_move_priority_keeps_the_work_estimate(self):
        mgr = PriorityQueueManager()
        mgr.enqueue(DummyTask("high-small"), model_id=5, priority=Priority.HIGH, work_estimate=100)
        moved = mgr.enqueue(DummyTask("normal-large"), model_id=5, priority=Priority.NORMAL, work_estimate=50_000)
        assert mgr.move_priority(moved, Priority.HIGH)
        # Both are HIGH now: the escalated entry keeps its (large) estimate,
        # so it still comes after the small one.
        assert mgr.dequeue(5).get_id() == "high-small"
        assert mgr.dequeue(5).get_id() == "normal-large"

    def test_entry_carries_its_work_estimate(self):
        mgr = PriorityQueueManager()
        entry_id = mgr.enqueue(DummyTask(1), model_id=5, priority=Priority.NORMAL, work_estimate=1234)
        assert mgr.get_entry_info(entry_id).work_estimate == 1234
        assert mgr.get_entry_info(mgr.enqueue(DummyTask(2), model_id=5)).work_estimate == 0
