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

    def test_interleave_holds_after_quiescent_regular_traffic(self):
        """The 1:2 bound must hold for the manager's lifetime, not just per
        burst: after regular arrivals that fully drain the queue, a flagged
        burst still takes at most one of every three dispatch slots.

        With enqueue-time ranks the burst's slots (0, 3, 6, ...) all sat
        below the next regular entry's rank-derived slot, so the whole burst
        dispatched back-to-back before any resumed regular traffic. The
        cursor is derived from actual dequeues, so no such drift exists.
        """
        mgr = PriorityQueueManager()
        # Six prior regular arrivals, each dequeued before the next: the old
        # regular rank counter advanced to 6 while the queue sat empty.
        for i in range(1, 7):
            mgr.enqueue(DummyTask(f"old{i}"), model_id=5, priority=Priority.NORMAL)
            mgr.dequeue(5)
        # A flagged burst arrives after the quiescent period, then regular
        # traffic resumes.
        for i in range(1, 5):
            mgr.enqueue(DummyTask(f"b{i}"), model_id=5, priority=Priority.NORMAL, background_app=True)
        for i in range(7, 10):
            mgr.enqueue(DummyTask(f"r{i}"), model_id=5, priority=Priority.NORMAL)
        # Bounded interleave: the burst may not dispatch back-to-back. The
        # last two flagged entries only go consecutively because every
        # regular entry is gone by then — nothing is left to starve.
        assert [mgr.dequeue(5).get_id() for _ in range(7)] == ["b1", "r7", "r8", "b2", "r9", "b3", "b4"]

    def test_new_flagged_arrival_waits_for_the_regular_pair(self):
        """A flagged entry arriving while regulars are waiting takes the
        next flagged slot of the cycle, not both regular slots: a fresh
        arrival never outranks entries already queued (a rank reset to 0 at
        that moment would have given it exactly that)."""
        mgr = PriorityQueueManager()
        mgr.enqueue(DummyTask("b1"), model_id=5, priority=Priority.NORMAL, background_app=True)
        mgr.enqueue(DummyTask("r1"), model_id=5, priority=Priority.NORMAL)
        mgr.enqueue(DummyTask("r2"), model_id=5, priority=Priority.NORMAL)
        assert mgr.dequeue(5).get_id() == "b1"
        # b2 lands right after b1 dispatched, while r1/r2 are still queued.
        mgr.enqueue(DummyTask("b2"), model_id=5, priority=Priority.NORMAL, background_app=True)
        assert [mgr.dequeue(5).get_id() for _ in range(3)] == ["r1", "r2", "b2"]

    def test_peek_returns_the_dispatch_head(self):
        """peek agrees with dequeue: mid-cycle (a flagged dispatch and one
        regular dispatch behind) the head is the regular entry even though a
        flagged one is still waiting."""
        mgr = PriorityQueueManager()
        mgr.enqueue(DummyTask("b1"), model_id=5, priority=Priority.NORMAL, background_app=True)
        mgr.enqueue(DummyTask("r1"), model_id=5, priority=Priority.NORMAL)
        mgr.enqueue(DummyTask("r2"), model_id=5, priority=Priority.NORMAL)
        task, priority = mgr.peek(5)
        assert (task.get_id(), priority) == ("b1", Priority.NORMAL)
        assert mgr.dequeue(5).get_id() == "b1"
        task, priority = mgr.peek(5)
        assert (task.get_id(), priority) == ("r1", Priority.NORMAL)
        assert mgr.dequeue(5).get_id() == "r1"

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
