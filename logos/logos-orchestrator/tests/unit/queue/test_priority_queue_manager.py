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
