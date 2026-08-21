"""A manual "Load lane" must clear the same gates as a planner-initiated load.

The operator-facing endpoint is a second way into the same lane placement, so it
has to refuse in every state the planner itself refuses — and for the same
reasons:

* while the worker is calibrating, because it has freed its VRAM for the probes
  and a lane placed there takes the memory they need;
* before the worker has reported its lanes, because acting on empty state can
  destroy the lanes that are actually loaded;
* with no capacity snapshot, because the executor's fallback is an
  unconditional VRAM reservation — it would place the lane without checking
  whether it fits.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from logos.capacity.capacity_planner import CapacityPlanner


def _planner(*, calibrating=False, has_status=True, capacity=object()) -> CapacityPlanner:
    planner = CapacityPlanner.__new__(CapacityPlanner)
    registry = MagicMock()
    registry.is_calibrating.return_value = calibrating
    registry.has_received_first_status.return_value = has_status
    planner._registry = registry
    facade = MagicMock()
    facade.get_capacity_info.return_value = capacity
    facade.get_provider_name.return_value = "worker-a"
    planner._facade = facade
    return planner


def test_ready_provider_is_accepted():
    assert _planner().manual_load_rejection_reason(1) is None


def test_calibrating_provider_is_refused():
    reason = _planner(calibrating=True).manual_load_rejection_reason(1)
    assert reason is not None
    assert "calibrating" in reason


def test_provider_without_first_status_is_refused():
    reason = _planner(has_status=False).manual_load_rejection_reason(1)
    assert reason is not None
    assert "not reported its lanes" in reason


def test_provider_without_capacity_snapshot_is_refused():
    reason = _planner(capacity=None).manual_load_rejection_reason(1)
    assert reason is not None
    assert "capacity information" in reason


def test_calibrating_wins_over_missing_capacity():
    """The more specific, more actionable reason is the one reported."""
    reason = _planner(calibrating=True, capacity=None).manual_load_rejection_reason(1)
    assert "calibrating" in reason


def test_load_lane_manually_does_not_dispatch_when_refused():
    planner = _planner(calibrating=True)
    planner._execute_action_with_confirmation = MagicMock()

    assert asyncio.run(planner.load_lane_manually(1, "org/model-a")) is False
    planner._execute_action_with_confirmation.assert_not_called()


def test_load_lane_manually_rechecks_capacity_before_dispatch():
    """The snapshot can go away between the endpoint's check and the dispatch.

    The endpoint answers 202 off `manual_load_rejection_reason`, then the load
    runs in the background — so the executor must not be reached on a snapshot
    that vanished in between.
    """
    planner = _planner()
    planner._execute_action_with_confirmation = MagicMock()
    # Passes the gate, then reports no snapshot on the dispatch-time re-read.
    planner._facade.get_capacity_info.side_effect = [object(), None]

    assert asyncio.run(planner.load_lane_manually(1, "org/model-a")) is False
    planner._execute_action_with_confirmation.assert_not_called()
