from streamlab.checkpoint import BarrierAligner
from streamlab.model import Record
from streamlab.state import partition_snapshot, restore_worker
from streamlab.watermarks import WatermarkTracker


def test_snapshot_round_trip_at_same_parallelism():
    values = {"customer-1": 4, "customer-2": 9, "customer-3": -2}
    snapshot = partition_snapshot(values, 2)
    restored = restore_worker(snapshot, 0, 2) | restore_worker(snapshot, 1, 2)
    assert restored == values


def test_ordered_barriers_emit_checkpoint():
    state = {"customer-1": 7}
    aligner = BarrierAligner(2)
    checkpoint, _ = aligner.handle_barrier(0, 4, lambda: state)
    assert checkpoint is None
    checkpoint, replay = aligner.handle_barrier(1, 4, lambda: state)
    assert checkpoint is not None
    assert checkpoint.state == state
    assert replay == []


def test_watermark_uses_slowest_active_input():
    tracker = WatermarkTracker(2, idle_timeout_ms=100)
    tracker.observe_record(0, 10)
    tracker.observe_record(1, 10)
    tracker.observe_watermark(0, 80, 20)
    tracker.observe_watermark(1, 60, 20)
    assert tracker.current(30) == 60


def test_records_before_any_barrier_are_forwarded():
    aligner = BarrierAligner(2)
    record = Record(1, "customer-7", 25, 3)
    assert aligner.handle_record(record) == [record]
