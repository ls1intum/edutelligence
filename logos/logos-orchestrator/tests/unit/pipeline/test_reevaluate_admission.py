"""The queue dispatcher must not drain the orchestrator queue onto one worker.

``reevaluate_model_queues`` runs after a lane loads or wakes and releases
queued futures in a batch. Sized only by the worker's total parallel capacity
it would hand the engine far more requests than it can begin serving — and
once forwarded, those requests can no longer be reordered by priority,
re-routed to a peer, or given back when the worker wants to drain. The batch
is therefore capped by the engine's live headroom.
"""

import asyncio
from unittest.mock import MagicMock

from logos.pipeline.correcting_scheduler import ClassificationCorrectingScheduler
from logos.queue import PriorityQueueManager
from logos.queue.priority_queue import Priority
from logos.sdi.models import AdmissionDecision

MODEL_ID = 7
PROVIDER_ID = 3


class _Facade:
    """Minimal logosnode facade for the dispatcher path."""

    def __init__(self, capacity: int, admission: AdmissionDecision | None):
        self._capacity = capacity
        self._admission = admission
        self.admission_calls = 0

    def is_provider_online(self, provider_id):
        return True

    def is_model_lane_ready(self, model_id, provider_id):
        return True

    def get_model_status(self, model_id, provider_id):
        status = MagicMock()
        status.active_requests = 0
        status.is_loaded = True
        status.queue_depth = 0
        return status

    def get_parallel_capacity(self, model_id, provider_id):
        return (self._capacity, "runtime")

    def get_capacity_info(self, provider_id):
        cap = MagicMock()
        cap.available_vram_mb = 32000
        return cap

    def get_provider_name(self, provider_id):
        return f"worker-{provider_id}"

    def get_model_name(self, model_id, provider_id):
        return "model-a"

    def evaluate_admission(self, model_id, provider_id):
        self.admission_calls += 1
        if self._admission is None:
            raise KeyError(provider_id)
        return self._admission


def _dispatch(capacity, admission, queued):
    facade = _Facade(capacity, admission)
    scheduler = ClassificationCorrectingScheduler(
        queue_manager=PriorityQueueManager(),
        logosnode_facade=facade,
        azure_facade=MagicMock(),
    )
    scheduler.update_model_registry({(MODEL_ID, PROVIDER_ID): "logosnode"})

    loop = asyncio.new_event_loop()
    try:
        futures = [loop.create_future() for _ in range(queued)]
        for future in futures:
            scheduler._queue_mgr.enqueue(future, MODEL_ID, PROVIDER_ID, Priority.NORMAL)
        scheduler.reevaluate_model_queues("model-a")
        # The dispatcher resolves futures via call_soon_threadsafe; turn the
        # loop once so the callbacks actually land.
        loop.run_until_complete(asyncio.sleep(0))
        return facade, [future.done() for future in futures]
    finally:
        loop.close()


def test_the_batch_is_bounded_by_what_the_lane_signals_justify():
    """Capacity says 256 slots; the lane signals justify releasing 3."""
    _facade, done = _dispatch(256, AdmissionDecision(can_admit=True, batch_limit=3), queued=10)
    assert sum(done) == 3


def test_nothing_is_dispatched_while_the_engine_is_backlogged():
    _facade, done = _dispatch(
        256,
        AdmissionDecision(can_admit=False, batch_limit=0, reason="backend_queue"),
        queued=5,
    )
    assert not any(done)


def test_capacity_still_binds_when_it_is_tighter_than_the_batch():
    _facade, done = _dispatch(2, AdmissionDecision(can_admit=True, batch_limit=8), queued=5)
    assert sum(done) == 2


def test_worker_without_admission_signals_keeps_the_old_behaviour():
    """No usable signal → fall back to the capacity gate alone."""
    _facade, done = _dispatch(4, AdmissionDecision(can_admit=True, batch_limit=None), queued=10)
    assert sum(done) == 4


def test_facade_that_cannot_answer_is_not_treated_as_a_block():
    facade, done = _dispatch(4, None, queued=10)
    assert facade.admission_calls == 1
    assert sum(done) == 4


# ---------------------------------------------------------------------------
# A worker report is what un-holds a paced request
#
# The forwarding gate spends a per-report budget, so a fresh report restores
# it. Nothing else would: the only other trigger is a completion, and on a
# ramp from idle nothing has completed yet.
# ---------------------------------------------------------------------------


def test_a_worker_report_releases_what_the_budget_was_holding():
    facade = _Facade(256, AdmissionDecision(can_admit=True, batch_limit=2))
    scheduler = ClassificationCorrectingScheduler(
        queue_manager=PriorityQueueManager(),
        logosnode_facade=facade,
        azure_facade=MagicMock(),
    )
    scheduler.update_model_registry({(MODEL_ID, PROVIDER_ID): "logosnode"})

    loop = asyncio.new_event_loop()
    try:
        futures = [loop.create_future() for _ in range(6)]
        for future in futures:
            scheduler._queue_mgr.enqueue(future, MODEL_ID, PROVIDER_ID, Priority.NORMAL)

        scheduler.on_worker_report(PROVIDER_ID)
        loop.run_until_complete(asyncio.sleep(0))
        assert sum(f.done() for f in futures) == 2, "one report is worth one step"

        scheduler.on_worker_report(PROVIDER_ID)
        loop.run_until_complete(asyncio.sleep(0))
        assert sum(f.done() for f in futures) == 4, "the next report is worth another"
    finally:
        loop.close()


def test_a_report_from_a_backlogged_worker_releases_nothing():
    facade = _Facade(256, AdmissionDecision(can_admit=False, batch_limit=0, reason="backend_queue"))
    scheduler = ClassificationCorrectingScheduler(
        queue_manager=PriorityQueueManager(),
        logosnode_facade=facade,
        azure_facade=MagicMock(),
    )
    scheduler.update_model_registry({(MODEL_ID, PROVIDER_ID): "logosnode"})

    loop = asyncio.new_event_loop()
    try:
        futures = [loop.create_future() for _ in range(3)]
        for future in futures:
            scheduler._queue_mgr.enqueue(future, MODEL_ID, PROVIDER_ID, Priority.NORMAL)
        scheduler.on_worker_report(PROVIDER_ID)
        loop.run_until_complete(asyncio.sleep(0))
        assert not any(f.done() for f in futures)
    finally:
        loop.close()
