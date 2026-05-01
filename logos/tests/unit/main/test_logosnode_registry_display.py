"""Tests for logosnode_registry display helpers.

Covers:
- _lane_log_snapshot: waiting/running sourced from backend_metrics scrape only.
- _render_lane_summary: new "waiting=/running=" format.
- _render_lane_diff: reports waiting/running deltas, not active.
"""

from __future__ import annotations

from logos.logosnode_registry import (
    _lane_log_snapshot,
    _render_lane_diff,
    _render_lane_summary,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_lane(
    *,
    lane_id: str = "lane-1",
    model: str = "test-model",
    active_requests: int = 0,
    backend_metrics: dict | None = None,
) -> dict:
    return {
        "lane_id": lane_id,
        "model": model,
        "runtime_state": "loaded",
        "sleep_state": "awake",
        "active_requests": active_requests,
        "effective_vram_mb": 8000.0,
        "backend_metrics": backend_metrics if backend_metrics is not None else {},
    }


# ---------------------------------------------------------------------------
# _lane_log_snapshot
# ---------------------------------------------------------------------------


def test_snapshot_with_backend_metrics_uses_scrape_values() -> None:
    lane = _make_lane(
        active_requests=5,  # leaky counter — must NOT be surfaced
        backend_metrics={
            "queue_waiting": 2.0,
            "requests_running": 1.0,
            "gpu_cache_usage_percent": 42.5,
            "prefix_cache_hit_rate": 0.511,
        },
    )
    snap = _lane_log_snapshot(lane)
    assert snap["queue_waiting"] == 2.0
    assert snap["requests_running"] == 1.0


def test_snapshot_without_backend_metrics_returns_none_for_waiting_and_running() -> (
    None
):
    """When backend_metrics is absent the snapshot must store None (renders as --)."""
    lane = _make_lane(active_requests=3, backend_metrics={})
    snap = _lane_log_snapshot(lane)
    assert snap["queue_waiting"] is None
    assert snap["requests_running"] is None


def test_snapshot_no_fallback_to_active_requests() -> None:
    """Even when active_requests > 0, missing scrape data yields None (not the leaky count)."""
    lane = _make_lane(active_requests=7, backend_metrics={})
    snap = _lane_log_snapshot(lane)
    assert snap["requests_running"] is None


def test_snapshot_zero_is_preserved_not_treated_as_missing() -> None:
    """A scraped value of 0 is legitimate and must be stored as 0, not None."""
    lane = _make_lane(
        backend_metrics={"queue_waiting": 0.0, "requests_running": 0.0},
    )
    snap = _lane_log_snapshot(lane)
    assert snap["queue_waiting"] == 0.0
    assert snap["requests_running"] == 0.0


# ---------------------------------------------------------------------------
# _render_lane_summary
# ---------------------------------------------------------------------------


def _snap(backend_metrics: dict | None = None, **lane_kwargs) -> dict:
    return _lane_log_snapshot(
        _make_lane(backend_metrics=backend_metrics, **lane_kwargs)
    )


def test_render_summary_with_metrics_shows_waiting_and_running() -> None:
    snap = _snap(backend_metrics={"queue_waiting": 3.0, "requests_running": 1.0})
    rendered = "\n".join(_render_lane_summary(snap))
    assert "waiting=3.0" in rendered
    assert "running=1.0" in rendered
    # Old fields must not appear in the summary line
    assert "active=" not in rendered
    assert "run=" not in rendered


def test_render_summary_without_metrics_shows_dashes() -> None:
    snap = _snap(backend_metrics={})
    rendered = "\n".join(_render_lane_summary(snap))
    assert "waiting=--" in rendered
    assert "running=--" in rendered


def test_render_summary_does_not_expose_active_counter() -> None:
    """active= must never appear in the rendered output, even with a non-zero counter."""
    snap = _snap(
        active_requests=99,
        backend_metrics={"queue_waiting": 0.0, "requests_running": 1.0},
    )
    rendered = "\n".join(_render_lane_summary(snap))
    assert "active=" not in rendered


# ---------------------------------------------------------------------------
# _render_lane_diff
# ---------------------------------------------------------------------------


def _make_snap(**overrides) -> dict:
    base = {
        "lane_id": "lane-1",
        "model": "m",
        "runtime_state": "loaded",
        "sleep_state": "awake",
        "active_requests": 0,
        "effective_vram_mb": 8000.0,
        "queue_waiting": None,
        "requests_running": None,
        "gpu_cache_usage_percent": None,
        "prefix_cache_hit_rate": None,
        "ttft_p95_seconds": None,
        "gpu_devices": "0",
    }
    base.update(overrides)
    return base


def test_diff_renderer_reports_waiting_delta() -> None:
    old = _make_snap(queue_waiting=0.0)
    new = _make_snap(queue_waiting=5.0)
    diff_lines = _render_lane_diff(old, new)
    combined = "\n".join(diff_lines)
    assert "queue" in combined
    assert "0.0" in combined
    assert "5.0" in combined


def test_diff_renderer_reports_running_delta() -> None:
    old = _make_snap(requests_running=0.0)
    new = _make_snap(requests_running=3.0)
    diff_lines = _render_lane_diff(old, new)
    combined = "\n".join(diff_lines)
    assert "running" in combined
    assert "0.0" in combined
    assert "3.0" in combined


def test_diff_renderer_does_not_emit_active_field() -> None:
    """The diff renderer must not produce an 'active:' change line."""
    old = _make_snap(active_requests=1)
    new = _make_snap(active_requests=5)
    diff_lines = _render_lane_diff(old, new)
    combined = "\n".join(diff_lines)
    assert "active:" not in combined


def test_diff_renderer_no_change_shows_no_tracked_fields() -> None:
    snap = _make_snap(requests_running=1.0, queue_waiting=0.0)
    diff_lines = _render_lane_diff(snap, snap)
    assert any("no tracked field changes" in line for line in diff_lines)
