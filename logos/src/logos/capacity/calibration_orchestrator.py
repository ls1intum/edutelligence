"""Server-side trigger for worker-driven VRAM calibration.

The CalibrationOrchestrator is now a thin gatekeeper. The worker owns the
calibration loop: it picks which uncalibrated model runs next, walks its own
model list, and emits ``calibration_*`` events back to the server when each
model completes. The orchestrator only:

  * Watches the maintenance window (default 02:00–05:00 Europe/Berlin).
  * When inside the window and no other worker has a session in progress,
    picks one idle, healthy worker that still has uncalibrated models and
    sends ``start_calibration_session``.
  * When outside the window, sends ``stop_calibration_session`` to the
    provider that holds the active session — the worker tears the in-flight
    vLLM probe down inside ~2s.
  * Reacts to ``calibration_session_finished`` / ``_cancelled`` events to
    free the active-provider slot so the next tick can pick someone else.

Design invariants (unchanged from the previous design):
- Only one worker calibrates at a time across the cluster.
- A worker is considered idle if it has no active inference requests AND is
  not already running a calibration session.
- The orchestrator never polls calibration status. The worker speaks first.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import time
from typing import TYPE_CHECKING

logger = logging.getLogger("logos.capacity.calibration_orchestrator")

if TYPE_CHECKING:
    from logos.logosnode_registry import LogosNodeRuntimeRegistry
    from logos.sdi.logosnode_facade import LogosNodeSchedulingDataFacade


# Terminal session events that free the active-provider slot.
_TERMINAL_SESSION_EVENTS = frozenset({"calibration_session_finished", "calibration_session_cancelled"})


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class CalibrationConfig:
    """Nightly calibration window and behaviour knobs.

    All values can be overridden via environment variables so that
    operators can tune them without touching YAML.

    LOGOS_CALIB_WINDOW_START  e.g. "02:00" (HH:MM, default 02:00)
    LOGOS_CALIB_WINDOW_END    e.g. "05:00" (HH:MM, default 05:00)
    LOGOS_CALIB_TIMEZONE      e.g. "Europe/Berlin" (default Europe/Berlin)
    LOGOS_CALIB_ENABLED       "true" / "false" (default true)
    LOGOS_CALIB_SLEEP_LEVEL   "1" or "2" (default 1)
    LOGOS_CALIB_TICK_SECONDS  trigger-loop tick interval in seconds (default 60)
    """

    window_start: time = field(default_factory=lambda: time(2, 0))
    window_end: time = field(default_factory=lambda: time(5, 0))
    timezone: str = "Europe/Berlin"
    enabled: bool = True
    sleep_level: int = 1
    tick_seconds: float = 60.0

    @classmethod
    def from_env(cls) -> "CalibrationConfig":
        """Build a CalibrationConfig from environment variables (with defaults)."""

        def _parse_time(raw: str, default: time) -> time:
            raw = raw.strip()
            if not raw:
                return default
            try:
                h, m = raw.split(":", 1)
                return time(int(h), int(m))
            except (ValueError, TypeError):
                logger.warning("CalibrationConfig: invalid time %r — using default %s", raw, default)
                return default

        def _parse_bool(raw: str, default: bool) -> bool:
            return raw.strip().lower() in {"1", "true", "yes"} if raw.strip() else default

        def _parse_int(raw: str, default: int) -> int:
            try:
                return int(raw.strip()) if raw.strip() else default
            except ValueError:
                return default

        def _parse_float(raw: str, default: float) -> float:
            try:
                return float(raw.strip()) if raw.strip() else default
            except ValueError:
                return default

        return cls(
            window_start=_parse_time(os.getenv("LOGOS_CALIB_WINDOW_START", ""), time(3, 0)),
            window_end=_parse_time(os.getenv("LOGOS_CALIB_WINDOW_END", ""), time(8, 0)),
            timezone=os.getenv("LOGOS_CALIB_TIMEZONE", "Europe/Berlin").strip() or "Europe/Berlin",
            enabled=_parse_bool(os.getenv("LOGOS_CALIB_ENABLED", ""), True),
            sleep_level=_parse_int(os.getenv("LOGOS_CALIB_SLEEP_LEVEL", ""), 1),
            tick_seconds=_parse_float(os.getenv("LOGOS_CALIB_TICK_SECONDS", ""), 60.0),
        )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class CalibrationOrchestrator:
    """Triggers worker-driven calibration sessions inside the nightly window."""

    def __init__(
        self,
        registry: "LogosNodeRuntimeRegistry",
        facade: "LogosNodeSchedulingDataFacade",
        config: CalibrationConfig | None = None,
    ) -> None:
        self._registry = registry
        self._facade = facade
        self._config = config or CalibrationConfig.from_env()
        self._task: asyncio.Task[None] | None = None
        # The single provider currently running a session, or None when no
        # session is in flight anywhere in the cluster. Updated when we
        # send start_calibration_session and cleared by on_event() when the
        # worker emits a terminal session event.
        self._active_provider_id: int | None = None
        # Providers we have already kicked off this window. A worker that
        # finishes its session is not asked again until the next window —
        # whatever models it couldn't calibrate (failures, unsupported)
        # would loop the same way on a retry. Cleared on window edge.
        self._completed_this_window: set[int] = set()
        self._was_in_window: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if not self._config.enabled:
            logger.info("CalibrationOrchestrator: disabled via config — not starting")
            return
        if self._task is not None and not self._task.done():
            return
        # Subscribe to worker events so we react to terminal session events
        # without polling. If the registry does not expose subscription
        # (older builds), we still function — the next tick would just
        # try to start another session on an idle provider while the
        # current one still runs, and the worker would refuse it. The
        # subscribe path is the fast path.
        subscribe = getattr(self._registry, "subscribe_to_events", None)
        if callable(subscribe):
            subscribe(self._on_provider_event)
        self._task = asyncio.create_task(self._tick_loop(), name="calibration-orchestrator")
        logger.info(
            "CalibrationOrchestrator: started (window %s–%s %s, tick=%.0fs)",
            self._config.window_start.strftime("%H:%M"),
            self._config.window_end.strftime("%H:%M"),
            self._config.timezone,
            self._config.tick_seconds,
        )

    async def stop(self) -> None:
        if self._task is None or self._task.done():
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        unsubscribe = getattr(self._registry, "unsubscribe_from_events", None)
        if callable(unsubscribe):
            unsubscribe(self._on_provider_event)
        logger.info("CalibrationOrchestrator: stopped")

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _tick_loop(self) -> None:
        while True:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("CalibrationOrchestrator: unhandled error in tick — will retry")
            await asyncio.sleep(self._config.tick_seconds)

    async def _tick(self) -> None:
        in_window = self._is_in_window()
        if in_window != self._was_in_window:
            # Window edge: reset per-window bookkeeping so the next window
            # gets a clean slate.
            self._completed_this_window.clear()
            self._was_in_window = in_window

        if not in_window:
            await self._stop_active_session_if_any("outside-window")
            return

        # Inside window: do nothing if a session is already running.
        if self._active_provider_id is not None:
            return

        target_provider_id = self._pick_next_provider()
        if target_provider_id is None:
            logger.debug("CalibrationOrchestrator: no idle worker with uncalibrated models — waiting for next tick")
            return

        await self._start_session_on(target_provider_id)

    # ------------------------------------------------------------------
    # Window check
    # ------------------------------------------------------------------

    def _is_in_window(self) -> bool:
        try:
            from zoneinfo import ZoneInfo  # Python 3.9+
        except ImportError:
            try:
                from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]
            except ImportError:
                logger.warning("CalibrationOrchestrator: zoneinfo not available — assuming inside window")
                return True
        from datetime import datetime

        tz = ZoneInfo(self._config.timezone)
        now = datetime.now(tz=tz).time().replace(tzinfo=None)
        start = self._config.window_start
        end = self._config.window_end

        if start <= end:
            return start <= now < end
        # Overnight window (e.g. 23:00–02:00)
        return now >= start or now < end

    # ------------------------------------------------------------------
    # Provider selection
    # ------------------------------------------------------------------

    def _pick_next_provider(self) -> int | None:
        """Return the first eligible provider that still has uncalibrated models."""
        for provider_id in self._facade.provider_ids():
            if provider_id in self._completed_this_window:
                continue
            if not self._registry.has_received_first_status(provider_id):
                continue
            if self._provider_is_unhealthy(provider_id):
                continue
            if self._provider_has_active_requests(provider_id):
                continue
            if not self._provider_has_uncalibrated_models(provider_id):
                # Whole worker is calibrated — mark done for this window so
                # we don't re-evaluate it every tick.
                self._completed_this_window.add(provider_id)
                continue
            return provider_id
        return None

    def _provider_is_unhealthy(self, provider_id: int) -> bool:
        """Return True if the worker's latest runtime status reports
        ``node_health.healthy=False``.
        """
        try:
            snap = self._registry.peek_runtime_snapshot(provider_id)
        except Exception:
            return False
        if not isinstance(snap, dict):
            return False
        runtime = snap.get("runtime")
        if not isinstance(runtime, dict):
            return False
        node_health = runtime.get("node_health")
        if not isinstance(node_health, dict):
            return False
        return not bool(node_health.get("healthy", True))

    def _provider_has_active_requests(self, provider_id: int) -> bool:
        """Return True if the provider has any active inference requests."""
        try:
            signals = self._facade.get_all_provider_lane_signals(provider_id)
        except Exception:
            # Telemetry unavailable — assume busy to avoid interrupting work.
            return True
        for sig in signals:
            if int(getattr(sig, "active_requests", 0) or 0) > 0:
                return True
            if float(getattr(sig, "queue_waiting", 0.0) or 0.0) > 0.0:
                return True
        return False

    def _provider_has_uncalibrated_models(self, provider_id: int) -> bool:
        """Return True when the worker still has at least one model that needs
        calibration. Mirrors the worker's own selection logic so we don't fire
        a session that immediately ends as a no-op.
        """
        candidates = self._facade.get_configured_models(provider_id)
        if not candidates:
            candidates = self._facade.get_worker_capabilities(provider_id)
        try:
            profiles = self._facade.get_model_profiles(provider_id)
        except Exception:
            profiles = {}

        for model_name in candidates:
            profile = profiles.get(model_name)
            if profile is not None and profile.calibration_unsupported:
                continue
            sleep_na = bool(profile is not None and profile.sleep_mode_disabled)
            collapsed_envelope = (
                profile is not None
                and profile.min_kv_cache_mb is not None
                and profile.max_kv_cache_mb is not None
                and profile.min_kv_cache_mb > 0
                and profile.min_kv_cache_mb == profile.max_kv_cache_mb
            )
            needs_calib = (
                profile is None
                or profile.base_residency_mb is None
                or (not sleep_na and profile.sleeping_residual_mb is None)
                or (not sleep_na and profile.sleep_l1_transient_host_ram_mb is None)
                or collapsed_envelope
            )
            if needs_calib:
                return True
        return False

    # ------------------------------------------------------------------
    # RPC drivers
    # ------------------------------------------------------------------

    async def _start_session_on(self, provider_id: int) -> None:
        from logos.logosnode_registry import LogosNodeCommandError, LogosNodeOfflineError

        provider_name = self._facade.get_provider_name(provider_id) or str(provider_id)
        # Mark active before sending so a concurrent terminal-event handler
        # (e.g. from a duplicate connect) can clear it cleanly without us
        # also firing the same start a second time on the next tick.
        self._active_provider_id = provider_id
        try:
            await self._registry.send_command(
                provider_id,
                "start_calibration_session",
                params={"sleep_level": self._config.sleep_level},
                timeout_seconds=30,
            )
            logger.info(
                "CalibrationOrchestrator: session started on provider=%s sleep_level=%d",
                provider_name,
                self._config.sleep_level,
            )
        except LogosNodeOfflineError:
            logger.warning(
                "CalibrationOrchestrator: provider=%s offline — could not start session",
                provider_name,
            )
            self._active_provider_id = None
        except LogosNodeCommandError as exc:
            logger.warning(
                "CalibrationOrchestrator: start_calibration_session failed on provider=%s: %s",
                provider_name,
                exc,
            )
            self._active_provider_id = None
            # Don't retry this provider in this window — whatever made the
            # worker refuse (e.g. node unhealthy at the last second) will
            # likely repeat next tick.
            self._completed_this_window.add(provider_id)
        except Exception:
            logger.exception(
                "CalibrationOrchestrator: unexpected error starting session on provider=%s",
                provider_name,
            )
            self._active_provider_id = None

    async def _stop_active_session_if_any(self, reason: str) -> None:
        """Outside the window (or on shutdown): tell the active worker to stop.

        The worker reacts within ~2s — wait_ready polls cancel_event during
        vLLM probe startup. The terminal session_cancelled event clears
        ``_active_provider_id`` via on_event().
        """
        provider_id = self._active_provider_id
        if provider_id is None:
            return
        from logos.logosnode_registry import LogosNodeCommandError, LogosNodeOfflineError

        provider_name = self._facade.get_provider_name(provider_id) or str(provider_id)
        logger.info(
            "CalibrationOrchestrator: stopping calibration session on provider=%s (%s)",
            provider_name,
            reason,
        )
        try:
            await self._registry.send_command(
                provider_id,
                "stop_calibration_session",
                timeout_seconds=20,
            )
        except (LogosNodeOfflineError, LogosNodeCommandError, Exception):
            logger.debug(
                "CalibrationOrchestrator: stop_calibration_session on provider=%s failed (ignored)",
                provider_name,
                exc_info=True,
            )
            # Even if the RPC fails (worker disconnected, etc.) we treat
            # the slot as freed — the orchestrator doesn't own the worker's
            # subprocess and a stale active slot would block other workers.
            self._active_provider_id = None

    # ------------------------------------------------------------------
    # Event hook
    # ------------------------------------------------------------------

    def _on_provider_event(self, provider_id: int, event: dict) -> None:
        """Registry calls this for every worker event.

        We only care about terminal session events on the active provider —
        they free the slot so the next tick can pick another worker.
        """
        if self._active_provider_id is None or provider_id != self._active_provider_id:
            return
        if not isinstance(event, dict):
            return
        event_name = str(event.get("event", "")).strip()
        if event_name not in _TERMINAL_SESSION_EVENTS:
            return
        provider_name = self._facade.get_provider_name(provider_id) or str(provider_id)
        logger.info(
            "CalibrationOrchestrator: provider=%s emitted %s — slot freed",
            provider_name,
            event_name,
        )
        # The worker walks its full model list every session. Whatever it
        # didn't calibrate this round (failures, unsupported, skipped) won't
        # succeed on a retry in this window. Mark done so we move on.
        self._completed_this_window.add(provider_id)
        self._active_provider_id = None
