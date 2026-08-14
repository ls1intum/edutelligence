"""Tests for placement telemetry.

The property that matters most here is that telemetry can never affect a
placement. A recorder that raises, or a database that is unreachable, must
leave the planner's behaviour bit-for-bit unchanged.
"""

from __future__ import annotations

import asyncio
import datetime

import pytest

from logos.capacity.capacity_planner import CapacityPlanner
from logos.sdi.models import CapacityPlanAction


class _Recorder:
    def __init__(self, explode: bool = False) -> None:
        self.events: list[dict] = []
        self.explode = explode

    def __call__(self, **fields):
        if self.explode:
            raise RuntimeError("recorder is broken")
        self.events.append(fields)


def _planner(recorder=None) -> CapacityPlanner:
    planner = CapacityPlanner.__new__(CapacityPlanner)
    planner._placement_recorder = recorder
    planner._facade = None
    return planner


def _action(action: str = "load") -> CapacityPlanAction:
    return CapacityPlanAction(
        provider_id=15,
        lane_id="lane-1",
        model_name="some/model",
        action=action,
        reason="test",
    )


def test_records_a_confirmed_placement():
    recorder = _Recorder()
    planner = _planner(recorder)

    planner._record_placement_event(
        _action("load"),
        confirmed=True,
        error_class=None,
        duration_ms=1234,
        started_at=datetime.datetime.now(datetime.timezone.utc),
    )

    assert len(recorder.events) == 1
    event = recorder.events[0]
    assert event["provider_id"] == 15
    assert event["model_name"] == "some/model"
    assert event["action"] == "load"
    assert event["outcome"] == "confirmed"
    assert event["duration_ms"] == 1234
    assert event["error_class"] is None


def test_distinguishes_unconfirmed_from_error():
    recorder = _Recorder()
    planner = _planner(recorder)
    now = datetime.datetime.now(datetime.timezone.utc)

    planner._record_placement_event(_action(), confirmed=False, error_class=None, duration_ms=1, started_at=now)
    planner._record_placement_event(
        _action(), confirmed=False, error_class="TimeoutError", duration_ms=2, started_at=now
    )

    assert [e["outcome"] for e in recorder.events] == ["unconfirmed", "error"]
    assert recorder.events[1]["error_class"] == "TimeoutError"


def test_no_recorder_configured_is_a_no_op():
    planner = _planner(None)
    planner._record_placement_event(
        _action(),
        confirmed=True,
        error_class=None,
        duration_ms=1,
        started_at=datetime.datetime.now(datetime.timezone.utc),
    )  # must not raise


def test_a_broken_recorder_cannot_break_a_placement():
    """The property the whole design turns on."""
    planner = _planner(_Recorder(explode=True))
    planner._record_placement_event(
        _action(),
        confirmed=True,
        error_class=None,
        duration_ms=1,
        started_at=datetime.datetime.now(datetime.timezone.utc),
    )  # must not raise


def test_wrapper_records_success_and_returns_the_result():
    recorder = _Recorder()
    planner = _planner(recorder)

    async def fake(action, timeout_seconds=60.0):
        return True

    planner._execute_action_uninstrumented = fake
    result = asyncio.run(CapacityPlanner._execute_action_with_confirmation(planner, _action()))

    assert result is True
    assert recorder.events[0]["outcome"] == "confirmed"
    assert recorder.events[0]["duration_ms"] >= 0


def test_wrapper_records_a_raising_placement_and_re_raises():
    recorder = _Recorder()
    planner = _planner(recorder)

    async def fake(action, timeout_seconds=60.0):
        raise TimeoutError("worker never confirmed")

    planner._execute_action_uninstrumented = fake
    with pytest.raises(TimeoutError):
        asyncio.run(CapacityPlanner._execute_action_with_confirmation(planner, _action()))

    assert recorder.events[0]["outcome"] == "error"
    assert recorder.events[0]["error_class"] == "TimeoutError"
