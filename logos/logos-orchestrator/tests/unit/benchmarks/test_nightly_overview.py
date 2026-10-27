from datetime import date, datetime
from unittest.mock import Mock

from logos.benchmarks.nightly_overview import overview


def row(pair, *, last=None, enabled=True, recovery=None, success=False):
    return dict(
        model_provider_id=pair,
        model_id=pair,
        provider_name=f"Worker {pair}",
        last_run_date=last,
        enabled=enabled,
        recovery=recovery,
        report=[{"status": "success"}] if success else [],
    )


def test_rotation_skips_offline_and_disabled_without_mutating_scheduler():
    scheduler = Mock()
    scheduler.target_lane.side_effect = lambda pair, **_: (
        (_ for _ in ()).throw(RuntimeError("Offline")) if pair == 1 else ({"provider_id": pair}, {}, {})
    )
    result = overview(
        [row(1), row(2, enabled=False), row(3), row(4), row(5)],
        scheduler,
        datetime.fromisoformat("2026-10-21T12:00:00+02:00"),
    )
    assert result["next_date"] == date(2026, 10, 22)
    assert [item["state"] for item in result["schedules"]] == ["blocked", "disabled", "next", "next", "queued"]
    for call in scheduler.target_lane.call_args_list:
        assert call.kwargs == {"disable_missing": False}


def test_window_claims_and_recent_success_are_separate_from_next_candidates():
    result = overview(
        [row(1), row(2), row(3, last=date(2026, 10, 21), success=True)],
        Mock(target_lane=Mock(return_value=({"provider_id": 1}, {}, {}))),
        datetime.fromisoformat("2026-10-21T05:30:00+02:00"),
    )
    assert result["next_date"] == date(2026, 10, 21)
    assert [item["state"] for item in result["schedules"]] == ["next", "queued", "recent"]


def test_recovery_blocks_all_candidates_and_old_success_is_not_recent():
    result = overview(
        [row(1, recovery={"provider_id": 1}), row(2), row(3, enabled=False, success=True, last=date(2026, 10, 1))],
        Mock(target_lane=Mock(return_value=({"provider_id": 1}, {}, {}))),
        datetime.fromisoformat("2026-10-21T12:00:00+02:00"),
    )
    assert [item["state"] for item in result["schedules"]] == ["blocked", "blocked", "disabled"]
    assert result["schedules"][2]["recent_success"] is False


def test_parallel_wave_selects_distinct_workers_before_deferred_pair(monkeypatch):
    monkeypatch.setenv("LOGOS_MAINTENANCE_MAX_NODES", "2")
    scheduler = Mock()
    scheduler.target_lane.side_effect = lambda pair, **_: ({"provider_id": 1 if pair < 3 else 2}, {}, {})
    result = overview([row(1), row(2), row(3)], scheduler, datetime.fromisoformat("2026-10-21T12:00:00+02:00"))
    assert [item["state"] for item in result["schedules"]] == ["next", "queued", "next"]


def test_deleted_deployments_still_consume_the_daily_quota():
    scheduler = Mock(target_lane=Mock(return_value=({"provider_id": 1}, {}, {})))
    result = overview([row(1)], scheduler, datetime.fromisoformat("2026-10-21T05:30:00+02:00"), claimed_count=2)
    assert result["next_date"] == date(2026, 10, 22)


def test_running_journal_is_reserved_not_reported_as_failed_recovery():
    schedule = {**row(1, recovery={"provider_id": 1}), "status": "running"}
    result = overview([schedule], Mock(), datetime.fromisoformat("2026-10-21T05:30:00+02:00"))
    assert result["schedules"][0]["state"] == "busy"


def test_disabled_schedule_keeps_recent_success_without_entering_rotation():
    scheduler = Mock()
    result = overview(
        [row(1, enabled=False, success=True, last=date(2026, 10, 21))],
        scheduler,
        datetime.fromisoformat("2026-10-21T12:00:00+02:00"),
    )
    schedule = result["schedules"][0]
    assert schedule["state"] == "disabled"
    assert schedule["reason"] == "Nightly runs are disabled"
    assert schedule["recent_success"] is True
    scheduler.target_lane.assert_not_called()
