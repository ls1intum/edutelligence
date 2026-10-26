"""Server-side trigger for worker-driven VRAM calibration.

The CalibrationOrchestrator is now a thin gatekeeper. The worker owns the
calibration loop: it picks which uncalibrated model runs next, walks its own
model list, and emits ``calibration_*`` events back to the server when each
model completes. The orchestrator only:

  * Watches the maintenance window (default 05:00–08:00 Europe/Berlin).
  * When inside the window and no other worker has a session in progress,
    picks one idle, healthy worker that still has uncalibrated models and
    lists the calibration commands in its hello, and sends
    ``start_calibration_session``.
  * When outside the window, sends ``stop_calibration_session`` to the
    provider that holds the active session — the worker tears the in-flight
    vLLM probe down inside ~2s.
  * Reacts to ``calibration_session_finished`` / ``_cancelled`` events to
    free the active-provider slot so the next tick can pick someone else.

Design invariants (unchanged from the previous design):
- LOGOS_MAINTENANCE_MAX_NODES limits simultaneous calibration workers.
- A worker is considered idle if it has no active inference requests AND is
  not already running a calibration session.
- The maintenance coordinator confirms worker completion before releasing the cluster slot.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import TYPE_CHECKING, Callable
from zoneinfo import ZoneInfo

# Terminal session events that free the active-provider slot. Shared with the
# registry, which uses the same names to track ProviderSession.calibrating —
# one definition keeps the two from drifting apart.
from logos.logosnode_registry import TERMINAL_CALIBRATION_SESSION_EVENTS as _TERMINAL_SESSION_EVENTS
from logos.maintenance_window import MaintenanceWindow, maintenance_node_limit

# Commands a worker must list in its hello before it is calibrated automatically.
_CALIBRATION_ACTIONS = ("start_calibration_session", "stop_calibration_session", "get_calibration_status")

logger = logging.getLogger("logos.capacity.calibration_orchestrator")

if TYPE_CHECKING:
    from logos.logosnode_registry import LogosNodeRuntimeRegistry
    from logos.sdi.logosnode_facade import LogosNodeSchedulingDataFacade


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class CalibrationConfig:
    """Nightly calibration window and behaviour knobs.

    All values can be overridden via environment variables so that
    operators can tune them without touching YAML.

    LOGOS_MAINTENANCE_WINDOW_START  HH:MM, default 05:00
    LOGOS_MAINTENANCE_WINDOW_END    HH:MM, default 08:00
    LOGOS_MAINTENANCE_TIMEZONE      default Europe/Berlin
    LOGOS_CALIB_ENABLED       "true" / "false" (default true)
    LOGOS_CALIB_SLEEP_LEVEL   "1" or "2" (default 1)
    LOGOS_CALIB_TICK_SECONDS  standalone trigger-loop interval (default 60);
                             the application uses the shared 15-second loop
    """

    window_start: time = field(default_factory=lambda: MaintenanceWindow().start)
    window_end: time = field(default_factory=lambda: MaintenanceWindow().end)
    timezone: str = MaintenanceWindow().timezone
    enabled: bool = True
    sleep_level: int = 1
    tick_seconds: float = 60.0

    @classmethod
    def from_env(cls) -> "CalibrationConfig":
        """Build a CalibrationConfig from environment variables (with defaults)."""

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

        defaults = cls()
        window = MaintenanceWindow.from_env()
        return cls(
            window_start=window.start,
            window_end=window.end,
            timezone=window.timezone,
            enabled=_parse_bool(os.getenv("LOGOS_CALIB_ENABLED", ""), defaults.enabled),
            sleep_level=_parse_int(os.getenv("LOGOS_CALIB_SLEEP_LEVEL", ""), defaults.sleep_level),
            tick_seconds=_parse_float(os.getenv("LOGOS_CALIB_TICK_SECONDS", ""), defaults.tick_seconds),
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
        worker_locked: Callable[[int], bool] | None = None,
    ) -> None:
        self._registry = registry
        self._facade = facade
        self._config = config or CalibrationConfig.from_env()
        # Whether an operator locked a worker; automatic calibration skips it.
        self._worker_locked: Callable[[int], bool] = worker_locked or (lambda _provider_id: False)
        self._task: asyncio.Task[None] | None = None
        self._active_provider_ids: set[int] = set()
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
        unsubscribe = getattr(self._registry, "unsubscribe_from_events", None)
        if callable(unsubscribe):
            unsubscribe(self._on_provider_event)
        if self._task is None or self._task.done():
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
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
        if not self._config.enabled:
            return
        in_window = self._is_in_window()
        if in_window != self._was_in_window:
            # Window edge: reset per-window bookkeeping so the next window
            # gets a clean slate.
            self._completed_this_window.clear()
            self._was_in_window = in_window

        if not in_window:
            await self._stop_active_session_if_any("outside-window")
            return

        attempted = set()
        while len(self._active_provider_ids) < maintenance_node_limit():
            target_provider_id = self._pick_next_provider(excluding=attempted)
            if target_provider_id is None:
                return
            attempted.add(target_provider_id)
            await self._start_session_on(target_provider_id)

    # ------------------------------------------------------------------
    # Window check
    # ------------------------------------------------------------------

    def benchmarks_must_wait(self) -> bool:
        """Eligible calibration work takes priority, even while its lanes drain."""
        if not self._config.enabled or not self._is_in_window():
            return False
        if not self._was_in_window:
            self._completed_this_window.clear()
        if self._active_provider_ids:
            return True
        return any(
            pid not in self._completed_this_window
            and self._registry.has_received_first_status(pid)
            and not self._provider_is_unhealthy(pid)
            # A locked worker's calibration cannot start, so it holds up nothing.
            and not self._worker_locked(pid)
            and self._supports_calibration(pid)
            and self._provider_has_uncalibrated_models(pid)
            for pid in self._facade.provider_ids()
        )

    def _is_in_window(self) -> bool:
        window = MaintenanceWindow(self._config.window_start, self._config.window_end, self._config.timezone)
        return window.contains(datetime.now(ZoneInfo(window.timezone)))

    # ------------------------------------------------------------------
    # Provider selection
    # ------------------------------------------------------------------

    def _pick_next_provider(self, excluding: set[int] | None = None) -> int | None:
        """Return the first eligible provider that still has uncalibrated models."""
        for provider_id in self._facade.provider_ids():
            if provider_id in self._active_provider_ids or provider_id in (excluding or set()):
                continue
            if provider_id in self._completed_this_window:
                continue
            if not self._registry.has_received_first_status(provider_id):
                continue
            if self._registry.is_cordoned(provider_id):
                # Its container is about to be replaced; a calibration session would end with it.
                continue
            if self._provider_is_unhealthy(provider_id):
                continue
            if self._worker_locked(provider_id):
                # Calibration stops every lane; on a locked worker only an
                # operator may start it.
                continue
            if not self._supports_calibration(provider_id):
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

    def _supports_calibration(self, provider_id: int) -> bool:
        """Whether the worker's build lists every command a coordinated session needs.

        Without the status command the coordinator cannot confirm that a
        session ended, so an automatic start would hold the maintenance slot
        on that worker's word alone.
        """
        return all(bool(self._registry.supports_action(provider_id, action)) for action in _CALIBRATION_ACTIONS)

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

    def _calibration_gpu_subset(self, provider_id: int) -> frozenset[int]:
        """GPUs the calibration holds on *provider_id*.

        Derived from the worker's nvidia GPU count as the largest power-of-two
        slice — the same slice the worker's lane manager holds and the probe is
        pinned to (see ``calibration_gpu_slice`` in the worker). Returns an
        empty set when the count cannot be determined, in which case the caller
        treats the whole node as busy (conservative, the old behaviour).
        """
        try:
            snap = self._registry.peek_runtime_snapshot(provider_id)
        except Exception:
            snap = None
        if not isinstance(snap, dict):
            return frozenset()
        device_list = ((snap.get("runtime") or {}).get("devices") or {}).get("devices") or []
        n_gpus = 0
        for dev in device_list:
            if not isinstance(dev, dict):
                continue
            if dev.get("kind") not in (None, "nvidia"):
                continue
            try:
                index = int((dev.get("extra") or {}).get("index"))
            except (TypeError, ValueError):
                continue
            if index >= 0:
                n_gpus += 1
        if n_gpus < 1:
            return frozenset()
        slice_size = 1 << (n_gpus.bit_length() - 1)
        return frozenset(range(slice_size))

    @staticmethod
    def _lane_touches_subset(gpu_devices: str, subset: frozenset[int]) -> bool:
        """True when a lane's GPU set intersects the calibration *subset*.

        Mirrors the worker's lane-manager guard: a blank/"all" selector spans
        every GPU (so it intersects), "none" spans none, and an explicit list
        is tested by intersection.
        """
        raw = (gpu_devices or "").strip().replace(" ", "")
        lowered = raw.lower()
        if lowered in {"", "all"}:
            return True
        if lowered == "none":
            return False
        indices = {int(part) for part in raw.split(",") if part.isdigit()}
        return bool(indices & subset)

    def _provider_has_active_requests(self, provider_id: int) -> bool:
        """Return True if the provider has active requests on the calibration slice.

        A lane busy only on the leftover GPUs (outside the calibration's
        power-of-two slice) no longer blocks scheduling a calibration — the probe
        only uses the slice, so a busy leftover GPU is
        irrelevant. When the slice cannot be determined, any busy lane blocks
        (the previous, conservative behaviour).
        """
        try:
            signals = self._facade.get_all_provider_lane_signals(provider_id)
        except Exception:
            # Telemetry unavailable — assume busy to avoid interrupting work.
            return True
        subset = self._calibration_gpu_subset(provider_id)
        for sig in signals:
            busy = (
                int(getattr(sig, "active_requests", 0) or 0) > 0
                or float(getattr(sig, "queue_waiting", 0.0) or 0.0) > 0.0
            )
            if not busy:
                continue
            if subset and not self._lane_touches_subset(str(getattr(sig, "gpu_devices", "") or ""), subset):
                # Busy only on a leftover GPU the probe does not touch.
                continue
            return True
        return False

    def _capacity_skip_models(self, provider_id: int) -> frozenset[str]:
        """Models known, from any node's calibration history, to need more
        capacity than *provider_id* has (Metal-only; always empty for CUDA).
        Per model: max ``metal_capacity_floor_mb`` across every provider,
        compared against this provider's own ``devices.total_memory_mb``.
        """
        try:
            snap = self._registry.peek_runtime_snapshot(provider_id)
        except Exception:
            return frozenset()
        if not isinstance(snap, dict):
            return frozenset()
        devices = (snap.get("runtime") or {}).get("devices") or {}
        # A Metal working-set floor says nothing about CUDA VRAM headroom
        # — only ever apply it to another Metal provider, never compare
        # it against a CUDA node's own total_memory_mb.
        if devices.get("mode") != "metal":
            return frozenset()
        provider_capacity_mb = float(devices.get("total_memory_mb") or 0.0)
        if provider_capacity_mb <= 0:
            return frozenset()

        floors: dict[str, float] = {}
        for pid in self._facade.provider_ids():
            try:
                profiles = self._facade.get_model_profiles(pid)
            except Exception:
                continue
            for model_name, profile in profiles.items():
                floor = profile.metal_capacity_floor_mb
                if floor is None:
                    continue
                if floor > floors.get(model_name, 0.0):
                    floors[model_name] = floor

        return frozenset(name for name, floor in floors.items() if provider_capacity_mb <= floor)

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
        capacity_skip = self._capacity_skip_models(provider_id)

        for model_name in candidates:
            if model_name in capacity_skip:
                continue
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
                or (
                    profile is not None
                    and profile.residency_source == "calibrated"
                    and not profile.kv_cache_to_max_model_len_pairs
                )
                or collapsed_envelope
                or bool(profile is not None and profile.calibration_stale)
            )
            if needs_calib:
                return True
        return False

    # ------------------------------------------------------------------
    # RPC drivers
    # ------------------------------------------------------------------

    async def _start_session_on(self, provider_id: int) -> None:
        from logos.logosnode_registry import LogosNodeCommandError, LogosNodeOfflineError, MaintenanceBusyError

        provider_name = self._facade.get_provider_name(provider_id) or str(provider_id)
        # Mark active before sending so a concurrent terminal-event handler
        # (e.g. from a duplicate connect) can clear it cleanly without us
        # also firing the same start a second time on the next tick.
        self._active_provider_ids.add(provider_id)
        skip_models = sorted(self._capacity_skip_models(provider_id))
        try:
            await self._registry.send_command(
                provider_id,
                "start_calibration_session",
                params={"sleep_level": self._config.sleep_level, "skip_models": skip_models},
                timeout_seconds=30,
            )
            logger.info(
                "CalibrationOrchestrator: session started on provider=%s sleep_level=%d",
                provider_name,
                self._config.sleep_level,
            )
        except MaintenanceBusyError:
            self._active_provider_ids.discard(provider_id)
        except LogosNodeOfflineError:
            logger.warning(
                "CalibrationOrchestrator: provider=%s offline — could not start session",
                provider_name,
            )
            self._active_provider_ids.discard(provider_id)
        except LogosNodeCommandError as exc:
            logger.warning(
                "CalibrationOrchestrator: start_calibration_session failed on provider=%s: %s",
                provider_name,
                exc,
            )
            self._active_provider_ids.discard(provider_id)
            # Don't retry this provider in this window — whatever made the
            # worker refuse (e.g. node unhealthy at the last second) will
            # likely repeat next tick.
            self._completed_this_window.add(provider_id)
        except Exception:
            logger.exception(
                "CalibrationOrchestrator: unexpected error starting session on provider=%s",
                provider_name,
            )
            self._active_provider_ids.discard(provider_id)

    async def _stop_active_session_if_any(self, reason: str) -> None:
        """Stop all automatic sessions; uncertain stops retain their durable claims."""
        for provider_id in tuple(self._active_provider_ids):
            await self._stop_session_on(provider_id, reason)

    async def _stop_session_on(self, provider_id: int, reason: str) -> None:
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
            # The coordinator retains the durable claim on an uncertain stop.
            # The shared loop reattaches it before the next stop attempt.
            self._active_provider_ids.discard(provider_id)

    # ------------------------------------------------------------------
    # Event hook
    # ------------------------------------------------------------------

    def _on_provider_event(self, provider_id: int, event: dict) -> None:
        """Registry calls this for every worker event.

        We only care about terminal session events on the active provider —
        they free the slot so the next tick can pick another worker.
        """
        if provider_id not in self._active_provider_ids:
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
        self._active_provider_ids.discard(provider_id)
