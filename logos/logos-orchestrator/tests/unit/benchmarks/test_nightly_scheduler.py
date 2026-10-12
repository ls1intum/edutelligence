import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from logos.benchmarks import nightly_scheduler as module
from logos.benchmarks.nightly import NightlyStopped
from logos.benchmarks.reservations import benchmark_reservations


@pytest.fixture
def scheduler(monkeypatch):
    registry = MagicMock()
    registry.is_provider_online.return_value = True
    registry.has_received_first_status.return_value = True
    registry.is_calibrating.return_value = False
    registry.active_provider_ids.return_value = [20, 21]
    registry.peek_runtime_snapshot.return_value = {
        "runtime": {
            "supports_benchmark_restart": True,
            "lanes": [
                {
                    "lane_id": "lane",
                    "runtime_state": "running",
                    "model": "model",
                    "lane_config": {
                        "lane_id": "lane",
                        "model": "model",
                        "vllm": True,
                        "vllm_config": {"max_num_seqs": 16, "max_num_batched_tokens": 4096},
                    },
                }
            ],
            "devices": {"nvidia_smi_available": True, "devices": [{"kind": "nvidia"}]},
        }
    }
    planner = MagicMock()
    planner._facade.model_inflight_requests.return_value = 0
    planner._drain_lane = AsyncMock(return_value=True)
    service = module.NightlyScheduler(registry, planner)
    service.restore = AsyncMock()
    db = MagicMock()
    db.__enter__.return_value = db
    db.get_model_provider_benchmark_target.return_value = {
        "provider_id": 20,
        "provider_type": "logosnode",
        "model_name": "model",
    }
    monkeypatch.setattr(module, "DBManager", lambda: db)
    monkeypatch.setattr(module, "local_now", lambda: datetime.fromisoformat("2026-10-13T03:00:00+02:00"))
    monkeypatch.setattr(module.store, "status", lambda _: {"enabled": True})
    monkeypatch.setattr(module.store, "lock_held", lambda _: True)
    service.saved = []
    monkeypatch.setattr(module.store, "save", lambda *args: service.saved.append(args))
    yield service
    benchmark_reservations.release(-31)


async def test_stall_retries_same_configuration_once_then_moves_on(scheduler):
    calls = []

    async def submit(pair, settings):
        calls.append(settings.model_dump())

        async def execute():
            if len(calls) <= 2:
                raise NightlyStopped("stalled")
            return len(calls)

        return len(calls), asyncio.create_task(execute())

    scheduler.submit = submit
    assert await scheduler.run_schedule(31, MagicMock())
    assert len(calls) == 6
    assert calls[0] == calls[1]
    assert calls[2] != calls[1]
    assert scheduler.saved[-1][1] == "completed"
    assert scheduler.saved[-1][3] is None
    assert benchmark_reservations.owner(20, "other") is None


async def test_cutoff_stops_remaining_configurations_and_restores(scheduler):
    async def execute():
        raise NightlyStopped("window_closed_below_half")

    scheduler.submit = AsyncMock(side_effect=lambda *args: asyncio.sleep(0))

    async def submit(*args):
        return 7, asyncio.create_task(execute())

    scheduler.submit = AsyncMock(side_effect=submit)
    assert await scheduler.run_schedule(31, MagicMock())
    assert scheduler.submit.await_count == 1
    scheduler.restore.assert_awaited_once()
    assert scheduler.saved[-1][1] == "window_closed_below_half"


async def test_recovery_failure_holds_node_and_stops_other_schedules(scheduler):
    scheduler.restore.side_effect = RuntimeError("worker disconnected")

    async def submit(*args):
        return 7, asyncio.create_task(asyncio.sleep(0, result=1))

    scheduler.submit = submit
    assert not await scheduler.run_schedule(31, MagicMock())
    assert scheduler.saved[-1][1] == "recovery_required"
    assert scheduler.saved[-1][3] is not None
    assert not benchmark_reservations.allows(20, "other", "production")


async def test_single_worker_never_taken_out_of_production(scheduler):
    scheduler.registry.active_provider_ids.return_value = [20]
    scheduler.submit = AsyncMock()
    assert await scheduler.run_schedule(31, MagicMock())
    scheduler.submit.assert_not_awaited()
    scheduler.restore.assert_not_awaited()
    assert "another healthy worker" in scheduler.saved[-1][2][0]["reason"]


async def test_no_configuration_or_retry_starts_at_0450(scheduler, monkeypatch):
    monkeypatch.setattr(module, "local_now", lambda: datetime.fromisoformat("2026-10-13T04:50:00+02:00"))
    scheduler.submit = AsyncMock()
    assert await scheduler.run_schedule(31, MagicMock())
    scheduler.submit.assert_not_awaited()
    assert scheduler.saved[-1][1] == "window_closed"


async def test_lost_cluster_lock_keeps_recovery_journal(scheduler, monkeypatch):
    async def submit(*args):
        async def run():
            raise NightlyStopped("lease_lost")

        return 7, asyncio.create_task(run())

    scheduler.submit = submit
    monkeypatch.setattr(module.store, "lock_held", lambda _: False)
    assert not await scheduler.run_schedule(31, MagicMock())
    scheduler.restore.assert_not_awaited()
    assert scheduler.saved[-1][3] is not None


async def test_failed_initial_drain_releases_worker_without_restart(scheduler):
    scheduler.restore = module.NightlyScheduler.restore.__get__(scheduler)
    scheduler.planner._drain_lane.return_value = False
    scheduler.submit = AsyncMock()
    assert await scheduler.run_schedule(31, MagicMock())
    scheduler.submit.assert_not_awaited()
    scheduler.registry.send_command.assert_not_called()
    assert scheduler.saved[-1][1] == "failed"
    assert scheduler.saved[-1][3] is None
    assert benchmark_reservations.allows(20, "model", "production")
