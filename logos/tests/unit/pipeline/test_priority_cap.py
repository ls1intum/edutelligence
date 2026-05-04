"""Tests for the per-process priority cap.

The cap is set per logos_key (process row) and used to throttle a peer Logos
forwarding traffic from a lower-priority environment. It clamps both the
initial enqueue priority and the starvation-aging ceiling.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from logos.pipeline.scheduler_interface import SchedulingRequest
from logos.pipeline.simple_scheduler import SimpleScheduler
from logos.queue.models import Priority
from logos.queue.priority_queue import PriorityQueueManager


def _make_scheduler(logosnode=None):
    qmgr = PriorityQueueManager()
    fake_logosnode = logosnode or MagicMock()
    fake_logosnode.get_provider_name.return_value = "worker"
    return SimpleScheduler(
        queue_manager=qmgr,
        logosnode_facade=fake_logosnode,
        azure_facade=MagicMock(),
        peer_facade=None,
        model_registry={},
    )


def _make_request(*, priority_int: int, priority_cap=None):
    deployments = [{"model_id": 1, "provider_id": 10, "type": "logosnode"}]
    return SchedulingRequest(
        request_id="r1",
        payload={"messages": []},
        deployments=deployments,
        classified_models=[(1, 1.0, priority_int, 1)],
        priority_cap=priority_cap,
    )


@pytest.mark.asyncio
async def test_ready_path_clamps_priority_to_cap():
    """A READY result records the capped priority, not the classified one."""
    from logos.sdi.models import LaneSchedulerSignals, ModelSchedulerView

    lane = LaneSchedulerSignals(
        lane_id="l1", model_name="m", runtime_state="loaded",
        sleep_state="unsupported", is_vllm=True, active_requests=0,
        queue_waiting=0.0, requests_running=0.0, gpu_cache_usage_percent=None,
        ttft_p95_seconds=0.0, effective_vram_mb=8000.0, num_parallel=4,
    )
    view = ModelSchedulerView(
        model_id=1, model_name="m", provider_id=10, is_loaded=True,
        best_lane_state="loaded", best_sleep_state="unsupported",
        aggregate_active_requests=0, aggregate_queue_waiting=0.0,
        warmest_ttft_p95_seconds=0.0, gpu_cache_pressure_max=None, lanes=[lane],
    )
    logosnode = MagicMock()
    logosnode.get_provider_name.return_value = "worker"
    logosnode.get_model_scheduler_view.return_value = view
    logosnode.get_model_status.return_value = MagicMock(
        active_requests=0, is_loaded=True
    )
    logosnode.get_capacity_info.return_value = MagicMock(available_vram_mb=8000)

    scheduler = _make_scheduler(logosnode=logosnode)
    # Classified at HIGH (10), capped at LOW (1).
    req = _make_request(priority_int=int(Priority.HIGH), priority_cap=Priority.LOW)

    result = await scheduler.schedule(req)

    assert result is not None
    assert result.priority_when_scheduled == "low"


def test_apply_priority_cap_clamps_only_above_cap():
    cap = Priority.NORMAL
    # HIGH gets clamped to NORMAL.
    assert SimpleScheduler._apply_priority_cap(int(Priority.HIGH), cap) == int(Priority.NORMAL)
    # LOW stays LOW (already below the cap).
    assert SimpleScheduler._apply_priority_cap(int(Priority.LOW), cap) == int(Priority.LOW)
    # NORMAL stays at the cap.
    assert SimpleScheduler._apply_priority_cap(int(Priority.NORMAL), cap) == int(Priority.NORMAL)


def test_apply_priority_cap_no_cap_is_identity():
    assert SimpleScheduler._apply_priority_cap(int(Priority.HIGH), None) == int(Priority.HIGH)
    assert SimpleScheduler._apply_priority_cap(int(Priority.LOW), None) == int(Priority.LOW)


def test_enqueue_records_max_priority_on_queue_entry():
    qmgr = PriorityQueueManager()
    entry_id = qmgr.enqueue(
        task=object(), model_id=1, priority=Priority.LOW, max_priority=Priority.LOW
    )
    info = qmgr.get_entry_info(entry_id)
    assert info is not None
    assert info.max_priority == Priority.LOW


def test_enqueue_default_max_priority_is_high():
    qmgr = PriorityQueueManager()
    entry_id = qmgr.enqueue(task=object(), model_id=1, priority=Priority.LOW)
    info = qmgr.get_entry_info(entry_id)
    assert info is not None
    assert info.max_priority == Priority.HIGH


def _scheduler_for_starvation(qmgr: PriorityQueueManager) -> SimpleScheduler:
    """SimpleScheduler instance (concrete) just for _check_starvation tests."""
    return SimpleScheduler(
        queue_manager=qmgr,
        logosnode_facade=MagicMock(),
        azure_facade=MagicMock(),
        peer_facade=None,
        model_registry={},
    )


def test_starvation_aging_respects_cap():
    """A LOW-priority entry capped at LOW must NOT escalate after 30s."""
    qmgr = PriorityQueueManager()
    entry_id = qmgr.enqueue(
        task=object(), model_id=1, priority=Priority.LOW, max_priority=Priority.LOW
    )
    info = qmgr.get_entry_info(entry_id)
    # Backdate by 60s so both 10s and 30s thresholds are exceeded.
    info.enqueue_time = datetime.now() - timedelta(seconds=60)

    scheduler = _scheduler_for_starvation(qmgr)
    scheduler._check_starvation(model_id=1)

    state = qmgr.get_state(1)
    assert state.low == 1
    assert state.normal == 0
    assert state.high == 0


def test_starvation_aging_clamps_to_normal_when_capped_at_normal():
    """A LOW entry capped at NORMAL escalates LOW→NORMAL after 10s but stops there."""
    qmgr = PriorityQueueManager()
    entry_id = qmgr.enqueue(
        task=object(), model_id=1, priority=Priority.LOW, max_priority=Priority.NORMAL
    )
    info = qmgr.get_entry_info(entry_id)
    info.enqueue_time = datetime.now() - timedelta(seconds=60)

    scheduler = _scheduler_for_starvation(qmgr)
    scheduler._check_starvation(model_id=1)

    state = qmgr.get_state(1)
    assert state.low == 0
    assert state.normal == 1
    assert state.high == 0


def test_starvation_aging_uncapped_escalates_to_high():
    """An uncapped LOW entry escalates all the way to HIGH after 30s (existing behavior)."""
    qmgr = PriorityQueueManager()
    entry_id = qmgr.enqueue(task=object(), model_id=1, priority=Priority.LOW)
    info = qmgr.get_entry_info(entry_id)
    info.enqueue_time = datetime.now() - timedelta(seconds=60)

    scheduler = _scheduler_for_starvation(qmgr)
    scheduler._check_starvation(model_id=1)

    state = qmgr.get_state(1)
    assert state.high == 1
    assert state.low == 0
    assert state.normal == 0
