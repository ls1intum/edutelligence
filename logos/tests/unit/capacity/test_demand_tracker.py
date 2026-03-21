"""Tests for DemandTracker."""

import concurrent.futures

from logos.capacity.demand_tracker import DemandTracker


def test_record_request_increments():
    tracker = DemandTracker()
    tracker.record_request("model-a")
    tracker.record_request("model-a")
    tracker.record_request("model-b")

    assert tracker.get_score("model-a") == 2.0
    assert tracker.get_score("model-b") == 1.0
    assert tracker.get_raw_count("model-a") == 2


def test_decay_all():
    tracker = DemandTracker()
    tracker.record_request("model-a")
    tracker.record_request("model-a")

    tracker.decay_all()
    assert abs(tracker.get_score("model-a") - 1.9) < 0.01  # 2.0 * 0.95


def test_decay_removes_below_threshold():
    tracker = DemandTracker()
    tracker.record_request("model-a")

    # Decay many times until below 0.01
    for _ in range(200):
        tracker.decay_all()

    assert tracker.get_score("model-a") == 0.0
    assert tracker.get_ranked_models() == []


def test_get_ranked_models():
    tracker = DemandTracker()
    tracker.record_request("model-a")
    tracker.record_request("model-b")
    tracker.record_request("model-b")
    tracker.record_request("model-c")
    tracker.record_request("model-c")
    tracker.record_request("model-c")

    ranked = tracker.get_ranked_models()
    assert len(ranked) == 3
    assert ranked[0][0] == "model-c"
    assert ranked[1][0] == "model-b"
    assert ranked[2][0] == "model-a"


def test_untracked_model_returns_zero():
    tracker = DemandTracker()
    assert tracker.get_score("nonexistent") == 0.0
    assert tracker.get_raw_count("nonexistent") == 0


def test_thread_safety():
    tracker = DemandTracker()

    def record_batch(model_name, count):
        for _ in range(count):
            tracker.record_request(model_name)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(record_batch, f"m-{i}", 100) for i in range(4)]
        for f in futures:
            f.result()

    for i in range(4):
        assert tracker.get_raw_count(f"m-{i}") == 100


def test_get_stats():
    tracker = DemandTracker()
    tracker.record_request("model-a")
    stats = tracker.get_stats()
    assert "scores" in stats
    assert "raw_counts" in stats
    assert stats["raw_counts"]["model-a"] == 1


def test_decay_cleans_stale_metadata():
    """After demand decays to zero and >1h passes, raw_count and last_request are cleaned."""
    import time

    tracker = DemandTracker()
    tracker.record_request("old-model")

    # Decay until removed from demand
    for _ in range(200):
        tracker.decay_all()
    assert tracker.get_score("old-model") == 0.0

    # Metadata still exists (last_request is recent)
    assert tracker.get_raw_count("old-model") == 1

    # Simulate stale timestamp (>1h ago)
    with tracker._lock:
        tracker._last_request["old-model"] = time.time() - 3700

    tracker.decay_all()  # Should clean up stale metadata

    assert tracker.get_raw_count("old-model") == 0
    stats = tracker.get_stats()
    assert "old-model" not in stats["last_request"]
