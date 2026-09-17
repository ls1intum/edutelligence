"""
Environment-gated worker-side perf tracing (``LOGOS_WORKER_PERF_TRACE=1``).

Each infer command gets a fresh tracer whose phase breakdown rides back in the
``command_result`` under the ``perf`` key; the orchestrator folds it into the
request's trace under ``rpc.worker.*`` when both sides trace. The transport
cost then shows up as ``rpc.send_command`` minus the worker phases.

While disabled, :func:`begin` returns ``None`` and the call sites cost a single
attribute check — no per-phase timing, no allocation.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional

_ENABLED = (os.environ.get("LOGOS_WORKER_PERF_TRACE") or "").strip().lower() in {"1", "true", "yes", "on"}


class _Span:
    """One traced phase; supports both ``with`` and ``async with``."""

    __slots__ = ("_tracer", "_name", "_start_ns")

    def __init__(self, tracer: "_Tracer", name: str) -> None:
        self._tracer = tracer
        self._name = name
        self._start_ns = 0

    def _start(self) -> None:
        self._start_ns = time.perf_counter_ns()

    def _stop(self) -> None:
        bucket = self._tracer._phases.setdefault(self._name, [0, 0])
        bucket[0] += time.perf_counter_ns() - self._start_ns
        bucket[1] += 1

    def __enter__(self) -> "_Span":
        self._start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._stop()

    async def __aenter__(self) -> "_Span":
        self._start()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        self._stop()


class _Tracer:
    """One command's phase accumulator."""

    __slots__ = ("_phases",)

    def __init__(self) -> None:
        # name → [total_ns, count]
        self._phases: Dict[str, list] = {}

    def phase(self, name: str) -> _Span:
        return _Span(self, name)

    def finish(self) -> Dict[str, Dict[str, int]]:
        """The shape the orchestrator's merge_worker expects."""
        return {name: {"total_ns": bucket[0], "count": bucket[1]} for name, bucket in self._phases.items()}


def begin() -> Optional[_Tracer]:
    """A fresh per-command tracer, or ``None`` while tracing is disabled."""
    return _Tracer() if _ENABLED else None
