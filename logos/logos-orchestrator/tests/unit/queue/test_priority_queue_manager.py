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


class TestSloFastLaneOrdering:
    """Within one priority level, request-SLO fast-lane entries dispatch in
    a bounded interleave with regular ones: one fast-lane, then two
    regular, repeating, each class in arrival order.

    The fast lane is the request-SLO attribute for ``x-app: cli-bg``
    traffic (an agent's background calls, e.g. its auto-permission
    classifier) that a full queue of interactive traffic would otherwise
    starve for the whole wait window. The interleave gives it a lane
    without letting a steady fast-lane stream starve ordinary
    same-priority traffic: regular entries are guaranteed 2 of every 3
    dispatch slots, so the worst-case wait behind a continuous fast-lane
    stream is two dispatches, not the whole queue.
    """

    def test_slo_fast_lane_dequeues_before_older_regular_entry(self):
        mgr = PriorityQueueManager()
        mgr.enqueue(DummyTask("interactive"), model_id=5, priority=Priority.NORMAL)
        mgr.enqueue(DummyTask("classifier"), model_id=5, priority=Priority.NORMAL, slo_fast_lane=True)
        assert mgr.dequeue(5).get_id() == "classifier"
        assert mgr.dequeue(5).get_id() == "interactive"

    def test_fifo_is_kept_within_each_class(self):
        mgr = PriorityQueueManager()
        mgr.enqueue(DummyTask("r1"), model_id=5, priority=Priority.NORMAL)
        mgr.enqueue(DummyTask("r2"), model_id=5, priority=Priority.NORMAL)
        mgr.enqueue(DummyTask("b1"), model_id=5, priority=Priority.NORMAL, slo_fast_lane=True)
        mgr.enqueue(DummyTask("b2"), model_id=5, priority=Priority.NORMAL, slo_fast_lane=True)
        # Interleave: flagged b1 first, then two regular (r1, r2), then the
        # next flagged (b2) — each class in arrival order.
        assert [mgr.dequeue(5).get_id() for _ in range(4)] == ["b1", "r1", "r2", "b2"]

    def test_flagged_stream_cannot_starve_regular_traffic(self):
        mgr = PriorityQueueManager()
        for i in range(1, 5):
            mgr.enqueue(DummyTask(f"b{i}"), model_id=5, priority=Priority.NORMAL, slo_fast_lane=True)
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
            mgr.enqueue(DummyTask(f"b{i}"), model_id=5, priority=Priority.NORMAL, slo_fast_lane=True)
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
        mgr.enqueue(DummyTask("b1"), model_id=5, priority=Priority.NORMAL, slo_fast_lane=True)
        mgr.enqueue(DummyTask("r1"), model_id=5, priority=Priority.NORMAL)
        mgr.enqueue(DummyTask("r2"), model_id=5, priority=Priority.NORMAL)
        assert mgr.dequeue(5).get_id() == "b1"
        # b2 lands right after b1 dispatched, while r1/r2 are still queued.
        mgr.enqueue(DummyTask("b2"), model_id=5, priority=Priority.NORMAL, slo_fast_lane=True)
        assert [mgr.dequeue(5).get_id() for _ in range(3)] == ["r1", "r2", "b2"]

    def test_peek_returns_the_dispatch_head(self):
        """peek agrees with dequeue: mid-cycle (a flagged dispatch and one
        regular dispatch behind) the head is the regular entry even though a
        flagged one is still waiting."""
        mgr = PriorityQueueManager()
        mgr.enqueue(DummyTask("b1"), model_id=5, priority=Priority.NORMAL, slo_fast_lane=True)
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
        mgr.enqueue(DummyTask("bg-normal"), model_id=5, priority=Priority.NORMAL, slo_fast_lane=True)
        mgr.enqueue(DummyTask("plain-high"), model_id=5, priority=Priority.HIGH)
        assert mgr.dequeue(5).get_id() == "plain-high"
        assert mgr.dequeue(5).get_id() == "bg-normal"

    def test_flag_cannot_jump_a_higher_raw_priority(self):
        """The interleave only reorders entries tied on (raw_priority,
        role_rank): a flagged entry at raw 5 must not dispatch ahead of a
        regular entry at raw 7, even though the flagged slot is owed on a
        fresh level."""
        mgr = PriorityQueueManager()
        mgr.enqueue(DummyTask("regular-7"), model_id=5, priority=Priority.NORMAL, raw_priority=7, role_rank=0)
        mgr.enqueue(
            DummyTask("flagged-5"),
            model_id=5,
            priority=Priority.NORMAL,
            raw_priority=5,
            role_rank=0,
            slo_fast_lane=True,
        )
        assert mgr.dequeue(5).get_id() == "regular-7"
        assert mgr.dequeue(5).get_id() == "flagged-5"

    def test_flag_cannot_jump_a_higher_role_rank(self):
        """Same, for the role-rank tiebreak: a flagged developer request
        (rank 0) must not dispatch ahead of a regular application request
        (rank 2) at the same raw priority — the flag cannot override the
        application > app admin > developer ordering."""
        mgr = PriorityQueueManager()
        mgr.enqueue(
            DummyTask("flagged-dev"),
            model_id=5,
            priority=Priority.NORMAL,
            raw_priority=5,
            role_rank=0,
            slo_fast_lane=True,
        )
        mgr.enqueue(DummyTask("regular-app"), model_id=5, priority=Priority.NORMAL, raw_priority=5, role_rank=2)
        assert mgr.dequeue(5).get_id() == "regular-app"
        assert mgr.dequeue(5).get_id() == "flagged-dev"

    def test_interleave_still_applies_within_the_tied_group(self):
        """The restriction is scoped to the tied group: entries sharing the
        highest (raw_priority, role_rank) pair still dispatch in the bounded
        interleave, and lower-priority regular traffic only advances once
        that group is drained."""
        mgr = PriorityQueueManager()
        mgr.enqueue(
            DummyTask("flagged-7"),
            model_id=5,
            priority=Priority.NORMAL,
            raw_priority=7,
            role_rank=0,
            slo_fast_lane=True,
        )
        mgr.enqueue(DummyTask("regular-7"), model_id=5, priority=Priority.NORMAL, raw_priority=7, role_rank=0)
        mgr.enqueue(DummyTask("regular-5"), model_id=5, priority=Priority.NORMAL, raw_priority=5, role_rank=0)
        # Tied group (7, 0) first: the flagged slot is owed on a fresh
        # level, then its regular entry; only then does the raw-5 go.
        assert [mgr.dequeue(5).get_id() for _ in range(3)] == ["flagged-7", "regular-7", "regular-5"]

    def test_move_priority_keeps_the_flag(self):
        mgr = PriorityQueueManager()
        mgr.enqueue(DummyTask("plain-high"), model_id=5, priority=Priority.HIGH)
        moved = mgr.enqueue(DummyTask("bg-normal"), model_id=5, priority=Priority.NORMAL, slo_fast_lane=True)
        assert mgr.move_priority(moved, Priority.HIGH)
        # Both are HIGH now: the escalated entry keeps its flag, so it still
        # comes before the plain one.
        assert mgr.dequeue(5).get_id() == "bg-normal"
        assert mgr.dequeue(5).get_id() == "plain-high"

    def test_entry_carries_the_flag(self):
        mgr = PriorityQueueManager()
        entry_id = mgr.enqueue(DummyTask(1), model_id=5, priority=Priority.NORMAL, slo_fast_lane=True)
        assert mgr.get_entry_info(entry_id).slo_fast_lane is True
        assert mgr.get_entry_info(mgr.enqueue(DummyTask(2), model_id=5)).slo_fast_lane is False


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


def test_default_priority_ranks_with_explicit_normal_by_role_rank():
    """Regression: a request with everything unset resolves to NORMAL's raw
    value (5), so it sits level with explicit NORMAL (5) traffic in the same
    bucket and the role-rank tiebreak applies between them. With the old
    raw_priority=0 the default entry ranked *below* explicit NORMAL and a
    higher role rank on it could never win."""
    mgr = PriorityQueueManager()
    # Default caller (application key, rank 2) resolved to NORMAL's raw 5 ...
    mgr.enqueue(
        DummyTask(1),
        model_id=5,
        priority=Priority.from_int(int(Priority.NORMAL)),
        raw_priority=int(Priority.NORMAL),
        role_rank=2,
    )
    # ... next to an explicit NORMAL (raw 5) developer request (rank 0).
    mgr.enqueue(DummyTask(2), model_id=5, priority=Priority.NORMAL, raw_priority=5, role_rank=0)

    # Same bucket, same raw: the higher role rank dequeues first.
    assert mgr.dequeue(5).get_id() == 1
    assert mgr.dequeue(5).get_id() == 2


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


def test_queued_entries_are_countable_by_caller_key():
    mgr = PriorityQueueManager()
    mgr.enqueue(DummyTask(1), model_id=5, api_key_id=7)
    mgr.enqueue(DummyTask(2), model_id=5, api_key_id=7)
    mgr.enqueue(DummyTask(3), model_id=5, api_key_id=9)
    mgr.enqueue(DummyTask(4), model_id=5)

    assert mgr.get_queued_by_api_key(5) == {7: 2, 9: 1}
    assert mgr.get_queued_by_api_key(99) == {}
