"""In-memory buffer of recent ingestion log records, for the Artemis admin UI.

Iris logs to stdout, so its records are only readable wherever that stream is
collected. When the collector is unavailable there is no way to see why an
ingestion run failed without shell access to the host, and the error key Artemis
receives ("SLIDE_VISION_FAILED") names the failure without explaining it. This
buffer closes that gap: Artemis reads it over an internal endpoint and shows it
next to its own records.

Deliberately bounded and in-memory. It is a debugging aid, not a log store: it
holds the last ``_CAPACITY`` records, it is lost on restart, and it never touches
disk. Anything that has to survive either belongs in a real log pipeline.

Only the ingestion and retrieval loggers are captured, at DEBUG. Attaching this
to the root logger would bury the ingestion story in unrelated request traffic
and would sweep in records from every other pipeline, which is both noisier and
a wider exposure than the question needs.
"""

import logging
import threading
from collections import deque
from typing import Any, Optional

#: How many records are kept. Roughly a megabyte of typical records - enough to
#: cover a whole ingestion run without being worth tuning.
_CAPACITY = 2000

#: Longest traceback kept per record. A truncated traceback still names the
#: failure and its first frames, which is what a reader needs; keeping entire
#: ones lets a single crash loop evict the whole buffer.
_MAX_TRACEBACK_LENGTH = 8000

#: The loggers whose records are captured, together with their descendants.
CAPTURED_LOGGERS = (
    "iris.pipeline",
    "iris.retrieval",
    "iris.ingestion",
    "iris.vector_database",
    "iris.web.routers",
)

_lock = threading.Lock()
_records: deque = deque(maxlen=_CAPACITY)


class RecentLogsHandler(logging.Handler):
    """Appends each record to the shared buffer, already rendered to strings."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = {
                "timestamp": record.created * 1000.0,
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
                "stackTrace": self._render_traceback(record),
            }
        except Exception:  # pylint: disable=broad-except
            # Logging must never break the code being logged.
            return
        with _lock:
            _records.append(entry)

    def _render_traceback(self, record: logging.LogRecord) -> Optional[str]:
        if not record.exc_info:
            return None
        try:
            rendered = self.format(record)
        except Exception:  # pylint: disable=broad-except
            return None
        if len(rendered) <= _MAX_TRACEBACK_LENGTH:
            return rendered
        return rendered[:_MAX_TRACEBACK_LENGTH] + "\n... (truncated)"


def install() -> None:
    """Attach the handler to the captured loggers at DEBUG. Idempotent."""
    handler = RecentLogsHandler(level=logging.DEBUG)
    handler.setFormatter(logging.Formatter("%(message)s"))
    for name in CAPTURED_LOGGERS:
        logger = logging.getLogger(name)
        if any(isinstance(h, RecentLogsHandler) for h in logger.handlers):
            continue
        logger.addHandler(handler)
        # Lower this logger's own level so DEBUG records reach the handler even
        # when the root level is higher; propagation to stdout is unchanged.
        if logger.level == logging.NOTSET or logger.level > logging.DEBUG:
            logger.setLevel(logging.DEBUG)


def snapshot(limit: int = 500, level: Optional[str] = None) -> list[dict[str, Any]]:
    """Return the retained records, newest first.

    :param limit: how many to return, capped at the buffer size
    :param level: only records at exactly this level name, or None for all
    :return: the matching records, newest first
    """
    with _lock:
        items = list(_records)
    if level:
        wanted = level.upper()
        items = [item for item in items if item["level"] == wanted]
    items.reverse()
    return items[: max(1, min(limit, _CAPACITY))]


def clear() -> None:
    """Drop every retained record, so a reproduction holds only that attempt."""
    with _lock:
        _records.clear()
