from datetime import datetime

import pytest

from logos.benchmarks.nightly import can_start
from logos.capacity.calibration_orchestrator import CalibrationConfig
from logos.maintenance_window import MaintenanceWindow


def test_one_override_controls_calibration_benchmarks_and_display(monkeypatch):
    monkeypatch.setenv("LOGOS_MAINTENANCE_WINDOW_START", "06:00")
    monkeypatch.setenv("LOGOS_MAINTENANCE_WINDOW_END", "09:00")
    monkeypatch.setenv("LOGOS_MAINTENANCE_TIMEZONE", "UTC")
    window = MaintenanceWindow.from_env()
    calibration = CalibrationConfig.from_env()
    assert (calibration.window_start, calibration.window_end, calibration.timezone) == (
        window.start,
        window.end,
        window.timezone,
    )
    assert window.describe() == dict(start="06:00", end="09:00", benchmark_start_cutoff="08:50", timezone="UTC")
    assert not can_start(datetime.fromisoformat("2026-10-20T05:59:59Z"))
    assert can_start(datetime.fromisoformat("2026-10-20T08:49:59Z"))
    assert not can_start(datetime.fromisoformat("2026-10-20T08:50:00Z"))
    assert window.contains(datetime.fromisoformat("2026-10-20T08:59:59Z"))
    assert not window.contains(datetime.fromisoformat("2026-10-20T09:00:00Z"))


def test_old_calibration_only_settings_cannot_split_the_window(monkeypatch):
    monkeypatch.setenv("LOGOS_CALIB_WINDOW_START", "03:00")
    monkeypatch.setenv("LOGOS_CALIB_WINDOW_END", "05:00")
    assert CalibrationConfig.from_env().window_start == MaintenanceWindow().start
    assert CalibrationConfig.from_env().window_end == MaintenanceWindow().end


@pytest.mark.parametrize("end", ["04:59", "05:00", "05:05", "05:10", "invalid"])
def test_invalid_window_fails_before_startup(monkeypatch, end):
    monkeypatch.setenv("LOGOS_MAINTENANCE_WINDOW_END", end)
    with pytest.raises(ValueError):
        MaintenanceWindow.from_env()


@pytest.mark.parametrize("value", [None, "", " \t "])
def test_missing_or_blank_shared_settings_use_defaults(monkeypatch, value):
    for name in ("START", "END", "TIMEZONE"):
        key = "LOGOS_MAINTENANCE_" + (name if name == "TIMEZONE" else "WINDOW_" + name)
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    assert MaintenanceWindow.from_env() == MaintenanceWindow()


@pytest.mark.parametrize("name,value", [("WINDOW_START", "bad"), ("WINDOW_END", "25:00"), ("TIMEZONE", "bad/zone")])
def test_nonempty_invalid_shared_settings_still_fail(monkeypatch, name, value):
    from zoneinfo import ZoneInfoNotFoundError

    monkeypatch.setenv("LOGOS_MAINTENANCE_" + name, value)
    with pytest.raises((ValueError, ZoneInfoNotFoundError)):
        MaintenanceWindow.from_env()


@pytest.mark.parametrize("value,expected", [(None, 1), ("", 1), ("  ", 1), ("1", 1), (" 2 ", 2), ("10", 10)])
def test_maintenance_node_limit(monkeypatch, value, expected):
    from logos.maintenance_window import maintenance_node_limit

    if value is None:
        monkeypatch.delenv("LOGOS_MAINTENANCE_MAX_NODES", raising=False)
    else:
        monkeypatch.setenv("LOGOS_MAINTENANCE_MAX_NODES", value)
    assert maintenance_node_limit() == expected


@pytest.mark.parametrize("value", ["0", "-1", "1.5", "invalid"])
def test_invalid_maintenance_limit_fails_at_startup(monkeypatch, value):
    monkeypatch.setenv("LOGOS_MAINTENANCE_MAX_NODES", value)
    with pytest.raises(ValueError):
        MaintenanceWindow.from_env()
