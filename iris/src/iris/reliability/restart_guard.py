"""Restart history and exit marker, kept on the diagnostics mount so they survive restarts.

The restart limit stops a broken deployment from restarting itself in a loop. If the history
cannot be read or written, no self-restart is allowed: an unknown history must not become a loop.
"""

import json
from pathlib import Path
from typing import Optional

from iris.common.logging_config import get_logger
from iris.config import ReliabilitySettings

logger = get_logger(__name__)

_HISTORY_FILE = "restart-history.json"
_MARKER_FILE = "exit-marker"

MARKER_RUNNING = "running"
MARKER_CLEAN = "clean"
MARKER_WATCHDOG = "watchdog-exit"


class RestartGuard:
    """Reads and writes the restart history and the exit marker."""

    def __init__(self, settings: ReliabilitySettings):
        self._settings = settings
        self._dir = Path(settings.diagnostics_dir)

    def _read_history(self) -> list[dict]:
        path = self._dir / _HISTORY_FILE
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list) or not all(
            isinstance(entry, dict) for entry in data
        ):
            raise ValueError("restart history is not a list of entries")
        return data

    def _write_history(self, history: list[dict]) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / _HISTORY_FILE
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(history), encoding="utf-8")
        tmp.replace(path)

    def _recent(self, history: list[dict], now: float) -> list[dict]:
        return [
            entry
            for entry in history
            if now - float(entry.get("at", 0)) <= self._settings.restart_window_seconds
        ]

    def record_and_allow_self_restart(self, now: float, reason: str) -> bool:
        """Decide whether the watchdog may restart the process now, and record it if so."""
        try:
            history = self._recent(self._read_history(), now)
            watchdog_restarts = [e for e in history if e.get("kind") == "watchdog"]
            if watchdog_restarts:
                last = max(float(e["at"]) for e in watchdog_restarts)
                if now - last < self._settings.restart_min_interval_seconds:
                    logger.error(
                        "Self-restart refused: last one was %.0f s ago", now - last
                    )
                    return False
            if len(watchdog_restarts) >= self._settings.restart_max_per_window:
                logger.error(
                    "Self-restart refused: %d in the last %.0f s",
                    len(watchdog_restarts),
                    self._settings.restart_window_seconds,
                )
                return False
            history.append({"at": now, "kind": "watchdog", "reason": reason})
            self._write_history(history)
            return True
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            logger.exception("Self-restart refused: the restart history is unusable")
            return False

    def record_unexpected_restart(self, now: float) -> int:
        """Record a restart nobody planned; returns how many happened within the min interval."""
        try:
            history = self._recent(self._read_history(), now)
            history.append({"at": now, "kind": "unexpected"})
            self._write_history(history)
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            logger.exception("Could not record the unexpected restart")
            return 1
        return sum(
            1
            for entry in history
            if entry.get("kind") == "unexpected"
            and now - float(entry["at"]) <= self._settings.restart_min_interval_seconds
        )

    def read_marker(self) -> Optional[str]:
        try:
            return (self._dir / _MARKER_FILE).read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return None
        except OSError:
            logger.exception("Could not read the exit marker")
            return None

    def write_marker(self, value: str) -> None:
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            (self._dir / _MARKER_FILE).write_text(value, encoding="utf-8")
        except OSError as e:
            # Expected outside Docker, where the diagnostics mount does not exist.
            logger.warning("Could not write the exit marker: %s", e)
