"""A cordoned worker is left alone by everything that would act on its lanes.

The node manager replaces the container of a cordoned worker. A lane the capacity planner placed or woke there, or a
calibration session started there, would be lost with the container, and the requests the worker drains must not be
disturbed.
"""

from __future__ import annotations

import logging
import time
from unittest.mock import MagicMock

import pytest

# Reuse the planner wiring of the calibration guard tests
from tests.unit.capacity.test_calibration_lane_guard import _planner_with_registry, _unplannable_planner

from logos.capacity.calibration_orchestrator import CalibrationOrchestrator
from logos.capacity.capacity_planner import _UNPLANNABLE_WARN_AFTER_SECONDS


def _registry(*, cordoned: bool) -> MagicMock:
    return MagicMock(
        **{
            "is_calibrating.return_value": False,
            "is_cordoned.return_value": cordoned,
            "has_received_first_status.return_value": True,
            "is_provider_online.return_value": True,
        }
    )


@pytest.mark.parametrize(("cordoned", "expected"), [(False, True), (True, False)])
def test_a_cordoned_worker_is_not_plannable(cordoned, expected):
    assert _planner_with_registry(_registry(cordoned=cordoned))._is_plannable(1) is expected


def test_a_cordoned_worker_is_not_reported_as_stuck(caplog):
    """The cordon lasts as long as a drain and a swap take. That is expected, not a fault to warn about."""
    planner = _unplannable_planner(_registry(cordoned=True))
    planner._unplannable_since[1] = time.time() - (_UNPLANNABLE_WARN_AFTER_SECONDS * 10)

    with caplog.at_level(logging.WARNING):
        planner._note_unplannable(1)

    assert caplog.records == []
    assert 1 not in planner._unplannable_since


def _calibration_orchestrator(cordoned: set[int]) -> CalibrationOrchestrator:
    orch = CalibrationOrchestrator.__new__(CalibrationOrchestrator)
    orch._completed_this_window = set()
    orch._facade = MagicMock(**{"provider_ids.return_value": [1, 2]})
    orch._registry = MagicMock()
    orch._registry.has_received_first_status.return_value = True
    orch._registry.is_cordoned.side_effect = lambda provider_id: provider_id in cordoned
    orch._provider_is_unhealthy = lambda provider_id: False
    orch._provider_has_active_requests = lambda provider_id: False
    orch._provider_has_uncalibrated_models = lambda provider_id: True
    return orch


def test_calibration_starts_on_an_idle_worker_that_is_not_cordoned():
    assert _calibration_orchestrator(set())._pick_next_provider() == 1


def test_calibration_skips_a_cordoned_worker():
    """An idle, drained worker looks like the ideal target, but its container is about to go."""
    assert _calibration_orchestrator({1})._pick_next_provider() == 2


def test_calibration_waits_when_every_worker_is_cordoned():
    assert _calibration_orchestrator({1, 2})._pick_next_provider() is None
