"""
Environment-gated per-request performance tracing.

Enabled via ``LOGOS_PERF_TRACE=1`` (default off). When disabled, every marker
is a single boolean check plus a no-op context manager, i.e. the tracing
plumbing costs nothing measurable on the hot path.

When enabled, callers mark phases around the interesting sections of the
request path::

    with perf_trace.phase(request_id, "db.response_block.usage_inserts"):
        ...

Phase durations accumulate as (total_ns, count) per phase name. The finished
trace is fetched exactly once via :func:`take` (pop semantics) — the benchmark
harness reads it through the ``/internal/perf_trace/{request_id}`` endpoint.

The store is bounded (LRU by insertion order) so a missed ``take`` cannot grow
memory without limit; it lives on the single asyncio event loop, so no
locking is required.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional

_TRACE_ENV_VAR = "LOGOS_PERF_TRACE"

# Bounded store: oldest traces are evicted first if never taken.
_MAX_TRACES = 2048


def _truthy(value: Optional[str]) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


_ENABLED = _truthy(os.environ.get(_TRACE_ENV_VAR))

# request_id → {"t0_ns": int, "end_ns": int, "phases": {name: [total_ns, count]}}
_traces: Dict[str, Dict[str, Any]] = {}


class _PhaseSpan:
    """One traced phase; supports both ``with`` and ``async with``."""

    __slots__ = ("_trace", "_name", "_start_ns")

    def __init__(self, trace: Dict[str, Any], name: str) -> None:
        self._trace = trace
        self._name = name
        self._start_ns = 0

    def _start(self) -> None:
        self._start_ns = time.perf_counter_ns()

    def _stop(self) -> None:
        bucket = self._trace["phases"].setdefault(self._name, [0, 0])
        bucket[0] += time.perf_counter_ns() - self._start_ns
        bucket[1] += 1

    def __enter__(self) -> "_PhaseSpan":
        self._start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._stop()

    async def __aenter__(self) -> "_PhaseSpan":
        self._start()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        self._stop()


class _NullSpan:
    """No-op span used while tracing is disabled (one shared instance)."""

    __slots__ = ()

    def __enter__(self) -> "_NullSpan":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    async def __aenter__(self) -> "_NullSpan":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None


_NULL_SPAN = _NullSpan()


def enabled() -> bool:
    """Whether perf tracing is active (env-gated, decided at import time)."""
    return _ENABLED


def begin(request_id: str) -> None:
    """Start tracing a request. Cheap no-op while disabled or unknown id."""
    if not _ENABLED or not request_id:
        return
    if len(_traces) >= _MAX_TRACES and request_id not in _traces:
        # Evict the oldest never-taken trace (dict keeps insertion order).
        _traces.pop(next(iter(_traces)), None)
    _traces[request_id] = {"t0_ns": time.perf_counter_ns(), "end_ns": 0, "phases": {}}


def phase(request_id: str, name: str) -> Any:
    """Context manager (sync ``with`` or ``async with``) marking a phase."""
    if not _ENABLED or not request_id:
        return _NULL_SPAN
    trace = _traces.get(request_id)
    if trace is None:
        return _NULL_SPAN
    return _PhaseSpan(trace, name)


def merge_worker(request_id: str, phases: Optional[Dict[str, Dict[str, int]]], prefix: str = "rpc.worker.") -> None:
    """Fold the worker-side phase breakdown into the request's trace.

    The worker (``LOGOS_WORKER_PERF_TRACE=1``) returns its phases in the same
    ``{name: {"total_ns", "count"}}`` shape inside the command result. When
    worker tracing is off the dict is absent/empty and this is a no-op; the
    transport cost then shows up as ``rpc.send_command − sum(rpc.worker.*)``.
    """
    if not _ENABLED or not request_id or not phases:
        return
    trace = _traces.get(request_id)
    if trace is None:
        return
    for name, bucket in phases.items():
        try:
            total_ns = int(bucket.get("total_ns", 0))
            count = int(bucket.get("count", 0))
        except (AttributeError, TypeError, ValueError):
            continue
        if total_ns <= 0 and count <= 0:
            continue
        target = trace["phases"].setdefault(prefix + name, [0, 0])
        target[0] += total_ns
        target[1] += count


def finish(request_id: str) -> None:
    """Mark the request as done (records the end offset)."""
    if not _ENABLED or not request_id:
        return
    trace = _traces.get(request_id)
    if trace is not None:
        trace["end_ns"] = time.perf_counter_ns()


def take(request_id: str) -> Optional[Dict[str, Any]]:
    """Pop and return the trace for ``request_id`` (None if absent).

    Shape: ``{"t0_ns": int, "end_ns": int,
    "phases": {name: {"total_ns": int, "count": int}}}``.
    ``end_ns`` is 0 when :func:`finish` was never reached.
    """
    if not request_id:
        return None
    trace = _traces.pop(request_id, None)
    if trace is None:
        return None
    return {
        "t0_ns": trace["t0_ns"],
        "end_ns": trace["end_ns"],
        "phases": {name: {"total_ns": bucket[0], "count": bucket[1]} for name, bucket in trace["phases"].items()},
    }


def reset() -> None:
    """Drop all pending traces (used by the internal flush endpoint)."""
    _traces.clear()
