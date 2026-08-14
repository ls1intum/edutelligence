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


# ----------------------------------------------------------------------
# Regressions from review
# ----------------------------------------------------------------------


def test_reads_declared_capacity_through_the_real_facade_method():
    """The first version called a method that does not exist.

    ``_facade.get_capacity`` is not part of LogosNodeSchedulingDataFacade -- the
    method is ``get_capacity_info``. The call raised AttributeError on every
    production event, the wrapper swallowed it, and declared_free_vram_mb was
    persisted as NULL: precisely the gap this telemetry exists to close. The
    earlier tests missed it because they set ``_facade = None``.

    This test therefore asserts against the *real* facade's interface.
    """
    from logos.sdi.logosnode_facade import LogosNodeSchedulingDataFacade

    assert hasattr(LogosNodeSchedulingDataFacade, "get_capacity_info")
    assert not hasattr(LogosNodeSchedulingDataFacade, "get_capacity")

    class _Facade:
        """Only implements what the real facade implements."""

        def get_capacity_info(self, provider_id):
            return type("Cap", (), {"available_vram_mb": 4096.0})()

        def get_model_profiles(self, provider_id):
            return {}

    recorder = _Recorder()
    planner = _planner(recorder)
    planner._facade = _Facade()

    planner._record_placement_event(
        _action("load"),
        confirmed=True,
        error_class=None,
        duration_ms=5,
        started_at=datetime.datetime.now(datetime.timezone.utc),
    )

    assert recorder.events[0]["declared_free_vram_mb"] == 4096.0


def test_escalated_stop_is_recorded_once_under_its_own_label():
    """Sleep-to-stop escalation must not write two rows.

    The escalation path used to recurse through the instrumented wrapper, so a
    single placement attempt produced two rows: the inner one for the stop, and
    an outer one carrying the stop's outcome under the original action's label.
    """
    recorder = _Recorder()
    planner = _planner(recorder)
    planner._facade = None

    async def fake(action, timeout_seconds=60.0):
        # Simulate the escalation branch: it sets the label and runs the stop
        # through the uninstrumented path.
        planner._escalated_action = "sleep_to_stop"
        return True

    planner._execute_action_uninstrumented = fake
    result = asyncio.run(CapacityPlanner._execute_action_with_confirmation(planner, _action("sleep_l2")))

    assert result is True
    assert len(recorder.events) == 1, "one placement attempt must produce one row"
    assert recorder.events[0]["action"] == "sleep_to_stop"


def test_escalation_label_does_not_leak_into_the_next_attempt():
    recorder = _Recorder()
    planner = _planner(recorder)
    planner._facade = None

    async def escalating(action, timeout_seconds=60.0):
        planner._escalated_action = "sleep_to_stop"
        return True

    async def plain(action, timeout_seconds=60.0):
        return True

    planner._execute_action_uninstrumented = escalating
    asyncio.run(CapacityPlanner._execute_action_with_confirmation(planner, _action("sleep_l2")))
    planner._execute_action_uninstrumented = plain
    asyncio.run(CapacityPlanner._execute_action_with_confirmation(planner, _action("load")))

    assert [e["action"] for e in recorder.events] == ["sleep_to_stop", "load"]
