"""Server-orchestrated nightly VRAM calibration.

The CalibrationOrchestrator runs a background asyncio loop that, once per
minute during a configurable time window (default 02:00–05:00 Europe/Berlin),
picks one uncalibrated model on one idle worker node and drives it through the
calibration cycle via the existing bridge RPC commands:

  start_calibration  →  { ok, model_name, sleep_level, started_at }
  get_calibration_status  →  { active, model_name, started_at }
  stop_calibration  →  { ok, was_active, model_name? }

Design invariants:
- Only one worker calibrates at a time (sequential, not concurrent).
- A worker is considered idle if it has no active requests AND its
  calibration-status reports active=False.
- A model "needs calibration" if its ModelProfile.base_residency_mb is None
  on a worker that lists it as a capability.
- Outside the time window the orchestrator sends stop_calibration to any worker
  that may be running one (best-effort) and idles until the next window opens.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import time
from typing import TYPE_CHECKING, Any

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

    LOGOS_CALIB_WINDOW_START  e.g. "02:00" (HH:MM, default 02:00)
    LOGOS_CALIB_WINDOW_END    e.g. "05:00" (HH:MM, default 05:00)
    LOGOS_CALIB_TIMEZONE      e.g. "Europe/Berlin" (default Europe/Berlin)
    LOGOS_CALIB_ENABLED       "true" / "false" (default true)
    LOGOS_CALIB_SLEEP_LEVEL   "1" or "2" (default 1)
    LOGOS_CALIB_TICK_SECONDS  poll interval in seconds (default 60)
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
            window_start=_parse_time(os.getenv("LOGOS_CALIB_WINDOW_START", ""), time(2, 0)),
            window_end=_parse_time(os.getenv("LOGOS_CALIB_WINDOW_END", ""), time(5, 0)),
            timezone=os.getenv("LOGOS_CALIB_TIMEZONE", "Europe/Berlin").strip() or "Europe/Berlin",
            enabled=_parse_bool(os.getenv("LOGOS_CALIB_ENABLED", ""), True),
            sleep_level=_parse_int(os.getenv("LOGOS_CALIB_SLEEP_LEVEL", ""), 1),
            tick_seconds=_parse_float(os.getenv("LOGOS_CALIB_TICK_SECONDS", ""), 60.0),
        )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class CalibrationOrchestrator:
    """Drives server-orchestrated nightly VRAM calibration."""

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

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if not self._config.enabled:
            logger.info("CalibrationOrchestrator: disabled via config — not starting")
            return
        if self._task is not None and not self._task.done():
            return
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
        if not self._is_in_window():
            # Outside window: cancel any running calibration (best-effort).
            await self._cancel_all_running()
            return

        # Inside window: pick one idle worker with an uncalibrated model.
        target = self._pick_calibration_target()
        if target is None:
            logger.debug("CalibrationOrchestrator: all models calibrated or no idle worker available")
            return

        provider_id, model_name = target
        provider_name = self._facade.get_provider_name(provider_id) or str(provider_id)

        # Check if that worker is already calibrating (maybe we triggered it
        # last tick and the thread started but didn't finish yet).
        status = await self._get_status(provider_id)
        if status is not None and status.get("active"):
            logger.debug(
                "CalibrationOrchestrator: worker=%s already calibrating model=%s — waiting",
                provider_name,
                status.get("model_name"),
            )
            return

        logger.info(
            "CalibrationOrchestrator: starting calibration provider=%s model=%s sleep_level=%d",
            provider_name,
            model_name,
            self._config.sleep_level,
        )
        await self._send_start_calibration(provider_id, model_name)

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
    # Target selection
    # ------------------------------------------------------------------

    def _pick_calibration_target(self) -> tuple[int, str] | None:
        """Return (provider_id, model_name) for the first model that needs
        calibration on an idle, connected worker — or None if none found."""
        for provider_id in self._facade.provider_ids():
            # Skip providers that haven't sent their first status yet.
            if not self._registry.has_received_first_status(provider_id):
                continue

            # Skip providers with active inference requests.
            if self._provider_has_active_requests(provider_id):
                continue

            # Find a model on this provider that lacks a full calibration.
            model_name = self._find_uncalibrated_model(provider_id)
            if model_name is not None:
                return provider_id, model_name

        return None

    def _provider_has_active_requests(self, provider_id: int) -> bool:
        """Return True if the provider has any active inference requests.

        `OllamaCapacity` (the only `get_capacity_info` return type) has no
        `active_requests` field — that data only exists per-lane in the
        scheduler signals. Sum across all lanes on the provider; treat any
        non-zero `active_requests` (currently-running) or `queue_waiting`
        (admitted but pending) as "busy".
        """
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

    def _find_uncalibrated_model(self, provider_id: int) -> str | None:
        """Return the first model on this provider that needs calibration.

        A model needs calibration when ANY of:
          - the profile is missing entirely,
          - core VRAM fields (``base_residency_mb`` / ``sleeping_residual_mb``)
            are missing,
          - ``sleep_l1_transient_host_ram_mb`` is missing — this is the field
            the planner's host-RAM sleep gate relies on. Production runs
            sleep_l1 on every idle lane after ~2 min, so a missing value
            forces the planner onto its flat-threshold fallback every time.
            We only measure level 1 here; level 2 (``sleep_l2_transient_…``)
            stays unmeasured because production effectively never fires
            sleep_l2 (``IDLE_SLEEP_L2 = 24h``). The planner gracefully falls
            back to a disk-size heuristic for sleep_l2 on demand.
        """
        capabilities = self._facade.get_worker_capabilities(provider_id)
        try:
            profiles = self._facade.get_model_profiles(provider_id)
        except Exception:
            profiles = {}

        for model_name in capabilities:
            profile = profiles.get(model_name)
            needs_calib = (
                profile is None
                or profile.base_residency_mb is None
                or profile.sleeping_residual_mb is None
                or profile.sleep_l1_transient_host_ram_mb is None
            )
            if needs_calib:
                return model_name

        return None

    # ------------------------------------------------------------------
    # RPC helpers
    # ------------------------------------------------------------------

    async def _send_start_calibration(self, provider_id: int, model_name: str) -> None:
        from logos.logosnode_registry import LogosNodeCommandError, LogosNodeOfflineError

        try:
            await self._registry.send_command(
                provider_id,
                "start_calibration",
                params={"model_name": model_name, "sleep_level": self._config.sleep_level},
                timeout_seconds=30,
            )
        except LogosNodeOfflineError:
            logger.warning(
                "CalibrationOrchestrator: provider=%s offline — cannot start calibration for %s",
                provider_id,
                model_name,
            )
        except LogosNodeCommandError as exc:
            logger.warning(
                "CalibrationOrchestrator: start_calibration failed for provider=%s model=%s: %s",
                provider_id,
                model_name,
                exc,
            )
        except Exception:
            logger.exception(
                "CalibrationOrchestrator: unexpected error starting calibration " "provider=%s model=%s",
                provider_id,
                model_name,
            )

    async def _get_status(self, provider_id: int) -> dict[str, Any] | None:
        from logos.logosnode_registry import LogosNodeCommandError, LogosNodeOfflineError

        try:
            return await self._registry.send_command(
                provider_id,
                "get_calibration_status",
                timeout_seconds=10,
            )
        except (LogosNodeOfflineError, LogosNodeCommandError, Exception):
            return None

    async def _cancel_all_running(self) -> None:
        """Outside the maintenance window: stop any in-progress calibrations."""
        from logos.logosnode_registry import LogosNodeCommandError, LogosNodeOfflineError

        for provider_id in self._facade.provider_ids():
            status = await self._get_status(provider_id)
            if status is None or not status.get("active"):
                continue
            provider_name = self._facade.get_provider_name(provider_id) or str(provider_id)
            logger.info(
                "CalibrationOrchestrator: outside window — stopping calibration on provider=%s",
                provider_name,
            )
            try:
                await self._registry.send_command(
                    provider_id,
                    "stop_calibration",
                    timeout_seconds=15,
                )
            except (LogosNodeOfflineError, LogosNodeCommandError, Exception):
                logger.debug(
                    "CalibrationOrchestrator: failed to stop calibration on provider=%s (ignored)",
                    provider_name,
                )
