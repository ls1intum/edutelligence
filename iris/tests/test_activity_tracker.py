import threading

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.domain.status.activity_dto import ActivityKind, ActivityState
from iris.pipeline.shared.activity_tracker import ActivityTracker


def test_start_start_finish_keeps_order_and_stable_ids():
    emitted = []
    tracker = ActivityTracker(lambda items, seq: emitted.append((seq, items)))

    first_id = tracker.start(ActivityKind.TOOL, "lecture_content_retrieval")
    second_id = tracker.start(ActivityKind.TOOL, "faq_content_retrieval")
    tracker.finish(first_id, result="2 sections")

    items, seq = tracker.snapshot()
    assert [item.id for item in items] == ["act-1", "act-2"]
    assert [item.state for item in items] == [
        ActivityState.FINISHED,
        ActivityState.RUNNING,
    ]
    assert items[0].result == "2 sections"
    assert items[0].duration_millis is not None
    assert seq == 3
    assert [entry[0] for entry in emitted] == [1, 2, 3]
    assert second_id == "act-2"


def test_seq_is_strictly_monotonic_across_mutations():
    emitted = []
    tracker = ActivityTracker(lambda unused_items, seq: emitted.append(seq))

    first_id = tracker.start(ActivityKind.TOOL, "a")
    second_id = tracker.start(ActivityKind.TOOL, "b")
    tracker.finish(first_id)
    tracker.fail(second_id)

    assert emitted == [1, 2, 3, 4]
    assert tracker.snapshot()[1] == 4


def test_snapshot_returns_copy():
    tracker = ActivityTracker(lambda unused_items, unused_seq: None)
    item_id = tracker.start(ActivityKind.TOOL, "a")

    items = tracker.snapshot()[0]
    items[0].state = ActivityState.FAILED
    items[0].name = "mutated"

    current_items = tracker.snapshot()[0]
    assert current_items[0].id == item_id
    assert current_items[0].state == ActivityState.RUNNING
    assert current_items[0].name == "a"


def test_thread_safety_smoke_counts_all_mutations():
    tracker = ActivityTracker(lambda unused_items, unused_seq: None)

    def run_items():
        for index in range(50):
            item_id = tracker.start(ActivityKind.TOOL, f"tool-{index}")
            tracker.finish(item_id)

    threads = [threading.Thread(target=run_items) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    items, seq = tracker.snapshot()
    assert len(items) == 400
    assert seq == 800
    assert all(item.state == ActivityState.FINISHED for item in items)


def test_unknown_item_id_does_not_raise_or_increment_seq():
    tracker = ActivityTracker(lambda unused_items, unused_seq: None)
    tracker.start(ActivityKind.TOOL, "a")

    tracker.finish("missing")
    tracker.fail("missing")

    assert tracker.snapshot()[1] == 1


def test_stale_emit_superseded_by_snapshot_seq():
    emitted = []
    gate = threading.Event()
    paused = threading.Event()

    def emit(items, seq):
        if seq == 1:
            paused.set()
            gate.wait(2)
        emitted.append((seq, [item.state for item in items]))

    tracker = ActivityTracker(emit)
    thread = threading.Thread(
        target=lambda: tracker.start(ActivityKind.TOOL, "lecture_content_retrieval")
    )
    thread.start()
    assert paused.wait(2)

    final_seq = tracker.authoritative_snapshot()[1]
    gate.set()
    thread.join(timeout=2)

    stale_seq = emitted[0][0]
    assert stale_seq == 1
    assert final_seq > stale_seq
