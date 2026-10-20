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
