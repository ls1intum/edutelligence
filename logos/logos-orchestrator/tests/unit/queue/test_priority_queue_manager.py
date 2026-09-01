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


class TestBackgroundAppOrdering:
    """Within one priority level, background-app entries dispatch in a
    bounded interleave with regular ones: one flagged, then two regular,
    repeating, each class in arrival order.

    The flag marks the ``x-app: cli-bg`` traffic (an agent's background
    calls, e.g. its auto-permission classifier) that a full queue of
    interactive traffic would otherwise starve for the whole wait window.
    The interleave gives it a fast lane without letting a steady flagged
    stream starve ordinary same-priority traffic: regular entries are
    guaranteed 2 of every 3 dispatch slots, so the worst-case wait behind
    a continuous flagged stream is two dispatches, not the whole queue.
    """

    def test_background_app_dequeues_before_older_regular_entry(self):
        mgr = PriorityQueueManager()
        mgr.enqueue(DummyTask("interactive"), model_id=5, priority=Priority.NORMAL)
        mgr.enqueue(DummyTask("classifier"), model_id=5, priority=Priority.NORMAL, background_app=True)
        assert mgr.dequeue(5).get_id() == "classifier"
        assert mgr.dequeue(5).get_id() == "interactive"

    def test_fifo_is_kept_within_each_class(self):
        mgr = PriorityQueueManager()
        mgr.enqueue(DummyTask("r1"), model_id=5, priority=Priority.NORMAL)
        mgr.enqueue(DummyTask("r2"), model_id=5, priority=Priority.NORMAL)
        mgr.enqueue(DummyTask("b1"), model_id=5, priority=Priority.NORMAL, background_app=True)
        mgr.enqueue(DummyTask("b2"), model_id=5, priority=Priority.NORMAL, background_app=True)
        # Interleave: flagged b1 first, then two regular (r1, r2), then the
        # next flagged (b2) — each class in arrival order.
        assert [mgr.dequeue(5).get_id() for _ in range(4)] == ["b1", "r1", "r2", "b2"]

    def test_flagged_stream_cannot_starve_regular_traffic(self):
        mgr = PriorityQueueManager()
        for i in range(1, 5):
            mgr.enqueue(DummyTask(f"b{i}"), model_id=5, priority=Priority.NORMAL, background_app=True)
        mgr.enqueue(DummyTask("r1"), model_id=5, priority=Priority.NORMAL)
        mgr.enqueue(DummyTask("r2"), model_id=5, priority=Priority.NORMAL)
        # The two regular entries dispatch before the second flagged one, no
        # matter how long the flagged stream in front of them is: the
        # interleave bounds their wait at two dispatches.
        assert [mgr.dequeue(5).get_id() for _ in range(6)] == ["b1", "r1", "r2", "b2", "b3", "b4"]

    def test_priority_still_dominates_the_flag(self):
        mgr = PriorityQueueManager()
        mgr.enqueue(DummyTask("bg-normal"), model_id=5, priority=Priority.NORMAL, background_app=True)
        mgr.enqueue(DummyTask("plain-high"), model_id=5, priority=Priority.HIGH)
        assert mgr.dequeue(5).get_id() == "plain-high"
        assert mgr.dequeue(5).get_id() == "bg-normal"

    def test_move_priority_keeps_the_flag(self):
        mgr = PriorityQueueManager()
        mgr.enqueue(DummyTask("plain-high"), model_id=5, priority=Priority.HIGH)
        moved = mgr.enqueue(DummyTask("bg-normal"), model_id=5, priority=Priority.NORMAL, background_app=True)
        assert mgr.move_priority(moved, Priority.HIGH)
        # Both are HIGH now: the escalated entry keeps its flag, so it still
        # comes before the plain one.
        assert mgr.dequeue(5).get_id() == "bg-normal"
        assert mgr.dequeue(5).get_id() == "plain-high"

    def test_entry_carries_the_flag(self):
        mgr = PriorityQueueManager()
        entry_id = mgr.enqueue(DummyTask(1), model_id=5, priority=Priority.NORMAL, background_app=True)
        assert mgr.get_entry_info(entry_id).background_app is True
        assert mgr.get_entry_info(mgr.enqueue(DummyTask(2), model_id=5)).background_app is False
