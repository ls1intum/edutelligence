"""CalibrationConfig.from_env() must never drift from the dataclass's own
field defaults — that drift (window_start/window_end defaulting to
02:00-05:00 on the dataclass but 03:00-08:00 in from_env's fallback,
while the deployed docker-compose default was 03:00-08:00 too) is the
exact bug this guards against.
"""

from __future__ import annotations

import pytest

from logos.capacity.calibration_orchestrator import CalibrationConfig

_ENV_VARS = (
    "LOGOS_CALIB_WINDOW_START",
    "LOGOS_CALIB_WINDOW_END",
    "LOGOS_CALIB_TIMEZONE",
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


def test_from_env_window_defaults_are_03_to_08():
    """Regression for the specific mismatch: both must read 03:00-08:00,
    matching the deployed docker-compose default."""
    config = CalibrationConfig.from_env()
    assert str(config.window_start) == "03:00:00"
    assert str(config.window_end) == "08:00:00"


def test_from_env_reads_overrides(monkeypatch):
    monkeypatch.setenv("LOGOS_CALIB_WINDOW_START", "01:15")
    monkeypatch.setenv("LOGOS_CALIB_TIMEZONE", "UTC")
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


def test_from_env_invalid_time_falls_back_to_dataclass_default(monkeypatch):
    """An unparsable override must fall back to the real dataclass
    default, not a second, independently-maintained literal."""
    monkeypatch.setenv("LOGOS_CALIB_WINDOW_START", "garbage")
    config = CalibrationConfig.from_env()
    assert config.window_start == CalibrationConfig().window_start
