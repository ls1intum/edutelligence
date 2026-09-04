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


def test_eligible_provider_set_blocks_failed_provider_from_dequeue():
    """A retry entry carries the pipeline's filtered deployment set: the
    excluded (failed) provider must not dequeue it, an eligible peer can."""
    mgr = PriorityQueueManager()
    mgr.enqueue(
        DummyTask(1),
        model_id=5,
        priority=Priority.NORMAL,
        eligible_provider_ids=frozenset({2}),
    )

    # The failed provider's lane release finds nothing it may dispatch.
    assert mgr.dequeue(5, provider_id=1) is None
    # The entry is still queued ...
    assert mgr.get_total_depth_by_model(5) == 1
    # ... and the eligible peer takes it.
    task = mgr.dequeue(5, provider_id=2)
    assert task is not None and task.get_id() == 1


def test_resume_priority_entry_stays_on_eligible_provider():
    """Same guarantee at RESUME priority: a stream-resume entry may not be
    dequeued by the node it is failing over from."""
    mgr = PriorityQueueManager()
    mgr.enqueue(
        DummyTask(1),
        model_id=5,
        priority=Priority.RESUME,
        eligible_provider_ids=frozenset({2}),
    )

    assert mgr.dequeue(5, provider_id=1, priority=Priority.RESUME) is None
    task, entry = mgr.dequeue_with_entry(5, provider_id=2, priority=Priority.RESUME)
    assert task is not None and task.get_id() == 1
    assert entry.current_priority is Priority.RESUME


def test_eligible_provider_set_scopes_cold_entry_visibility():
    """A cold retry entry that a provider may not dispatch must not count as
    its cold-queued demand — waking that lane for it would be wasted."""
    mgr = PriorityQueueManager()
    mgr.enqueue(
        DummyTask(1),
        model_id=5,
        priority=Priority.NORMAL,
        is_cold_at_queue=True,
        eligible_provider_ids=frozenset({2}),
    )

    assert mgr.has_cold_queued_entries(5, 1) is False
    assert mgr.has_cold_queued_entries(5, 2) is True
