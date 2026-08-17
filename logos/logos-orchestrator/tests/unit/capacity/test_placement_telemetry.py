"""Tests for placement telemetry.

The property that matters most here is that telemetry can never affect a
placement. A recorder that raises, or a database that is unreachable, must
leave the planner's behaviour bit-for-bit unchanged.
"""

from __future__ import annotations

import asyncio
import datetime

import pytest

from logos.capacity.capacity_planner import _ESCALATED_ACTION, CapacityPlanner
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
        declared_free_vram_mb=None,
        escalated_action=None,
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

    planner._record_placement_event(
        _action(),
        confirmed=False,
        error_class=None,
        duration_ms=1,
        started_at=now,
        declared_free_vram_mb=None,
        escalated_action=None,
    )
    planner._record_placement_event(
        _action(),
        confirmed=False,
        error_class="TimeoutError",
        duration_ms=2,
        started_at=now,
        declared_free_vram_mb=None,
        escalated_action=None,
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
        declared_free_vram_mb=None,
        escalated_action=None,
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
        declared_free_vram_mb=None,
        escalated_action=None,
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

    planner = _planner(_Recorder())
    planner._facade = _Facade()

    assert planner._declared_free_vram_mb(15) == 4096.0


def test_unreadable_capacity_is_none_rather_than_zero():
    """A missing reading and a node with no memory left must stay distinct.

    Coercing a failed read to 0.0 would enter the record as "this node declared
    no headroom", which is a measurement the orchestrator never made.
    """

    class _Broken:
        def get_capacity_info(self, provider_id):
            raise RuntimeError("provider unreachable")

    class _Silent:
        def get_capacity_info(self, provider_id):
            return None

    for facade in (_Broken(), _Silent(), None):
        planner = _planner(_Recorder())
        planner._facade = facade
        assert planner._declared_free_vram_mb(15) is None


def test_declared_capacity_is_captured_before_the_placement_executes():
    """The figure recorded must be the one the decision rested on.

    Reading the capacity inside the ``finally`` block -- as the first version
    did -- samples the provider *after* the placement already consumed the
    memory. That records the outcome of the placement rather than the claim
    that justified it, which inverts the meaning of the column: the whole
    purpose of the row is to compare what a node declared beforehand against
    whether the placement then held.
    """

    class _Facade:
        """Reports whatever the node currently declares."""

        def __init__(self) -> None:
            self.available = 8192.0

        def get_capacity_info(self, provider_id):
            return type("Cap", (), {"available_vram_mb": self.available})()

    facade = _Facade()
    recorder = _Recorder()
    planner = _planner(recorder)
    planner._facade = facade

    async def fake(action, timeout_seconds=60.0):
        # The placement consumes the headroom it was granted, so a read taken
        # after this point sees a different -- and wrong -- number.
        facade.available = 512.0
        return True

    planner._execute_action_uninstrumented = fake
    asyncio.run(CapacityPlanner._execute_action_with_confirmation(planner, _action("load")))

    assert recorder.events[0]["declared_free_vram_mb"] == 8192.0


def test_escalated_stop_is_recorded_once_under_its_own_label():
    """Sleep-to-stop escalation must not write two rows.

    The escalation path used to recurse through the instrumented wrapper, so a
    single placement attempt produced two rows: the inner one for the stop, and
    an outer one carrying the stop's outcome under the original action's label.
    """
    recorder = _Recorder()
    planner = _planner(recorder)

    async def fake(action, timeout_seconds=60.0):
        # Simulate the escalation branch: it sets the label and runs the stop
        # through the uninstrumented path.
        _ESCALATED_ACTION.set("sleep_to_stop")
        return True

    planner._execute_action_uninstrumented = fake
    result = asyncio.run(CapacityPlanner._execute_action_with_confirmation(planner, _action("sleep_l2")))

    assert result is True
    assert len(recorder.events) == 1, "one placement attempt must produce one row"
    assert recorder.events[0]["action"] == "sleep_to_stop"


def test_escalation_label_does_not_leak_into_the_next_attempt():
    recorder = _Recorder()
    planner = _planner(recorder)

    async def escalating(action, timeout_seconds=60.0):
        _ESCALATED_ACTION.set("sleep_to_stop")
        return True

    async def plain(action, timeout_seconds=60.0):
        return True

    planner._execute_action_uninstrumented = escalating
    asyncio.run(CapacityPlanner._execute_action_with_confirmation(planner, _action("sleep_l2")))
    planner._execute_action_uninstrumented = plain
    asyncio.run(CapacityPlanner._execute_action_with_confirmation(planner, _action("load")))

    assert [e["action"] for e in recorder.events] == ["sleep_to_stop", "load"]


def test_concurrent_placements_do_not_share_an_escalation_label():
    """Placements run concurrently, so the label cannot live on the planner.

    With the label held as an instance attribute, an escalating placement
    relabelled every other placement still in flight: the planner is one object
    and ``self._escalated_action`` is one slot. Here a slow plain ``load`` is
    interleaved with a fast escalating ``sleep_l2``; the load must still be
    recorded as a load.
    """
    recorder = _Recorder()
    planner = _planner(recorder)

    async def dispatch(action, timeout_seconds=60.0):
        if action.action == "sleep_l2":
            _ESCALATED_ACTION.set("sleep_to_stop")
            return True
        # Yield twice so the escalating placement finishes in between.
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        return True

    planner._execute_action_uninstrumented = dispatch

    async def run_both():
        await asyncio.gather(
            CapacityPlanner._execute_action_with_confirmation(planner, _action("load")),
            CapacityPlanner._execute_action_with_confirmation(planner, _action("sleep_l2")),
        )

    asyncio.run(run_both())

    assert sorted(e["action"] for e in recorder.events) == ["load", "sleep_to_stop"]
