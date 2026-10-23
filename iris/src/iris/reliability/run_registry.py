"""Registry of the agent pipeline runs in flight, read by the watchdog and the thread dump."""

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from iris.config import ReliabilitySettings


@dataclass(eq=False)
class RunRecord:
    """One agent pipeline run, as the watchdog sees it."""

    run_id: str
    pipeline: str
    variant: str
    local: bool
    callback: Any
    thread_id: int
    # time.perf_counter() at pipeline start, the same clock the pipeline's own timings use.
    started_at: float
    # Seconds until the answer must be sent; None for pipelines without a deadline.
    deadline_seconds: Optional[float] = None
    model_id: Optional[str] = None
    is_chat: bool = False
    action_in_flight: bool = False
    last_heartbeat_at: float = field(default_factory=time.perf_counter)


def chat_deadline_seconds(
    settings: ReliabilitySettings, variant_id: str, local: bool
) -> float:
    if local:
        return settings.chat_local_deadline_seconds
    if variant_id == "advanced":
        return settings.chat_advanced_deadline_seconds
    return settings.chat_deadline_seconds


class RunRegistry:
    """Thread-safe set of the runs in flight."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runs: list[RunRecord] = []

    def register(self, record: RunRecord) -> RunRecord:
        with self._lock:
            self._runs.append(record)
        return record

    def unregister(self, record: RunRecord) -> None:
        with self._lock:
            if record in self._runs:
                self._runs.remove(record)

    def snapshot(self) -> list[RunRecord]:
        with self._lock:
            return list(self._runs)


run_registry = RunRegistry()
