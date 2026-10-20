"""Calibration window defaults match the shared overnight maintenance window."""

from __future__ import annotations

import pytest

from logos.capacity.calibration_orchestrator import CalibrationConfig

_ENV_VARS = (
    "LOGOS_MAINTENANCE_WINDOW_START",
    "LOGOS_MAINTENANCE_WINDOW_END",
    "LOGOS_MAINTENANCE_TIMEZONE",
    "LOGOS_CALIB_ENABLED",
    "LOGOS_CALIB_SLEEP_LEVEL",
    "LOGOS_CALIB_TICK_SECONDS",
)


@pytest.fixture(autouse=True)
def _clean_calibration_env(monkeypatch):
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_from_env_defaults_match_dataclass_defaults():
    """With no environment variables set, from_env() must equal the bare
    dataclass — the single source of truth these defaults come from."""
    assert CalibrationConfig.from_env() == CalibrationConfig()


def test_from_env_window_defaults_are_05_to_08():
    """Regression for the specific mismatch: both must read 05:00-08:00,
    matching the deployed docker-compose default."""
    config = CalibrationConfig.from_env()
    assert str(config.window_start) == "05:00:00"
    assert str(config.window_end) == "08:00:00"


def test_from_env_reads_overrides(monkeypatch):
    monkeypatch.setenv("LOGOS_MAINTENANCE_WINDOW_START", "01:15")
    monkeypatch.setenv("LOGOS_MAINTENANCE_TIMEZONE", "UTC")
    monkeypatch.setenv("LOGOS_CALIB_SLEEP_LEVEL", "2")
    monkeypatch.setenv("LOGOS_CALIB_ENABLED", "false")
    monkeypatch.setenv("LOGOS_CALIB_TICK_SECONDS", "15")

    config = CalibrationConfig.from_env()

    assert str(config.window_start) == "01:15:00"
    assert config.timezone == "UTC"
    assert config.sleep_level == 2
    assert config.enabled is False
    assert config.tick_seconds == 15.0
    # Untouched fields still fall back to the dataclass default.
    assert str(config.window_end) == "08:00:00"


def test_from_env_invalid_time_rejects_configuration(monkeypatch):
    monkeypatch.setenv("LOGOS_MAINTENANCE_WINDOW_START", "garbage")
    with pytest.raises(ValueError):
        CalibrationConfig.from_env()
