"""Tests for the admission and yielding logic.

These are the decisions that keep the runner from stealing capacity out from
under users, so they are tested against payloads shaped like the orchestrator's
real `scheduler_state` response rather than against mocks of our own reading.
"""

from __future__ import annotations

import pytest
from app import capacity
from app.config import settings


def scheduler_state(models: list[dict], queue_total: int = 0) -> dict:
    """Build a payload in the orchestrator's debug_state() shape."""
    return {
        "queue_total": queue_total,
        "logosnode": {
            "providers": {
                "1": {
                    "name": "node-a",
                    "models": {str(i): m for i, m in enumerate(models)},
                }
            }
        },
    }


def loaded(active: int, capacity_: int, queue_depth: int = 0) -> dict:
    return {
        "model_name": "qwen",
        "active": active,
        "max_capacity": capacity_,
        "queue_depth": queue_depth,
        "loaded": True,
    }


class TestParseSchedulerState:
    def test_idle_fleet_reads_as_zero_load(self):
        reading = capacity.parse_scheduler_state(scheduler_state([loaded(0, 8)]))
        assert reading.ok
        assert reading.load == 0.0
        assert reading.total_slots == 8

    def test_load_is_the_busy_share_of_loaded_slots(self):
        reading = capacity.parse_scheduler_state(scheduler_state([loaded(2, 8), loaded(2, 8)]))
        assert reading.load == pytest.approx(0.25)
        assert reading.busy_slots == 4
        assert reading.total_slots == 16

    def test_unloaded_models_contribute_no_capacity(self):
        # An unloaded model's slots do not exist yet. Counting them would make
        # a node with nothing resident look like a mostly-idle one.
        payload = scheduler_state([loaded(4, 4)])
        payload["logosnode"]["providers"]["1"]["models"]["9"] = {
            "model_name": "cold",
            "active": 0,
            "max_capacity": 32,
            "loaded": False,
        }
        reading = capacity.parse_scheduler_state(payload)
        assert reading.total_slots == 4
        assert reading.load == 1.0

    def test_nothing_resident_reads_as_idle_not_saturated(self):
        reading = capacity.parse_scheduler_state(scheduler_state([]))
        assert reading.ok
        assert reading.load == 0.0
        assert reading.total_slots == 0

    def test_per_model_queue_depth_counts_towards_the_queue(self):
        reading = capacity.parse_scheduler_state(scheduler_state([loaded(1, 8, queue_depth=3)], queue_total=1))
        assert reading.queue_total == 4
        assert reading.saturated

    def test_active_above_capacity_cannot_exceed_full_load(self):
        # The orchestrator can briefly report more in flight than the declared
        # ceiling; a load above 1.0 would break every threshold comparison.
        reading = capacity.parse_scheduler_state(scheduler_state([loaded(12, 8)]))
        assert reading.load == 1.0
        assert reading.busy_slots == 8


class TestStartDecision:
    def test_starts_when_idle(self):
        reading = capacity.parse_scheduler_state(scheduler_state([loaded(0, 8)]))
        may_start, _ = capacity.start_decision(reading, running=0, paused=0)
        assert may_start

    def test_refuses_while_users_queue_even_if_slots_look_free(self):
        reading = capacity.parse_scheduler_state(scheduler_state([loaded(0, 8)], queue_total=1))
        may_start, reason = capacity.start_decision(reading, running=0, paused=0)
        assert not may_start
        assert "queue" in reason

    def test_refuses_above_the_start_threshold(self):
        busy = int(settings.start_below_load * 8) + 1
        reading = capacity.parse_scheduler_state(scheduler_state([loaded(busy, 8)]))
        may_start, _ = capacity.start_decision(reading, running=0, paused=0)
        assert not may_start

    def test_refuses_at_the_parallel_ceiling(self):
        reading = capacity.parse_scheduler_state(scheduler_state([loaded(0, 8)]))
        may_start, reason = capacity.start_decision(reading, running=settings.max_parallel_sessions, paused=0)
        assert not may_start
        assert "ceiling" in reason

    def test_paused_sessions_count_against_the_ceiling(self):
        # A paused session still holds a container and a workspace, so it must
        # occupy a slot; otherwise pausing would let the runner over-admit.
        reading = capacity.parse_scheduler_state(scheduler_state([loaded(0, 8)]))
        may_start, _ = capacity.start_decision(reading, running=0, paused=settings.max_parallel_sessions)
        assert not may_start

    def test_unknown_capacity_refuses_to_start(self):
        may_start, reason = capacity.start_decision(capacity.UNKNOWN, running=0, paused=0)
        assert not may_start
        assert "unknown" in reason


class TestPauseAndResume:
    def test_pauses_when_users_queue(self):
        reading = capacity.parse_scheduler_state(scheduler_state([loaded(1, 8)], queue_total=2))
        should_pause, _ = capacity.pause_decision(reading)
        assert should_pause

    def test_pauses_when_capacity_is_unknown(self):
        # Losing sight of the orchestrator while sessions run is exactly when
        # the cheapest thing to interrupt should be interrupted.
        should_pause, _ = capacity.pause_decision(capacity.UNKNOWN)
        assert should_pause

    def test_does_not_pause_a_quiet_fleet(self):
        reading = capacity.parse_scheduler_state(scheduler_state([loaded(1, 8)]))
        should_pause, _ = capacity.pause_decision(reading)
        assert not should_pause

    def test_resume_uses_the_start_threshold_not_the_pause_one(self):
        # Load between the two thresholds: no longer pause-worthy, but not yet
        # quiet enough to resume. Resuming here would pause again next tick.
        between = (settings.start_below_load + settings.pause_above_load) / 2
        slots = 100
        reading = capacity.parse_scheduler_state(scheduler_state([loaded(int(between * slots), slots)]))
        assert not capacity.pause_decision(reading)[0]
        assert not capacity.resume_decision(reading)[0]

    def test_resumes_once_the_fleet_is_quiet(self):
        reading = capacity.parse_scheduler_state(scheduler_state([loaded(0, 8)]))
        may_resume, _ = capacity.resume_decision(reading)
        assert may_resume
