"""One configured window for automatic calibration, benchmarks and their UI."""

import os
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo


def maintenance_node_limit() -> int:
    """Maximum simultaneous maintenance workers; one keeps maintenance sequential."""
    raw = _env("LOGOS_MAINTENANCE_MAX_NODES", "1")
    limit = int(raw)
    if limit < 1:
        raise ValueError("LOGOS_MAINTENANCE_MAX_NODES must be a positive integer")
    return limit


def _env(name: str, default: str) -> str:
    return (os.getenv(name) or "").strip() or default


@dataclass(frozen=True)
class MaintenanceWindow:
    start: time = time(5)
    end: time = time(8)
    timezone: str = "Europe/Berlin"

    @classmethod
    def from_env(cls) -> "MaintenanceWindow":
        """Reject invalid shared settings instead of silently using different windows."""
        maintenance_node_limit()
        defaults = cls()
        window = cls(
            start=time.fromisoformat(_env("LOGOS_MAINTENANCE_WINDOW_START", defaults.start.isoformat())),
            end=time.fromisoformat(_env("LOGOS_MAINTENANCE_WINDOW_END", defaults.end.isoformat())),
            timezone=_env("LOGOS_MAINTENANCE_TIMEZONE", defaults.timezone),
        )
        if window.start.tzinfo or window.end.tzinfo:
            raise ValueError("Maintenance times must be local times without a UTC offset")
        if any(value.second or value.microsecond for value in (window.start, window.end)):
            raise ValueError("Maintenance times must use whole minutes")
        ZoneInfo(window.timezone)
        duration = window.end.hour * 60 + window.end.minute - window.start.hour * 60 - window.start.minute
        if duration <= 10:
            raise ValueError("The maintenance window must end on the same day, more than 10 minutes after its start")
        return window

    def bounds(self, now: datetime) -> tuple[datetime, datetime]:
        """Return the shared start and end on the local calendar date."""
        if now.utcoffset() is None:
            raise ValueError("The maintenance clock must include a timezone")
        local = now.astimezone(ZoneInfo(self.timezone))
        start = datetime.combine(local.date(), self.start, local.tzinfo)
        end = datetime.combine(local.date(), self.end, local.tzinfo)
        return start, end

    def contains(self, now: datetime) -> bool:
        start, end = self.bounds(now)
        return start <= now < end

    def can_start_benchmark(self, now: datetime) -> bool:
        start, end = self.bounds(now)
        return start <= now < end - timedelta(minutes=10)

    def describe(self) -> dict[str, str]:
        """Expose the effective window and derived start cutoff to administrators."""
        end = datetime.combine(datetime.min.date(), self.end)
        return {
            "start": self.start.strftime("%H:%M"),
            "end": self.end.strftime("%H:%M"),
            "benchmark_start_cutoff": (end - timedelta(minutes=10)).strftime("%H:%M"),
            "timezone": self.timezone,
        }
