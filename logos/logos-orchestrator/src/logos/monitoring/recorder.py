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

# Age past which a tracked request is assumed to be a bookkeeping leak rather
# than a slow request. Deliberately far beyond anything legitimate: the queue
# wait alone is bounded at 1200s and a cold load plus generation can add to
# that, so an hour of headroom keeps the sweep from ever touching a live
# request. Without a bound, one missed terminal path grows the map — and the
# gauge derived from it — without limit.
_STALE_REQUEST_AGE_S = 2 * 60 * 60

# How often the opportunistic sweep may run. The recorder has no background
# loop of its own, so it piggybacks on request arrivals.
_STALE_SWEEP_INTERVAL_S = 60.0
_last_stale_sweep = 0.0


def _publish_in_flight() -> None:
    """Publish the in-flight gauge from the tracked set.

    The gauge used to be hand-maintained with paired ``inc()``/``dec()``
    calls, which drifted in both directions: terminal paths that never
    reached ``record_complete`` (a client disconnect, a rate-limit or budget
    reject) left an increment behind forever, while a request that failed
    classification completed without ever having been enqueued and
    decremented one it never added. Deriving the value from the map it is
    supposed to describe makes both impossible.
    """
    prom.REQUESTS_IN_FLIGHT.set(len(_request_states))


def _sweep_stale_requests(now: float) -> None:
    """Drop tracked requests too old to still be running.

    A safety net, not the mechanism: terminal paths are expected to finalise
    their own request. This only keeps a future missed path from growing the
    map without bound and pinning the gauge to a number that never comes
    down again.
    """
    global _last_stale_sweep
    if now - _last_stale_sweep < _STALE_SWEEP_INTERVAL_S:
        return
    _last_stale_sweep = now

    cutoff = now - _STALE_REQUEST_AGE_S
    stale = [request_id for request_id, (start, _m, _p) in _request_states.items() if start < cutoff]
    for request_id in stale:
        _request_states.pop(request_id, None)
    if stale:
        logger.warning(
            "Dropped %d request(s) tracked for more than %ds — a terminal path did not finalise them",
            len(stale),
            _STALE_REQUEST_AGE_S,
        )


def _nonneg_int(value: Any) -> Optional[int]:
    """A non-negative int token count, or None when the value is unusable.

    ``bool`` is an ``int`` subclass but never a token count, so it is
    excluded explicitly (same rule as ``extract_token_usage``).
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


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
        if queue_depth is not None:
            prom.QUEUE_DEPTH.set(queue_depth)
        model, provider = _resolve_label_names(model_id, provider_id)
        now = time.monotonic()
        _sweep_stale_requests(now)
        _request_states[request_id] = (now, model, provider)
        _publish_in_flight()

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

    def _settle(
        self,
        request_id: str,
        result_status: ResultStatus | str,
        cold_start: Optional[bool] = None,
        usage_tokens: Optional[Dict[str, int]] = None,
    ) -> str:
        """Close out a request's metrics and return the status string.

        Idempotent: a request that was already settled, or one that never
        reached ``record_enqueue`` (a classification failure completes before
        it is ever enqueued), contributes no duration observation and cannot
        move the in-flight gauge.

        ``usage_tokens`` is the ``extract_token_usage`` dict of a completed
        request (``prompt_tokens`` / ``completion_tokens`` /
        ``prompt_cached_tokens``). Token counters count what the provider
        actually processed, so they are observed for every outcome — a
        timeout that streamed most of the generation still consumed those
        tokens.
        """
        status_value = result_status.value if isinstance(result_status, ResultStatus) else str(result_status)

        state = _request_states.pop(request_id, None)
        _publish_in_flight()
        if state is None:
            # Nothing to settle: either this request was already settled — a
            # context-resolution failure passes through `_record_log_failure`
            # twice, once in the mode handler and once in the outer exception
            # handler — or it never got as far as being enqueued. Counting
            # here would inflate the outcome totals past the enqueue count;
            # keeping the counter inside this branch makes
            # `enqueued == sum(terminal states)` hold by construction.
            return status_value

        prom.REQUESTS_TOTAL.labels(status=status_value).inc()

        start, model, provider = state
        prom.REQUEST_DURATION_SECONDS.labels(
            model=model,
            provider=provider,
            status=status_value,
        ).observe(time.monotonic() - start)

        if cold_start:
            prom.COLD_STARTS_TOTAL.labels(model=model, provider=provider).inc()
        if usage_tokens:
            self._observe_token_usage(model, provider, usage_tokens)
        return status_value

    @staticmethod
    def _observe_token_usage(model: str, provider: str, usage_tokens: Dict[str, int]) -> None:
        """Feed the token counters and the per-model context-window histogram.

        ``extract_token_usage`` already stores ints only, but the recorder
        must not break a request over a malformed dict, so each value is
        coerced defensively and skipped when absent.
        """
        prompt_tokens = _nonneg_int(usage_tokens.get("prompt_tokens"))
        completion_tokens = _nonneg_int(usage_tokens.get("completion_tokens"))
        cached_tokens = _nonneg_int(usage_tokens.get("prompt_cached_tokens"))

        if prompt_tokens is not None:
            prom.PROMPT_TOKENS_TOTAL.labels(model=model, provider=provider).inc(prompt_tokens)
        if completion_tokens is not None:
            prom.GENERATION_TOKENS_TOTAL.labels(model=model, provider=provider).inc(completion_tokens)
        if cached_tokens is not None:
            prom.CACHED_PROMPT_TOKENS_TOTAL.labels(model=model, provider=provider).inc(cached_tokens)

        context_tokens = (prompt_tokens or 0) + (completion_tokens or 0)
        if context_tokens > 0:
            # How much of the model's context window the request used — the
            # signal for whether a deployment can be downsized or needs a
            # bigger window.
            prom.REQUEST_CONTEXT_TOKENS.labels(model=model).observe(context_tokens)

    def discard(self, request_id: str, result_status: ResultStatus | str) -> None:
        """Finalise a request whose terminal state was persisted elsewhere.

        Used by the failure paths that write the log row themselves — a
        client disconnect, a rate-limit or budget reject. They used to leave
        the request counted as in-flight forever; production was leaking
        ~470 of them a day, which is what made the gauge climb without ever
        coming back down.
        """
        self._settle(request_id, result_status)

    def record_complete(
        self,
        request_id: str,
        result_status: ResultStatus | str,
        cold_start: Optional[bool] = None,
        error_message: Optional[str] = None,
        usage_tokens: Optional[Dict[str, int]] = None,
    ) -> None:
        status_value = self._settle(request_id, result_status, cold_start, usage_tokens)

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
