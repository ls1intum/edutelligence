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


# ---------------------------------------------------------------------------
# Phase 2E: Burst detection
# ---------------------------------------------------------------------------


def test_is_burst_false_below_threshold():
    """Below threshold requests should not trigger burst."""
    tracker = DemandTracker()
    for _ in range(4):
        tracker.record_request("model-a")
    assert tracker.is_burst("model-a") is False


def test_is_burst_true_at_threshold():
    """At or above threshold should trigger burst."""
    tracker = DemandTracker()
    for _ in range(5):
        tracker.record_request("model-a")
    assert tracker.is_burst("model-a") is True


def test_burst_increases_demand_score():
    """During burst, demand score should increase faster (1.5x per request)."""
    tracker = DemandTracker()
    # First 4 requests: normal (1.0 each) = 4.0
    for _ in range(4):
        tracker.record_request("model-a")
    score_before_burst = tracker.get_score("model-a")
    assert score_before_burst == 4.0

    # 5th request triggers burst multiplier
    tracker.record_request("model-a")
    score_after = tracker.get_score("model-a")
    assert score_after == 4.0 + 1.5  # 5th request at 1.5x


def test_is_burst_untracked_model():
    """Untracked model should not be in burst."""
    tracker = DemandTracker()
    assert tracker.is_burst("nonexistent") is False


def test_burst_counts_in_stats():
    """Stats should include burst counts."""
    tracker = DemandTracker()
    for _ in range(6):
        tracker.record_request("model-a")
    stats = tracker.get_stats()
    assert "burst_counts" in stats
    assert stats["burst_counts"]["model-a"] == 6


def test_is_burst_custom_window_and_threshold():
    """Custom window and threshold parameters should work."""
    tracker = DemandTracker()
    for _ in range(3):
        tracker.record_request("model-a")
    # Default threshold (5): not burst
    assert tracker.is_burst("model-a") is False
    # Custom threshold (3): burst
    assert tracker.is_burst("model-a", threshold=3) is True
