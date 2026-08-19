"""
Lightweight request monitoring recorder.

Writes request performance fields onto the existing `log_entry` row keyed by
request_id. Designed to be optional and non-intrusive: failures are logged and
never propagate back into scheduling/request handling.
"""

from __future__ import annotations

import datetime
import logging
import time
from typing import Any, Callable, Dict, Optional

from logos.dbutils.dbmanager import DBManager
from logos.dbutils.dbmodules import ResultStatus
from logos.monitoring import prometheus_metrics as prom
from logos.terminal_logging import model_name_cache, provider_name_cache

logger = logging.getLogger(__name__)

# Track in-flight requests: request_id → (start_time, model, provider).
# start_time feeds the duration histogram; model/provider are the label
# values for REQUEST_DURATION_SECONDS / COLD_STARTS_TOTAL (see #738) —
# "unknown" is only the pre-selection fallback.
_request_states: Dict[str, tuple[float, str, str]] = {}


def _resolve_label_names(model_id: Optional[int], provider_id: Optional[int]) -> tuple[str, str]:
    """Resolve the model/provider label values for completion metrics.

    Uses the in-memory name caches (DB-backed, at most one lookup per id).
    None ids — requests that failed before a model/provider was selected —
    keep the "unknown" fallback so no observation is dropped.
    """
    model = model_name_cache.get(model_id) if model_id is not None else "unknown"
    provider = provider_name_cache.get(provider_id) if provider_id is not None else "unknown"
    return model, provider


class MonitoringRecorder:
    """
    Minimal recorder that updates request lifecycle fields on log_entry.
    """

    def __init__(self, db_factory: Callable[[], DBManager] = DBManager) -> None:
        self._db_factory = db_factory

    def record_enqueue(
        self,
        request_id: str,
        model_id: Optional[int],
        provider_id: Optional[int],
        initial_priority: Optional[str],
        queue_depth: Optional[int],
        timeout_s: Optional[int] = None,
    ) -> None:
        prom.REQUESTS_TOTAL.labels(status="enqueued").inc()
        prom.REQUESTS_IN_FLIGHT.inc()
        if queue_depth is not None:
            prom.QUEUE_DEPTH.set(queue_depth)
        model, provider = _resolve_label_names(model_id, provider_id)
        _request_states[request_id] = (time.monotonic(), model, provider)

        payload = {
            "model_id": model_id,
            "provider_id": provider_id,
            "initial_priority": initial_priority,
            "queue_depth_at_enqueue": queue_depth,
            "timeout_s": timeout_s,
        }
        self._write(request_id, **payload)

    def record_scheduled(
        self,
        request_id: str,
        model_id: int,
        provider_id: Optional[int],
        priority_when_scheduled: Optional[str],
        queue_depth_at_schedule: Optional[int],
        provider_metrics: Dict[str, Any] = None,
    ) -> None:
        """
        Record when a request is scheduled.

        Args:
            request_id: Unique request ID.
            model_id: Selected model ID.
            provider_id: Selected provider ID.
            priority_when_scheduled: Priority string (low/normal/high).
            queue_depth_at_schedule: Total system queue depth at scheduling time.
            provider_metrics: Dictionary of provider-specific metrics (e.g. VRAM, rate limits).
        """
        prom.REQUESTS_TOTAL.labels(status="scheduled").inc()
        prom.SCHEDULING_DECISIONS_TOTAL.labels(result="scheduled").inc()

        # Overwrite the enqueue-time labels with the actually selected
        # model/provider; keep the original start time for duration.
        model, provider = _resolve_label_names(model_id, provider_id)
        previous = _request_states.get(request_id)
        start = previous[0] if previous is not None else time.monotonic()
        _request_states[request_id] = (start, model, provider)

        payload = {
            "model_id": model_id,
            "provider_id": provider_id,
            "priority_when_scheduled": priority_when_scheduled,
            "queue_depth_at_schedule": queue_depth_at_schedule,
            "scheduled_ts": datetime.datetime.now(datetime.timezone.utc),
        }

        # Flatten provider metrics for DB columns
        if provider_metrics:
            for key, value in provider_metrics.items():
                if key in [
                    "available_vram_mb",
                    "azure_rate_remaining_requests",
                    "azure_rate_remaining_tokens",
                ]:
                    payload[key] = value
        self._write(request_id, **payload)

    def record_complete(
        self,
        request_id: str,
        result_status: ResultStatus | str,
        cold_start: Optional[bool] = None,
        error_message: Optional[str] = None,
    ) -> None:
        status_value = result_status.value if isinstance(result_status, ResultStatus) else str(result_status)

        prom.REQUESTS_TOTAL.labels(status=status_value).inc()
        prom.REQUESTS_IN_FLIGHT.dec()

        state = _request_states.pop(request_id, None)
        if state is not None:
            start, model, provider = state
        else:
            start, model, provider = None, "unknown", "unknown"

        if start is not None:
            duration = time.monotonic() - start
            prom.REQUEST_DURATION_SECONDS.labels(
                model=model,
                provider=provider,
                status=status_value,
            ).observe(duration)

        if cold_start:
            prom.COLD_STARTS_TOTAL.labels(model=model).inc()

        payload = {
            "request_complete_ts": datetime.datetime.now(datetime.timezone.utc),
            "result_status": status_value,
            "cold_start": cold_start,
            "error_message": error_message,
        }
        self._write(request_id, **payload)

    def record_provider(self, request_id: str, provider_id: int) -> None:
        """Attach provider_id once it is resolved (after scheduling)."""
        self._write(request_id, provider_id=provider_id)

    def record_provider_metrics(self, request_id: str, provider_metrics: Dict[str, Any]) -> None:
        """
        Update provider metrics (e.g. Azure rate limits) for a request.
        """
        if not provider_metrics:
            return

        payload = {}
        for key, value in provider_metrics.items():
            if key in [
                "available_vram_mb",
                "azure_rate_remaining_requests",
                "azure_rate_remaining_tokens",
            ]:
                payload[key] = value

        if payload:
            self._write(request_id, **payload)

    def _write(self, request_id: str, **fields: object) -> None:
        try:
            with self._db_factory() as db:
                db.update_request_log_metrics(request_id=request_id, **fields)
        except Exception as exc:  # pragma: no cover - monitoring must not break prod
            logger.debug("Failed to record monitoring event for %s: %s", request_id, exc)
