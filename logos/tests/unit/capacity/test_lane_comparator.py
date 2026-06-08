"""Tests for the lane_comparator module (Phase 1.4 — single tie-break source)."""

from logos.capacity.lane_comparator import best_lane, lane_sort_key
from logos.sdi.models import LaneSchedulerSignals


def _lane(
    lane_id: str = "lane",
    runtime_state: str = "loaded",
    sleep_state: str = "awake",
    queue_waiting: float = 0.0,
    requests_running: float = 0.0,
    active_requests: int = 0,
    ttft_p95_seconds: float = 0.0,
    effective_vram_mb: float = 0.0,
) -> LaneSchedulerSignals:
    return LaneSchedulerSignals(
        lane_id=lane_id,
        model_name="m",
        runtime_state=runtime_state,
        sleep_state=sleep_state,
        is_vllm=True,
        active_requests=active_requests,
        queue_waiting=queue_waiting,
        requests_running=requests_running,
        gpu_cache_usage_percent=None,
        ttft_p95_seconds=ttft_p95_seconds,
        e2e_latency_p50_seconds=0.0,
        effective_vram_mb=effective_vram_mb,
        num_parallel=0,
    )


def test_state_rank_running_beats_loaded_beats_sleeping():
    a = _lane("a", runtime_state="running")
    b = _lane("b", runtime_state="loaded")
    c = _lane("c", runtime_state="sleeping")
    assert best_lane([c, b, a]).lane_id == "a"
    assert best_lane([c, a, b]).lane_id == "a"
    # Without running, loaded wins over sleeping
    assert best_lane([c, b]).lane_id == "b"


def test_lower_queue_wait_wins_within_state():
    a = _lane("a", runtime_state="loaded", queue_waiting=10.0)
    b = _lane("b", runtime_state="loaded", queue_waiting=2.0)
    assert best_lane([a, b]).lane_id == "b"


def test_lower_running_wins_when_queue_tied():
    a = _lane("a", runtime_state="loaded", queue_waiting=0.0, requests_running=5.0)
    b = _lane("b", runtime_state="loaded", queue_waiting=0.0, requests_running=1.0)
    assert best_lane([a, b]).lane_id == "b"


def test_lower_active_requests_wins():
    a = _lane("a", queue_waiting=0.0, requests_running=0.0, active_requests=4)
    b = _lane("b", queue_waiting=0.0, requests_running=0.0, active_requests=1)
    assert best_lane([a, b]).lane_id == "b"


def test_lower_ttft_p95_wins():
    a = _lane("a", ttft_p95_seconds=2.5)
    b = _lane("b", ttft_p95_seconds=0.5)
    assert best_lane([a, b]).lane_id == "b"


def test_more_effective_vram_wins_at_tail():
    # All earlier dimensions tied → larger effective_vram_mb is preferred
    # (negated in the sort key).
    a = _lane("a", effective_vram_mb=1024.0)
    b = _lane("b", effective_vram_mb=4096.0)
    assert best_lane([a, b]).lane_id == "b"


def test_lane_id_alphabetical_final_tiebreaker():
    a = _lane("zzz")
    b = _lane("aaa")
    assert best_lane([a, b]).lane_id == "aaa"


def test_unknown_runtime_state_sinks_to_bottom():
    a = _lane("a", runtime_state="banana")
    b = _lane("b", runtime_state="sleeping")
    assert best_lane([a, b]).lane_id == "b"


def test_best_lane_empty():
    assert best_lane([]) is None


def test_lane_sort_key_returns_tuple():
    key = lane_sort_key(_lane("x"))
    assert isinstance(key, tuple)
    assert len(key) == 7
