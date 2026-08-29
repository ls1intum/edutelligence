"""An announced upcoming use (POST /v1/models/{id}/warmup) has to survive to the
planner's cold-load gate.

The demand score cannot carry this signal. It is decayed once per cycle *before*
the demand evaluation runs, so a single increment of weight w is already w×0.7 by
the time it meets DEMAND_LOAD_FLOOR — a lone warmup can never clear a floor of
1.0, whatever weight it is given. Real traffic does not hit this because a queued
request bypasses the floor outright, and a warmup deliberately has no queue entry
(it must not bill anyone or occupy a slot). So the announcement is recorded as a
fact of its own, and these tests pin down the three things that fact must do:
outlive nothing, expire, and be spent exactly once.
"""

from __future__ import annotations

from logos.capacity.capacity_planner import CapacityPlanner


def _planner() -> CapacityPlanner:
    planner = CapacityPlanner.__new__(CapacityPlanner)
    planner._announced_use = {}
    # announce_upcoming_use wakes the cycle through hint_capacity_needed, which
    # is a no-op while the planner is not running — which is what these tests
    # want, since the wake-up is not the behaviour under test here.
    planner._enabled = False
    planner._tick_event = None
    return planner


def test_an_announcement_is_visible_to_the_load_gate():
    planner = _planner()

    planner.announce_upcoming_use("qwen-27b")

    assert planner._has_announced_use("qwen-27b") is True


def test_a_model_nobody_announced_is_not():
    planner = _planner()
    planner.announce_upcoming_use("qwen-27b")

    assert planner._has_announced_use("some-other-model") is False


def test_an_announcement_expires():
    """A session the developer abandoned before sending anything must not keep
    arguing for a lane forever."""
    planner = _planner()
    planner.announce_upcoming_use("qwen-27b")

    planner._announced_use["qwen-27b"] -= CapacityPlanner.ANNOUNCED_USE_TTL_SECONDS + 1

    assert planner._has_announced_use("qwen-27b") is False


def test_an_expired_announcement_is_dropped_by_the_next_one():
    """The dict only ever holds models someone asked for, so it is trimmed on
    write rather than on a timer."""
    planner = _planner()
    planner.announce_upcoming_use("stale-model")
    planner._announced_use["stale-model"] -= CapacityPlanner.ANNOUNCED_USE_TTL_SECONDS + 1

    planner.announce_upcoming_use("qwen-27b")

    assert "stale-model" not in planner._announced_use
    assert planner._has_announced_use("qwen-27b") is True


def test_one_announcement_is_one_load():
    """Consumed when it produces a planned load: otherwise the same hint clears
    the floor again next cycle and argues for a second lane while the first is
    still coming up."""
    planner = _planner()
    planner.announce_upcoming_use("qwen-27b")

    planner._consume_announced_use("qwen-27b")

    assert planner._has_announced_use("qwen-27b") is False


def test_consuming_an_absent_announcement_is_harmless():
    """The gate calls this on every free-VRAM load, including the ones that got
    there on real demand and never had an announcement."""
    _planner()._consume_announced_use("never-announced")


def test_re_announcing_refreshes_the_deadline():
    """A long session keeps saying it is there; each one restarts the clock."""
    planner = _planner()
    planner.announce_upcoming_use("qwen-27b")
    planner._announced_use["qwen-27b"] -= CapacityPlanner.ANNOUNCED_USE_TTL_SECONDS + 1

    planner.announce_upcoming_use("qwen-27b")

    assert planner._has_announced_use("qwen-27b") is True
