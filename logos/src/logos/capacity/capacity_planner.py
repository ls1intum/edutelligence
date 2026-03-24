# src/logos/capacity/capacity_planner.py
"""
Background capacity planner that monitors demand patterns
and proactively manages worker node lane configurations.

Runs on a configurable cycle (default 30s). Independently ablatable
via LOGOS_CAPACITY_PLANNER_ENABLED=false.
"""

import asyncio
import copy
from datetime import datetime, timezone
import logging
import time
from typing import Any, Dict, List, Optional

from logos.logosnode_registry import LogosNodeRuntimeRegistry
from logos.sdi.logosnode_facade import LogosNodeSchedulingDataFacade
from logos.sdi.models import CapacityPlanAction, LaneSchedulerSignals, ModelProfile
from logos.terminal_logging import (
    BOLD,
    CYAN,
    DIM,
    GREEN,
    RED,
    YELLOW,
    format_state,
    lane_metric_float,
    lane_ttft_p95_seconds,
    paint,
    render_section,
    wrap_plain,
)

from .demand_tracker import DemandTracker
from logos.monitoring import prometheus_metrics as prom

logger = logging.getLogger(__name__)


class CapacityPlanner:
    """
    Background planner running every cycle_seconds.

    Per-cycle decision pipeline:
    1. Decay demand scores
    2. Read current lane states from all connected providers
    3. Track idle durations per lane
    4. Compute idle tier actions (sleep/stop)
    5. Compute demand-based actions (wake/load)
    6. Compute GPU utilization tuning actions (for vLLM lanes)
    7. Validate VRAM budget for all actions
    8. Execute validated actions with confirmation
    """

    # Idle tier thresholds (seconds of no activity)
    IDLE_SLEEP_L1 = 300      # vLLM lane idle 5min → sleep level 1
    IDLE_SLEEP_L2 = 600      # vLLM lane sleeping L1 for 10min → sleep level 2
    IDLE_STOP = 900          # any lane idle 15min → stop/remove

    # Demand thresholds
    DEMAND_WAKE_THRESHOLD = 1.0
    DEMAND_LOAD_THRESHOLD = 2.0

    # GPU utilization tuning
    GPU_UTIL_MIN = 0.50
    GPU_UTIL_MAX = 0.95
    GPU_CACHE_HIGH = 85.0
    GPU_CACHE_LOW = 40.0

    # VRAM safety margin
    VRAM_SAFETY_MARGIN = 1.1  # 10% margin

    # Preemptive load-then-sleep
    PREEMPTIVE_SLEEP_MIN_FREE_VRAM_RATIO = 0.20
    PREEMPTIVE_SLEEP_MAX_MODELS = 3

    # Slow-path request preparation
    REQUEST_WAKE_TIMEOUT_SECONDS = 120.0

    def __init__(
        self,
        logosnode_facade: LogosNodeSchedulingDataFacade,
        logosnode_registry: LogosNodeRuntimeRegistry,
        demand_tracker: DemandTracker,
        cycle_seconds: float = 30.0,
        enabled: bool = True,
    ) -> None:
        self._facade = logosnode_facade
        self._registry = logosnode_registry
        self._demand = demand_tracker
        self._cycle_seconds = cycle_seconds
        self._enabled = enabled
        self._lane_idle_since: dict[tuple[int, str], float] = {}
        self._lane_sleep_since: dict[tuple[int, str], float] = {}
        self._lane_sleep_level: dict[tuple[int, str], int] = {}
        self._task: Optional[asyncio.Task] = None
        self._cycle_count = 0

    async def start(self) -> None:
        """Start the planner background loop."""
        if self._enabled:
            self._task = asyncio.create_task(self._run_loop(), name="capacity-planner")
            logger.info("Capacity planner started (cycle=%ss)", self._cycle_seconds)

    async def stop(self) -> None:
        """Stop the planner."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            logger.info("Capacity planner stopped")

    async def _run_loop(self) -> None:
        await asyncio.sleep(self._cycle_seconds)  # Initial delay to let system settle
        while True:
            try:
                await self._run_cycle()
                self._cycle_count += 1
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Capacity planner cycle failed")
            await asyncio.sleep(self._cycle_seconds)

    async def _run_cycle(self) -> None:
        """Execute one planner cycle."""
        cycle_start = time.time()
        self._demand.decay_all()

        # Update demand gauges
        for model_name, score in self._demand.get_ranked_models():
            prom.DEMAND_SCORE.labels(model=model_name).set(score)
            prom.DEMAND_RAW_COUNT.labels(model=model_name).set(
                self._demand.get_raw_count(model_name)
            )

        all_actions: List[CapacityPlanAction] = []

        provider_ids = self._facade.provider_ids()
        self._log_cluster_summary(provider_ids)

        for provider_id in provider_ids:
            # Skip providers that haven't sent their first status yet —
            # we don't know what lanes are already loaded and acting on
            # stale/empty state can destroy existing lanes.
            if self._registry and not self._registry.has_received_first_status(provider_id):
                logger.debug(
                    "Skipping provider %s: waiting for first status report after connect",
                    provider_id,
                )
                continue

            try:
                lanes = self._facade.get_all_provider_lane_signals(provider_id)
            except Exception:
                continue

            self._update_idle_tracking(provider_id, lanes)
            all_actions.extend(self._compute_idle_actions(provider_id, lanes))
            all_actions.extend(self._compute_demand_actions(provider_id, lanes))
            all_actions.extend(self._compute_kv_cache_tuning_actions(provider_id, lanes))
            all_actions.extend(self._compute_preemptive_sleep_actions(provider_id, lanes))

        if all_actions:
            self._log_action_plan(all_actions)

        validated = self._validate_vram_budget(all_actions)

        for action in validated:
            try:
                await self._execute_action_with_confirmation(action)
                prom.CAPACITY_PLANNER_ACTIONS_TOTAL.labels(action=action.action).inc()
            except Exception:
                logger.exception(
                    "Failed to execute capacity action: %s on lane %s",
                    action.action, action.lane_id,
                )

        prom.CAPACITY_PLANNER_CYCLE_DURATION_SECONDS.observe(time.time() - cycle_start)

    def _log_cluster_summary(self, provider_ids: List[int]) -> None:
        """Print a colored cluster overview for the current planner cycle."""
        lines: list[str] = []
        connected = 0
        total_used_vram = 0.0
        total_free_vram = 0.0
        state_counts: dict[str, int] = {}
        for pid in provider_ids:
            snap = self._registry.peek_runtime_snapshot(pid) if self._registry else None
            if snap is None:
                lines.append(f"{paint('⊘', RED)} provider={pid} {paint('offline', DIM)}")
                continue

            connected += 1
            rt = snap.get("runtime") or {}
            worker_id = snap.get("worker_id", "?")
            caps = sorted(snap.get("capabilities_models") or [])
            cap = rt.get("capacity") or {}
            lanes_list = rt.get("lanes") or []
            total_vram = (rt.get("devices") or {}).get("total_memory_mb", 0)
            free_vram = cap.get("free_memory_mb", 0)
            total_used_vram += total_vram - free_vram
            total_free_vram += free_vram
            for lane in (lanes_list if isinstance(lanes_list, list) else []):
                if isinstance(lane, dict):
                    rs = str(lane.get("runtime_state") or "unknown")
                    state_counts[rs] = state_counts.get(rs, 0) + 1
            used_pct = ((total_vram - free_vram) / total_vram * 100) if total_vram > 0 else 0
            heartbeat_age_s = self._heartbeat_age_seconds(snap.get("last_heartbeat"))
            worker_color = GREEN if heartbeat_age_s <= 15 else YELLOW if heartbeat_age_s <= 30 else RED

            lines.append(
                f"{paint('●', worker_color)} provider={pid} worker={paint(str(worker_id), BOLD)} "
                f"status={paint('active', worker_color)} hb={heartbeat_age_s:.0f}s "
                f"vram={paint(f'{total_vram - free_vram:.0f}/{total_vram:.0f}MB', BOLD)} ({used_pct:.0f}%)"
            )
            capabilities_text = ", ".join(caps) if caps else "none"
            lines.extend(wrap_plain(f"capabilities: {capabilities_text}", indent="    "))

            lane_count = int(cap.get("lane_count", len(lanes_list)) or len(lanes_list))
            loaded_count = int(cap.get("loaded_lane_count", 0) or 0)
            sleeping_count = int(cap.get("sleeping_lane_count", 0) or 0)
            active_requests = int(cap.get("active_requests", 0) or 0)
            lines.append(
                f"    lanes={lane_count} loaded={loaded_count} sleeping={sleeping_count} active_requests={active_requests}"
            )

            if not isinstance(lanes_list, list) or not lanes_list:
                lines.append(f"    {paint('no lanes reported', DIM)}")
                continue

            for lane in sorted(lanes_list, key=self._lane_log_sort_key):
                if not isinstance(lane, dict):
                    continue
                lines.extend(self._format_runtime_lane_lines(lane, indent="    "))

        # Demand scores
        demand_stats = self._demand.get_stats()
        active_demand = {k: v for k, v in demand_stats.get("scores", {}).items() if v > 0.1}
        if active_demand:
            lines.append(paint("Demand", YELLOW, BOLD) + ": " + ", ".join(
                f"{m}={s:.2f}" for m, s in sorted(active_demand.items(), key=lambda x: -x[1])
            ))

        lines.append(
            paint(f"Workers connected: {connected}/{len(provider_ids)}", DIM)
        )
        logger.info(
            render_section(
                f"Planner Cycle {self._cycle_count}",
                lines,
                accent=CYAN,
            )
        )

        # Update Prometheus gauges
        prom.WORKER_NODES_CONNECTED.set(connected)
        prom.WORKER_VRAM_USED_MB.set(total_used_vram)
        prom.WORKER_VRAM_FREE_MB.set(total_free_vram)
        for state in ("cold", "starting", "loaded", "running", "sleeping", "stopped", "error"):
            prom.WORKER_LANES_BY_STATE.labels(state=state).set(state_counts.get(state, 0))

    @staticmethod
    def _heartbeat_age_seconds(last_heartbeat: Any) -> float:
        """Return heartbeat age in seconds from an ISO timestamp."""
        if not isinstance(last_heartbeat, str) or not last_heartbeat.strip():
            return 0.0
        try:
            parsed = datetime.fromisoformat(last_heartbeat.replace("Z", "+00:00"))
        except ValueError:
            return 0.0
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0.0, time.time() - parsed.timestamp())

    @staticmethod
    def _lane_log_sort_key(lane: dict[str, Any]) -> tuple[int, str]:
        """Prefer warmer lanes first in cycle summaries."""
        runtime_state = str(lane.get("runtime_state") or "")
        order = {
            "running": 0,
            "loaded": 1,
            "sleeping": 2,
            "starting": 3,
            "cold": 4,
            "stopped": 5,
            "error": 6,
        }
        return (order.get(runtime_state, 99), str(lane.get("lane_id") or ""))

    def _format_runtime_lane_lines(self, lane: dict[str, Any], *, indent: str) -> list[str]:
        """Render a single runtime lane into concise, wrapped log lines."""
        lane_id = str(lane.get("lane_id") or "?")
        model = str(lane.get("model") or "?")
        runtime_state = str(lane.get("runtime_state") or "?")
        sleep_state = str(lane.get("sleep_state") or "?")
        active_requests = int(lane.get("active_requests", 0) or 0)
        effective_vram_mb = float(lane.get("effective_vram_mb", 0.0) or 0.0)
        backend_metrics = lane.get("backend_metrics") if isinstance(lane.get("backend_metrics"), dict) else {}
        lane_config = lane.get("lane_config") if isinstance(lane.get("lane_config"), dict) else {}

        queue_waiting = lane_metric_float(backend_metrics.get("queue_waiting"))
        requests_running = lane_metric_float(backend_metrics.get("requests_running"))
        if requests_running is None:
            requests_running = float(active_requests)
        cache_pressure = lane_metric_float(
            backend_metrics.get("gpu_cache_usage_percent", backend_metrics.get("gpu_cache_usage_perc"))
        )
        ttft_p95 = lane_ttft_p95_seconds(backend_metrics)
        prefix_hit = lane_metric_float(backend_metrics.get("prefix_cache_hit_rate"))
        gpu_devices = (
            lane_config.get("gpu_devices")
            or lane.get("gpu_devices")
            or lane.get("effective_gpu_devices")
            or "-"
        )

        queue_text = f"{queue_waiting:.1f}" if queue_waiting is not None else "--"
        running_text = f"{requests_running:.1f}" if requests_running is not None else "--"
        cache_text = f"{cache_pressure:.0f}%" if cache_pressure is not None else "--"
        ttft_text = f"{ttft_p95:.2f}s" if ttft_p95 is not None else "--"
        prefix_text = f"{prefix_hit:.0%}" if prefix_hit is not None else "--"

        lines = [f"{indent}{paint('▸', GREEN if runtime_state in {'loaded', 'running'} else YELLOW)} {lane_id}"]
        lines.extend(wrap_plain(f"model: {model}", indent=f"{indent}  "))
        lines.append(
            f"{indent}  state={format_state(runtime_state, sleep_state)} "
            f"mem={effective_vram_mb:.0f}MB gpus={gpu_devices}"
        )
        lines.append(
            f"{indent}  active={active_requests} run={running_text} "
            f"queue={queue_text} kv_cache={cache_text} ttft_p95={ttft_text} prefix_hit={prefix_text}"
        )
        return lines

    def _log_action_plan(self, actions: list[CapacityPlanAction]) -> None:
        """Render pending planner actions as a separate log section."""
        lines: list[str] = []
        action_colors = {
            "load": GREEN,
            "wake": GREEN,
            "sleep_l1": YELLOW,
            "sleep_l2": YELLOW,
            "stop": RED,
            "reconfigure_kv_cache": CYAN,
        }
        for action in actions:
            color = action_colors.get(action.action, CYAN)
            lines.append(
                f"{paint('→', color)} {paint(action.action, color, BOLD)} "
                f"provider={action.provider_id} lane={action.lane_id}"
            )
            lines.extend(wrap_plain(f"model: {action.model_name}", indent="    "))
            lines.extend(wrap_plain(f"reason: {action.reason}", indent="    "))
        logger.info(
            render_section(
                f"Planner Actions · cycle {self._cycle_count} · {len(actions)} change(s)",
                lines,
                accent=CYAN,
            )
        )

    async def prepare_lane_for_request(
        self,
        provider_id: int,
        model_name: str,
        timeout_seconds: float = 180.0,
    ) -> dict[str, Any] | None:
        """Prepare a lane for request-time execution.

        This path is synchronous to the request. It can:
        1. Wake a sleeping lane (reclaiming VRAM from idle competitors if needed)
        2. Cold-load a model that has no lane at all (with VRAM budget validation)
        """
        # Don't attempt lane preparation until the worker has reported its
        # current state — otherwise we may cold-load a model that is already
        # loaded, or issue a declarative apply_lanes that destroys existing lanes.
        if self._registry and not self._registry.has_received_first_status(provider_id):
            logger.info(
                "Deferring lane preparation for provider=%s model=%s: "
                "waiting for first status report after connect",
                provider_id, model_name,
            )
            return None

        target = self._pick_request_target_lane(provider_id, model_name)

        if target is not None:
            return await self._prepare_existing_lane(
                provider_id, model_name, target, timeout_seconds,
            )

        # No lane exists — attempt request-time cold load
        return await self._cold_load_for_request(
            provider_id, model_name, timeout_seconds,
        )

    async def _prepare_existing_lane(
        self,
        provider_id: int,
        model_name: str,
        target: LaneSchedulerSignals,
        timeout_seconds: float,
    ) -> dict[str, Any] | None:
        """Wake or prepare an existing lane for a request."""
        profile = self._safe_get_profiles(provider_id).get(model_name)
        if target.runtime_state in {"sleeping", "cold"}:
            ok = await self._ensure_request_capacity(
                provider_id=provider_id,
                target=target,
                profile=profile,
                timeout_seconds=timeout_seconds,
            )
            if not ok:
                return None

        if target.runtime_state == "sleeping":
            woke = await self._execute_action_with_confirmation(
                CapacityPlanAction(
                    action="wake",
                    provider_id=provider_id,
                    lane_id=target.lane_id,
                    model_name=model_name,
                    reason="Request-time wake for selected sleeping lane",
                ),
                timeout_seconds=max(timeout_seconds, self.REQUEST_WAKE_TIMEOUT_SECONDS),
            )
            if not woke:
                return None

        try:
            return await self._registry.select_lane_for_model(provider_id, model_name)
        except Exception:
            logger.debug(
                "Failed to re-select prepared lane for provider=%s model=%s",
                provider_id,
                model_name,
                exc_info=True,
            )
            return None

    async def _cold_load_for_request(
        self,
        provider_id: int,
        model_name: str,
        timeout_seconds: float,
    ) -> dict[str, Any] | None:
        """Load a model that has no lane at all (request-time cold load)."""
        profile = self._safe_get_profiles(provider_id).get(model_name)
        capacity = self._safe_get_capacity(provider_id)
        if capacity is None:
            logger.debug("No capacity info for provider %s, cannot cold-load %s", provider_id, model_name)
            return None

        if not self._passes_minimum_load_feasibility(model_name, profile, capacity):
            return None

        lane_id = self._planner_lane_id(model_name)
        load_action = CapacityPlanAction(
            action="load",
            provider_id=provider_id,
            lane_id=lane_id,
            model_name=model_name,
            params=self._build_load_params(model_name, lane_id, profile, capacity),
            reason="Request-time cold load",
        )

        estimated = self._estimate_action_vram(load_action, profile, capacity)
        available = float(capacity.available_vram_mb)

        logger.info(
            "Cold-load VRAM check for %s on provider %s: estimated=%.0fMB, available=%.0fMB, "
            "profile=%s, engine=%s, total_vram=%s, base_residency=%s, loaded_vram=%s",
            model_name, provider_id, estimated, available,
            profile is not None,
            getattr(profile, "engine", None),
            getattr(capacity, "total_vram_mb", None),
            getattr(profile, "base_residency_mb", None) if profile else None,
            getattr(profile, "loaded_vram_mb", None) if profile else None,
        )

        if available < estimated * self.VRAM_SAFETY_MARGIN:
            # Build a synthetic target signal for VRAM reclaim
            synthetic_target = LaneSchedulerSignals(
                lane_id=lane_id,
                model_name=model_name,
                runtime_state="cold",
                sleep_state="unsupported",
                is_vllm=profile.engine == "vllm" if profile else False,
                active_requests=0,
                queue_waiting=0.0,
                requests_running=0.0,
                gpu_cache_usage_percent=None,
                ttft_p95_seconds=0.0,
                effective_vram_mb=0.0,
                num_parallel=0,
            )
            ok = await self._ensure_request_capacity(
                provider_id=provider_id,
                target=synthetic_target,
                profile=profile,
                timeout_seconds=timeout_seconds,
            )
            if not ok:
                logger.info(
                    "Cannot reclaim enough VRAM for cold load of %s on provider %s",
                    model_name, provider_id,
                )
                return None

        logger.info("Cold-loading %s on provider %s (lane=%s)", model_name, provider_id, lane_id)
        loaded = await self._execute_action_with_confirmation(
            load_action, timeout_seconds=max(timeout_seconds, 180.0),
        )
        if not loaded:
            return None

        try:
            return await self._registry.select_lane_for_model(provider_id, model_name)
        except Exception:
            logger.debug(
                "Failed to select cold-loaded lane for provider=%s model=%s",
                provider_id, model_name, exc_info=True,
            )
            return None

    # ------------------------------------------------------------------
    # Idle tracking
    # ------------------------------------------------------------------

    @staticmethod
    def _lane_key(provider_id: int, lane_id: str) -> tuple[int, str]:
        return (provider_id, lane_id)

    def _clear_lane_tracking(self, key: tuple[int, str]) -> None:
        self._lane_idle_since.pop(key, None)
        self._lane_sleep_since.pop(key, None)
        self._lane_sleep_level.pop(key, None)

    def _record_confirmed_action_state(
        self, action: CapacityPlanAction, confirmed_at: float
    ) -> None:
        key = self._lane_key(action.provider_id, action.lane_id)

        if action.action == "sleep_l1":
            self._lane_sleep_since.setdefault(key, confirmed_at)
            self._lane_sleep_level[key] = 1
            self._lane_idle_since.setdefault(key, confirmed_at)
            return

        if action.action == "sleep_l2":
            self._lane_sleep_since.setdefault(key, confirmed_at)
            self._lane_sleep_level[key] = 2
            self._lane_idle_since.setdefault(key, confirmed_at)
            return

        if action.action in {"wake", "load"}:
            self._lane_sleep_since.pop(key, None)
            self._lane_sleep_level.pop(key, None)
            self._lane_idle_since[key] = confirmed_at
            return

        if action.action == "stop":
            self._clear_lane_tracking(key)

    def _update_idle_tracking(self, provider_id: int, lanes: List[LaneSchedulerSignals]) -> None:
        """Track idle durations per lane."""
        now = time.time()
        active_keys = set()
        for lane in lanes:
            key = self._lane_key(provider_id, lane.lane_id)
            active_keys.add(key)
            is_active = lane.active_requests > 0 or lane.queue_waiting > 0
            is_sleeping = lane.sleep_state == "sleeping"
            was_sleeping = key in self._lane_sleep_since or self._lane_sleep_level.get(key, 0) > 0

            if is_active:
                self._lane_idle_since[key] = now
            elif was_sleeping and not is_sleeping:
                self._lane_idle_since[key] = now
            elif key not in self._lane_idle_since:
                self._lane_idle_since[key] = now

            if is_sleeping:
                self._lane_sleep_since.setdefault(key, now)
                self._lane_sleep_level[key] = max(self._lane_sleep_level.get(key, 0), 1)
            else:
                self._lane_sleep_since.pop(key, None)
                self._lane_sleep_level.pop(key, None)

        # Clean up lanes that no longer exist
        tracked_keys = {
            key
            for key in (
                set(self._lane_idle_since)
                | set(self._lane_sleep_since)
                | set(self._lane_sleep_level)
            )
            if key[0] == provider_id
        }
        stale = [k for k in tracked_keys if k not in active_keys]
        for k in stale:
            self._clear_lane_tracking(k)

    def _compute_idle_actions(
        self, provider_id: int, lanes: List[LaneSchedulerSignals]
    ) -> List[CapacityPlanAction]:
        """Compute sleep/stop actions for idle lanes."""
        now = time.time()
        actions = []

        for lane in lanes:
            key = self._lane_key(provider_id, lane.lane_id)
            idle_start = self._lane_idle_since.get(key)
            sleep_start = self._lane_sleep_since.get(key)
            sleep_level = self._lane_sleep_level.get(key, 0)
            idle_seconds = (now - idle_start) if idle_start is not None else None
            sleep_seconds = (now - sleep_start) if sleep_start is not None else None

            # Skip lanes that are already stopped/error
            if lane.runtime_state in ("stopped", "error", "cold"):
                continue

            # Stop after 15 minutes idle — but ONLY if other models need the VRAM.
            # Keeping idle lanes sleeping is cheap and avoids costly cold starts.
            if (
                idle_seconds is not None
                and idle_seconds >= self.IDLE_STOP
                and lane.active_requests == 0
            ):
                if self._has_vram_pressure(provider_id, lane.model_name):
                    actions.append(CapacityPlanAction(
                        action="stop",
                        provider_id=provider_id,
                        lane_id=lane.lane_id,
                        model_name=lane.model_name,
                        reason=f"Idle for {idle_seconds:.0f}s with VRAM pressure from other models",
                    ))
                    continue

            # Only vLLM lanes support sleep
            if not lane.is_vllm:
                continue

            # Sleep L2 after 10 minutes of observed L1 sleep
            if (
                lane.sleep_state == "sleeping"
                and lane.active_requests == 0
                and sleep_level < 2
                and sleep_seconds is not None
                and sleep_seconds >= self.IDLE_SLEEP_L2
            ):
                actions.append(CapacityPlanAction(
                    action="sleep_l2",
                    provider_id=provider_id,
                    lane_id=lane.lane_id,
                    model_name=lane.model_name,
                    params={"level": 2},
                    reason=f"Sleeping L1 for {sleep_seconds:.0f}s, deepening to L2",
                ))
                continue

            # Sleep L1 after 5 minutes idle (awake or unknown state, no active requests)
            if (
                lane.sleep_state in ("awake", "unknown")
                and lane.runtime_state in ("loaded", "running")
                and lane.active_requests == 0
                and sleep_level < 1
                and idle_seconds is not None
                and idle_seconds >= self.IDLE_SLEEP_L1
            ):
                actions.append(CapacityPlanAction(
                    action="sleep_l1",
                    provider_id=provider_id,
                    lane_id=lane.lane_id,
                    model_name=lane.model_name,
                    params={"level": 1},
                    reason=f"Idle for {idle_seconds:.0f}s, sleeping L1",
                ))

        return actions

    def _has_vram_pressure(self, provider_id: int, exclude_model: str) -> bool:
        """Check if other models need VRAM on this provider.

        Returns True when:
        - Another model has demand but no lane (needs load), OR
        - Available VRAM is below 20% and there's any other model demand
        """
        ranked = self._demand.get_ranked_models()
        other_demand = [
            (name, score) for name, score in ranked
            if name != exclude_model and score > 0
        ]
        if not other_demand:
            return False

        # Check if any demanded model has no lane (would need a cold load)
        try:
            lanes = self._facade.get_all_provider_lane_signals(provider_id)
        except Exception:
            return False
        active_models = {lane.model_name for lane in lanes}
        for name, score in other_demand:
            if name not in active_models and score >= self.DEMAND_LOAD_THRESHOLD:
                return True

        # Check if VRAM is tight
        capacity = self._safe_get_capacity(provider_id)
        if capacity is not None:
            total = float(capacity.total_vram_mb)
            available = float(capacity.available_vram_mb)
            if total > 0 and available / total < self.PREEMPTIVE_SLEEP_MIN_FREE_VRAM_RATIO:
                return True

        return False

    # ------------------------------------------------------------------
    # Demand-based actions
    # ------------------------------------------------------------------

    def _compute_demand_actions(
        self, provider_id: int, lanes: List[LaneSchedulerSignals]
    ) -> List[CapacityPlanAction]:
        """Compute wake/load actions based on demand patterns."""
        if self._registry.peek_runtime_snapshot(provider_id) is None:
            logger.debug(
                "Skipping demand actions for provider=%s: no active logosnode runtime snapshot",
                provider_id,
            )
            return []

        actions = []
        ranked = self._demand.get_ranked_models()
        try:
            profiles = self._facade.get_model_profiles(provider_id)
        except Exception:
            profiles = {}
        try:
            capabilities = set(self._facade.get_worker_capabilities(provider_id))
        except Exception:
            capabilities = set()
        try:
            capacity = self._facade.get_capacity_info(provider_id)
        except Exception:
            capacity = None

        # Build index of current lanes by model
        lanes_by_model: dict[str, List[LaneSchedulerSignals]] = {}
        for lane in lanes:
            lanes_by_model.setdefault(lane.model_name, []).append(lane)

        planned_models: set[str] = set()

        for model_name, score in ranked:
            if capabilities and model_name not in capabilities:
                continue
            model_lanes = lanes_by_model.get(model_name, [])

            # Wake a sleeping lane if demand exceeds threshold
            if score >= self.DEMAND_WAKE_THRESHOLD:
                sleeping_lanes = [
                    l for l in model_lanes
                    if l.sleep_state == "sleeping"
                ]
                if sleeping_lanes:
                    target = sleeping_lanes[0]
                    actions.append(CapacityPlanAction(
                        action="wake",
                        provider_id=provider_id,
                        lane_id=target.lane_id,
                        model_name=model_name,
                        reason=f"Demand score={score:.2f} >= {self.DEMAND_WAKE_THRESHOLD}, waking sleeping lane",
                    ))
                    planned_models.add(model_name)
                    continue

            # Load a new lane if demand is high and no lane exists
            if score >= self.DEMAND_LOAD_THRESHOLD and not model_lanes:
                profile = profiles.get(model_name)
                if not self._passes_minimum_load_feasibility(model_name, profile, capacity):
                    continue
                lane_id = self._planner_lane_id(model_name)
                actions.append(CapacityPlanAction(
                    action="load",
                    provider_id=provider_id,
                    lane_id=lane_id,
                    model_name=model_name,
                    params=self._build_load_params(model_name, lane_id, profile, capacity),
                    reason=f"Demand score={score:.2f} >= {self.DEMAND_LOAD_THRESHOLD}, preemptive load",
                ))
                planned_models.add(model_name)

        # Capability seeding: if worker has zero lanes but declared capabilities,
        # seed load actions for in-demand models it can serve.
        if not lanes:
            for model_name in capabilities:
                if model_name in planned_models:
                    continue
                score = self._demand.get_score(model_name)
                if score <= 0:
                    continue
                profile = profiles.get(model_name)
                if not self._passes_minimum_load_feasibility(model_name, profile, capacity):
                    continue
                lane_id = self._planner_lane_id(model_name)
                actions.append(CapacityPlanAction(
                    action="load",
                    provider_id=provider_id,
                    lane_id=lane_id,
                    model_name=model_name,
                    params=self._build_load_params(model_name, lane_id, profile, capacity),
                    reason=f"Capability seeding: worker declares {model_name}, demand={score:.2f}",
                ))

        return actions

    def _compute_preemptive_sleep_actions(
        self, provider_id: int, lanes: List[LaneSchedulerSignals]
    ) -> List[CapacityPlanAction]:
        """Proactively load previously-served models into sleeping state.

        When a model was previously loaded and sleeping (sleeping_residual_mb known)
        but its lane was stopped, loading it back and immediately sleeping it keeps
        future requests at ~2s wake latency instead of ~45s cold start.

        Only acts when sufficient free VRAM exists (>20% of total after accounting
        for the sleeping residual cost).
        """
        profiles = self._safe_get_profiles(provider_id)
        capacity = self._safe_get_capacity(provider_id)
        if not profiles or capacity is None:
            return []

        total_vram = float(capacity.total_vram_mb)
        available_vram = float(capacity.available_vram_mb)
        if total_vram <= 0:
            return []

        # Only act if sufficient headroom exists
        if available_vram / total_vram < self.PREEMPTIVE_SLEEP_MIN_FREE_VRAM_RATIO:
            return []

        # Models that currently have a lane (any state)
        active_models = {lane.model_name for lane in lanes}

        # Find models with sleeping profiles but no lane
        candidates: list[tuple[float, str, ModelProfile]] = []
        for model_name, profile in profiles.items():
            if model_name in active_models:
                continue
            if profile.sleeping_residual_mb is None or profile.sleeping_residual_mb <= 0:
                continue
            if profile.engine != "vllm":
                continue  # Only vLLM supports sleep mode
            demand_score = self._demand.get_score(model_name)
            candidates.append((demand_score, model_name, profile))

        if not candidates:
            return []

        # Sort by demand score descending, take top N
        candidates.sort(key=lambda c: c[0], reverse=True)
        candidates = candidates[:self.PREEMPTIVE_SLEEP_MAX_MODELS]

        actions = []
        remaining_vram = available_vram

        for _score, model_name, profile in candidates:
            # The net cost after sleep is just the sleeping residual
            residual = float(profile.sleeping_residual_mb or 0.0)
            # But we need enough VRAM to load first (then sleep frees most of it)
            load_cost = profile.estimate_vram_mb()
            if remaining_vram < load_cost * self.VRAM_SAFETY_MARGIN:
                continue
            # After load + sleep, net VRAM consumed is just the residual
            if (remaining_vram - residual) / total_vram < self.PREEMPTIVE_SLEEP_MIN_FREE_VRAM_RATIO:
                continue

            lane_id = self._planner_lane_id(model_name)
            actions.append(CapacityPlanAction(
                action="load",
                provider_id=provider_id,
                lane_id=lane_id,
                model_name=model_name,
                params=self._build_load_params(model_name, lane_id, profile, capacity),
                reason=f"Preemptive load-then-sleep (residual={residual:.0f}MB)",
            ))
            actions.append(CapacityPlanAction(
                action="sleep_l1",
                provider_id=provider_id,
                lane_id=lane_id,
                model_name=model_name,
                params={"level": 1},
                reason=f"Preemptive sleep after load (residual={residual:.0f}MB)",
            ))
            remaining_vram -= residual

        return actions

    def _safe_get_profiles(self, provider_id: int) -> dict[str, ModelProfile]:
        try:
            return self._facade.get_model_profiles(provider_id)
        except Exception:
            return {}

    def _safe_get_capacity(self, provider_id: int):
        try:
            return self._facade.get_capacity_info(provider_id)
        except Exception:
            return None

    def _safe_get_lanes(self, provider_id: int) -> list[LaneSchedulerSignals]:
        try:
            return self._facade.get_all_provider_lane_signals(provider_id)
        except Exception:
            return []

    def _pick_request_target_lane(
        self,
        provider_id: int,
        model_name: str,
    ) -> Optional[LaneSchedulerSignals]:
        lanes = [
            lane
            for lane in self._safe_get_lanes(provider_id)
            if lane.model_name == model_name and lane.runtime_state not in {"stopped", "error"}
        ]
        if not lanes:
            return None

        state_rank = {
            "running": 0,
            "loaded": 1,
            "sleeping": 2,
            "cold": 3,
            "starting": 4,
        }
        lanes.sort(
            key=lambda lane: (
                state_rank.get(lane.runtime_state, 99),
                lane.queue_waiting,
                lane.requests_running,
                lane.active_requests,
                lane.ttft_p95_seconds,
                -float(lane.effective_vram_mb or 0.0),
                lane.lane_id,
            )
        )
        return lanes[0]

    async def _ensure_request_capacity(
        self,
        *,
        provider_id: int,
        target: LaneSchedulerSignals,
        profile: Optional[ModelProfile],
        timeout_seconds: float,
    ) -> bool:
        capacity = self._safe_get_capacity(provider_id)
        if capacity is None:
            return False

        target_action = CapacityPlanAction(
            action="wake" if target.runtime_state == "sleeping" else "load",
            provider_id=provider_id,
            lane_id=target.lane_id,
            model_name=target.model_name,
            params=self._build_load_params(target.model_name, target.lane_id, profile, capacity),
            reason="Request-time lane preparation",
        )

        while True:
            capacity = self._safe_get_capacity(provider_id)
            if capacity is None:
                return False

            needed = self._estimate_action_vram(target_action, profile, capacity) * self.VRAM_SAFETY_MARGIN
            available = float(capacity.available_vram_mb)
            if available >= needed:
                return True

            reclaim = self._next_request_reclaim_action(
                provider_id=provider_id,
                target=target,
                lanes=self._safe_get_lanes(provider_id),
                profiles=self._safe_get_profiles(provider_id),
            )
            if reclaim is None:
                logger.info(
                    "No idle reclaim action available for provider=%s model=%s (need=%.0fMB available=%.0fMB)",
                    provider_id,
                    target.model_name,
                    needed,
                    available,
                )
                return False

            ok = await self._execute_action_with_confirmation(
                reclaim,
                timeout_seconds=min(timeout_seconds, 45.0),
            )
            if not ok:
                return False

    def _next_request_reclaim_action(
        self,
        *,
        provider_id: int,
        target: LaneSchedulerSignals,
        lanes: list[LaneSchedulerSignals],
        profiles: dict[str, ModelProfile],
    ) -> Optional[CapacityPlanAction]:
        sleep_candidates: list[tuple[float, CapacityPlanAction]] = []
        stop_candidates: list[tuple[float, CapacityPlanAction]] = []

        for lane in lanes:
            if lane.lane_id == target.lane_id or lane.model_name == target.model_name:
                continue
            if lane.active_requests > 0 or lane.queue_waiting > 0:
                continue
            if lane.runtime_state in {"stopped", "error", "cold", "starting"}:
                continue

            profile = profiles.get(lane.model_name)
            current_vram = float(lane.effective_vram_mb or 0.0)
            if current_vram <= 0 and profile is not None:
                current_vram = float(profile.estimate_vram_mb())
            residual_vram = float(profile.sleeping_residual_mb or 0.0) if profile is not None else 0.0

            if lane.is_vllm and lane.runtime_state in {"loaded", "running"} and lane.sleep_state == "awake":
                freed = max(current_vram - residual_vram, 0.0)
                if freed > 0:
                    sleep_candidates.append(
                        (
                            freed,
                            CapacityPlanAction(
                                action="sleep_l1",
                                provider_id=provider_id,
                                lane_id=lane.lane_id,
                                model_name=lane.model_name,
                                reason=f"Request-time reclaim for {target.model_name}",
                            ),
                        )
                    )
                if current_vram > 0:
                    stop_candidates.append(
                        (
                            current_vram,
                            CapacityPlanAction(
                                action="stop",
                                provider_id=provider_id,
                                lane_id=lane.lane_id,
                                model_name=lane.model_name,
                                reason=f"Request-time reclaim for {target.model_name}",
                            ),
                        )
                    )
                continue

            if current_vram > 0:
                stop_candidates.append(
                    (
                        current_vram,
                        CapacityPlanAction(
                            action="stop",
                            provider_id=provider_id,
                            lane_id=lane.lane_id,
                            model_name=lane.model_name,
                            reason=f"Request-time reclaim for {target.model_name}",
                        ),
                    )
                )

        if sleep_candidates:
            sleep_candidates.sort(key=lambda item: item[0], reverse=True)
            return sleep_candidates[0][1]
        if stop_candidates:
            stop_candidates.sort(key=lambda item: item[0], reverse=True)
            return stop_candidates[0][1]
        return None

    # ------------------------------------------------------------------
    # GPU utilization tuning (vLLM only)
    # ------------------------------------------------------------------

    # KV cache tuning step: 20% of current KV budget
    KV_CACHE_TUNE_STEP = 0.20
    # Minimum KV cache: 512 MB (below this, model can barely serve requests)
    KV_CACHE_MIN_MB = 512.0

    def _compute_kv_cache_tuning_actions(
        self, provider_id: int, lanes: List[LaneSchedulerSignals]
    ) -> List[CapacityPlanAction]:
        """Tune kv_cache_memory_bytes based on KV cache pressure.

        gpu_memory_utilization stays at 0.95 (ceiling). Only KV cache size
        is adjusted up/down based on observed cache usage percentage.
        """
        actions = []
        try:
            profiles = self._facade.get_model_profiles(provider_id)
        except Exception:
            profiles = {}

        for lane in lanes:
            if not lane.is_vllm:
                continue
            if lane.gpu_cache_usage_percent is None:
                continue
            if lane.runtime_state not in ("loaded", "running"):
                continue

            cache_pct = lane.gpu_cache_usage_percent
            profile = profiles.get(lane.model_name)
            if profile is None:
                continue

            # Determine current KV budget
            current_kv_mb = float(profile.kv_budget_mb or 0.0)
            if current_kv_mb <= 0 and profile.kv_per_token_bytes and profile.kv_per_token_bytes > 0:
                ctx = min(profile.max_context_length or self.DEFAULT_CONTEXT_CAP, self.DEFAULT_CONTEXT_CAP)
                current_kv_mb = (profile.kv_per_token_bytes * ctx * self.DEFAULT_CONCURRENCY) / (1024 * 1024)
            if current_kv_mb <= 0:
                base = profile.estimate_base_residency_mb()
                if base and base > 0:
                    current_kv_mb = base * self.KV_CACHE_HEADROOM_RATIO
                else:
                    continue  # can't tune without knowing current KV size

            step_mb = current_kv_mb * self.KV_CACHE_TUNE_STEP

            if cache_pct > self.GPU_CACHE_HIGH:
                new_kv_mb = current_kv_mb + step_mb
                new_kv_str = self._format_bytes_human(int(new_kv_mb * 1024 * 1024))
                actions.append(CapacityPlanAction(
                    action="reconfigure_kv_cache",
                    provider_id=provider_id,
                    lane_id=lane.lane_id,
                    model_name=lane.model_name,
                    params={
                        "updates": {
                            "vllm_config": {
                                "kv_cache_memory_bytes": new_kv_str,
                            }
                        }
                    },
                    reason=(
                        f"KV cache pressure high ({cache_pct:.1f}% > {self.GPU_CACHE_HIGH}%), "
                        f"increasing kv_cache from {current_kv_mb:.0f}MB to {new_kv_mb:.0f}MB"
                    ),
                ))
            elif cache_pct < self.GPU_CACHE_LOW:
                other_demand = any(
                    score > 0
                    for model_name, score in self._demand.get_ranked_models()
                    if model_name != lane.model_name
                )
                if other_demand:
                    new_kv_mb = max(self.KV_CACHE_MIN_MB, current_kv_mb - step_mb)
                    if abs(new_kv_mb - current_kv_mb) < 64:  # <64MB change not worth it
                        continue
                    new_kv_str = self._format_bytes_human(int(new_kv_mb * 1024 * 1024))
                    actions.append(CapacityPlanAction(
                        action="reconfigure_kv_cache",
                        provider_id=provider_id,
                        lane_id=lane.lane_id,
                        model_name=lane.model_name,
                        params={
                            "updates": {
                                "vllm_config": {
                                    "kv_cache_memory_bytes": new_kv_str,
                                }
                            }
                        },
                        reason=(
                            f"KV cache low ({cache_pct:.1f}% < {self.GPU_CACHE_LOW}%), "
                            f"other models need VRAM, reducing kv_cache from {current_kv_mb:.0f}MB to {new_kv_mb:.0f}MB"
                        ),
                    ))

        return actions

    # ------------------------------------------------------------------
    # VRAM budget validation
    # ------------------------------------------------------------------

    def _passes_minimum_load_feasibility(
        self,
        model_name: str,
        profile: Optional[ModelProfile],
        capacity,
        kv_cache_bytes_str: Optional[str] = None,
    ) -> bool:
        """Quick feasibility check: base_model_size + kv_cache <= available_vram.

        Uses HF API data from profile (fetched by worker), or name heuristic.
        Returns True if load seems feasible, False if it would definitely OOM.
        Returns True (allow) when we cannot estimate — don't block unknowns.
        """
        if capacity is None:
            return False
        available_mb = float(getattr(capacity, "available_vram_mb", 0) or 0)
        if available_mb <= 0:
            return False

        base_mb: Optional[float] = None
        if profile is not None:
            base_mb = profile.estimate_base_residency_mb()
        if base_mb is None:
            from logos.sdi.models import (
                _base_residency_from_bytes,
                _estimated_disk_size_bytes_from_model_name,
            )
            disk = _estimated_disk_size_bytes_from_model_name(model_name)
            base_mb = _base_residency_from_bytes(disk)
        if base_mb is None:
            return True  # can't estimate, allow

        kv_mb = 0.0
        if kv_cache_bytes_str:
            kv_mb = self._parse_kv_cache_to_mb(kv_cache_bytes_str)
        elif profile is not None and profile.kv_budget_mb and profile.kv_budget_mb > 0:
            kv_mb = float(profile.kv_budget_mb)
        elif profile is not None and profile.kv_per_token_bytes and profile.kv_per_token_bytes > 0:
            ctx = min(profile.max_context_length or self.DEFAULT_CONTEXT_CAP, self.DEFAULT_CONTEXT_CAP)
            kv_mb = (profile.kv_per_token_bytes * ctx * self.DEFAULT_CONCURRENCY) / (1024 * 1024)
        else:
            kv_mb = base_mb * self.KV_CACHE_HEADROOM_RATIO

        minimum_needed = base_mb + kv_mb
        feasible = available_mb >= minimum_needed * self.VRAM_SAFETY_MARGIN
        if not feasible:
            logger.info(
                "Feasibility FAILED for %s: need %.0fMB (base=%.0fMB + kv=%.0fMB) "
                "× %.1f margin, have %.0fMB",
                model_name, minimum_needed, base_mb, kv_mb,
                self.VRAM_SAFETY_MARGIN, available_mb,
            )
        return feasible

    def _validate_vram_budget(
        self, actions: List[CapacityPlanAction]
    ) -> List[CapacityPlanAction]:
        """Filter out actions that would exceed available VRAM.

        For load/wake actions, checks estimated VRAM against available capacity
        with a safety margin. Tracks cumulative consumption per provider.
        """
        validated = []
        cumulative_vram: dict[int, float] = {}

        # Process sleep/stop first (they free VRAM)
        free_actions = [a for a in actions if a.action in ("sleep_l1", "sleep_l2", "stop")]
        consume_actions = [a for a in actions if a.action in ("wake", "load")]
        other_actions = [a for a in actions if a.action not in ("sleep_l1", "sleep_l2", "stop", "wake", "load")]

        # Always allow sleep/stop and reconfigure actions
        validated.extend(free_actions)
        validated.extend(other_actions)

        # For consuming actions, check VRAM budget
        for action in consume_actions:
            provider_id = action.provider_id

            try:
                capacity = self._facade.get_capacity_info(provider_id)
                available = float(capacity.available_vram_mb) - cumulative_vram.get(provider_id, 0.0)
            except Exception:
                logger.debug("Cannot check VRAM for provider %s, rejecting %s", provider_id, action.action)
                continue

            try:
                profiles = self._facade.get_model_profiles(provider_id)
            except Exception:
                profiles = {}

            profile = profiles.get(action.model_name)
            estimated_vram = self._estimate_action_vram(action, profile, capacity)

            if available < estimated_vram * self.VRAM_SAFETY_MARGIN:
                logger.warning(
                    "VRAM budget check failed for %s on %s: available=%.0fMB, "
                    "estimated=%.0fMB (with margin=%.0fMB)",
                    action.action, action.model_name,
                    available, estimated_vram, estimated_vram * self.VRAM_SAFETY_MARGIN,
                )
                continue

            cumulative_vram[provider_id] = cumulative_vram.get(provider_id, 0.0) + estimated_vram
            validated.append(action)

        return validated

    def _planner_lane_id(self, model_name: str) -> str:
        sanitized = model_name.replace("/", "_").replace(":", "_").replace(" ", "_")
        return f"planner-{sanitized}"

    def _build_load_params(
        self,
        model_name: str,
        lane_id: str,
        profile: Optional[ModelProfile],
        capacity=None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "lane_id": lane_id,
            "model": model_name,
        }
        if profile is None or profile.engine != "vllm":
            return params
        params["vllm"] = True
        vllm_config: Dict[str, Any] = {
            "enable_sleep_mode": True,
            "server_dev_mode": True,
        }
        # Only send TP if the profile has an observed value from a previous load.
        # Otherwise, let the worker auto-detect based on its GPU count.
        if profile.tensor_parallel_size and int(profile.tensor_parallel_size) > 1:
            vllm_config["tensor_parallel_size"] = int(profile.tensor_parallel_size)
        kv = self._compute_kv_cache_bytes(profile, capacity)
        if kv:
            # When we have an explicit KV budget, send only the KV cache size.
            # Do not also force gpu_memory_utilization: vLLM still treats that
            # as a startup guard, which can block an otherwise valid load.
            vllm_config["kv_cache_memory_bytes"] = kv
        params["vllm_config"] = vllm_config
        return params

    def _build_apply_lanes_params_for_load(
        self,
        action: CapacityPlanAction,
    ) -> Dict[str, Any]:
        """Build a full desired lane set for a load action.

        ``apply_lanes`` on the worker is declarative: any lane omitted from the
        payload is removed. Request-time cold loads therefore must preserve the
        existing worker lane set and merge the new lane into it, instead of
        sending a single-lane replacement payload.
        """
        desired_by_lane_id: dict[str, dict[str, Any]] = {}

        snap = self._registry.peek_runtime_snapshot(action.provider_id) if self._registry else None
        runtime = snap.get("runtime") if isinstance(snap, dict) else None
        lanes = runtime.get("lanes") if isinstance(runtime, dict) else None

        if isinstance(lanes, list):
            for lane in lanes:
                if not isinstance(lane, dict):
                    continue

                runtime_state = str(lane.get("runtime_state") or "").strip().lower()
                if runtime_state in {"stopped", "error"}:
                    continue

                lane_config = lane.get("lane_config")
                if isinstance(lane_config, dict):
                    desired_lane = copy.deepcopy(lane_config)
                else:
                    desired_lane = self._reconstruct_lane_config_from_runtime_lane(lane)
                    if desired_lane is None:
                        continue

                lane_id = str(
                    desired_lane.get("lane_id")
                    or lane.get("lane_id")
                    or self._planner_lane_id(str(desired_lane.get("model") or lane.get("model") or ""))
                ).strip()
                if not lane_id:
                    continue
                desired_lane["lane_id"] = lane_id
                desired_by_lane_id[lane_id] = desired_lane

        desired_by_lane_id[action.lane_id] = {
            "lane_id": action.lane_id,
            "model": action.model_name,
            **copy.deepcopy(action.params),
        }
        return {"lanes": list(desired_by_lane_id.values())}

    def _reconstruct_lane_config_from_runtime_lane(
        self,
        lane: dict[str, Any],
    ) -> Dict[str, Any] | None:
        """Best-effort fallback when a runtime lane lacks explicit lane_config."""
        model_name = str(lane.get("model") or "").strip()
        if not model_name:
            return None

        config: dict[str, Any] = {
            "lane_id": str(lane.get("lane_id") or self._planner_lane_id(model_name)),
            "model": model_name,
        }
        if bool(lane.get("vllm")):
            config["vllm"] = True

        for field in (
            "num_parallel",
            "context_length",
            "keep_alive",
            "kv_cache_type",
            "flash_attention",
            "gpu_devices",
        ):
            value = lane.get(field)
            if value not in (None, ""):
                config[field] = value
        return config

    # KV cache estimation
    KV_CACHE_HEADROOM_RATIO = 0.35  # last-resort fallback for models without HF config
    DEFAULT_CONTEXT_CAP = 8192      # conservative initial context window
    DEFAULT_CONCURRENCY = 4         # target concurrent sequences

    def _compute_kv_cache_bytes(
        self, profile: Optional[ModelProfile], capacity=None
    ) -> Optional[str]:
        """Compute kv_cache_memory_bytes string for vLLM.

        Priority:
        1. Observed kv_budget_mb from previous load (most accurate)
        2. Exact calculation from model architecture (kv_per_token_bytes × context × concurrency)
        3. Last resort: base_residency × headroom ratio

        Returns human-readable string like '1792M' or None if we can't estimate.
        """
        if profile is None:
            return None

        # 1. Observed KV budget from previous load
        if profile.kv_budget_mb and profile.kv_budget_mb > 0:
            kv_bytes = int(float(profile.kv_budget_mb) * 1024 * 1024)
            if kv_bytes > 0:
                return self._format_bytes_human(kv_bytes)

        # 2. Exact calculation from model architecture
        if profile.kv_per_token_bytes and profile.kv_per_token_bytes > 0:
            context = min(
                profile.max_context_length or self.DEFAULT_CONTEXT_CAP,
                self.DEFAULT_CONTEXT_CAP,
            )
            kv_bytes = profile.kv_per_token_bytes * context * self.DEFAULT_CONCURRENCY
            if kv_bytes > 0:
                return self._format_bytes_human(kv_bytes)

        # 3. Fallback: headroom ratio (only for models without HF config)
        base = profile.estimate_base_residency_mb()
        if base is not None and base > 0:
            kv_bytes = int(base * self.KV_CACHE_HEADROOM_RATIO * 1024 * 1024)
            if kv_bytes > 0:
                return self._format_bytes_human(kv_bytes)

        return None

    @staticmethod
    def _format_bytes_human(n: int) -> str:
        """Format byte count as human-readable string for vLLM CLI."""
        if n >= 1024 * 1024 * 1024 and n % (1024 * 1024 * 1024) == 0:
            return f"{n // (1024 * 1024 * 1024)}G"
        if n >= 1024 * 1024 and n % (1024 * 1024) == 0:
            return f"{n // (1024 * 1024)}M"
        return str(n)

    @staticmethod
    def _parse_kv_cache_to_mb(value: str) -> float:
        """Parse kv_cache_memory_bytes string to MB. E.g. '4G' → 4096.0."""
        if not value:
            return 0.0
        v = value.strip().upper()
        if v.endswith("G"):
            return float(v[:-1]) * 1024
        if v.endswith("M"):
            return float(v[:-1])
        if v.endswith("K"):
            return float(v[:-1]) / 1024
        return float(v) / (1024 * 1024)

    def _recommended_vllm_gpu_util(self, profile: Optional[ModelProfile], capacity=None) -> float:
        """Return GPU utilization ceiling. KV cache is now controlled directly."""
        return self.GPU_UTIL_MAX

    def _estimate_action_vram(
        self,
        action: CapacityPlanAction,
        profile: Optional[ModelProfile],
        capacity,
    ) -> float:
        """Estimate VRAM cost of an action.

        For vLLM: base_residency + kv_cache_mb (parsed from action params).
        KV cache is now controlled directly via --kv-cache-memory-bytes,
        so we no longer derive cost from total_vram × gpu_memory_utilization.
        """
        if profile is not None and profile.engine == "vllm":
            base_residency = float(profile.estimate_base_residency_mb() or 0.0)

            # Extract kv_cache_memory_bytes from the action's vllm_config params
            params = action.params or {}
            vllm_config = params.get("vllm_config") if isinstance(params.get("vllm_config"), dict) else {}
            kv_str = vllm_config.get("kv_cache_memory_bytes", "")
            kv_mb = self._parse_kv_cache_to_mb(kv_str) if kv_str else 0.0

            # Fallback chain: observed budget → exact per-token → headroom ratio
            if kv_mb <= 0:
                if profile.kv_budget_mb and profile.kv_budget_mb > 0:
                    kv_mb = float(profile.kv_budget_mb)
                elif profile.kv_per_token_bytes and profile.kv_per_token_bytes > 0:
                    ctx = min(profile.max_context_length or self.DEFAULT_CONTEXT_CAP, self.DEFAULT_CONTEXT_CAP)
                    kv_mb = (profile.kv_per_token_bytes * ctx * self.DEFAULT_CONCURRENCY) / (1024 * 1024)
                elif base_residency > 0:
                    kv_mb = base_residency * self.KV_CACHE_HEADROOM_RATIO

            loaded_vram = base_residency + kv_mb
            sleeping_residual = float(profile.sleeping_residual_mb or 0.0)

            if action.action == "wake":
                return max(0.0, loaded_vram - sleeping_residual)
            if action.action == "load":
                return loaded_vram
            return 0.0

        if profile is not None:
            loaded_vram = profile.estimate_vram_mb()
            sleeping_residual = profile.sleeping_residual_mb or 0.0
        else:
            loaded_vram = 4096.0  # conservative fallback
            sleeping_residual = 0.0

        if action.action == "wake":
            return loaded_vram - sleeping_residual
        if action.action == "load":
            return loaded_vram

        return 0.0

    # ------------------------------------------------------------------
    # Execution with confirmation
    # ------------------------------------------------------------------

    async def _execute_action_with_confirmation(
        self, action: CapacityPlanAction, timeout_seconds: float = 60.0
    ) -> bool:
        """Execute action and wait for worker status to confirm expected state.

        Returns True if confirmed, False if timeout.
        """
        logger.info(
            "Executing capacity action: %s on lane %s (model=%s, provider=%s) — %s",
            action.action, action.lane_id, action.model_name,
            action.provider_id, action.reason,
        )

        # KV cache reconfiguration: sleep first for warm restart, then reconfigure
        if action.action == "reconfigure_kv_cache":
            try:
                logger.info(
                    "Sleeping lane %s before KV cache reconfigure (warm restart)",
                    action.lane_id,
                )
                await self._registry.send_command(
                    action.provider_id,
                    "sleep_lane",
                    {"lane_id": action.lane_id, "level": 1, "mode": "wait"},
                    timeout_seconds=15,
                )
            except Exception:
                logger.warning(
                    "Sleep before reconfigure failed for lane %s, proceeding with cold restart",
                    action.lane_id, exc_info=True,
                )
            try:
                await self._registry.send_command(
                    action.provider_id,
                    "reconfigure_lane",
                    {"lane_id": action.lane_id, **action.params},
                    timeout_seconds=int(min(timeout_seconds, 30)),
                )
            except Exception:
                logger.exception(
                    "Failed to send reconfigure_lane for lane %s", action.lane_id,
                )
                return False

            confirmed = await self._poll_confirmation(action, timeout_seconds)
            if not confirmed:
                logger.warning(
                    "Confirmation timeout for reconfigure_kv_cache on lane %s after %.0fs",
                    action.lane_id, timeout_seconds,
                )
            return confirmed

        command_map = {
            "sleep_l1": ("sleep_lane", {"lane_id": action.lane_id, "level": 1}),
            "sleep_l2": ("sleep_lane", {"lane_id": action.lane_id, "level": 2}),
            "wake": ("wake_lane", {"lane_id": action.lane_id}),
            "stop": ("delete_lane", {"lane_id": action.lane_id}),
            "load": ("add_lane", action.params),
        }

        command_entry = command_map.get(action.action)
        if command_entry is None:
            logger.warning("Unknown capacity action: %s", action.action)
            return False

        command_action, command_params = command_entry

        # Slow-path actions need longer command timeouts since the worker blocks
        # until vLLM finishes the operation.
        cmd_timeout = (
            int(timeout_seconds)
            if action.action in {"load", "wake"}
            else int(min(timeout_seconds, 30))
        )
        try:
            await self._registry.send_command(
                action.provider_id,
                command_action,
                command_params,
                timeout_seconds=cmd_timeout,
            )
        except Exception:
            logger.exception(
                "Failed to send %s command for lane %s",
                action.action, action.lane_id,
            )
            return False

        # Poll for confirmation
        confirmed = await self._poll_confirmation(action, timeout_seconds)
        if not confirmed:
            logger.warning(
                "Confirmation timeout for %s on lane %s after %.0fs",
                action.action, action.lane_id, timeout_seconds,
            )
        return confirmed

    async def _poll_confirmation(
        self, action: CapacityPlanAction, timeout_seconds: float
    ) -> bool:
        """Poll runtime snapshot until lane reaches expected state."""
        deadline = time.time() + timeout_seconds
        poll_interval = 2.0

        while time.time() < deadline:
            await asyncio.sleep(poll_interval)

            snap = self._registry.peek_runtime_snapshot(action.provider_id)
            if snap is None:
                continue

            runtime = snap.get("runtime") or {}
            lanes = runtime.get("lanes") or []
            if not isinstance(lanes, list):
                continue

            lane_dict = next(
                (l for l in lanes if isinstance(l, dict) and l.get("lane_id") == action.lane_id),
                None,
            )

            if self._check_expected_state(action, lane_dict):
                self._record_confirmed_action_state(action, time.time())
                logger.info(
                    "Confirmed %s on lane %s (model=%s)",
                    action.action, action.lane_id, action.model_name,
                )
                return True

        return False

    def _check_expected_state(
        self, action: CapacityPlanAction, lane: Optional[Dict[str, Any]]
    ) -> bool:
        """Check if lane state matches expectation for the action."""
        if action.action in ("sleep_l1", "sleep_l2"):
            return lane is not None and lane.get("sleep_state") == "sleeping"
        if action.action == "wake":
            return lane is not None and lane.get("runtime_state") in ("loaded", "running")
        if action.action == "stop":
            return lane is None  # Lane should be gone
        if action.action == "load":
            # Look for any lane with the model name in loaded/running state
            return lane is not None and lane.get("runtime_state") in ("loaded", "running")
        if action.action == "reconfigure_kv_cache":
            return True  # Reconfiguration confirmed by command success
        return False

    def get_stats(self) -> dict:
        """Return planner state for debugging."""
        return {
            "enabled": self._enabled,
            "cycle_count": self._cycle_count,
            "cycle_seconds": self._cycle_seconds,
            "idle_lanes": {
                f"{pid}:{lid}": time.time() - since
                for (pid, lid), since in self._lane_idle_since.items()
            },
            "sleeping_lanes": {
                f"{pid}:{lid}": {
                    "sleep_seconds": time.time() - since,
                    "sleep_level": self._lane_sleep_level.get((pid, lid), 0),
                }
                for (pid, lid), since in self._lane_sleep_since.items()
            },
            "demand": self._demand.get_stats(),
        }
