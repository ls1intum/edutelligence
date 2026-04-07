"""Helpers for readable terminal-oriented structured logging."""

from __future__ import annotations

from datetime import datetime
import logging
import re
import shutil
import textwrap
from typing import Any

GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"
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
    body = [f"{paint('│', DIM)} {line}" if line else paint("│", DIM) for line in body_lines]
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

    def __init__(self, fmt: str | None = None, datefmt: str | None = "%H:%M:%S") -> None:
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
        """Format timestamps as HH:MM:SS.mmm for compact terminal logs."""
        dt = datetime.fromtimestamp(record.created)
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
                continuation_prefix + line for line in self.formatStack(record.stack_info).splitlines()
            )
        return formatted


class UvicornAccessFilter(logging.Filter):
    """Hide routine successful access logs already represented elsewhere."""

    _SUPPRESSED_PATH_SNIPPETS = (
        'GET /health ',
        'GET /openapi.json ',
        'POST /logosdb/providers/logosnode/auth ',
        'GET /logosdb/providers/logosnode/runtime ',
    )

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if any(snippet in message for snippet in self._SUPPRESSED_PATH_SNIPPETS):
            if '" 200 ' in message or '" 101 ' in message:
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
