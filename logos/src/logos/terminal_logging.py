"""Helpers for readable terminal-oriented structured logging.

Colour legend (each colour means exactly one thing):
  GREEN   = healthy / success
  YELLOW  = warning / degraded / queued
  RED     = error / unavailable
  CYAN    = identifiers (request IDs, lane IDs)
  MAGENTA = scheduler / routing events
  BLUE    = capacity / VRAM events
  BOLD    = model names, important counts
  DIM     = timestamps, secondary info
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import textwrap
from datetime import datetime, timezone
from typing import Any

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # Python < 3.9 fallback
    ZoneInfo = None  # type: ignore[assignment,misc]
    ZoneInfoNotFoundError = Exception  # type: ignore[assignment,misc]

GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"
MAGENTA = "\033[35m"
BLUE = "\033[34m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_LOGGER_ALIASES = {
    "LogosLogger": "app",
    "logos.capacity.capacity_planner": "planner",
    "logos.logosnode_registry": "registry",
    "logos.pipeline.correcting_scheduler": "scheduler",
    "logos.pipeline.base_scheduler": "scheduler",
    "logos.pipeline.executor": "executor",
    "logos.sdi.logosnode_facade": "logosnode",
    "logos.sdi.azure_facade": "azure",
    "uvicorn": "server",
    "uvicorn.error": "server",
    "uvicorn.access": "access",
    "http": "http",
    "-http": "http",
}
_LEVEL_ALIASES = {
    "DEBUG": "D",
    "INFO": "I",
    "WARNING": "W",
    "ERROR": "E",
    "CRITICAL": "C",
}


def paint(text: str, *styles: str) -> str:
    """Wrap text in ANSI styles."""
    if not styles:
        return text
    return f"{''.join(styles)}{text}{RESET}"


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from text."""
    return _ANSI_RE.sub("", text)


# ── Semantic style helpers ────────────────────────────────────────────────────


def style_model(name: str) -> str:
    """Bold model name."""
    return paint(str(name), BOLD)


def style_request_id(rid: str) -> str:
    """Cyan request identifier."""
    return paint(str(rid), CYAN)


def style_duration(ms: float) -> str:
    """Dim duration value with ms/s unit."""
    if ms >= 1000:
        return paint(f"{ms / 1000:.1f}s", DIM)
    return paint(f"{ms:.0f}ms", DIM)


def style_count(n: int | float) -> str:
    """Bold count/token number."""
    return paint(str(int(n)), BOLD)


# ── Human-readable unit formatting (German SI) ───────────────────────────────


def _de_fmt(value: float, decimals: int = 1) -> str:
    """Format a float with German decimal/thousands separators (no locale dep.)."""
    # Format with regular dot decimal first, then swap separators
    formatted = f"{value:,.{decimals}f}"  # e.g. "1,234.5"
    # Swap: ',' → tmp, '.' → ',', tmp → '.'
    formatted = formatted.replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return formatted


def format_bytes(mb: float) -> str:
    """Auto-scale MB to GB/TB with German number formatting (. thousands, , decimal).

    Examples: format_bytes(91657) → '89,5 GB'  format_bytes(512) → '512 MB'
    """
    if mb is None:
        return "? MB"
    mb = float(mb)
    if mb >= 1024 * 1024:
        return f"{_de_fmt(mb / (1024 * 1024))} TB"
    if mb >= 1024:
        return f"{_de_fmt(mb / 1024)} GB"
    return f"{_de_fmt(mb, decimals=0)} MB"


def format_number(n: float | int) -> str:
    """Format a number with German thousands separator (.).

    Example: format_number(1234567) → '1.234.567'
    """
    if n is None:
        return "?"
    formatted = f"{int(n):,}"  # e.g. "1,234,567"
    return formatted.replace(",", ".")


def format_vram(used_mb: float, total_mb: float) -> str:
    """Format VRAM usage as 'used/total (pct %)'."""
    pct = (used_mb / total_mb * 100) if total_mb > 0 else 0.0
    return f"{format_bytes(used_mb)}/{format_bytes(total_mb)} ({pct:.0f} %)"


# ── Model name cache ──────────────────────────────────────────────────────────


class ModelNameCache:
    """Thread-safe in-memory model-id → name resolver backed by the DB.

    Never hits the DB more than once per model_id. Falls back to str(model_id)
    on any error so log calls are always safe.
    """

    def __init__(self) -> None:
        self._cache: dict[int, str] = {}

    def get(self, model_id: int) -> str:
        """Return the model name for *model_id*, resolving via DB on first call."""
        if model_id in self._cache:
            return self._cache[model_id]
        name = self._resolve(model_id)
        self._cache[model_id] = name
        return name

    def _resolve(self, model_id: int) -> str:
        try:
            from logos.dbutils.dbmanager import DBManager  # noqa: PLC0415

            with DBManager() as db:
                info = db.get_model(model_id)
            return (info or {}).get("name") or str(model_id)
        except Exception:  # noqa: BLE001  # pylint: disable=broad-except
            return str(model_id)

    def prime(self, model_id: int, name: str) -> None:
        """Pre-populate the cache without a DB round-trip."""
        if name:
            self._cache[model_id] = name


#: Global singleton — import and use directly in other modules.
model_name_cache = ModelNameCache()


def terminal_width(default: int = 120, max_width: int = 140) -> int:
    """Best-effort terminal width for wrapped console sections."""
    try:
        width = shutil.get_terminal_size(fallback=(default, 24)).columns
    except OSError:
        width = default
    return max(88, min(width, max_width))


def wrap_plain(
    text: str,
    *,
    indent: str = "",
    subsequent_indent: str | None = None,
    width: int | None = None,
) -> list[str]:
    """Wrap plain text to the terminal width."""
    width = terminal_width() if width is None else max(40, width)
    subsequent_indent = indent if subsequent_indent is None else subsequent_indent
    wrapped = textwrap.wrap(
        text,
        width=max(20, width - len(strip_ansi(indent))),
        initial_indent=indent,
        subsequent_indent=subsequent_indent,
        break_long_words=False,
        break_on_hyphens=False,
    )
    return wrapped or [indent.rstrip()]


def render_section(title: str, body_lines: list[str], *, accent: str = CYAN) -> str:
    """Render a compact multiline section for terminal logs."""
    header = f"{paint('╭─', DIM)} {paint(title, BOLD, accent)}"
    body = [
        f"{paint('│', DIM)} {line}" if line else paint("│", DIM) for line in body_lines
    ]
    footer = paint("╰────────────────────────────────────────", DIM)
    return "\n".join([header, *body, footer])


def lane_state_color(runtime_state: str, sleep_state: str) -> str:
    """Return the preferred color for a lane state."""
    state = (runtime_state or "").strip().lower()
    sleep = (sleep_state or "").strip().lower()
    if state == "running":
        return GREEN + BOLD
    if state == "loaded" and sleep != "sleeping":
        return GREEN
    if sleep == "sleeping" or state == "sleeping":
        return YELLOW
    if state in {"starting", "cold"}:
        return CYAN
    if state in {"error", "stopped"}:
        return RED
    return DIM


def format_state(runtime_state: str, sleep_state: str) -> str:
    """Colorize a combined runtime/sleep state label."""
    color = lane_state_color(runtime_state, sleep_state)
    combined = f"{runtime_state or '?'} / {sleep_state or '?'}"
    return paint(combined, color)


def lane_metric_float(value: Any) -> float | None:
    """Convert a metric value to float when possible."""
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def lane_ttft_p95_seconds(backend_metrics: dict[str, Any]) -> float | None:
    """Estimate p95 TTFT from a Prometheus histogram dict."""
    histogram = backend_metrics.get("ttft_histogram")
    if not isinstance(histogram, dict) or not histogram:
        return None

    buckets: list[tuple[float, float]] = []
    for raw_bucket, raw_count in histogram.items():
        count = lane_metric_float(raw_count)
        if count is None or count < 0:
            continue
        bucket_label = str(raw_bucket).strip()
        if not bucket_label:
            continue
        if bucket_label == "+Inf":
            upper = float("inf")
        else:
            try:
                upper = float(bucket_label)
            except ValueError:
                continue
        buckets.append((upper, count))

    if not buckets:
        return None

    buckets.sort(key=lambda item: item[0])
    total = max(count for _upper, count in buckets)
    if total <= 0:
        return None
    target = total * 0.95
    for upper, count in buckets:
        if count >= target:
            return None if upper == float("inf") else upper
    last_upper = buckets[-1][0]
    return None if last_upper == float("inf") else last_upper


class MultiLineFormatter(logging.Formatter):
    """Formatter that prefixes every line of a multiline log record."""

    # Resolved once at class-instantiation time so every record conversion is O(1).
    _tz: Any = None  # zoneinfo.ZoneInfo or None (= UTC)
    _tz_resolved = False

    @classmethod
    def _get_tz(cls) -> Any:
        """Resolve TZ env var to a ZoneInfo object (cached)."""
        if cls._tz_resolved:
            return cls._tz
        cls._tz_resolved = True
        tz_name = os.environ.get("TZ", "Europe/Berlin")
        if ZoneInfo is not None:
            try:
                cls._tz = ZoneInfo(tz_name)
            except (ZoneInfoNotFoundError, KeyError):
                import logging as _log

                _log.getLogger(__name__).warning(
                    "TZ=%r is not a valid IANA timezone — falling back to UTC", tz_name
                )
                cls._tz = timezone.utc
        else:
            cls._tz = timezone.utc
        return cls._tz

    def __init__(
        self, fmt: str | None = None, datefmt: str | None = "%H:%M:%S"
    ) -> None:
        super().__init__(fmt=fmt, datefmt=datefmt)

    @staticmethod
    def _logger_label(name: str) -> str:
        alias = _LOGGER_ALIASES.get(name)
        if alias:
            return alias
        if not name:
            return "root"
        tail = name.rsplit(".", 1)[-1]
        return tail.replace("_", "-")

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        """Format timestamps as HH:MM:SS.mmm in the configured timezone."""
        tz = self._get_tz()
        dt = datetime.fromtimestamp(record.created, tz=tz)
        base = dt.strftime(datefmt or "%H:%M:%S")
        return f"{base}.{int(record.msecs):03d}"

    def format(self, record: logging.LogRecord) -> str:
        record.message = record.getMessage()
        if self.usesTime():
            record.asctime = self.formatTime(record, self.datefmt)

        logger_label = self._logger_label(record.name)
        level_label = _LEVEL_ALIASES.get(record.levelname, record.levelname[:1])
        prefix = f"{record.asctime} {logger_label:<10} {level_label} "
        continuation_prefix = " " * len(strip_ansi(prefix))
        lines = str(record.message).splitlines() or [""]
        formatted = "\n".join(
            [prefix + lines[0], *[continuation_prefix + line for line in lines[1:]]]
        )

        if record.exc_info and not record.exc_text:
            record.exc_text = self.formatException(record.exc_info)
        if record.exc_text:
            formatted += "\n" + "\n".join(
                continuation_prefix + line for line in record.exc_text.splitlines()
            )
        if record.stack_info:
            formatted += "\n" + "\n".join(
                continuation_prefix + line
                for line in self.formatStack(record.stack_info).splitlines()
            )
        return formatted


class UvicornAccessFilter(logging.Filter):
    """Hide routine successful access logs already represented elsewhere."""

    _SUPPRESSED_PATH_SNIPPETS = (
        "GET /health ",
        "GET /openapi.json ",
        "POST /logosdb/providers/logosnode/auth ",
        "GET /logosdb/providers/logosnode/runtime ",
    )
    # Inference endpoints: we emit our own per-request completion log line.
    _INFERENCE_PATH_SNIPPETS = (
        "POST /v1/chat/completions ",
        "POST /openai/chat/completions ",
        "POST /v1/completions ",
        "POST /openai/completions ",
        "POST /v1/embeddings ",
        "POST /openai/embeddings ",
    )

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if any(snippet in message for snippet in self._SUPPRESSED_PATH_SNIPPETS):
            if '" 200 ' in message or '" 101 ' in message:
                return False
        # Suppress 200 OK for inference endpoints — our completion log replaces this.
        if any(snippet in message for snippet in self._INFERENCE_PATH_SNIPPETS):
            if '" 200 ' in message:
                return False
        return True


class UvicornErrorFilter(logging.Filter):
    """Hide websocket noise and keep meaningful server lifecycle messages."""

    _SUPPRESSED_SUBSTRINGS = (
        "WebSocket /logosdb/providers/logosnode/session",
        "connection open",
        "connection closed",
    )

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return not any(snippet in message for snippet in self._SUPPRESSED_SUBSTRINGS)
