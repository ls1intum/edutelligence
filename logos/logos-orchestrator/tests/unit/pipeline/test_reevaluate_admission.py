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


def test_batch_is_capped_by_live_engine_headroom():
    """Capacity says 256 slots; the engine can start 3 right now."""
    _facade, done = _dispatch(256, AdmissionDecision(can_admit=True, headroom=3), queued=10)
    assert sum(done) == 3


def test_nothing_is_dispatched_while_the_engine_is_backlogged():
    _facade, done = _dispatch(
        256,
        AdmissionDecision(can_admit=False, headroom=0, reason="backend_queue"),
        queued=5,
    )
    assert not any(done)


def test_capacity_still_binds_when_it_is_tighter_than_headroom():
    _facade, done = _dispatch(2, AdmissionDecision(can_admit=True, headroom=8), queued=5)
    assert sum(done) == 2


def test_worker_without_admission_signals_keeps_the_old_behaviour():
    """No usable signal → fall back to the capacity gate alone."""
    _facade, done = _dispatch(4, AdmissionDecision(can_admit=True, headroom=None), queued=10)
    assert sum(done) == 4


def test_facade_that_cannot_answer_is_not_treated_as_a_block():
    facade, done = _dispatch(4, None, queued=10)
    assert facade.admission_calls == 1
    assert sum(done) == 4
