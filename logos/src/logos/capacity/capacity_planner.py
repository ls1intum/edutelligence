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
from itertools import combinations
import logging
import os
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
from .vram_ledger import VRAMLedger
from logos.monitoring import prometheus_metrics as prom

logger = logging.getLogger(__name__)


class CapacityPlanner:
    """
    Background planner running every cycle_seconds.

    Per-cycle decision pipeline:
    1. Decay demand scores
    2. Read current lane states from all connected providers
    3. Track idle durations per lane
    4. Compute idle tier actions (sleep only)
    5. Compute demand-based actions (wake/load)
    6. Compute GPU utilization tuning actions (for vLLM lanes)
    7. Validate VRAM budget for all actions
    8. Execute validated actions with confirmation
    """

    # Idle tier thresholds (seconds of no activity)
    IDLE_SLEEP_L1 = 300      # vLLM lane idle 5min → sleep level 1
    IDLE_SLEEP_L2 = 600      # vLLM lane sleeping L1 for 10min → sleep level 2
    # Demand floors: minimum score to act at all (noise filter).
    # Applied only when VRAM is freely available and no eviction is required.
    DEMAND_WAKE_FLOOR = 0.5    # one partial-demand signal is enough to wake
    DEMAND_LOAD_FLOOR = 1.0    # one real request is enough to load on empty VRAM

    # Competitive ratios: applied when eviction IS required.
    # target_effective_demand > max(eviction_set_demand) * RATIO to proceed.
    WAKE_COMPETITIVE_RATIO = 1.5   # target must beat eviction set by 50%
    LOAD_COMPETITIVE_RATIO = 2.0   # target must beat eviction set by 2×
    DRAIN_COMPETITIVE_RATIO = 3.0  # target must 3× outweigh victim (prevents flip-flop)

    # Queue depth contribution to effective demand at decision time.
    QUEUE_WEIGHT = 0.25  # score += QUEUE_WEIGHT * lane.queue_waiting

    # Backward-compat aliases used by tests and external callers
    DEMAND_WAKE_THRESHOLD = DEMAND_WAKE_FLOOR
    DEMAND_LOAD_THRESHOLD = DEMAND_LOAD_FLOOR

    # Demand-preemptive drain: graceful swap of busy lanes for starving models
    DRAIN_TIMEOUT_SECONDS = 60.0           # Max wait for active requests to finish

    # Minimum tenure: after a model wakes/loads, give it at least this
    # long to serve its queue before it can be drained for another model.
    # Without this, a freshly-woken model has 0 active requests, making
    # it an easy drain target — causing thrashing cascades where models
    # wake and immediately sleep without serving anything.
    LANE_MIN_TENURE_SECONDS = 5.0
    # Backward-compat aliases (tests / external callers)
    DRAIN_MIN_COLD_LOADED_SECONDS = 0.0
    DRAIN_MIN_WOKEN_SECONDS = 0.0
    DRAIN_DEMAND_SCORE_THRESHOLD = DRAIN_COMPETITIVE_RATIO

    # GPU utilization tuning
    GPU_UTIL_MIN = 0.50
    GPU_UTIL_MAX = 0.95
    GPU_CACHE_HIGH = 85.0
    GPU_CACHE_LOW = 40.0

    # VRAM safety margin
    VRAM_SAFETY_MARGIN = 1.0  # no margin — calibrated profiles include KV, measurements are exact
    # Tensor-parallel overhead: NCCL buffers + duplicated embedding/output layers
    TP_OVERHEAD_RATIO = 0.10  # 10% overhead per GPU for TP > 1

    # Preemptive load-then-sleep
    PREEMPTIVE_SLEEP_MIN_FREE_VRAM_RATIO = 0.20
    PREEMPTIVE_SLEEP_MAX_MODELS = 3
    PREEMPTIVE_LOAD_REASON = "Preemptive load-then-sleep"
    PREEMPTIVE_SLEEP_REASON = "Preemptive sleep after load"

    # Slow-path request preparation
    REQUEST_WAKE_TIMEOUT_SECONDS = 30.0
    WAKE_FAILURE_COOLDOWN_SECONDS = 15.0
    COOLDOWN_WAIT_BUFFER_SECONDS = 2.0   # extra margin added after load cooldown expires
    BUSY_DRAIN_POLL_SECONDS = 5.0        # poll interval while waiting for a busy lane to drain
    WAKE_PER_GPU_SAFETY_MARGIN = 1.15    # 15% per-GPU margin for wake ops — CUDA allocator pools
                                         # and KV-cache growth can consume memory between the check
                                         # and the actual wake, causing OOM on tight fits
    CALIBRATED_PER_GPU_SAFETY_MARGIN = 1.05  # 5% margin for calibrated models — base_residency is
                                         # measured but vLLM needs small headroom for startup
                                         # (CUDA context, NCCL init, allocator pools)
    TP_RANK0_VRAM_FRACTION = 0.62        # rank 0 hosts API server, tokenizer, sampling, embedding
                                         # layers — empirically ~60% of total VRAM for TP=2;
                                         # use 0.62 for safety margin

    def __init__(
        self,
        logosnode_facade: LogosNodeSchedulingDataFacade,
        logosnode_registry: LogosNodeRuntimeRegistry,
        demand_tracker: DemandTracker,
        cycle_seconds: float = 10.0,
        enabled: bool = True,
        on_state_change: Optional[Any] = None,
    ) -> None:
        self._facade = logosnode_facade
        self._registry = logosnode_registry
        self._demand = demand_tracker
        self._cycle_seconds = cycle_seconds
        self._enabled = enabled
        self._on_state_change = on_state_change
        self._lane_idle_since: dict[tuple[int, str], float] = {}
        self._lane_sleep_since: dict[tuple[int, str], float] = {}
        self._lane_sleep_level: dict[tuple[int, str], int] = {}
        self._lane_loaded_at: dict[tuple[int, str], float] = {}
        self._lane_wake_failure_until: dict[tuple[int, str], float] = {}
        self._preemptive_sleep_ready: set[tuple[int, str]] = set()
        # Per-(provider, model) locks for cold-load deduplication.
        # Two requests for different models on the same provider can proceed
        # concurrently; two requests for the same model are serialized so only
        # one triggers the cold load.
        self._model_prepare_locks: dict[tuple[int, str], asyncio.Lock] = {}
        self._load_cooldown_seconds = float(
            os.environ.get("LOGOS_LOAD_COOLDOWN_SECONDS", "60")
        )
        self._task: Optional[asyncio.Task] = None
        self._cycle_count = 0
        self._use_additive_loads = os.environ.get(
            "LOGOS_USE_ADDITIVE_LOADS", "true"
        ).strip().lower() not in ("0", "false", "no")

        # Phase 1a: Track inflight desired-state mutations so rapid sequential
        # apply_lanes calls don't build from stale registry data.
        # Key: provider_id -> {lane_id -> lane_config_dict}
        self._inflight_desired: dict[int, dict[str, dict[str, Any]]] = {}
        # Track inflight removals separately: provider_id -> set of lane_ids
        self._inflight_removals: dict[int, set[str]] = {}

        # Phase 1b: Per-lane action locks to serialize operations on the same
        # lane without blocking unrelated lanes.
        self._lane_action_locks: dict[tuple[int, str], asyncio.Lock] = {}

        # Phase 3a: Lanes pre-marked as cold — excluded from scheduling before
        # physical removal so new requests don't route to dying lanes.
        self._marked_cold_lanes: set[tuple[int, str]] = set()

        # Track how a lane was loaded: True = cold load, False = wake from sleep
        self._lane_was_cold_loaded: dict[tuple[int, str], bool] = {}

        # Drain suppression: prevent fire-and-forget from reloading recently drained models
        self._drain_timestamps: dict[tuple[int, str], float] = {}  # (provider_id, model_name) → drain time

        # Pending capacity: models whose fire-and-forget capacity trigger failed.
        # Re-attempted when any reclaim action confirms (freed VRAM may suffice).
        # Key: model_name → (provider_id, registered_at)
        self._pending_capacity: dict[str, tuple[int, float]] = {}

        # Phase 4b: Atomic VRAM reservation ledger — prevents double-booking
        # when concurrent load/wake/sleep/stop operations overlap.
        self._vram_ledger = VRAMLedger()

        # Per-provider capacity lock: serializes _ensure_request_capacity calls
        # so concurrent reclaim plans can't deadlock by competing for the same
        # freed VRAM.  Only one capacity operation (drain/sleep/stop → load/wake)
        # runs at a time per provider.  Fast-path checks (model already running)
        # still happen inside the lock but return immediately.
        self._provider_capacity_locks: dict[int, asyncio.Lock] = {}

        # Phase 2: KV cache pressure history and rebalance timing
        self._kv_cache_pressure_history: dict[tuple[int, str], list[tuple[float, float]]] = {}
        # Initialize to now so the first rebalance waits the full interval
        # (prevents immediate sleep of freshly loaded lanes for KV resizing)
        self._last_kv_rebalance_time: float = time.time()
        # Deferred KV reconfigurations waiting for lane to go idle
        self._deferred_kv_reconfigs: dict[tuple[int, str], CapacityPlanAction] = {}

    def _model_prepare_lock(self, provider_id: int, model_name: str) -> asyncio.Lock:
        """Get or create a per-(provider, model) lock for cold-load serialization."""
        key = (int(provider_id), model_name)
        lock = self._model_prepare_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._model_prepare_locks[key] = lock
        return lock

    def _provider_capacity_lock(self, provider_id: int) -> asyncio.Lock:
        """Get or create a per-provider lock for capacity operations."""
        lock = self._provider_capacity_locks.get(provider_id)
        if lock is None:
            lock = asyncio.Lock()
            self._provider_capacity_locks[provider_id] = lock
        return lock

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

        # Safety net: clean up any VRAM reservations leaked by crashed operations
        stale_count = self._vram_ledger.cleanup_stale(max_age_seconds=120.0)
        if stale_count > 0:
            logger.warning("Cleaned %d stale VRAM reservations", stale_count)

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
            self._record_kv_pressure_history(provider_id, lanes)
            all_actions.extend(self._compute_idle_actions(provider_id, lanes))
            all_actions.extend(self._compute_demand_actions(provider_id, lanes))
            all_actions.extend(self._compute_demand_drain_actions(provider_id, lanes))
            # TODO: KV fleet rebalancing disabled — was computing budgets from total
            # worker VRAM instead of per-lane GPU VRAM, causing OOM on reconfigure.
            # Re-enable after the per-GPU fix is verified in production.
            # all_actions.extend(self._compute_fleet_kv_allocation(provider_id, lanes))
            all_actions.extend(self._compute_preemptive_sleep_actions(provider_id, lanes))
            # Execute any deferred KV reconfigs for lanes that have gone idle
            # all_actions.extend(self._flush_deferred_kv_reconfigs(provider_id, lanes))

        if all_actions:
            self._log_action_plan(all_actions)

        validated = self._validate_vram_budget(all_actions)

        for action in validated:
            try:
                # Acquire per-lane lock so concurrent operations on the same
                # lane are serialized, but unrelated lanes remain unblocked.
                async with self._lane_lock(action.provider_id, action.lane_id):
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
                name = self._facade.get_provider_name(pid) or "?"
                lines.append(f"{paint('⊘', RED)} provider={paint(name, BOLD)} {paint('offline', DIM)}")
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
                f"{paint('●', worker_color)} provider={paint(str(worker_id), BOLD)} "
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
        demand_score = self._demand.get_score(model)
        demand_text = f"{demand_score:.2f}" if demand_score > 0 else "0"
        lines.append(
            f"{indent}  active={active_requests} run={running_text} "
            f"queue={queue_text} kv_cache={cache_text} ttft_p95={ttft_text} "
            f"prefix_hit={prefix_text} demand={demand_text}"
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
            pname = self._facade.get_provider_name(action.provider_id) or str(action.provider_id)
            lines.append(
                f"{paint('→', color)} {paint(action.action, color, BOLD)} "
                f"provider={pname} lane={action.lane_id}"
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

        # Don't reload a model that was recently drained — the drain decision
        # was intentional and reloading immediately causes oscillation.
        # Exception: if the incumbent model is idle (0 active requests), the
        # drain rationale no longer applies — allow the load so queued requests
        # don't starve.
        drain_key = (provider_id, model_name)
        drain_time = self._drain_timestamps.get(drain_key)
        if drain_time is not None:
            elapsed = time.time() - drain_time
            cooldown = self._get_effective_tenure(was_cold_loaded=False)
            if elapsed < cooldown:
                # Check if the incumbent is still busy
                incumbent_busy = False
                all_lanes = self._safe_get_lanes(provider_id)
                for lane in all_lanes:
                    if lane.model_name != model_name and lane.runtime_state in ("loaded", "running"):
                        if lane.active_requests > 0 or lane.queue_waiting > 0:
                            incumbent_busy = True
                            break
                if incumbent_busy:
                    logger.info(
                        "Skipping prepare for %s on provider %s: drained %.0fs ago "
                        "(cooldown %.0fs, incumbent busy)",
                        model_name, provider_id, elapsed, cooldown,
                    )
                    return None
                else:
                    logger.info(
                        "Allowing prepare for %s on provider %s despite drain %.0fs ago: "
                        "incumbent is idle",
                        model_name, provider_id, elapsed,
                    )
                    self._drain_timestamps.pop(drain_key, None)
            else:
                # Cooldown expired — clear the entry
                self._drain_timestamps.pop(drain_key, None)

        target = self._pick_request_target_lane(provider_id, model_name)
        if target is not None and target.runtime_state not in {"sleeping", "cold"}:
            return await self._prepare_existing_lane(
                provider_id, model_name, target, timeout_seconds,
            )

        async with self._model_prepare_lock(provider_id, model_name):
            # Re-check after acquiring lock — another request for the same model
            # may have completed the cold load while we were waiting.
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
        if (
            target.runtime_state == "sleeping"
            and self._lane_is_in_wake_failure_cooldown(provider_id, target.lane_id)
        ):
            logger.info(
                "Skipping wake retry for lane %s on provider %s: recent wake failure cooldown active",
                target.lane_id,
                provider_id,
            )
            return None
        if target.runtime_state in {"sleeping", "cold"}:
            ok = await self._ensure_request_capacity(
                provider_id=provider_id,
                target=target,
                profile=profile,
                timeout_seconds=timeout_seconds,
            )
            if not ok:
                self._pending_capacity[model_name] = (provider_id, time.time())
                return None

        if target.runtime_state == "sleeping":
            async with self._lane_lock(provider_id, target.lane_id):
                # Re-check lane state after acquiring lock — a concurrent task
                # may have already woken this lane while we waited for the lock.
                current_lanes = self._safe_get_lanes(provider_id)
                current_target = next(
                    (l for l in current_lanes if l.lane_id == target.lane_id),
                    None,
                )
                if current_target is not None and current_target.runtime_state not in ("sleeping", "cold"):
                    logger.info(
                        "Lane %s already awake (state=%s) after acquiring lock, skipping wake",
                        target.lane_id, current_target.runtime_state,
                    )
                else:
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

    async def _stop_sleeping_lanes_for_headroom(
        self,
        provider_id: int,
        loading_model: str,
        timeout_seconds: float,
    ) -> None:
        """Stop all sleeping lanes on a provider to free residual VRAM.

        Called before a cold load when the post-load headroom would be tight.
        Sleeping lanes hold ~1-2 GB of residual VRAM each; stopping them
        releases that memory so vLLM has maximum CUDA free space for startup.
        """
        lanes = self._facade.get_all_provider_lane_signals(provider_id)
        for lane in lanes:
            if lane.model_name == loading_model:
                continue
            if lane.sleep_state != "sleeping":
                continue
            stop_action = CapacityPlanAction(
                action="stop",
                provider_id=provider_id,
                lane_id=lane.lane_id,
                model_name=lane.model_name,
                reason=f"Headroom reclaim for cold load of {loading_model}",
            )
            logger.info(
                "Stopping sleeping lane %s (model=%s, vram=%.0fMB) "
                "to free headroom for cold load of %s",
                lane.lane_id, lane.model_name,
                lane.effective_vram_mb or 0, loading_model,
            )
            self._mark_lane_cold(provider_id, lane.lane_id)
            async with self._lane_lock(provider_id, lane.lane_id):
                await self._execute_action_with_confirmation(
                    stop_action, timeout_seconds=min(timeout_seconds, 30.0),
                )

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
            logger.debug("No capacity info for provider %s, cannot cold-load %s", self._facade.get_provider_name(provider_id) or provider_id, model_name)
            return None

        # No early feasibility bail-out here — the reclaim loop below will
        # sleep/stop idle lanes to free VRAM.  The feasibility check against
        # current available VRAM would reject loads that are perfectly viable
        # after reclaiming.  If the model truly can't fit (misconfiguration),
        # the reclaim loop will exhaust candidates and return None.

        lane_id = self._planner_lane_id(model_name)
        load_action = CapacityPlanAction(
            action="load",
            provider_id=provider_id,
            lane_id=lane_id,
            model_name=model_name,
            params=self._build_load_params(model_name, lane_id, profile, capacity, provider_id),
            reason="Request-time cold load",
        )

        estimated = self._estimate_action_vram(load_action, profile, capacity)
        available = float(capacity.available_vram_mb)

        residency_src = getattr(profile, "residency_source", None) if profile else None
        logger.info(
            "Cold-load VRAM check for %s on provider %s: "
            "estimated=%.0f MB, available=%.0f MB, "
            "base_residency=%s MB (%s), engine=%s, total_vram=%s",
            model_name, provider_id, estimated, available,
            getattr(profile, "base_residency_mb", None) if profile else None,
            residency_src or "no-profile",
            getattr(profile, "engine", None),
            getattr(capacity, "total_vram_mb", None),
        )

        # Use the same reclaim engine as wake — it checks aggregate + per-GPU
        # VRAM with ledger awareness, and returns True immediately if sufficient.
        # If not, it runs the full reclaim loop (sleep loaded lanes, drain busy
        # lanes, stop non-vLLM lanes) with provider capacity lock serialization.
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
                model_name, self._facade.get_provider_name(provider_id) or provider_id,
            )
            self._pending_capacity[model_name] = (provider_id, time.time())
            return None

        logger.info("Cold-loading %s on provider %s (lane=%s)", model_name, self._facade.get_provider_name(provider_id) or provider_id, lane_id)
        async with self._lane_lock(provider_id, lane_id):
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
        self._lane_wake_failure_until.pop(key, None)
        self._preemptive_sleep_ready.discard(key)

    def _mark_wake_failure(
        self,
        provider_id: int,
        lane_id: str,
        *,
        details: str | None = None,
        now: float | None = None,
    ) -> None:
        key = self._lane_key(provider_id, lane_id)
        current_time = time.time() if now is None else now
        self._lane_wake_failure_until[key] = (
            current_time + self.WAKE_FAILURE_COOLDOWN_SECONDS
        )
        logger.warning(
            "Marked lane %s on provider %s as wake-failed for %.0fs%s",
            lane_id,
            provider_id,
            self.WAKE_FAILURE_COOLDOWN_SECONDS,
            f": {details}" if details else "",
        )

    def _clear_wake_failure(self, provider_id: int, lane_id: str) -> None:
        self._lane_wake_failure_until.pop(self._lane_key(provider_id, lane_id), None)

    def _lane_is_in_wake_failure_cooldown(
        self,
        provider_id: int,
        lane_id: str,
        *,
        now: float | None = None,
    ) -> bool:
        key = self._lane_key(provider_id, lane_id)
        retry_at = self._lane_wake_failure_until.get(key)
        if retry_at is None:
            return False
        current_time = time.time() if now is None else now
        if current_time >= retry_at:
            self._lane_wake_failure_until.pop(key, None)
            return False
        return True

    def _record_confirmed_action_state(
        self, action: CapacityPlanAction, confirmed_at: float
    ) -> None:
        key = self._lane_key(action.provider_id, action.lane_id)

        if action.action == "sleep_l1":
            self._preemptive_sleep_ready.discard(key)
            self._lane_sleep_since.setdefault(key, confirmed_at)
            self._lane_sleep_level[key] = 1
            self._lane_idle_since.setdefault(key, confirmed_at)
            # Record drain timestamp only on successful drain-sleep so
            # fire-and-forget doesn't immediately reload this model.
            if action.reason and "drain" in action.reason.lower():
                self._drain_timestamps[
                    (action.provider_id, action.model_name)
                ] = confirmed_at
            return

        if action.action == "sleep_l2":
            self._preemptive_sleep_ready.discard(key)
            self._lane_sleep_since.setdefault(key, confirmed_at)
            self._lane_sleep_level[key] = 2
            self._lane_idle_since.setdefault(key, confirmed_at)
            return

        if action.action in {"wake", "load"}:
            self._clear_wake_failure(action.provider_id, action.lane_id)
            self._lane_sleep_since.pop(key, None)
            self._lane_sleep_level.pop(key, None)
            self._lane_idle_since[key] = confirmed_at
            self._lane_loaded_at[key] = confirmed_at
            self._lane_was_cold_loaded[key] = (action.action == "load")
            try:
                from logos.monitoring import prometheus_metrics as prom
                prom.CAPACITY_PLANNER_SWITCHES_TOTAL.inc()
            except Exception:
                pass
            if action.action == "load" and self._is_preemptive_load_action(action):
                self._preemptive_sleep_ready.add(key)
            else:
                self._preemptive_sleep_ready.discard(key)
            return

        if action.action == "stop":
            self._clear_lane_tracking(key)
            self._lane_loaded_at.pop(key, None)
            self._lane_was_cold_loaded.pop(key, None)

    @classmethod
    def _is_preemptive_load_action(cls, action: CapacityPlanAction) -> bool:
        return action.action == "load" and action.reason.startswith(cls.PREEMPTIVE_LOAD_REASON)

    @classmethod
    def _is_preemptive_sleep_action(cls, action: CapacityPlanAction) -> bool:
        return action.action == "sleep_l1" and action.reason.startswith(cls.PREEMPTIVE_SLEEP_REASON)

    def _lane_is_in_load_cooldown(
        self,
        provider_id: int,
        lane_id: str,
        *,
        now: float | None = None,
    ) -> bool:
        if self._load_cooldown_seconds <= 0:
            return False
        key = self._lane_key(provider_id, lane_id)
        loaded_at = self._lane_loaded_at.get(key)
        if loaded_at is None:
            return False
        check_time = time.time() if now is None else now
        return (check_time - loaded_at) < self._load_cooldown_seconds

    def _time_until_cooldown_unblocked_stop(
        self,
        *,
        provider_id: int,
        target: LaneSchedulerSignals,
        lanes: list[LaneSchedulerSignals],
        profiles: dict[str, ModelProfile],
        required_free_mb: float,
        now: float,
    ) -> Optional[float]:
        """Return seconds until the earliest cooldown-blocked stop candidate becomes
        actionable, or None if no such candidate exists.

        A lane qualifies as a cooldown-blocked stop candidate when ALL of:
          - It is not the target lane and not running the target model
          - It has no active requests and no queued requests
          - It is not in a terminal/transient state (stopped/error/cold/starting)
          - Its current_vram > 0 (stopping it would free meaningful VRAM)
          - current_vram >= required_free_mb (single lane stop would satisfy shortfall)
          - It IS currently in load cooldown (the only reason it was skipped)
        """
        if self._load_cooldown_seconds <= 0:
            return None

        min_wait: Optional[float] = None

        for lane in lanes:
            if lane.lane_id == target.lane_id or lane.model_name == target.model_name:
                continue
            if lane.active_requests > 0 or lane.queue_waiting > 0:
                continue
            if lane.runtime_state in {"stopped", "error", "cold", "starting"}:
                continue
            # Skip awake vLLM lanes — these are reclaimed via sleep (which
            # is allowed even within cooldown) rather than direct stop.
            # After sleeping, the lane re-enters as a sleeping stop candidate.
            if (lane.is_vllm
                    and lane.runtime_state in {"loaded", "running"}
                    and lane.sleep_state == "awake"):
                continue

            key = self._lane_key(provider_id, lane.lane_id)
            loaded_at = self._lane_loaded_at.get(key)
            if loaded_at is None:
                continue
            remaining = self._load_cooldown_seconds - (now - loaded_at)
            if remaining <= 0:
                continue  # not actually in cooldown

            profile = profiles.get(lane.model_name)
            current_vram = float(lane.effective_vram_mb or 0.0)
            if current_vram <= 0 and profile is not None:
                current_vram = self._estimate_model_loaded_vram(profile)
            if lane.is_vllm and lane.runtime_state == "sleeping" and profile is not None:
                base_residency = float(getattr(profile, "base_residency_mb", 0) or 0)
                if base_residency > current_vram:
                    current_vram = base_residency
            if current_vram <= 0:
                continue
            # Per-GPU feasibility: for TP>1 models, a lane's VRAM is split
            # across its GPUs — check per-GPU freed vs per-GPU shortfall.
            if required_free_mb > 0:
                lane_tp = int(lane.tensor_parallel_size or 0) or 1
                if lane_tp <= 1 and profile is not None:
                    lane_tp = max(int(profile.tensor_parallel_size or 0), 1)
                target_tp = int(target.tensor_parallel_size or 0) or 1
                if target_tp <= 1:
                    target_profile = profiles.get(target.model_name)
                    if target_profile is not None:
                        target_tp = max(int(target_profile.tensor_parallel_size or 0), 1)
                per_gpu_freed = current_vram / lane_tp
                per_gpu_needed = required_free_mb / target_tp
                if per_gpu_freed < per_gpu_needed:
                    continue  # even if unblocked, per-GPU freed can't satisfy the shortfall

            if min_wait is None or remaining < min_wait:
                min_wait = remaining

        return min_wait

    def _time_until_idle_tenure_unblocked(
        self,
        *,
        provider_id: int,
        target: LaneSchedulerSignals,
        lanes: list[LaneSchedulerSignals],
        profiles: dict[str, ModelProfile],
        now: float,
    ) -> Optional[float]:
        """Return seconds until the earliest tenure-blocked idle lane becomes
        sleepable, or None if no such candidate exists.

        This mirrors ``_time_until_cooldown_unblocked_stop`` but checks idle
        loaded/running vLLM lanes that are blocked only by tenure protection.

        Tenure is waived (returns None for that lane) when the loaded model has
        zero pending work and the target has queued requests — there is no point
        keeping a totally idle model loaded while another model's queue grows.
        """
        target_queue = self._get_queue_depth_for_model(
            provider_id, target.model_name, lanes,
        )
        min_wait: Optional[float] = None

        for lane in lanes:
            if lane.lane_id == target.lane_id or lane.model_name == target.model_name:
                continue
            if lane.active_requests > 0 or lane.queue_waiting > 0:
                continue
            if lane.runtime_state in {"stopped", "error", "cold", "starting"}:
                continue
            if not (lane.is_vllm
                    and lane.runtime_state in {"loaded", "running"}
                    and lane.sleep_state == "awake"):
                continue

            # Check if this lane is actually blocked by tenure
            key = self._lane_key(provider_id, lane.lane_id)
            loaded_at = self._lane_loaded_at.get(key)
            if loaded_at is None:
                continue  # no timestamp — not blocked
            was_cold = self._lane_was_cold_loaded.get(key, True)
            min_tenure = self._get_effective_tenure(was_cold)
            remaining_tenure = min_tenure - (now - loaded_at)
            if remaining_tenure <= 0:
                continue  # not actually blocked

            # Would tenure be waived?  If model is idle (checked above via
            # active_requests/queue_waiting) and has no scheduler queue, and
            # target has queued work, the waiver applies — don't count this
            # lane as tenure-blocked.
            lane_queue = self._get_queue_depth_for_model(
                provider_id, lane.model_name, lanes,
            )
            if lane_queue == 0 and target_queue > 0:
                continue  # tenure would be waived

            if min_wait is None or remaining_tenure < min_wait:
                min_wait = remaining_tenure

        return min_wait

    def _has_blocking_busy_lanes(
        self,
        *,
        provider_id: int,
        target: LaneSchedulerSignals,
        lanes: list[LaneSchedulerSignals],
        profiles: dict[str, ModelProfile],
        required_free_mb: float,
    ) -> bool:
        """Return True if there are busy lanes that would be valid stop candidates
        once their active requests finish.

        Unlike _should_initiate_drain (which preempts running requests immediately),
        this helper identifies lanes where waiting for current requests to complete
        would unlock a clean stop — no demand-ratio check is needed because once
        a lane is idle it is eligible for a normal stop regardless of demand.

        A busy lane qualifies when ALL of:
          - Not the target lane / model
          - Has active_requests > 0 or queue_waiting > 0 (currently busy)
          - Runtime state is serviceable (not stopped/error/cold/starting)
          - GPU overlap with target (stopping it would free the right GPUs)
          - Sufficient VRAM to satisfy the shortfall alone
        """
        target_gpu_ids = self._parse_gpu_device_ids(target.gpu_devices)

        for lane in lanes:
            if lane.lane_id == target.lane_id or lane.model_name == target.model_name:
                continue
            if lane.active_requests <= 0 and lane.queue_waiting <= 0:
                continue  # not busy — irrelevant to this check
            if lane.runtime_state in {"stopped", "error", "cold", "starting"}:
                continue

            # GPU overlap: if we know target GPUs and the lane's GPUs, they must overlap.
            # Unknown placement (empty string) is treated optimistically.
            if target_gpu_ids:
                busy_gpu_ids = self._parse_gpu_device_ids(lane.gpu_devices)
                if busy_gpu_ids and not (set(target_gpu_ids) & set(busy_gpu_ids)):
                    continue  # wrong GPUs — waiting for drain won't help

            # VRAM: this lane alone must be able to satisfy the shortfall.
            # For TP>1 models, check per-GPU feasibility — a lane's total VRAM
            # is split across its GPUs, and the target's shortfall is per-GPU.
            profile = profiles.get(lane.model_name)
            current_vram = float(lane.effective_vram_mb or 0.0)
            if current_vram <= 0 and profile is not None:
                current_vram = self._estimate_model_loaded_vram(profile)
            if current_vram <= 0:
                continue
            if required_free_mb > 0:
                lane_tp = int(lane.tensor_parallel_size or 0) or 1
                if lane_tp <= 1 and profile is not None:
                    lane_tp = max(int(profile.tensor_parallel_size or 0), 1)
                target_tp = int(target.tensor_parallel_size or 0) or 1
                if target_tp <= 1:
                    target_profile = profiles.get(target.model_name)
                    if target_profile is not None:
                        target_tp = max(int(target_profile.tensor_parallel_size or 0), 1)
                per_gpu_freed = current_vram / lane_tp
                per_gpu_needed = required_free_mb / target_tp
                logger.debug(
                    "_has_blocking_busy_lanes: lane=%s vram=%.0f lane_tp=%d "
                    "target_tp=%d per_gpu_freed=%.0f per_gpu_needed=%.0f "
                    "passes=%s",
                    lane.lane_id, current_vram, lane_tp,
                    target_tp, per_gpu_freed, per_gpu_needed,
                    per_gpu_freed >= per_gpu_needed,
                )
                if per_gpu_freed < per_gpu_needed:
                    continue

            return True

        return False

    def _time_until_drain_cooldown_unblocked(
        self,
        *,
        provider_id: int,
        target: LaneSchedulerSignals,
        lanes: list[LaneSchedulerSignals],
        profiles: dict[str, ModelProfile],
        required_free_mb: float,
        now: float,
    ) -> Optional[float]:
        """Return seconds until a drain-cooldown-blocked busy lane becomes drainable.

        Checks busy lanes that would pass ``_should_initiate_drain`` on all criteria
        EXCEPT the adaptive tenure cooldown.  Returns the shortest remaining
        cooldown, or ``None`` when no such lane exists.
        """
        min_wait: Optional[float] = None
        target_gpu_ids = self._parse_gpu_device_ids(target.gpu_devices)
        target_eff = self._effective_demand(target.model_name, provider_id, lanes)

        for lane in lanes:
            if lane.lane_id == target.lane_id or lane.model_name == target.model_name:
                continue
            if lane.active_requests <= 0 and lane.queue_waiting <= 0:
                continue  # not busy
            if lane.runtime_state in {"stopped", "error", "cold", "starting"}:
                continue

            # 1. Demand ratio check (must pass unless both near-zero)
            busy_eff = self._effective_demand(lane.model_name, provider_id, lanes, lane)
            both_near_zero = target_eff < 0.1 and busy_eff < 0.1
            if not both_near_zero and target_eff <= busy_eff * self.DRAIN_COMPETITIVE_RATIO:
                continue

            # 2. Drain cooldown check — compute remaining time
            key = self._lane_key(provider_id, lane.lane_id)
            loaded_at = self._lane_loaded_at.get(key)
            if loaded_at is None:
                continue  # unknown load time — not blocked by cooldown
            was_cold = self._lane_was_cold_loaded.get(key, True)
            min_seconds = self._get_effective_tenure(was_cold)
            drain_remaining = min_seconds - (now - loaded_at)
            if drain_remaining <= 0:
                continue  # cooldown already expired — not what we're looking for

            # 3. GPU overlap (must pass)
            if target_gpu_ids:
                busy_gpu_ids = self._parse_gpu_device_ids(lane.gpu_devices)
                if busy_gpu_ids and not (set(target_gpu_ids) & set(busy_gpu_ids)):
                    continue

            # 4. VRAM feasibility with per-GPU check (must pass)
            profile = profiles.get(lane.model_name)
            current_vram = float(lane.effective_vram_mb or 0.0)
            if current_vram <= 0 and profile is not None:
                current_vram = self._estimate_model_loaded_vram(profile)
            if current_vram <= 0:
                continue
            if required_free_mb > 0:
                lane_tp = int(lane.tensor_parallel_size or 0) or 1
                if lane_tp <= 1 and profile is not None:
                    lane_tp = max(int(profile.tensor_parallel_size or 0), 1)
                target_tp = int(target.tensor_parallel_size or 0) or 1
                if target_tp <= 1:
                    target_profile = profiles.get(target.model_name)
                    if target_profile is not None:
                        target_tp = max(int(target_profile.tensor_parallel_size or 0), 1)
                per_gpu_freed = current_vram / lane_tp
                per_gpu_needed = required_free_mb / target_tp
                if per_gpu_freed < per_gpu_needed:
                    continue

            if min_wait is None or drain_remaining < min_wait:
                min_wait = drain_remaining

        return min_wait

    def _lane_exists_in_runtime(self, provider_id: int, lane_id: str) -> bool:
        if self._registry is not None:
            snap = self._registry.peek_runtime_snapshot(provider_id)
            lanes = ((snap or {}).get("runtime") or {}).get("lanes") or []
            if isinstance(lanes, list):
                for lane in lanes:
                    if isinstance(lane, dict) and str(lane.get("lane_id") or "") == lane_id:
                        return True
        return any(lane.lane_id == lane_id for lane in self._safe_get_lanes(provider_id))

    # ------------------------------------------------------------------
    # GPU-aware eviction helpers
    # ------------------------------------------------------------------

    def _effective_demand(
        self,
        model_name: str,
        provider_id: int | None = None,
        lanes: list | None = None,
        lane: Optional[LaneSchedulerSignals] = None,
    ) -> float:
        """Demand score + QUEUE_WEIGHT × queue depth.

        Uses scheduler queue depth (via _get_queue_depth_for_model) when
        provider_id and lanes are available — this captures requests waiting
        in the Logos scheduler queue, critical for sleeping/cold models where
        lane queue_waiting is 0.  Falls back to lane.queue_waiting for callers
        that don't have provider context.
        """
        base = self._demand.get_score(model_name)
        if provider_id is not None and lanes is not None:
            queue = float(self._get_queue_depth_for_model(
                provider_id, model_name, lanes,
            ))
        elif lane is not None:
            queue = float(lane.queue_waiting)
        else:
            queue = 0.0
        return base + self.QUEUE_WEIGHT * queue

    # ------------------------------------------------------------------
    # Anti-thrashing helpers
    # ------------------------------------------------------------------

    def _get_effective_tenure(self, was_cold_loaded: bool = False) -> float:
        """Return minimum lane tenure (uniform — sleep is cheap)."""
        return self.LANE_MIN_TENURE_SECONDS

    def _get_queue_depth_for_model(
        self,
        provider_id: int,
        model_name: str,
        lanes: list,
    ) -> int:
        """Total demand for a model: lane active/queued + scheduler queue.

        Combines three populations:
        - active_requests: currently being processed by the backend
        - queue_waiting: queued inside vLLM's batching system
        - scheduler queue: requests waiting in the Logos scheduler queue
          (critical for sleeping models where active/queue_waiting are both 0)
        """
        lane_total = 0
        for lane in lanes:
            if lane.model_name == model_name:
                lane_total += lane.active_requests + int(lane.queue_waiting)
        scheduler_queue = self._facade.get_scheduler_queue_depth_by_model_name(
            model_name, provider_id,
        )
        return lane_total + scheduler_queue

    def _retry_pending_capacity(self, provider_id: int) -> None:
        """Re-attempt capacity preparation for models whose earlier trigger failed.

        Called after any successful reclaim action confirms — freed VRAM may
        now be sufficient for a previously-blocked wake/load.
        """
        now = time.time()
        to_retry: list[str] = []
        stale: list[str] = []

        for model_name, (pid, registered_at) in list(self._pending_capacity.items()):
            if pid != provider_id:
                continue
            # Expire after 60s — the planner cycle will handle it
            if now - registered_at > 60.0:
                stale.append(model_name)
                continue
            # Already resolved — lane is now available
            lanes = self._safe_get_lanes(provider_id)
            has_ready_lane = any(
                l.model_name == model_name
                and l.runtime_state in ("loaded", "running")
                and l.sleep_state != "sleeping"
                for l in lanes
            )
            if has_ready_lane:
                stale.append(model_name)
                continue
            to_retry.append(model_name)

        for m in stale:
            self._pending_capacity.pop(m, None)

        for m in to_retry:
            self._pending_capacity.pop(m, None)
            logger.info("Retrying pending capacity for %s on provider %d", m, provider_id)
            asyncio.create_task(
                self.prepare_lane_for_request(provider_id, m, timeout_seconds=30.0)
            )

    def _get_per_gpu_free(self, provider_id: int) -> dict[int, float]:
        """Return {gpu_id: free_mb} from the worker runtime snapshot.

        Subtracts in-flight VRAM ledger commitments per GPU.
        Returns an empty dict when no device info is available.
        """
        if self._registry is None:
            return {}
        snap = self._registry.peek_runtime_snapshot(provider_id)
        if snap is None:
            return {}
        devices_info = (snap.get("runtime") or {}).get("devices") or {}
        device_list = devices_info.get("devices") or []
        if not isinstance(device_list, list):
            return {}
        result: dict[int, float] = {}
        for dev in device_list:
            if not isinstance(dev, dict):
                continue
            raw_id = dev.get("device_id")
            try:
                gid = int(raw_id)
            except (TypeError, ValueError):
                continue
            free_mb = float(dev.get("memory_free_mb") or 0.0)
            if free_mb <= 0:
                total_mb = float(dev.get("memory_total_mb") or 0.0)
                used_mb = float(dev.get("memory_used_mb") or 0.0)
                if total_mb > 0:
                    free_mb = max(total_mb - used_mb, 0.0)
            free_mb = self._vram_ledger.get_gpu_effective_available_mb(
                provider_id, gid, free_mb,
            )
            result[gid] = free_mb
        return result

    def _find_eviction_set(
        self,
        provider_id: int,
        required_gpus: frozenset[int],
        per_gpu_deficit: dict[int, float],
        lanes: List[LaneSchedulerSignals],
        profiles: dict[str, "ModelProfile"],
    ) -> Optional[list[tuple[LaneSchedulerSignals, str, float]]]:
        """Find the minimum-score set of lanes to evict to cover per_gpu_deficit.

        Returns a list of (lane, action, effective_demand) tuples, or None if
        the deficit cannot be covered even evicting all eligible candidates.

        Each entry's action is "sleep_l1" (preferred, KV freed) or "stop"
        (when sleeping won't free enough or model has no sleep support).

        GPU-aware: each candidate only contributes freed VRAM to the GPUs it
        occupies that overlap with required_gpus.  The constraint is satisfied
        when every GPU in required_gpus has had its deficit covered.

        Algorithm: greedy by effective_demand ascending (evict cheapest first).
        """
        # Nothing to do if deficit is already met
        if all(d <= 0 for d in per_gpu_deficit.values()):
            return []

        # Build candidate list: idle/sleeping lanes on overlapping GPUs
        now = time.time()

        class _Cand:
            __slots__ = ("lane", "action", "eff_demand", "freed_per_gpu")
            def __init__(self, lane, action, eff_demand, freed_per_gpu):
                self.lane = lane
                self.action = action
                self.eff_demand = eff_demand
                self.freed_per_gpu: dict[int, float] = freed_per_gpu

        candidates: list[_Cand] = []
        for lane in lanes:
            # Skip if lane has active traffic or scheduler queue demand
            total_demand = self._get_queue_depth_for_model(provider_id, lane.model_name, lanes)
            if lane.active_requests > 0 or lane.queue_waiting > 0 or total_demand > 0:
                continue
            if self._lane_is_in_load_cooldown(provider_id, lane.lane_id, now=now):
                continue

            lane_gpus = frozenset(self._parse_gpu_device_ids(lane.gpu_devices))
            # Determine GPU overlap with required set
            if required_gpus:
                overlap = lane_gpus & required_gpus
            else:
                overlap = lane_gpus  # no constraint → all GPUs count

            if not overlap and required_gpus:
                continue  # This lane is on disjoint GPUs — useless

            profile = profiles.get(lane.model_name)
            tp = max(len(lane_gpus), 1)

            # Prefer sleep (less disruptive); fall back to stop
            if lane.is_vllm and lane.runtime_state in ("loaded", "running") and lane.sleep_state == "awake":
                action = "sleep_l1"
                current_mb = float(lane.effective_vram_mb or 0.0)
                if current_mb <= 0 and profile:
                    current_mb = self._estimate_model_loaded_vram(profile)
                residual_mb = float(profile.sleeping_residual_mb or 0.0) if profile else 0.0
                freed_total = max(current_mb - residual_mb, 0.0)
            elif lane.runtime_state in ("sleeping",) and lane.sleep_state == "sleeping":
                action = "stop"
                residual_mb = float(lane.effective_vram_mb or 0.0)
                if residual_mb <= 0 and profile:
                    residual_mb = float(profile.sleeping_residual_mb or 0.0)
                # Sleeping vLLM lanes underreport GPU usage via --query-compute-apps:
                # the CUDA allocator keeps model weights in its pool, invisible to
                # per-process queries.  Use profile base_residency as a floor.
                if lane.is_vllm and profile is not None:
                    base_residency = float(getattr(profile, "base_residency_mb", 0) or 0)
                    if base_residency > residual_mb:
                        residual_mb = base_residency
                freed_total = residual_mb
            else:
                continue  # busy, cold, stopped, or starting — not evictable

            if freed_total <= 0:
                continue

            # Distribute freed VRAM across the GPUs this lane occupies
            freed_per_gpu_val = freed_total / tp
            freed_per_gpu: dict[int, float] = {
                g: freed_per_gpu_val for g in (overlap if required_gpus else lane_gpus)
            }

            eff = self._effective_demand(lane.model_name, provider_id, lanes, lane)
            candidates.append(_Cand(lane, action, eff, freed_per_gpu))

        # Sort by (action_cost, effective_demand) ascending: prefer sleep over
        # stop at any demand level, then sacrifice least-valued models first.
        # Stopping a sleeping lane is destructive (requires cold load to recover),
        # while sleeping a loaded lane is cheap (fast wake, ~2-3s).
        _action_cost = {"sleep_l1": 0, "sleep_l2": 0, "stop": 1}
        candidates.sort(key=lambda c: (_action_cost.get(c.action, 2), c.eff_demand))

        logger.info(
            "Eviction candidates for provider=%s gpus=%s deficit=%s: [%s]",
            provider_id,
            sorted(required_gpus) if required_gpus else "any",
            {g: f"{d:.0f}MB" for g, d in per_gpu_deficit.items()},
            ", ".join(
                f"{c.lane.lane_id}(eff={c.eff_demand:.2f}, action={c.action}, "
                f"free={sum(c.freed_per_gpu.values()):.0f}MB)"
                for c in candidates
            ) if candidates else "none",
        )

        # Greedy covering: pick candidates until all per-GPU deficits are met
        remaining: dict[int, float] = dict(per_gpu_deficit)
        chosen: list[tuple[LaneSchedulerSignals, str, float]] = []

        for cand in candidates:
            if all(v <= 0 for v in remaining.values()):
                break
            # Only include if it helps at least one still-deficient GPU
            useful = any(
                remaining.get(g, 0) > 0
                for g in cand.freed_per_gpu
            )
            if not useful:
                continue
            chosen.append((cand.lane, cand.action, cand.eff_demand))
            for g, freed in cand.freed_per_gpu.items():
                if g in remaining:
                    remaining[g] = max(0.0, remaining[g] - freed)

        if all(v <= 0 for v in remaining.values()):
            return chosen
        logger.info(
            "Eviction set INSUFFICIENT for provider=%s: remaining deficit=%s after %d candidates",
            provider_id, {g: f"{d:.0f}MB" for g, d in remaining.items() if d > 0}, len(chosen),
        )
        return None  # couldn't cover the deficit

    def _pick_cold_load_placement(
        self,
        provider_id: int,
        load_cost_mb: float,
        tp: int,
        lanes: List[LaneSchedulerSignals],
        profiles: dict[str, "ModelProfile"],
    ) -> Optional[tuple[frozenset[int], list[tuple[LaneSchedulerSignals, str, float]]]]:
        """Find the best GPU set for a cold load and its required eviction set.

        Tries every combination of `tp` GPUs.  For each combination, computes
        the per-GPU deficit and calls _find_eviction_set.  Returns the placement
        whose eviction set has the lowest maximum effective-demand score (i.e. the
        one that sacrifices the least-valuable models).

        Returns (gpu_set, eviction_set) or None if no feasible placement exists.
        """
        per_gpu_needed = load_cost_mb / max(tp, 1)
        per_gpu_free = self._get_per_gpu_free(provider_id)

        if not per_gpu_free:
            # No per-GPU info — fall back to aggregate check with no GPU constraint
            capacity = self._safe_get_capacity(provider_id)
            available = float(capacity.available_vram_mb) if capacity else 0.0
            deficit = max(0.0, load_cost_mb * self.VRAM_SAFETY_MARGIN - available)
            if deficit <= 0:
                return frozenset(), []
            eviction_set = self._find_eviction_set(
                provider_id, frozenset(), {}, lanes, profiles,
            )
            # Can't do proper per-GPU accounting; return aggregate result
            if eviction_set is None:
                return None
            return frozenset(), eviction_set

        all_gpu_ids = sorted(per_gpu_free.keys())
        if len(all_gpu_ids) < tp:
            return None  # Not enough GPUs

        best: Optional[tuple[frozenset[int], list, float]] = None  # (gpus, eviction, max_score)

        for gpu_combo in combinations(all_gpu_ids, tp):
            gpu_set = frozenset(gpu_combo)
            per_gpu_deficit: dict[int, float] = {}
            for g in gpu_set:
                free = per_gpu_free.get(g, 0.0)
                deficit = max(0.0, per_gpu_needed * self.VRAM_SAFETY_MARGIN - free)
                if deficit > 0:
                    per_gpu_deficit[g] = deficit

            eviction_set = self._find_eviction_set(
                provider_id, gpu_set, per_gpu_deficit, lanes, profiles,
            )
            if eviction_set is None:
                continue  # Can't cover this GPU combo

            max_score = max((s for _, _, s in eviction_set), default=0.0)
            if best is None or max_score < best[2]:
                best = (gpu_set, eviction_set, max_score)

        if best is None:
            return None
        return best[0], best[1]

    @staticmethod
    def _parse_gpu_device_ids(gpu_devices: str | None) -> tuple[int, ...]:
        if not gpu_devices:
            return ()
        result: set[int] = set()
        for part in str(gpu_devices).split(","):
            part = part.strip()
            if part.isdigit():
                result.add(int(part))
        return tuple(sorted(result))

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
        """Compute background sleep actions for idle lanes.

        The background planner never stops lanes just because they have been idle.
        Lane removal is only done by explicit reclaim when another request/load
        actually needs the VRAM.
        """
        now = time.time()
        actions = []

        for lane in lanes:
            key = self._lane_key(provider_id, lane.lane_id)
            idle_start = self._lane_idle_since.get(key)
            sleep_start = self._lane_sleep_since.get(key)
            sleep_level = self._lane_sleep_level.get(key, 0)
            idle_seconds = (now - idle_start) if idle_start is not None else None
            sleep_seconds = (now - sleep_start) if sleep_start is not None else None

            if idle_seconds is not None or sleep_seconds is not None:
                logger.info(
                    "Idle check lane=%s model=%s state=%s/%s idle=%.0fs sleep=%.0fs sleep_level=%d",
                    lane.lane_id, lane.model_name, lane.runtime_state, lane.sleep_state,
                    idle_seconds or 0.0, sleep_seconds or 0.0, sleep_level,
                )

            # Skip lanes that are already stopped/error
            if lane.runtime_state in ("stopped", "error", "cold"):
                continue

            # Only vLLM lanes support sleep
            if not lane.is_vllm:
                continue

            # Sleep L2 after 10 minutes of observed L1 sleep
            if (
                lane.sleep_state == "sleeping"
                and lane.active_requests == 0
                and self._get_queue_depth_for_model(provider_id, lane.model_name, lanes) == 0
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
                and self._get_queue_depth_for_model(provider_id, lane.model_name, lanes) == 0
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

    def _would_evict_cooled_lane(
        self,
        provider_id: int,
        model_name: str,
        profiles: dict[str, "ModelProfile"],
        capacity,
    ) -> bool:
        """Check if loading a model would require evicting a lane still in cooldown.

        Only blocks planner-initiated loads. Request-time cold loads bypass this.
        Uses full base+KV cost so vLLM models are not under-estimated.
        """
        if capacity is None or self._load_cooldown_seconds <= 0:
            return False

        profile = profiles.get(model_name)
        if profile is None:
            return False  # Can't estimate, don't block
        estimated_mb = self._estimate_model_loaded_vram(profile)

        available = float(capacity.available_vram_mb)
        if available >= estimated_mb * self.VRAM_SAFETY_MARGIN:
            return False  # Enough free VRAM, no eviction needed

        # Would need eviction — check if any candidate lane is in cooldown
        now = time.time()
        try:
            lanes = self._facade.get_all_provider_lane_signals(provider_id)
        except Exception:
            return False
        for lane in lanes:
            if lane.model_name == model_name:
                continue
            if lane.active_requests > 0:
                continue
            if self._lane_is_in_load_cooldown(provider_id, lane.lane_id, now=now):
                return True
        return False

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
        """Compute wake/load actions based on demand patterns.

        Decision tree for both wake and load:

        1.  Compute effective_demand = score + QUEUE_WEIGHT × queue_waiting.
        2.  Find the minimum-score eviction set needed to free enough GPU memory.
        3a. Eviction set is EMPTY  → resources freely available; act on any demand
            above the floor (DEMAND_WAKE_FLOOR / DEMAND_LOAD_FLOOR).  This covers
            the common cases: plenty of VRAM, sleeping lane, or a cold empty worker.
        3b. Eviction set is NON-EMPTY → resources are contested; only act when
            effective_demand(target) > max(eviction_set_demand) × RATIO.
        3c. Eviction set is None     → can't make room at all; skip this model.

        When an eviction set is non-empty, the sleep/stop actions for the victims
        are prepended to the batch so _validate_vram_budget sees freed VRAM before
        the load/wake consumes it.
        """
        if self._registry.peek_runtime_snapshot(provider_id) is None:
            logger.debug(
                "Skipping demand actions for provider=%s: no active logosnode runtime snapshot",
                provider_id,
            )
            return []

        # If the request-time path has an in-flight VRAM reservation (cold load,
        # wake) for this provider, back off entirely.  The VRAM ledger subtracts
        # reserved memory from available-VRAM, causing the planner to see
        # artificially low free VRAM and emit spurious evictions (e.g. stopping a
        # sleeping lane that has plenty of room to coexist with the incoming model).
        # The planner will retry next cycle once the reservation clears.
        #
        # We check both the ledger (covers the load/wake phase after the capacity
        # lock is released) and the lock itself (covers the reclaim phase before
        # the reservation is created).
        # TODO: per-lane awareness instead of full-provider skip — the current
        #       check blocks planning for ALL models on the provider even when only
        #       one lane is being loaded.  A finer-grained approach would track
        #       which model/lane the in-flight operation targets and only skip
        #       planning decisions that conflict with it.
        committed = self._vram_ledger.get_committed_mb(provider_id)
        capacity_locked = self._provider_capacity_lock(provider_id).locked()
        if committed > 0 or capacity_locked:
            logger.info(
                "Skipping demand planning for provider=%s: "
                "in-flight VRAM reservation (committed=%.0fMB locked=%s)",
                provider_id, committed, capacity_locked,
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

        lanes_by_model: dict[str, List[LaneSchedulerSignals]] = {}
        for lane in lanes:
            lanes_by_model.setdefault(lane.model_name, []).append(lane)

        planned_models: set[str] = set()
        # Track which lanes have already been claimed as eviction victims this
        # cycle so we don't evict the same lane twice for two different loads.
        claimed_victims: set[str] = set()

        # Build candidate list: ranked demand models + any capability model
        # with queued scheduler requests (covers cold models whose demand
        # decayed but still have requests waiting in the scheduler queue).
        candidates: list[tuple[str, float]] = list(ranked)
        ranked_names = {m for m, _ in ranked}
        for cap_model in capabilities - ranked_names:
            sq = self._facade.get_scheduler_queue_depth_by_model_name(cap_model, provider_id)
            if sq > 0:
                candidates.append((cap_model, 0.0))

        for model_name, score in candidates:
            if capabilities and model_name not in capabilities:
                continue
            model_lanes = lanes_by_model.get(model_name, [])
            eff = self._effective_demand(model_name, provider_id, lanes)
            logger.info(
                "Demand eval model=%s score=%.2f eff=%.2f caps=%s lanes=%d",
                model_name, score, eff,
                "yes" if (not capabilities or model_name in capabilities) else "NO-cap",
                len(model_lanes),
            )

            # ── WAKE: sleeping lane exists ────────────────────────────────────
            sleeping_lanes = [
                l for l in model_lanes
                if l.sleep_state == "sleeping"
                and not self._lane_is_in_wake_failure_cooldown(provider_id, l.lane_id)
            ]
            if sleeping_lanes:
                target = sleeping_lanes[0]
                profile = profiles.get(model_name)

                # Per-GPU deficit on the GPUs the sleeping lane occupies
                target_gpus = frozenset(self._parse_gpu_device_ids(target.gpu_devices))
                tp = max(len(target_gpus), 1)
                loaded_mb = self._estimate_model_loaded_vram(profile) if profile else 4096.0
                residual_mb = float(profile.sleeping_residual_mb or 0.0) if profile else 0.0
                wake_cost_per_gpu = max(loaded_mb - residual_mb, 0.0) / tp

                per_gpu_free = self._get_per_gpu_free(provider_id)
                per_gpu_deficit: dict[int, float] = {}
                if target_gpus and per_gpu_free:
                    for g in target_gpus:
                        free = per_gpu_free.get(g, 0.0)
                        deficit = max(0.0, wake_cost_per_gpu * self.VRAM_SAFETY_MARGIN - free)
                        if deficit > 0:
                            per_gpu_deficit[g] = deficit
                else:
                    # No per-GPU info: fall back to aggregate
                    avail = float(capacity.available_vram_mb) if capacity else 0.0
                    deficit = max(0.0, (loaded_mb - residual_mb) * self.VRAM_SAFETY_MARGIN - avail)
                    if deficit > 0:
                        per_gpu_deficit[-1] = deficit  # sentinel for aggregate

                logger.info(
                    "Wake candidate model=%s lane=%s gpus=%s loaded_mb=%.0f residual_mb=%.0f "
                    "wake_cost_per_gpu=%.0f deficit=%s eviction_needed=%s",
                    model_name, target.lane_id, target.gpu_devices,
                    loaded_mb, residual_mb, wake_cost_per_gpu,
                    {g: f"{d:.0f}MB" for g, d in per_gpu_deficit.items()} if per_gpu_deficit else "none",
                    "yes" if per_gpu_deficit else "no",
                )

                # Remove already-claimed victims from eviction candidates
                available_lanes = [l for l in lanes if l.lane_id not in claimed_victims]
                eviction_set = self._find_eviction_set(
                    provider_id, target_gpus, per_gpu_deficit, available_lanes, profiles,
                )

                if eviction_set is None:
                    logger.debug("Skipping wake of %s: cannot free enough GPU memory", model_name)
                elif not eviction_set:
                    # Plenty of VRAM — act on floor score.
                    # Bypass floor when there are actual requests in scheduler queue.
                    has_queued = self._get_queue_depth_for_model(provider_id, model_name, lanes) > 0
                    if eff >= self.DEMAND_WAKE_FLOOR or has_queued:
                        actions.append(CapacityPlanAction(
                            action="wake",
                            provider_id=provider_id,
                            lane_id=target.lane_id,
                            model_name=model_name,
                            reason=f"Demand score={score:.2f}, eff={eff:.2f} ≥ floor={self.DEMAND_WAKE_FLOOR}; VRAM free",
                        ))
                        planned_models.add(model_name)
                else:
                    # Contention — target must outweigh the eviction set
                    max_victim_score = max(s for _, _, s in eviction_set)
                    if eff > max_victim_score * self.WAKE_COMPETITIVE_RATIO:
                        for vlane, vaction, _ in eviction_set:
                            if vlane.lane_id in claimed_victims:
                                continue
                            claimed_victims.add(vlane.lane_id)
                            actions.append(CapacityPlanAction(
                                action=vaction,
                                provider_id=provider_id,
                                lane_id=vlane.lane_id,
                                model_name=vlane.model_name,
                                reason=(
                                    f"Evicted for {model_name} wake "
                                    f"(target_eff={eff:.2f} > victim={max_victim_score:.2f}×{self.WAKE_COMPETITIVE_RATIO})"
                                ),
                            ))
                        actions.append(CapacityPlanAction(
                            action="wake",
                            provider_id=provider_id,
                            lane_id=target.lane_id,
                            model_name=model_name,
                            reason=(
                                f"Demand eff={eff:.2f} > eviction_max={max_victim_score:.2f}"
                                f"×{self.WAKE_COMPETITIVE_RATIO} (competitive wake)"
                            ),
                        ))
                        planned_models.add(model_name)
                    else:
                        logger.debug(
                            "Skipping wake of %s: eff=%.2f not competitive vs eviction_max=%.2f×%.1f",
                            model_name, eff, max_victim_score, self.WAKE_COMPETITIVE_RATIO,
                        )
                continue  # sleeping lane found; don't also try cold load

            # ── COLD LOAD: no usable lane exists ─────────────────────────────
            active_lanes = [
                l for l in model_lanes
                if l.runtime_state not in {"stopped", "error"}
                and l.sleep_state != "sleeping"  # sleeping handled above
            ]
            if active_lanes:
                continue  # has a usable (non-sleeping, non-stopped) lane

            if self._would_evict_cooled_lane(provider_id, model_name, profiles, capacity):
                logger.debug(
                    "Skipping planner load of %s: would evict a recently loaded lane (cooldown=%.0fs)",
                    model_name, self._load_cooldown_seconds,
                )
                continue

            profile = profiles.get(model_name)
            tp = 1
            if profile and profile.tensor_parallel_size and int(profile.tensor_parallel_size) > 1:
                tp = int(profile.tensor_parallel_size)
            load_cost = self._estimate_model_loaded_vram(profile) if profile else 4096.0
            is_calibrated = (
                profile is not None
                and profile.residency_source in ("calibrated", "measured")
            )
            if tp > 1 and not is_calibrated:
                # Calibrated base_residency already includes TP overhead from
                # the actual measured run.  Only add the estimate for unknown models.
                load_cost *= (1.0 + self.TP_OVERHEAD_RATIO)

            available_lanes = [l for l in lanes if l.lane_id not in claimed_victims]
            placement = self._pick_cold_load_placement(
                provider_id, load_cost, tp, available_lanes, profiles,
            )

            if placement is None:
                logger.debug("Skipping load of %s: cannot find feasible GPU placement", model_name)
                continue

            _, eviction_set = placement
            logger.info(
                "Load candidate model=%s tp=%d load_cost=%.0fMB placement=%s eviction_needed=%s",
                model_name, tp, load_cost,
                "feasible" if placement is not None else "INFEASIBLE",
                ("yes: " + ", ".join(f"{v.lane_id}({a})" for v, a, _ in eviction_set)) if eviction_set else "no",
            )

            if not eviction_set:
                # Resources freely available — act on floor score.
                # Bypass floor when there are actual requests waiting in the
                # scheduler queue: a queued request IS real demand even if
                # the DemandTracker score has decayed.
                has_queued = self._get_queue_depth_for_model(provider_id, model_name, lanes) > 0
                if eff < self.DEMAND_LOAD_FLOOR and not has_queued:
                    continue
                if not self._passes_minimum_load_feasibility(model_name, profile, capacity, provider_id=provider_id):
                    continue
                lane_id = self._planner_lane_id(model_name)
                actions.append(CapacityPlanAction(
                    action="load",
                    provider_id=provider_id,
                    lane_id=lane_id,
                    model_name=model_name,
                    params=self._build_load_params(model_name, lane_id, profile, capacity, provider_id),
                    reason=f"Demand eff={eff:.2f} ≥ floor={self.DEMAND_LOAD_FLOOR}; VRAM free",
                ))
                planned_models.add(model_name)
            else:
                # Contention — target must outweigh the eviction set
                max_victim_score = max(s for _, _, s in eviction_set)
                if eff > max_victim_score * self.LOAD_COMPETITIVE_RATIO:
                    lane_id = self._planner_lane_id(model_name)
                    for vlane, vaction, _ in eviction_set:
                        if vlane.lane_id in claimed_victims:
                            continue
                        claimed_victims.add(vlane.lane_id)
                        actions.append(CapacityPlanAction(
                            action=vaction,
                            provider_id=provider_id,
                            lane_id=vlane.lane_id,
                            model_name=vlane.model_name,
                            reason=(
                                f"Evicted for {model_name} load "
                                f"(target_eff={eff:.2f} > victim={max_victim_score:.2f}×{self.LOAD_COMPETITIVE_RATIO})"
                            ),
                        ))
                    if not self._passes_minimum_load_feasibility(model_name, profile, capacity, provider_id=provider_id):
                        continue
                    actions.append(CapacityPlanAction(
                        action="load",
                        provider_id=provider_id,
                        lane_id=lane_id,
                        model_name=model_name,
                        params=self._build_load_params(model_name, lane_id, profile, capacity, provider_id),
                        reason=(
                            f"Demand eff={eff:.2f} > eviction_max={max_victim_score:.2f}"
                            f"×{self.LOAD_COMPETITIVE_RATIO} (competitive load)"
                        ),
                    ))
                    planned_models.add(model_name)
                else:
                    logger.debug(
                        "Skipping load of %s: eff=%.2f not competitive vs eviction_max=%.2f×%.1f",
                        model_name, eff, max_victim_score, self.LOAD_COMPETITIVE_RATIO,
                    )

        # ── CAPABILITY SEEDING: empty worker ─────────────────────────────────
        # Cold worker with zero lanes but declared capabilities: load any in-demand
        # model immediately (eviction_set will always be empty → floor check only).
        if not lanes:
            for model_name in capabilities:
                if model_name in planned_models:
                    continue
                eff = self._effective_demand(model_name, provider_id, lanes)
                if eff < self.DEMAND_LOAD_FLOOR:
                    continue
                profile = profiles.get(model_name)
                if not self._passes_minimum_load_feasibility(model_name, profile, capacity, provider_id=provider_id):
                    continue
                lane_id = self._planner_lane_id(model_name)
                actions.append(CapacityPlanAction(
                    action="load",
                    provider_id=provider_id,
                    lane_id=lane_id,
                    model_name=model_name,
                    params=self._build_load_params(model_name, lane_id, profile, capacity, provider_id),
                    reason=f"Capability seeding: worker declares {model_name}, eff={eff:.2f}",
                ))

        return actions

    def _compute_demand_drain_actions(
        self, provider_id: int, lanes: List[LaneSchedulerSignals],
    ) -> List[CapacityPlanAction]:
        """Return stop actions to evict busy lanes for starving high-demand models.

        Runs in the background planner cycle. Detects when a model has
        accumulated demand but cannot be served because VRAM is held by a
        lower-demand model with active requests. Returns a committed stop action
        so _execute_action drains and stops the lane atomically.
        """
        ranked = self._demand.get_ranked_models()
        profiles = self._safe_get_profiles(provider_id)
        actions: list[CapacityPlanAction] = []
        try:
            capabilities = set(self._facade.get_worker_capabilities(provider_id))
        except Exception:
            capabilities = set()

        lanes_by_model: dict[str, list[LaneSchedulerSignals]] = {}
        for lane in lanes:
            lanes_by_model.setdefault(lane.model_name, []).append(lane)

        for model_name, score in ranked:
            if score < self.DRAIN_DEMAND_SCORE_THRESHOLD:
                continue
            # Skip models not served by this provider — demand from unknown/
            # misconfigured model names (e.g. provider-type strings) would
            # otherwise trigger spurious drain evaluations every cycle.
            if capabilities and model_name not in capabilities:
                continue
            model_lanes = lanes_by_model.get(model_name, [])
            has_usable = any(
                l.runtime_state in ("loaded", "running")
                and l.sleep_state != "sleeping"
                for l in model_lanes
            )
            logger.info(
                "Drain eval model=%s score=%.2f has_usable_lane=%s",
                model_name, score, has_usable,
            )
            if has_usable:
                continue  # Model already has a serving lane

            # This model needs VRAM — check if any busy lane should be stopped
            # Build a synthetic target for the eviction check
            synthetic_target = LaneSchedulerSignals(
                lane_id=self._planner_lane_id(model_name),
                model_name=model_name,
                runtime_state="cold",
                sleep_state="unsupported",
                is_vllm=True,
                active_requests=0,
                queue_waiting=0.0,
                requests_running=0.0,
                gpu_cache_usage_percent=None,
                ttft_p95_seconds=0.0,
                effective_vram_mb=0.0,
                num_parallel=0,
                gpu_devices=None,
            )
            # Inherit GPU placement from sleeping lane of same model if exists
            sleeping_lane = next(
                (l for l in model_lanes if l.sleep_state == "sleeping"),
                None,
            )
            if sleeping_lane and sleeping_lane.gpu_devices:
                synthetic_target = LaneSchedulerSignals(
                    lane_id=synthetic_target.lane_id,
                    model_name=model_name,
                    runtime_state="cold",
                    sleep_state="unsupported",
                    is_vllm=True,
                    active_requests=0,
                    queue_waiting=0.0,
                    requests_running=0.0,
                    gpu_cache_usage_percent=None,
                    ttft_p95_seconds=0.0,
                    effective_vram_mb=0.0,
                    num_parallel=0,
                    gpu_devices=sleeping_lane.gpu_devices,
                )

            for lane in lanes:
                if lane.model_name == model_name:
                    continue
                if lane.active_requests == 0 and lane.queue_waiting == 0:
                    continue  # Already idle — normal reclaim handles this
                if self._should_initiate_drain(
                    provider_id, lane, synthetic_target, profiles,
                ):
                    current_vram = float(lane.effective_vram_mb or 0.0)
                    if current_vram <= 0:
                        profile = profiles.get(lane.model_name)
                        if profile is not None:
                            current_vram = self._estimate_model_loaded_vram(profile)
                    if current_vram > 0:
                        # Prefer sleep over stop: keeps model warm for fast wake
                        lane_profile = profiles.get(lane.model_name)
                        sleeping_residual = float(
                            getattr(lane_profile, "sleeping_residual_mb", 0) or 0
                        ) if lane_profile else 0.0
                        if sleeping_residual > 0:
                            drain_action = "sleep_l1"
                            drain_reason = f"Demand drain: sleep for {model_name}"
                            drain_params = {}
                        else:
                            drain_action = "stop"
                            drain_reason = f"Demand drain: stop for {model_name}"
                            drain_params = {"_stop_penalty": 1}
                        actions.append(CapacityPlanAction(
                            action=drain_action,
                            provider_id=provider_id,
                            lane_id=lane.lane_id,
                            model_name=lane.model_name,
                            params=drain_params,
                            reason=drain_reason,
                        ))
                        logger.info(
                            "Drain initiated: %s lane=%s model=%s (vram=%.0fMB) for starving model=%s score=%.2f",
                            drain_action, lane.lane_id, lane.model_name, current_vram, model_name, score,
                        )
                    break  # Only one lane at a time per cycle

        return actions

    def _compute_preemptive_sleep_actions(
        self, provider_id: int, lanes: List[LaneSchedulerSignals]
    ) -> List[CapacityPlanAction]:
        """Proactively load stopped models into sleeping state to pre-warm them.

        Scenario: deepseek-8B was previously loaded here and its sleeping residual
        (~1.5 GB) is known, but its lane has since been stopped.  Rather than
        waiting for the next request and paying a ~45 s cold-start, we reload it
        now and immediately sleep it so future wakes cost only ~2 s.

        Pre-sleep idle awake neighbours first
        ─────────────────────────────────────
        If other vLLM lanes are awake (sleep_state=awake) with zero active requests,
        they are still holding their full KV-cache allocation in GPU memory.  vLLM
        profiles all free GPU memory at startup to decide how many KV blocks it can
        allocate, so those idle KV pools crowd out the new model's initialization
        even when the aggregate free-VRAM check passes.

        We therefore emit sleep_l1 actions for every idle awake lane *before* the
        new load — exactly what _next_request_reclaim_action does at request time.
        To avoid duplicating sleep actions already produced by _compute_idle_actions
        (which fires for lanes idle ≥ IDLE_SLEEP_L1 = 5 min), we only emit a
        pre-sleep here for lanes whose idle timer has not yet reached the threshold.

        VRAM accounting
        ───────────────
        Load cost uses _estimate_action_vram (base + KV), not estimate_vram_mb
        (base only), so the check matches what vLLM actually allocates.
        The budget calculation adds freed-by-pre-sleep to available VRAM, mirroring
        what _validate_vram_budget does when sleep and load share the same batch.
        Guard: ≥ 20 % of total VRAM must remain free after the load settles
        (net cost = sleeping residual, not full load size).
        """
        profiles = self._safe_get_profiles(provider_id)
        capacity = self._safe_get_capacity(provider_id)
        if not profiles or capacity is None:
            return []

        total_vram = float(capacity.total_vram_mb)
        available_vram = float(capacity.available_vram_mb)
        if total_vram <= 0:
            return []

        if available_vram / total_vram < self.PREEMPTIVE_SLEEP_MIN_FREE_VRAM_RATIO:
            return []

        active_models = {lane.model_name for lane in lanes}

        # Candidates: stopped models with a known sleeping residual (vLLM only).
        candidates: list[tuple[float, str, ModelProfile]] = []
        for model_name, profile in profiles.items():
            if model_name in active_models:
                continue
            if not (profile.sleeping_residual_mb and profile.sleeping_residual_mb > 0):
                continue
            if profile.engine != "vllm":
                continue
            candidates.append((self._demand.get_score(model_name), model_name, profile))

        if not candidates:
            return []

        candidates.sort(key=lambda c: c[0], reverse=True)
        # Don't preemptively load models with zero demand — loading a model nobody
        # has asked for can trigger pre-sleep of active lanes and cause 503s for
        # real traffic while the speculative load is in flight.
        candidates = [c for c in candidates if c[0] > 0]
        candidates = candidates[:self.PREEMPTIVE_SLEEP_MAX_MODELS]

        if candidates:
            logger.info(
                "Preemptive sleep candidates for provider=%s: %s",
                self._facade.get_provider_name(provider_id) or provider_id,
                ", ".join(f"{name}(demand={score:.2f}, residual={profile.sleeping_residual_mb:.0f}MB)"
                          for score, name, profile in candidates),
            )
        else:
            logger.info("Preemptive sleep: no candidates for provider=%s (no stopped models with known residual and demand>0)", self._facade.get_provider_name(provider_id) or provider_id)

        now = time.time()

        # Collect idle awake lanes that _compute_idle_actions will NOT already sleep
        # (those at or past the 5-min threshold are handled by the idle path and must
        # not be duplicated here, as double-crediting would corrupt the VRAM budget).
        pre_sleep_candidates: list[tuple[str, CapacityPlanAction, float]] = []
        for lane in lanes:
            if lane.active_requests > 0 or lane.queue_waiting > 0:
                continue
            if not lane.is_vllm:
                continue
            if lane.runtime_state not in ("loaded", "running"):
                continue
            if lane.sleep_state != "awake":
                continue
            if self._lane_is_in_load_cooldown(provider_id, lane.lane_id, now=now):
                continue
            # Skip lanes that the idle path will already sleep this cycle
            idle_start = self._lane_idle_since.get(self._lane_key(provider_id, lane.lane_id))
            idle_seconds = (now - idle_start) if idle_start is not None else 0.0
            if idle_seconds >= self.IDLE_SLEEP_L1:
                continue  # _compute_idle_actions covers this lane — no duplicate needed

            lane_profile = profiles.get(lane.model_name)
            current_vram = float(lane.effective_vram_mb or 0.0)
            if current_vram <= 0 and lane_profile is not None:
                current_vram = self._estimate_model_loaded_vram(lane_profile)
            lane_residual = float(lane_profile.sleeping_residual_mb or 0.0) if lane_profile else 0.0
            freed = max(current_vram - lane_residual, 0.0)
            if freed > 0:
                pre_sleep_candidates.append((
                    lane.lane_id,
                    CapacityPlanAction(
                        action="sleep_l1",
                        provider_id=provider_id,
                        lane_id=lane.lane_id,
                        model_name=lane.model_name,
                        reason=(
                            f"Preemptive reclaim: sleeping idle awake lane "
                            f"(idle={idle_seconds:.0f}s) before new load"
                        ),
                    ),
                    freed,
                ))

        freed_by_pre_sleep = sum(f for _, _, f in pre_sleep_candidates)
        actions: list[CapacityPlanAction] = []
        # Track remaining VRAM as if the pre-sleeps have already executed so
        # each candidate sees the same cleared headroom.
        remaining_vram = available_vram + freed_by_pre_sleep
        pre_sleeps_emitted = False

        for _score, model_name, profile in candidates:
            residual = float(profile.sleeping_residual_mb)
            lane_id = self._planner_lane_id(model_name)
            load_action = CapacityPlanAction(
                action="load",
                provider_id=provider_id,
                lane_id=lane_id,
                model_name=model_name,
                params=self._build_load_params(model_name, lane_id, profile, capacity, provider_id),
                reason=f"{self.PREEMPTIVE_LOAD_REASON} (residual={residual:.0f}MB)",
            )

            # Load cost: full base + KV — what vLLM actually allocates at startup.
            load_cost = self._estimate_action_vram(load_action, profile, capacity)
            logger.info(
                "Preemptive load check model=%s: load_cost=%.0fMB remaining_vram=%.0fMB "
                "margin=%.1f needed=%.0fMB residual=%.0fMB",
                model_name, load_cost, remaining_vram,
                self.VRAM_SAFETY_MARGIN, load_cost * self.VRAM_SAFETY_MARGIN, residual,
            )
            if remaining_vram < load_cost * self.VRAM_SAFETY_MARGIN:
                logger.info(
                    "Preemptive load SKIP model=%s: insufficient VRAM (have %.0fMB, need %.0fMB)",
                    model_name, remaining_vram, load_cost * self.VRAM_SAFETY_MARGIN,
                )
                continue
            # Net cost after load+sleep is just the residual; keep ≥ 20 % free.
            if (remaining_vram - residual) / total_vram < self.PREEMPTIVE_SLEEP_MIN_FREE_VRAM_RATIO:
                continue

            # Emit the pre-sleep actions once, before the first load, so the
            # execution batch sees sleep→free VRAM before load→consume VRAM.
            if not pre_sleeps_emitted:
                for _, sleep_action, _ in pre_sleep_candidates:
                    actions.append(sleep_action)
                pre_sleeps_emitted = True

            actions.append(load_action)
            actions.append(CapacityPlanAction(
                action="sleep_l1",
                provider_id=provider_id,
                lane_id=lane_id,
                model_name=model_name,
                params={"level": 1},
                reason=f"{self.PREEMPTIVE_SLEEP_REASON} (residual={residual:.0f}MB)",
            ))
            # Deduct the full load cost, not just the sleeping residual. Loads in the
            # same batch are executed sequentially with async confirmations — the sleep
            # of model A is not confirmed before the load of model B is dispatched, so
            # all loads in this batch are effectively concurrent from a VRAM perspective.
            # Using residual here would cause the planner to overcommit VRAM when two
            # large models are scheduled together (e.g. 14B takes 24 GB but only 1.4 GB
            # residual is deducted, making the 7B look like it fits too).
            remaining_vram -= load_cost

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

    async def _wait_for_provider(self, provider_id: int, deadline: float):
        """Wait for a provider to become available after a transient disconnect.

        Returns the CapacitySnapshot once available, or None if deadline exceeded.
        WebSocket keepalive timeouts cause brief (~3-5s) windows where the provider
        appears offline.  Instead of immediately failing all queued requests, poll
        until the provider reconnects or the deadline passes.
        """
        while True:
            remaining = deadline - time.time()
            if remaining <= self.PROVIDER_RECONNECT_POLL_SECONDS:
                logger.info(
                    "ensure_capacity provider=%s: provider offline, "
                    "%.1fs remaining — giving up",
                    provider_id, remaining,
                )
                return None
            logger.info(
                "ensure_capacity provider=%s: provider offline (transient disconnect?) "
                "— waiting %.1fs then retrying (%.0fs budget remaining)",
                provider_id, self.PROVIDER_RECONNECT_POLL_SECONDS, remaining,
            )
            await asyncio.sleep(self.PROVIDER_RECONNECT_POLL_SECONDS)
            capacity = self._safe_get_capacity(provider_id)
            if capacity is not None:
                logger.info(
                    "ensure_capacity provider=%s: provider back online "
                    "(available=%.0fMB)",
                    provider_id, float(capacity.available_vram_mb),
                )
                return capacity

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

    PROVIDER_RECONNECT_POLL_SECONDS = 2.0

    async def _ensure_request_capacity(
        self,
        *,
        provider_id: int,
        target: LaneSchedulerSignals,
        profile: Optional[ModelProfile],
        timeout_seconds: float,
    ) -> bool:
        # Convert to an absolute deadline once so accumulated sleeps reduce the
        # remaining budget correctly on every subsequent loop iteration.
        deadline = time.time() + timeout_seconds

        # Wait for provider to be available (handles transient WebSocket disconnects).
        capacity = self._safe_get_capacity(provider_id)
        if capacity is None:
            capacity = await self._wait_for_provider(provider_id, deadline)
            if capacity is None:
                return False

        target_action = CapacityPlanAction(
            action="wake" if target.runtime_state == "sleeping" else "load",
            provider_id=provider_id,
            lane_id=target.lane_id,
            model_name=target.model_name,
            params=self._build_load_params(target.model_name, target.lane_id, profile, capacity, provider_id),
            reason="Request-time lane preparation",
        )

        # Serialize capacity operations per provider.  Without this, concurrent
        # ensure_capacity calls for different models create competing VRAM
        # reservations that deadlock: each sees the other's in-flight reservation
        # as committed, driving available VRAM negative.  The lock ensures only
        # one capacity reclaim (drain → sleep/stop → load/wake) runs at a time
        # per provider, eliminating the race where freed VRAM from one drain is
        # "stolen" by a concurrent operation before the next drain step.
        lock = self._provider_capacity_lock(provider_id)
        remaining_for_lock = deadline - time.time()
        if remaining_for_lock <= 0:
            return False
        try:
            await asyncio.wait_for(lock.acquire(), timeout=remaining_for_lock)
        except asyncio.TimeoutError:
            logger.info(
                "ensure_capacity provider=%s model=%s: timed out waiting for "
                "provider capacity lock (%.1fs)",
                provider_id, target.model_name, remaining_for_lock,
            )
            return False

        try:
          while True:
            now = time.time()
            remaining = deadline - now
            if remaining <= 0:
                logger.info(
                    "ensure_capacity provider=%s model=%s: deadline exceeded, giving up",
                    provider_id, target.model_name,
                )
                return False

            capacity = self._safe_get_capacity(provider_id)
            if capacity is None:
                capacity = await self._wait_for_provider(provider_id, deadline)
                if capacity is None:
                    return False

            needed = self._estimate_action_vram(target_action, profile, capacity) * self.VRAM_SAFETY_MARGIN
            # Use ledger-aware available VRAM (subtracts in-flight reservations)
            raw_available = float(capacity.available_vram_mb)
            available = self._vram_ledger.get_effective_available_mb(
                provider_id, raw_available,
            )
            provider_ready = available >= needed
            shortfall = max(needed - available, 0.0)

            logger.info(
                "ensure_capacity provider=%s model=%s action=%s: "
                "needed=%.0fMB available=%.0fMB(raw=%.0fMB) provider_ready=%s shortfall=%.0fMB",
                provider_id, target.model_name, target_action.action,
                needed, available, raw_available, provider_ready, shortfall,
            )

            target_gpu_devices = target.gpu_devices
            if not target_gpu_devices and target_action.params:
                target_gpu_devices = target_action.params.get("gpu_devices")
            target_gpu_ids = self._parse_gpu_device_ids(target_gpu_devices)
            per_gpu_free = self._get_per_gpu_free(provider_id)
            if (
                target_gpu_ids
                and per_gpu_free is not None
                and all(dev in per_gpu_free for dev in target_gpu_ids)
            ):
                tp = len(target_gpu_ids)
                is_calibrated = (
                    profile is not None
                    and profile.residency_source in ("calibrated", "measured")
                )
                if tp > 1:
                    if is_calibrated:
                        # Calibrated base_residency is the measured total across
                        # all TP ranks — even split is accurate.
                        per_gpu_needed = needed / tp
                    else:
                        # Unknown model: TP rank 0 hosts API server, tokenizer,
                        # sampling, embedding — ~60% of total VRAM.  Require
                        # every GPU to have room for the worst case (rank 0).
                        per_gpu_needed = needed * self.TP_RANK0_VRAM_FRACTION
                else:
                    per_gpu_needed = needed
                # Wake operations are concurrent with loaded models on the same
                # GPUs — CUDA allocator pools and KV-cache growth can consume
                # memory between this check and the actual wake.  Apply extra
                # safety margin so tight fits fall through to the reclaim path
                # rather than risking a CUDA OOM.
                # Calibrated models use a smaller margin (5%) since base_residency
                # is measured; uncalibrated models use the full 15% wake margin.
                if is_calibrated:
                    per_gpu_needed *= self.CALIBRATED_PER_GPU_SAFETY_MARGIN
                elif target_action.action == "wake":
                    per_gpu_needed *= self.WAKE_PER_GPU_SAFETY_MARGIN
                gpu_effective = [
                    self._vram_ledger.get_gpu_effective_available_mb(
                        provider_id,
                        dev,
                        float(per_gpu_free[dev]),
                    )
                    for dev in target_gpu_ids
                ]
                per_gpu_ready = all(free_mb >= per_gpu_needed for free_mb in gpu_effective)
                logger.info(
                    "ensure_capacity provider=%s model=%s: known-GPU path "
                    "target_gpus=%s per_gpu_needed=%.0fMB gpu_effective=%s per_gpu_ready=%s",
                    provider_id, target.model_name,
                    list(target_gpu_ids),
                    per_gpu_needed,
                    [f"{v:.0f}MB" for v in gpu_effective],
                    per_gpu_ready,
                )
                if provider_ready and per_gpu_ready:
                    return True
                # For wake operations the model weights are already resident on
                # these GPUs (sleeping in the CUDA allocator pool).  The per-GPU
                # check uses a conservative TP_RANK0_VRAM_FRACTION × WAKE_SAFETY
                # margin that can over-estimate.  If provider-level VRAM is
                # sufficient, trust it — the wake just re-activates memory that's
                # already allocated on the correct devices.
                if provider_ready and target_action.action == "wake":
                    logger.info(
                        "ensure_capacity provider=%s model=%s: per-GPU shortfall but "
                        "provider_ready=True for wake (weights already on GPUs) → proceed",
                        provider_id, target.model_name,
                    )
                    return True
                gpu_shortfall = max(
                    per_gpu_needed - min(gpu_effective),
                    0.0,
                ) * len(target_gpu_ids)
                shortfall = max(shortfall, gpu_shortfall)
                logger.info(
                    "ensure_capacity provider=%s model=%s: GPU shortfall=%.0fMB → reclaim needed",
                    provider_id, target.model_name, shortfall,
                )
            elif per_gpu_free and not target_gpu_ids:
                # GPU placement unknown — infer TP from profile so TP>1 models
                # are not incorrectly required to fit on a single GPU.
                # tp=1: model lands on best GPU → check best GPU against full need.
                # tp>1: model spreads across tp GPUs → check tp-th best GPU against
                #        need/tp (same logic as _cold_load_for_request).
                tp = 1
                if profile is not None and profile.tensor_parallel_size and int(profile.tensor_parallel_size) > 1:
                    tp = int(profile.tensor_parallel_size)
                elif profile is not None and capacity is not None:
                    inferred = self._infer_tensor_parallel(profile, capacity, provider_id)
                    if inferred and inferred > 1:
                        tp = inferred
                is_calibrated_tp = (
                    profile is not None
                    and profile.residency_source in ("calibrated", "measured")
                )
                if tp > 1:
                    if is_calibrated_tp:
                        per_gpu_needed = needed / tp
                    else:
                        per_gpu_needed = needed * self.TP_RANK0_VRAM_FRACTION
                else:
                    per_gpu_needed = needed
                if is_calibrated_tp:
                    per_gpu_needed *= self.CALIBRATED_PER_GPU_SAFETY_MARGIN
                elif target_action.action == "wake":
                    per_gpu_needed *= self.WAKE_PER_GPU_SAFETY_MARGIN
                sorted_free = sorted(
                    (
                        self._vram_ledger.get_gpu_effective_available_mb(
                            provider_id, dev, float(free_mb),
                        )
                        for dev, free_mb in per_gpu_free.items()
                    ),
                    reverse=True,
                )
                nth_gpu_free = sorted_free[tp - 1] if len(sorted_free) >= tp else 0.0
                logger.info(
                    "ensure_capacity provider=%s model=%s: unknown-GPU path "
                    "tp=%d per_gpu_needed=%.0fMB sorted_free=%s nth_gpu_free=%.0fMB fits=%s",
                    provider_id, target.model_name,
                    tp, per_gpu_needed,
                    [f"{v:.0f}MB" for v in sorted_free],
                    nth_gpu_free,
                    nth_gpu_free >= per_gpu_needed,
                )
                if nth_gpu_free >= per_gpu_needed:
                    return True
                shortfall = max(shortfall, (per_gpu_needed - nth_gpu_free) * tp)
                logger.info(
                    "ensure_capacity provider=%s model=%s: per-GPU shortfall → total shortfall=%.0fMB",
                    provider_id, target.model_name, shortfall,
                )
                # Per-GPU check failed but provider-level VRAM is sufficient.
                # For wake: trust provider-level — weights already on GPUs,
                # TP_RANK0_VRAM_FRACTION is conservative, wake re-activates
                # existing memory.  For load: per-GPU matters — new allocation.
                if provider_ready and target_action.action == "wake":
                    logger.info(
                        "ensure_capacity provider=%s model=%s: per-GPU shortfall but "
                        "provider_ready=True for wake (weights already on GPUs) → proceed",
                        provider_id, target.model_name,
                    )
                    return True
            elif provider_ready:
                logger.info(
                    "ensure_capacity provider=%s model=%s: no per-GPU data, provider_ready → proceed",
                    provider_id, target.model_name,
                )
                return True

            lanes = self._safe_get_lanes(provider_id)
            profiles = self._safe_get_profiles(provider_id)

            reclaim = self._next_request_reclaim_action(
                provider_id=provider_id,
                target=target,
                lanes=lanes,
                profiles=profiles,
                required_free_mb=shortfall,
            )
            if reclaim is None:
                # No immediately actionable reclaim candidate.
                #
                # Check 1: idle stop candidates blocked only by load cooldown.
                # These become valid after a deterministic wait.
                cooldown_wait = self._time_until_cooldown_unblocked_stop(
                    provider_id=provider_id,
                    target=target,
                    lanes=lanes,
                    profiles=profiles,
                    required_free_mb=shortfall,
                    now=now,
                )
                if cooldown_wait is not None:
                    wait_total = cooldown_wait + self.COOLDOWN_WAIT_BUFFER_SECONDS
                    if wait_total < remaining:
                        logger.info(
                            "ensure_capacity provider=%s model=%s: no action now but "
                            "cooldown expires in %.1fs — waiting %.1fs then retrying "
                            "(%.0fs budget remaining)",
                            provider_id, target.model_name,
                            cooldown_wait, wait_total, remaining,
                        )
                        await asyncio.sleep(wait_total)
                        continue
                    logger.info(
                        "ensure_capacity provider=%s model=%s: cooldown-blocked candidate "
                        "exists but wait=%.1fs exceeds remaining budget=%.1fs — giving up",
                        provider_id, target.model_name, wait_total, remaining,
                    )
                    return False

                # Check 1b: idle loaded lanes blocked only by tenure protection.
                # These become valid once their minimum tenure expires.
                tenure_wait = self._time_until_idle_tenure_unblocked(
                    provider_id=provider_id,
                    target=target,
                    lanes=lanes,
                    profiles=profiles,
                    now=now,
                )
                if tenure_wait is not None:
                    wait_total = tenure_wait + self.COOLDOWN_WAIT_BUFFER_SECONDS
                    if wait_total < remaining:
                        logger.info(
                            "ensure_capacity provider=%s model=%s: no action now but "
                            "idle lane tenure expires in %.1fs — waiting %.1fs then retrying "
                            "(%.0fs budget remaining)",
                            provider_id, target.model_name,
                            tenure_wait, wait_total, remaining,
                        )
                        await asyncio.sleep(wait_total)
                        continue
                    logger.info(
                        "ensure_capacity provider=%s model=%s: tenure-blocked idle lane "
                        "exists but wait=%.1fs exceeds remaining budget=%.1fs — giving up",
                        provider_id, target.model_name, wait_total, remaining,
                    )
                    return False

                # Check 2: busy lanes — either drain-cooldown-blocked (deterministic
                # wait) or waiting for active requests to finish (poll).
                drain_cd_wait = self._time_until_drain_cooldown_unblocked(
                    provider_id=provider_id,
                    target=target,
                    lanes=lanes,
                    profiles=profiles,
                    required_free_mb=shortfall,
                    now=now,
                )
                has_busy = self._has_blocking_busy_lanes(
                    provider_id=provider_id,
                    target=target,
                    lanes=lanes,
                    profiles=profiles,
                    required_free_mb=shortfall,
                )
                if drain_cd_wait is not None or has_busy:
                    if drain_cd_wait is not None:
                        # Drain cooldown expires soon — wait precisely then retry
                        wait = drain_cd_wait + self.COOLDOWN_WAIT_BUFFER_SECONDS
                    else:
                        # No drain cooldown, just busy — poll for request completion
                        wait = self.BUSY_DRAIN_POLL_SECONDS
                    if wait < remaining:
                        logger.info(
                            "ensure_capacity provider=%s model=%s: busy lane holds "
                            "needed memory — waiting %.1fs (%s) then retrying "
                            "(%.0fs budget remaining)",
                            provider_id, target.model_name, wait,
                            "drain cooldown" if drain_cd_wait is not None else "poll",
                            remaining,
                        )
                        await asyncio.sleep(wait)
                        continue
                    logger.info(
                        "ensure_capacity provider=%s model=%s: busy lane blocks reclaim "
                        "but wait=%.1fs exceeds remaining budget=%.1fs — giving up",
                        provider_id, target.model_name, wait, remaining,
                    )
                    return False

                committed = self.get_pending_vram_mb(provider_id)
                logger.info(
                    "No idle reclaim action available for provider=%s model=%s "
                    "(need=%.0fMB available=%.0fMB committed=%.0fMB)",
                    provider_id,
                    target.model_name,
                    needed,
                    available,
                    committed,
                )
                # If there are in-flight VRAM reservations (another load/wake
                # in progress), wait for them to complete rather than giving up.
                # Once the in-flight operation finishes, the reserved VRAM
                # becomes available and we may be able to proceed.
                if committed > 0 and remaining > 5:
                    wait = min(5.0, remaining - 1)
                    logger.info(
                        "ensure_capacity provider=%s model=%s: in-flight reservation "
                        "(committed=%.0fMB) — waiting %.1fs for it to clear "
                        "(%.0fs budget remaining)",
                        provider_id, target.model_name, committed, wait, remaining,
                    )
                    await asyncio.sleep(wait)
                    continue
                return False

            # Re-check tenure before executing: between candidate selection
            # and execution, a concurrent ensure_capacity may have woken
            # this lane.  Don't immediately sleep a freshly-woken lane.
            if reclaim.action == "sleep_l1":
                lane_key = (reclaim.provider_id, reclaim.lane_id)
                loaded_at = self._lane_loaded_at.get(lane_key)
                min_tenure = self._get_effective_tenure()
                if min_tenure > 0:
                    if self._vram_ledger.has_active_reservation(
                        reclaim.provider_id, reclaim.lane_id,
                    ):
                        logger.info(
                            "Tenure protection at execution: skip sleep lane=%s "
                            "(in-flight VRAM reservation)",
                            reclaim.lane_id,
                        )
                        continue
                    if loaded_at is not None:
                        tenure_elapsed = time.time() - loaded_at
                        if tenure_elapsed < min_tenure:
                            logger.info(
                                "Tenure protection at execution: skip sleep lane=%s "
                                "(%.1f/%.1fs since wake)",
                                reclaim.lane_id, tenure_elapsed, min_tenure,
                            )
                            continue  # re-enter loop, re-evaluate

            async with self._lane_lock(reclaim.provider_id, reclaim.lane_id):
                ok = await self._execute_action_with_confirmation(
                    reclaim,
                    timeout_seconds=min(remaining, 45.0),
                )
            if not ok:
                # Execution failed (cooldown race, drain timeout, or worker error).
                # Re-enter the loop so the deadline guard and updated lane state
                # decide whether another attempt is viable.  The deadline at the
                # top of each iteration prevents infinite retries.
                logger.info(
                    "ensure_capacity provider=%s model=%s: reclaim action failed "
                    "(lane=%s action=%s) — re-checking with %.0fs remaining",
                    provider_id, target.model_name,
                    reclaim.lane_id, reclaim.action, remaining,
                )
                # Back off briefly to prevent a tight spin loop when the same
                # action keeps failing (e.g. stop on an already-stopped lane).
                await asyncio.sleep(min(2.0, max(0.5, remaining * 0.1)))
                continue
        finally:
            lock.release()

    @staticmethod
    def _gpu_overlap(gpu_a: Optional[str], gpu_b: Optional[str]) -> int:
        """Count overlapping GPU device indices between two lanes."""
        set_a = set(CapacityPlanner._parse_gpu_device_ids(gpu_a))
        set_b = set(CapacityPlanner._parse_gpu_device_ids(gpu_b))
        return len(set_a & set_b)

    def _next_request_reclaim_action(
        self,
        *,
        provider_id: int,
        target: LaneSchedulerSignals,
        lanes: list[LaneSchedulerSignals],
        profiles: dict[str, ModelProfile],
        required_free_mb: float = 0.0,
    ) -> Optional[CapacityPlanAction]:
        sleep_candidates: list[tuple[float, CapacityPlanAction]] = []
        stop_candidates: list[tuple[float, CapacityPlanAction]] = []
        now = time.time()

        for lane in lanes:
            if lane.lane_id == target.lane_id or lane.model_name == target.model_name:
                continue
            if lane.active_requests > 0 or lane.queue_waiting > 0:
                # Lane is busy — add as reclaim candidate if it qualifies for eviction.
                # Prefer sleep_l1 over stop: sleeping frees most VRAM while keeping
                # the model ready for fast wake (~2-3s vs 30-60s cold-load).
                # Only use stop if sleeping wouldn't free enough VRAM.
                if self._should_initiate_drain(provider_id, lane, target, profiles):
                    current_vram = float(lane.effective_vram_mb or 0.0)
                    lane_profile = profiles.get(lane.model_name)
                    if current_vram <= 0 and lane_profile is not None:
                        current_vram = self._estimate_model_loaded_vram(lane_profile)
                    if current_vram > 0:
                        sleeping_residual = float(
                            getattr(lane_profile, "sleeping_residual_mb", 0) or 0
                        ) if lane_profile else 0.0
                        freed_by_sleep = max(0.0, current_vram - sleeping_residual)
                        if lane.is_vllm and sleeping_residual > 0:
                            # For vLLM lanes, ALWAYS prefer sleep over stop.
                            # Sleeping frees 14-18 GB (loaded - residual) while
                            # keeping the model warm for 2-3s wake.  Stopping
                            # frees the full amount but costs 30-60s cold reload.
                            # Even if freed_by_sleep < required_free_mb, sleep is
                            # still the right choice — a second lane can be slept
                            # or the residual alone may suffice.
                            sleep_candidates.append((
                                freed_by_sleep,
                                CapacityPlanAction(
                                    action="sleep_l1",
                                    provider_id=provider_id,
                                    lane_id=lane.lane_id,
                                    model_name=lane.model_name,
                                    reason=f"Request-time reclaim (drain+sleep) for {target.model_name}",
                                ),
                            ))
                        elif freed_by_sleep >= required_free_mb and sleeping_residual > 0:
                            # Non-vLLM lane: sleeping frees enough
                            sleep_candidates.append((
                                freed_by_sleep,
                                CapacityPlanAction(
                                    action="sleep_l1",
                                    provider_id=provider_id,
                                    lane_id=lane.lane_id,
                                    model_name=lane.model_name,
                                    reason=f"Request-time reclaim (drain+sleep) for {target.model_name}",
                                ),
                            ))
                        else:
                            # Non-vLLM or no residual: must fully stop
                            if not self._lane_is_in_load_cooldown(provider_id, lane.lane_id, now=now):
                                stop_candidates.append((
                                    current_vram,
                                    CapacityPlanAction(
                                        action="stop",
                                        provider_id=provider_id,
                                        lane_id=lane.lane_id,
                                        model_name=lane.model_name,
                                        params={"_stop_penalty": 1},
                                        reason=f"Request-time reclaim (drain+stop) for {target.model_name}",
                                    ),
                                ))
                continue
            if lane.runtime_state in {"stopped", "error", "cold", "starting"}:
                continue
            # Block reclaim if the victim lane is actively processing requests
            # — drain will handle in-flight work safely.
            if lane.active_requests > 0 or lane.queue_waiting > 0:
                logger.info(
                    "Idle reclaim skip: victim %s lane=%s still busy "
                    "(active=%d, queue=%.0f)",
                    lane.model_name, lane.lane_id,
                    lane.active_requests, lane.queue_waiting,
                )
                continue
            # Queue-aware fairness: if the victim model has MORE pending
            # requests in the scheduler queue than the target, keep serving
            # the victim — it has higher demand right now.  This naturally
            # gives more GPU time to heavily loaded models (skewed workloads)
            # while still switching for evenly distributed traffic.
            # Only raw scheduler queue is used, not DemandTracker history,
            # to avoid the self-reinforcing score asymmetry.
            victim_sched_queue = self._facade.get_scheduler_queue_depth_by_model_name(
                lane.model_name, provider_id,
            )
            target_sched_queue = self._facade.get_scheduler_queue_depth_by_model_name(
                target.model_name, provider_id,
            )
            if victim_sched_queue > 0 and victim_sched_queue > target_sched_queue:
                logger.info(
                    "Idle reclaim skip: victim %s scheduler_queue=%d > "
                    "target %s scheduler_queue=%d — serving higher demand first",
                    lane.model_name, victim_sched_queue,
                    target.model_name, target_sched_queue,
                )
                continue
            # Load cooldown blocks stop (prevents thrashing) but not sleep —
            # sleeping only releases KV-cache memory without evicting the model,
            # so it is safe to sleep even a recently-loaded idle lane.
            in_cooldown = self._lane_is_in_load_cooldown(provider_id, lane.lane_id, now=now)

            profile = profiles.get(lane.model_name)
            current_vram = float(lane.effective_vram_mb or 0.0)
            if current_vram <= 0 and profile is not None:
                current_vram = self._estimate_model_loaded_vram(profile)
            residual_vram = float(profile.sleeping_residual_mb or 0.0) if profile is not None else 0.0

            # Sleeping vLLM lanes hold their residual (~0.7-1.5 GB) in actual
            # device memory.  Stopping a sleeping lane frees that residual but
            # destroys the fast-wake benefit (~2-3s vs 30-60s cold load).
            # Add as last-resort stop candidates (high penalty) — only chosen
            # when sleeping awake lanes can't free enough VRAM.
            if lane.is_vllm and lane.runtime_state == "sleeping":
                if residual_vram > 0 and not in_cooldown:
                    stop_candidates.append((
                        residual_vram,
                        CapacityPlanAction(
                            action="stop",
                            provider_id=provider_id,
                            lane_id=lane.lane_id,
                            model_name=lane.model_name,
                            params={"_stop_penalty": 2},
                            reason=f"Request-time reclaim (stop sleeping) for {target.model_name}",
                        ),
                    ))
                continue

            if lane.is_vllm and lane.runtime_state in {"loaded", "running"} and lane.sleep_state == "awake":
                # Idle loaded vLLM lane — candidate for sleep.
                # Tenure gate: a freshly-woken/loaded model has 0 active
                # requests and looks "idle", but its queued requests haven't
                # started processing yet.  Without tenure, it gets immediately
                # slept for another model → thrashing cascades where models
                # wake and sleep without serving anything.
                lane_key = (provider_id, lane.lane_id)
                loaded_at = self._lane_loaded_at.get(lane_key)
                min_tenure = self._get_effective_tenure()
                if min_tenure > 0:
                    # Block 1: in-flight VRAM reservation means a concurrent
                    # ensure_capacity is loading/waking this lane right now.
                    # The runtime snapshot may already show "loaded" but the
                    # operation hasn't finished — never sleep it.
                    if self._vram_ledger.has_active_reservation(provider_id, lane.lane_id):
                        logger.info(
                            "Tenure protection: skip idle sleep lane=%s "
                            "(in-flight VRAM reservation) for %s",
                            lane.lane_id, target.model_name,
                        )
                        continue
                    # Block 2: loaded_at tracks when we confirmed the lane
                    # available.  If None, the lane appeared in the runtime
                    # snapshot without going through our wake/load flow (e.g.
                    # initial sync after server restart).  Seed it now so that
                    # tenure expires after min_tenure seconds — the lane has
                    # clearly been loaded for a while if it survived a restart.
                    if loaded_at is None:
                        loaded_at = time.time() - min_tenure
                        self._lane_loaded_at[lane_key] = loaded_at
                        logger.info(
                            "Tenure: seeded loaded_at for untracked lane=%s "
                            "(will be reclaimable immediately)",
                            lane.lane_id,
                        )
                    tenure_elapsed = time.time() - loaded_at
                    if tenure_elapsed < min_tenure:
                        logger.info(
                            "Tenure protection: skip idle sleep lane=%s "
                            "(%.1f/%.1fs since wake) for %s",
                            lane.lane_id, tenure_elapsed, min_tenure,
                            target.model_name,
                        )
                        continue
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
                # Never go loaded → stopped directly for vLLM lanes.
                continue

            if current_vram > 0 and not in_cooldown:
                stop_candidates.append(
                    (
                        current_vram,
                        CapacityPlanAction(
                            action="stop",
                            provider_id=provider_id,
                            lane_id=lane.lane_id,
                            model_name=lane.model_name,
                            params={
                                "_stop_penalty": 1,
                            },
                            reason=f"Request-time reclaim for {target.model_name}",
                        ),
                    )
                )

        # Phase 3d: Build GPU overlap map for correlated freeing.
        # When target has known GPU placement, prefer freeing lanes on the same GPUs.
        target_gpus = target.gpu_devices
        gpu_overlap_by_lane: dict[str, int] = {}
        if target_gpus:
            for lane in lanes:
                if lane.lane_id != target.lane_id:
                    gpu_overlap_by_lane[lane.lane_id] = self._gpu_overlap(target_gpus, lane.gpu_devices)

        has_low_penalty_stop = any(
            (candidate[1].params or {}).get("_stop_penalty", 1) <= 0
            for candidate in stop_candidates
        )

        # Combined: merge sleep and stop candidates into a unified list.
        # For lanes that appear in both, the planner will naturally prefer sleep
        # unless the stop is an already-sleeping lane with zero stop penalty.
        combined = list(sleep_candidates) + list(stop_candidates)
        if combined and has_low_penalty_stop:
            combined_plan = self._best_reclaim_plan_combined(
                combined,
                required_free_mb=required_free_mb,
            )
            if combined_plan:
                return self._pick_next_reclaim_action_from_plan(combined_plan, gpu_overlap_by_lane)

        # Phase 3c: Try sleep-only first when there is no cheap sleeping-lane stop.
        if sleep_candidates:
            sleep_plan = self._best_reclaim_plan(
                sleep_candidates,
                required_free_mb=required_free_mb,
            )
            if sleep_plan:
                return self._pick_next_reclaim_action_from_plan(sleep_plan, gpu_overlap_by_lane)

        if combined:
            combined_plan = self._best_reclaim_plan_combined(
                combined,
                required_free_mb=required_free_mb,
            )
            if combined_plan:
                return self._pick_next_reclaim_action_from_plan(combined_plan, gpu_overlap_by_lane)
            # Fallback: pick the single largest action (prefer sleep over stop, prefer GPU overlap)
            combined.sort(key=lambda item: (
                (item[1].params or {}).get(
                    "_stop_penalty",
                    0 if item[1].action != "stop" else 1,
                ),
                -gpu_overlap_by_lane.get(item[1].lane_id, 0),
                -item[0],
                item[1].lane_id,
            ))
            return combined[0][1]
        return None

    @staticmethod
    def _best_reclaim_plan(
        candidates: list[tuple[float, CapacityPlanAction]],
        *,
        required_free_mb: float,
    ) -> list[tuple[float, CapacityPlanAction]]:
        """Find the least-destructive reclaim set that satisfies the shortfall.

        Preference order:
        1. Lowest total freed VRAM that still satisfies the request
        2. Lowest single-lane impact within that set
        3. Fewer actions
        4. Stable lane-id ordering

        Request-time lane counts are small, so an exact subset search is fine.
        """
        if required_free_mb <= 0:
            return []
        if not candidates:
            return []

        best_combo: tuple[int, ...] | None = None
        best_score: tuple[float, float, int, tuple[str, ...]] | None = None

        for size in range(1, len(candidates) + 1):
            for combo in combinations(range(len(candidates)), size):
                total_freed = sum(candidates[i][0] for i in combo)
                if total_freed + 1e-6 < required_free_mb:
                    continue
                max_single_freed = max(candidates[i][0] for i in combo)
                lane_ids = tuple(sorted(candidates[i][1].lane_id for i in combo))
                score = (total_freed, max_single_freed, size, lane_ids)
                if best_score is None or score < best_score:
                    best_score = score
                    best_combo = combo

        if best_combo is None:
            return []
        return [candidates[i] for i in best_combo]

    @staticmethod
    def _best_reclaim_plan_combined(
        candidates: list[tuple[float, CapacityPlanAction]],
        *,
        required_free_mb: float,
    ) -> list[tuple[float, CapacityPlanAction]]:
        """Find the least-destructive reclaim set from mixed sleep+stop candidates.

        Unlike _best_reclaim_plan, this handles candidates where the same lane
        may appear as both sleep and stop. Deduplicates per lane (picks sleep
        over stop when both are in the combo). Scoring penalizes stop actions
        to prefer sleep-heavy plans.
        """
        if required_free_mb <= 0 or not candidates:
            return []

        # Deduplicate: for each lane, only consider the combo entry that actually
        # appears. We filter combos that pick both sleep and stop for the same lane.
        best_combo: tuple[int, ...] | None = None
        best_score: tuple[int, float, float, int, tuple[str, ...]] | None = None

        for size in range(1, min(len(candidates) + 1, 6)):  # cap at 5 to avoid explosion
            for combo in combinations(range(len(candidates)), size):
                # Check for duplicate lanes (same lane as both sleep and stop)
                lane_ids_in_combo = [candidates[i][1].lane_id for i in combo]
                if len(lane_ids_in_combo) != len(set(lane_ids_in_combo)):
                    continue

                total_freed = sum(candidates[i][0] for i in combo)
                if total_freed + 1e-6 < required_free_mb:
                    continue

                stop_penalty = sum(
                    int((candidates[i][1].params or {}).get("_stop_penalty", 1))
                    for i in combo
                    if candidates[i][1].action == "stop"
                )
                max_single_freed = max(candidates[i][0] for i in combo)
                lane_ids = tuple(sorted(candidates[i][1].lane_id for i in combo))
                score = (stop_penalty, total_freed, max_single_freed, size, lane_ids)
                if best_score is None or score < best_score:
                    best_score = score
                    best_combo = combo

        if best_combo is None:
            return []
        return [candidates[i] for i in best_combo]

    @staticmethod
    def _pick_next_reclaim_action_from_plan(
        plan: list[tuple[float, CapacityPlanAction]],
        gpu_overlap_by_lane: Optional[dict[str, int]] = None,
    ) -> CapacityPlanAction:
        """Execute the best step inside the chosen low-damage reclaim plan first.

        Prefers actions with GPU overlap (frees memory where it's needed),
        then largest freed VRAM, then stable lane ordering.
        """
        overlap = gpu_overlap_by_lane or {}
        plan = sorted(plan, key=lambda item: (
            -overlap.get(item[1].lane_id, 0),
            -item[0],
            item[1].lane_id,
        ))
        return plan[0][1]

    # ------------------------------------------------------------------
    # GPU utilization tuning (vLLM only)
    # ------------------------------------------------------------------

    # Minimum KV cache: 512 MB (below this, model can barely serve requests)
    KV_CACHE_MIN_MB = 512.0
    # Fleet KV rebalance interval (seconds)
    KV_CACHE_REBALANCE_INTERVAL_SECONDS = 1800  # 30 minutes
    # Dampening: only reconfigure if delta > 20% of current KV budget
    KV_CACHE_REBALANCE_DAMPENING = 0.20
    # Emergency threshold: bypass interval if sustained pressure this high
    KV_CACHE_EMERGENCY_THRESHOLD = 95.0
    KV_CACHE_EMERGENCY_MIN_READINGS = 5
    # Pressure history window (number of readings to keep)
    KV_PRESSURE_HISTORY_SIZE = 60  # ~30 min at 30s cycles

    def _record_kv_pressure_history(
        self, provider_id: int, lanes: List[LaneSchedulerSignals],
    ) -> None:
        """Record per-lane KV cache pressure every cycle (cheap, no actions)."""
        now = time.time()
        for lane in lanes:
            if not lane.is_vllm or lane.gpu_cache_usage_percent is None:
                continue
            if lane.runtime_state not in ("loaded", "running"):
                continue
            key = self._lane_key(provider_id, lane.lane_id)
            history = self._kv_cache_pressure_history.setdefault(key, [])
            history.append((now, lane.gpu_cache_usage_percent))
            # Trim old entries
            if len(history) > self.KV_PRESSURE_HISTORY_SIZE:
                self._kv_cache_pressure_history[key] = history[-self.KV_PRESSURE_HISTORY_SIZE:]

    def _avg_kv_pressure(self, provider_id: int, lane_id: str) -> float:
        """Return average KV cache pressure from history (0.0 if no history)."""
        key = self._lane_key(provider_id, lane_id)
        history = self._kv_cache_pressure_history.get(key, [])
        if not history:
            return 0.0
        return sum(pct for _, pct in history) / len(history)

    def _is_kv_emergency(self, provider_id: int, lane_id: str) -> bool:
        """Check if lane has sustained emergency-level KV pressure."""
        key = self._lane_key(provider_id, lane_id)
        history = self._kv_cache_pressure_history.get(key, [])
        if len(history) < self.KV_CACHE_EMERGENCY_MIN_READINGS:
            return False
        recent = history[-self.KV_CACHE_EMERGENCY_MIN_READINGS:]
        return all(pct >= self.KV_CACHE_EMERGENCY_THRESHOLD for _, pct in recent)

    def _compute_fleet_kv_allocation(
        self, provider_id: int, lanes: List[LaneSchedulerSignals]
    ) -> List[CapacityPlanAction]:
        """Fleet-level KV budget allocation across all vLLM lanes on a provider.

        Replaces per-lane reactive tuning. Runs every KV_CACHE_REBALANCE_INTERVAL_SECONDS
        (30 min) unless an emergency is detected. Each lane's KV budget is computed from
        the VRAM of the GPUs it actually occupies (TP size), not the whole worker's total.
        """
        now = time.time()

        # Check if any lane has an emergency (bypasses interval)
        has_emergency = any(
            self._is_kv_emergency(provider_id, lane.lane_id)
            for lane in lanes if lane.is_vllm
        )
        if not has_emergency and (now - self._last_kv_rebalance_time) < self.KV_CACHE_REBALANCE_INTERVAL_SECONDS:
            return []

        try:
            profiles = self._facade.get_model_profiles(provider_id)
        except Exception:
            return []

        capacity = self._safe_get_capacity(provider_id)
        if capacity is None:
            return []

        # Determine per-GPU VRAM from runtime snapshot
        total_vram = float(capacity.total_vram_mb)
        snap = self._registry.peek_runtime_snapshot(provider_id) if self._registry else None
        devices_info = ((snap.get("runtime") or {}).get("devices") or {}) if snap else {}
        device_list = devices_info.get("devices") or []
        gpu_count = len(device_list) if isinstance(device_list, list) else 1
        per_gpu_vram = total_vram / max(gpu_count, 1)

        # Collect vLLM lanes with their profiles and per-lane GPU count
        vllm_lanes: list[tuple[LaneSchedulerSignals, ModelProfile, int]] = []
        for lane in lanes:
            if not lane.is_vllm:
                continue
            if lane.runtime_state not in ("loaded", "running", "sleeping"):
                continue
            profile = profiles.get(lane.model_name)
            if profile is None:
                continue
            base = float(profile.estimate_base_residency_mb() or 0.0)
            if base <= 0:
                continue
            # Determine how many GPUs this lane occupies
            lane_gpu_count = 1
            if lane.tensor_parallel_size and int(lane.tensor_parallel_size) > 1:
                lane_gpu_count = int(lane.tensor_parallel_size)
            elif lane.gpu_devices:
                devs = [d.strip() for d in lane.gpu_devices.split(",") if d.strip().isdigit()]
                if devs:
                    lane_gpu_count = len(devs)
            vllm_lanes.append((lane, profile, lane_gpu_count))

        if not vllm_lanes:
            return []

        # Compute per-lane KV pool based on the GPUs each lane uses
        # Each lane's KV budget is: (lane_gpu_count * per_gpu_vram) - base_residency - safety_margin
        lane_kv_pools: list[float] = []
        for lane, profile, lane_gpu_count in vllm_lanes:
            lane_vram = per_gpu_vram * lane_gpu_count
            base = float(profile.estimate_base_residency_mb() or 0.0)
            safety_margin_mb = lane_vram * (1 - self.GPU_UTIL_MAX)
            lane_kv_pool = max(0.0, lane_vram - base - safety_margin_mb)
            lane_kv_pools.append(lane_kv_pool)

        actions: list[CapacityPlanAction] = []

        for i, (lane, profile, lane_gpu_count) in enumerate(vllm_lanes):
            # Each lane's KV share is bounded by its own GPU VRAM, not the whole worker
            kv_share = lane_kv_pools[i]
            kv_share = max(kv_share, self.KV_CACHE_MIN_MB)

            # Determine current KV budget
            current_kv_mb = self._current_lane_kv_mb(profile)
            if current_kv_mb <= 0:
                continue

            delta_pct = abs(kv_share - current_kv_mb) / current_kv_mb if current_kv_mb > 0 else 1.0

            # Dampening: skip if change is < 20% (avoid thrashing)
            if delta_pct < self.KV_CACHE_REBALANCE_DAMPENING:
                continue

            # Don't reconfigure lanes that don't need it:
            # - Low cache usage (< HIGH) means the lane has enough KV cache
            # - Healthy band (LOW..HIGH) with good TTFT means it's working fine
            # Only reconfigure when cache is consistently saturated (> HIGH)
            # or there's a KV emergency
            ttft = lane.ttft_p95_seconds or 0.0
            cache_pct = lane.gpu_cache_usage_percent or 0.0
            if not self._is_kv_emergency(provider_id, lane.lane_id):
                if cache_pct <= self.GPU_CACHE_HIGH and ttft < 2.0:
                    continue

            new_kv_str = self._format_bytes_human(int(kv_share * 1024 * 1024))
            demand_score = self._demand.get_score(lane.model_name)
            avg_pressure = self._avg_kv_pressure(provider_id, lane.lane_id)

            action = CapacityPlanAction(
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
                    f"Fleet KV rebalance: {current_kv_mb:.0f}MB → {kv_share:.0f}MB "
                    f"(demand={demand_score:.2f}, avg_pressure={avg_pressure:.1f}%, "
                    f"delta={delta_pct:.0%})"
                ),
            )

            # Skip lanes that already have a deferred reconfig pending (avoid duplicates)
            key = self._lane_key(provider_id, lane.lane_id)
            if key in self._deferred_kv_reconfigs:
                # Update the deferred action with the latest allocation
                self._deferred_kv_reconfigs[key] = action
                continue

            # Never reconfigure a lane with active requests — defer instead
            if lane.active_requests > 0 or lane.queue_waiting > 0:
                self._deferred_kv_reconfigs[key] = action
                logger.info(
                    "Deferring KV reconfig for busy lane %s (active=%d, queue=%.1f)",
                    lane.lane_id, lane.active_requests, lane.queue_waiting,
                )
                continue

            # Skip sleeping lanes — leave them as-is
            if lane.runtime_state == "sleeping":
                continue

            actions.append(action)

        if actions or has_emergency:
            self._last_kv_rebalance_time = now

        return actions

    def _current_lane_kv_mb(self, profile: ModelProfile) -> float:
        """KV cache budget in MB for an active lane — delegates to the shared estimation chain."""
        return self._estimate_kv_mb(profile)

    def _flush_deferred_kv_reconfigs(
        self, provider_id: int, lanes: List[LaneSchedulerSignals]
    ) -> List[CapacityPlanAction]:
        """Execute deferred KV reconfigs for lanes that have gone idle."""
        actions = []
        active_lanes = {lane.lane_id: lane for lane in lanes}

        keys_to_flush = [
            key for key in list(self._deferred_kv_reconfigs)
            if key[0] == provider_id
        ]
        for key in keys_to_flush:
            lane = active_lanes.get(key[1])
            if lane is None:
                # Lane no longer exists — discard deferred action
                del self._deferred_kv_reconfigs[key]
                continue
            if lane.active_requests > 0 or lane.queue_waiting > 0:
                continue  # Still busy, keep deferred
            if lane.runtime_state == "sleeping":
                del self._deferred_kv_reconfigs[key]
                continue  # Don't reconfigure sleeping lanes

            action = self._deferred_kv_reconfigs.pop(key)
            actions.append(action)
            logger.info(
                "Flushing deferred KV reconfig for now-idle lane %s",
                lane.lane_id,
            )

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
        provider_id: Optional[int] = None,
    ) -> bool:
        """Quick gate before emitting a planner-initiated load action.

        Checks base_residency + KV cache ≤ available_vram (with safety margin).
        Uses the profile's HF-derived data when available, falls back to a name
        heuristic.  Returns True (allow) when no estimate is possible — unknown
        models should not be silently blocked.

        For TP > 1 models, also checks per-GPU feasibility from runtime snapshot
        device info, since total free VRAM can be misleading on heterogeneous or
        unevenly loaded multi-GPU nodes (e.g. 20 GB total free but split 18+2).
        """
        if capacity is None:
            return False
        available_mb = float(getattr(capacity, "available_vram_mb", 0) or 0)
        # Subtract VRAM reserved by in-flight operations
        if provider_id is not None:
            available_mb -= self.get_pending_vram_mb(provider_id)
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

        is_calibrated = (profile is not None and
                         profile.residency_source in ("calibrated", "measured"))

        if is_calibrated:
            # base_residency_mb already includes KV cache and TP overhead — use directly.
            minimum_needed = base_mb
            kv_mb = 0.0
            # Preserve actual TP for per-GPU check (even split, no RANK0 inflation).
            tp = 1
            if profile is not None and profile.tensor_parallel_size and int(profile.tensor_parallel_size) > 1:
                tp = int(profile.tensor_parallel_size)
        else:
            if kv_cache_bytes_str:
                kv_mb = self._parse_kv_cache_to_mb(kv_cache_bytes_str)
            elif profile is not None:
                kv_mb = self._estimate_kv_mb(profile)
            else:
                kv_mb = base_mb * self.KV_CACHE_HEADROOM_RATIO

            minimum_needed = base_mb + kv_mb

            # Determine TP size for this model
            tp = 1
            if profile is not None and profile.tensor_parallel_size and int(profile.tensor_parallel_size) > 1:
                tp = int(profile.tensor_parallel_size)
            elif provider_id is not None and base_mb is not None:
                inferred = self._infer_tensor_parallel(profile, capacity, provider_id) if profile else None
                if inferred and inferred > 1:
                    tp = inferred

            if tp > 1:
                # Add TP overhead: NCCL buffers, duplicated embedding/output layers
                minimum_needed *= (1.0 + self.TP_OVERHEAD_RATIO)

        # Total VRAM check
        feasible = available_mb >= minimum_needed * self.VRAM_SAFETY_MARGIN
        if not feasible:
            logger.info(
                "Feasibility FAILED for %s: need %.0fMB%s × %.2f margin, have %.0fMB",
                model_name, minimum_needed,
                " (calibrated, KV+TP included)" if is_calibrated else f" (base={base_mb:.0f}MB + kv={kv_mb:.0f}MB)",
                self.VRAM_SAFETY_MARGIN, available_mb,
            )
            return False

        # Per-GPU feasibility check for TP models
        # Use calibrated safety margin for cold-start overhead (CUDA context,
        # NCCL init, allocator pools) — must match _ensure_request_capacity.
        if tp > 1 and provider_id is not None:
            gpu_margin = self.CALIBRATED_PER_GPU_SAFETY_MARGIN if is_calibrated else None
            per_gpu_ok = self._check_per_gpu_feasibility(
                provider_id, minimum_needed, tp, model_name,
                per_gpu_margin=gpu_margin,
            )
            if not per_gpu_ok:
                return False

        return True

    def _check_per_gpu_feasibility(
        self,
        provider_id: int,
        total_needed_mb: float,
        tp: int,
        model_name: str,
        per_gpu_margin: Optional[float] = None,
    ) -> bool:
        """Check if a TP model fits on tp individual GPUs given per-GPU free VRAM.

        Total free VRAM can be misleading for multi-GPU systems. A 2×16GB system
        with 18GB+2GB free shows 20GB total free, but a TP=2 model needing
        10GB/GPU would fail on GPU1.

        Uses DeviceInfo from the worker runtime snapshot (serialized as dicts
        with fields: device_id, memory_free_mb, memory_total_mb, memory_used_mb).
        """
        if self._registry is None:
            return True  # can't check, allow
        snap = self._registry.peek_runtime_snapshot(provider_id)
        if snap is None:
            return True

        devices_info = (snap.get("runtime") or {}).get("devices") or {}
        device_list = devices_info.get("devices") or []
        if not isinstance(device_list, list) or len(device_list) < tp:
            return True  # can't check, allow

        # Gather per-GPU free memory from DeviceInfo dicts, subtracting
        # VRAM committed by in-flight ledger reservations on each GPU.
        per_gpu_free: list[tuple[str, float]] = []
        for dev in device_list:
            if not isinstance(dev, dict):
                continue
            dev_id = str(dev.get("device_id", "?"))
            free_mb = float(dev.get("memory_free_mb", 0) or 0)
            if free_mb <= 0:
                total_mb = float(dev.get("memory_total_mb", 0) or 0)
                used_mb = float(dev.get("memory_used_mb", 0) or 0)
                if total_mb > 0 and used_mb >= 0:
                    free_mb = max(total_mb - used_mb, 0.0)
            # Subtract VRAM already committed by in-flight operations on this GPU
            try:
                dev_id_int = int(dev_id) if dev_id.isdigit() else -1
            except (ValueError, AttributeError):
                dev_id_int = -1
            if dev_id_int >= 0:
                free_mb = self._vram_ledger.get_gpu_effective_available_mb(
                    provider_id, dev_id_int, free_mb,
                )
            per_gpu_free.append((dev_id, free_mb))

        if len(per_gpu_free) < tp:
            return True  # can't determine per-GPU, allow

        # Sort by most free first; check if the tp-th GPU has enough
        per_gpu_free.sort(key=lambda x: x[1], reverse=True)
        margin = per_gpu_margin if per_gpu_margin is not None else self.VRAM_SAFETY_MARGIN
        per_gpu_needed = (total_needed_mb / tp) * margin
        best_tp_gpus = per_gpu_free[:tp]
        weakest_gpu = best_tp_gpus[-1]

        if weakest_gpu[1] < per_gpu_needed:
            logger.info(
                "Per-GPU feasibility FAILED for %s (TP=%d): need %.0fMB/GPU, "
                "best %d GPUs have %s free (after ledger commitments)",
                model_name, tp, per_gpu_needed,
                tp,
                ", ".join(f"GPU{did}={free:.0f}MB" for did, free in best_tp_gpus),
            )
            return False
        return True

    def _validate_vram_budget(
        self, actions: List[CapacityPlanAction]
    ) -> List[CapacityPlanAction]:
        """Filter out actions that would exceed available VRAM.

        For load/wake actions, checks estimated VRAM against available capacity
        with a safety margin. Tracks cumulative consumption per provider,
        including VRAM freed by sleep/stop actions in the same batch and
        VRAM reserved by in-flight operations.
        """
        validated_ids: set[int] = set()
        cumulative_vram: dict[int, float] = {}

        # Process sleep/stop first (they free VRAM)
        free_actions = [a for a in actions if a.action in ("sleep_l1", "sleep_l2", "stop")]
        consume_actions = [a for a in actions if a.action in ("wake", "load")]
        other_actions = [a for a in actions if a.action not in ("sleep_l1", "sleep_l2", "stop", "wake", "load")]

        # Always allow sleep/stop and reconfigure actions
        validated_ids.update(id(action) for action in free_actions)
        validated_ids.update(id(action) for action in other_actions)

        # Credit freed VRAM from sleep/stop actions to cumulative tracking
        for action in free_actions:
            try:
                profiles = self._facade.get_model_profiles(action.provider_id)
            except Exception:
                profiles = {}
            profile = profiles.get(action.model_name)
            freed = self._estimate_freed_vram(action, profile)
            if freed > 0:
                cumulative_vram[action.provider_id] = (
                    cumulative_vram.get(action.provider_id, 0.0) - freed
                )

        # For consuming actions, check VRAM budget
        for action in consume_actions:
            provider_id = action.provider_id

            try:
                capacity = self._facade.get_capacity_info(provider_id)
                available = (
                    float(capacity.available_vram_mb)
                    - cumulative_vram.get(provider_id, 0.0)
                    - self.get_pending_vram_mb(provider_id)
                )
            except Exception:
                logger.debug("Cannot check VRAM for provider %s, rejecting %s", self._facade.get_provider_name(provider_id) or provider_id, action.action)
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
            else:
                logger.info(
                    "VRAM budget OK for %s on provider=%s: available=%.0fMB estimated=%.0fMB (margin=%.0fMB) cumulative=%.0fMB",
                    action.model_name, provider_id,
                    available, estimated_vram, estimated_vram * self.VRAM_SAFETY_MARGIN,
                    cumulative_vram.get(provider_id, 0.0),
                )

            cumulative_vram[provider_id] = cumulative_vram.get(provider_id, 0.0) + estimated_vram
            validated_ids.add(id(action))

        return [action for action in actions if id(action) in validated_ids]

    def _planner_lane_id(self, model_name: str) -> str:
        sanitized = model_name.replace("/", "_").replace(":", "_").replace(" ", "_")
        return f"planner-{sanitized}"

    def _build_load_params(
        self,
        model_name: str,
        lane_id: str,
        profile: Optional[ModelProfile],
        capacity=None,
        provider_id: Optional[int] = None,
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
        # Send TP if profile has an observed value, or infer from model size vs GPU VRAM.
        tp = 1
        if profile.tensor_parallel_size and int(profile.tensor_parallel_size) > 1:
            tp = int(profile.tensor_parallel_size)
            vllm_config["tensor_parallel_size"] = tp
        elif capacity is not None and provider_id is not None:
            inferred_tp = self._infer_tensor_parallel(profile, capacity, provider_id)
            if inferred_tp and inferred_tp > 1:
                tp = inferred_tp
                vllm_config["tensor_parallel_size"] = tp
        # TP>1: force enforce_eager=True — CUDA graph capture crashes the
        # Marlin MoE kernel on Turing GPUs (cudaErrorLaunchFailure in
        # fused_marlin_moe during compile_or_warm_up_model).
        if tp > 1:
            vllm_config["enforce_eager"] = True
        kv = self._compute_kv_cache_bytes(profile)
        if kv:
            # When we have an explicit KV budget, send only the KV cache size.
            # Do not also force gpu_memory_utilization: vLLM still treats that
            # as a startup guard, which can block an otherwise valid load.
            vllm_config["kv_cache_memory_bytes"] = kv
        # Qwen3/3.5 chat models default to thinking mode which puts tokens in
        # reasoning_content instead of content — invisible to most clients.
        # Disable by default; users can override per-request.
        if self._model_defaults_to_thinking(model_name):
            vllm_config["chat_template_kwargs"] = {"enable_thinking": False}
        params["vllm_config"] = vllm_config
        return params

    @staticmethod
    def _model_defaults_to_thinking(model_name: str) -> bool:
        """Check if a model uses thinking mode by default (Qwen3/3.5 chat models)."""
        low = model_name.lower()
        if "qwen3" not in low:
            return False
        # Coder models benefit from thinking; embedding models don't chat
        if any(s in low for s in ("coder", "embedding", "embed")):
            return False
        return True

    def _infer_tensor_parallel(
        self, profile: ModelProfile, capacity, provider_id: int,
    ) -> Optional[int]:
        """Infer tensor_parallel_size from model size vs per-GPU VRAM.

        Only infers TP > 1 when the model clearly won't fit on a single GPU.
        Returns None if inference is not possible or TP=1 is sufficient.
        """
        import math

        base_mb = profile.estimate_base_residency_mb()
        if base_mb is None or base_mb <= 0:
            return None

        total_vram = float(getattr(capacity, "total_vram_mb", 0))
        if total_vram <= 0:
            return None

        # Get device count from runtime snapshot
        snap = self._registry.peek_runtime_snapshot(provider_id) if self._registry else None
        if snap is None:
            return None
        devices_info = (snap.get("runtime") or {}).get("devices") or {}
        device_list = devices_info.get("devices") or []
        gpu_count = len(device_list) if isinstance(device_list, list) else 0
        if gpu_count <= 1:
            return None

        per_gpu_vram = total_vram / gpu_count
        # Model needs TP if base residency exceeds 85% of single GPU
        if base_mb <= per_gpu_vram * 0.85:
            return None

        tp = math.ceil(base_mb / (per_gpu_vram * 0.85))
        # Clamp to available GPU count and round to power of 2
        tp = min(tp, gpu_count)
        # Round up to nearest power of 2 (vLLM requirement)
        tp = 1 << (tp - 1).bit_length()
        return min(tp, gpu_count)

    # KV cache estimation
    KV_CACHE_HEADROOM_RATIO = 0.35  # last-resort fallback for models without HF config
    DEFAULT_CONTEXT_CAP = 8192      # conservative initial context window
    DEFAULT_CONCURRENCY = 4         # target concurrent sequences

    def _compute_kv_cache_bytes(self, profile: Optional[ModelProfile]) -> Optional[str]:
        """Compute the --kv-cache-memory-bytes string to pass to vLLM on startup.

        Delegates to _estimate_kv_mb for the numeric value, then formats it as
        a human-readable string accepted by the vLLM CLI (e.g. '4096M', '2G').
        Returns None only when there is no profile to estimate from.
        """
        if profile is None:
            return None
        kv_mb = self._estimate_kv_mb(profile)
        if kv_mb <= 0:
            return None
        return self._format_bytes_human(int(kv_mb * 1024 * 1024))

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

    def _estimate_kv_mb(self, profile: ModelProfile) -> float:
        """KV cache allocation in MB, using the same priority chain as _compute_kv_cache_bytes.

        1. Observed kv_budget_mb from a previous load on this provider (most accurate).
        2. Architecture-exact: kv_per_token_bytes × context_cap × concurrency.
        3. Last-resort fallback: base_residency × KV_CACHE_HEADROOM_RATIO (used only
           when the HF model config has not been fetched yet).
        """
        if profile.kv_budget_mb and profile.kv_budget_mb > 0:
            return float(profile.kv_budget_mb)
        if profile.kv_per_token_bytes and profile.kv_per_token_bytes > 0:
            ctx = min(profile.max_context_length or self.DEFAULT_CONTEXT_CAP, self.DEFAULT_CONTEXT_CAP)
            return (profile.kv_per_token_bytes * ctx * self.DEFAULT_CONCURRENCY) / (1024 * 1024)
        base = profile.estimate_base_residency_mb()
        if base and base > 0:
            return base * self.KV_CACHE_HEADROOM_RATIO
        return 0.0

    def _estimate_model_loaded_vram(self, profile: ModelProfile) -> float:
        """Total GPU memory (MB) used by a model when fully loaded and awake.

        For calibrated/measured vLLM profiles: base_residency_mb already includes
        the KV cache — return it directly.

        For uncalibrated vLLM profiles: base_residency is weights only, so add
        the estimated KV pool on top.

        For other engines: use the directly measured loaded_vram_mb from the profile.
        """
        if profile.engine == "vllm":
            base = float(profile.estimate_base_residency_mb() or 0.0)
            if profile.residency_source in ("calibrated", "measured"):
                return base  # KV already baked in
            kv = self._estimate_kv_mb(profile)
            return base + kv
        return profile.estimate_vram_mb()

    def _estimate_action_vram(
        self,
        action: CapacityPlanAction,
        profile: Optional[ModelProfile],
        capacity,
    ) -> float:
        """Incremental VRAM (MB) consumed by a load or wake action.

        load  → full model footprint (base + KV for vLLM).
        wake  → delta above the sleeping residual already in GPU memory
                (e.g. sleeping at 1.5 GB, full load 6 GB → wake costs 4.5 GB).

        For TP > 1 vLLM models adds TP_OVERHEAD_RATIO for NCCL buffers, duplicated
        embedding/output layers, and all-reduce scratch.
        """
        if profile is not None and profile.engine == "vllm":
            base_residency = float(profile.estimate_base_residency_mb() or 0.0)
            is_calibrated = profile.residency_source in ("calibrated", "measured")

            if is_calibrated:
                # base_residency already includes KV cache — use directly.
                # TP overhead is also baked in from the actual measured run.
                loaded_vram = base_residency
            else:
                # Uncalibrated: base_residency is weights only — add KV estimate.
                params = action.params or {}
                vllm_config = params.get("vllm_config") if isinstance(params.get("vllm_config"), dict) else {}
                kv_str = vllm_config.get("kv_cache_memory_bytes", "")
                kv_mb = self._parse_kv_cache_to_mb(kv_str) if kv_str else 0.0
                if kv_mb <= 0:
                    kv_mb = self._estimate_kv_mb(profile)
                loaded_vram = base_residency + kv_mb

                tp = int(vllm_config.get("tensor_parallel_size", 0) or 0)
                if tp <= 0 and profile.tensor_parallel_size:
                    tp = int(profile.tensor_parallel_size)
                if tp > 1:
                    loaded_vram *= (1.0 + self.TP_OVERHEAD_RATIO)

            sleeping_residual = float(profile.sleeping_residual_mb or 0.0)

            if action.action == "wake":
                return max(0.0, loaded_vram - sleeping_residual)
            if action.action == "load":
                return loaded_vram
            return 0.0

        if profile is not None:
            loaded_vram = self._estimate_model_loaded_vram(profile)
            sleeping_residual = float(profile.sleeping_residual_mb or 0.0)
        else:
            loaded_vram = 4096.0  # conservative fallback
            sleeping_residual = 0.0

        if action.action == "wake":
            return max(0.0, loaded_vram - sleeping_residual)
        if action.action == "load":
            return loaded_vram
        return 0.0

    def _estimate_freed_vram(
        self,
        action: CapacityPlanAction,
        profile: Optional[ModelProfile],
    ) -> float:
        """VRAM (MB) returned to the pool by a sleep or stop action.

        stop     → full loaded footprint (base + KV) is freed.
        sleep_l1/l2 → only the KV pool is freed; base weights remain as the
                      sleeping residual (e.g. 6 GB loaded, 1.5 GB residual → 4.5 GB freed).
        """
        if profile is None:
            return 0.0
        loaded_vram = self._estimate_model_loaded_vram(profile)
        sleeping_residual = float(profile.sleeping_residual_mb or 0.0)
        if action.action == "stop":
            return loaded_vram
        if action.action in ("sleep_l1", "sleep_l2"):
            return max(0.0, loaded_vram - sleeping_residual)
        return 0.0

    # ------------------------------------------------------------------
    # Execution with confirmation
    # ------------------------------------------------------------------

    async def _drain_lane(
        self, provider_id: int, lane_id: str, timeout_seconds: float = 30.0
    ) -> bool:
        """Wait for a lane's active requests to drain before a destructive action.

        Returns True if drained (active_requests == 0 AND vLLM internal
        queue_waiting == 0), False on timeout.  With concurrency
        oversubscription, vLLM may hold requests in its internal queue
        that haven't started processing yet — we must wait for those too.
        """
        deadline = time.time() + timeout_seconds
        poll_interval = 2.0
        while time.time() < deadline:
            snap = self._registry.peek_runtime_snapshot(provider_id)
            if snap is None:
                return True  # no snapshot = no active requests visible
            lanes = (snap.get("runtime") or {}).get("lanes") or []
            lane = next(
                (l for l in lanes if isinstance(l, dict) and l.get("lane_id") == lane_id),
                None,
            )
            if lane is None:
                return True  # lane already gone
            active = int(lane.get("active_requests") or 0)
            backend = lane.get("backend_metrics") if isinstance(lane.get("backend_metrics"), dict) else {}
            vllm_queue = int(float(backend.get("queue_waiting") or 0))
            vllm_running = int(float(backend.get("requests_running") or 0))
            if active == 0 and vllm_queue == 0 and vllm_running == 0:
                return True
            logger.info(
                "Waiting for lane %s to drain (%d active, %d vllm_running, "
                "%d vllm_queued, %.0fs remaining)",
                lane_id, active, vllm_running, vllm_queue,
                deadline - time.time(),
            )
            await asyncio.sleep(poll_interval)
        logger.warning(
            "Drain timeout for lane %s on provider %s after %.0fs",
            lane_id, provider_id, timeout_seconds,
        )
        return False

    def _build_desired_lane_set(
        self,
        provider_id: int,
        *,
        add_lane: Optional[Dict[str, Any]] = None,
        remove_lane_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Build the full desired lane set by merging current state with a change.

        Reads current lanes from the registry's desired_lanes (seeded from
        the worker's first status report), then overlays any inflight mutations
        (adds/removes that have been sent but not yet confirmed) to prevent
        rapid sequential applies from overwriting each other.
        """
        current = self._registry.get_desired_lane_set(provider_id)
        desired: dict[str, dict[str, Any]] = {}
        for lc in current:
            lid = str(lc.get("lane_id") or lc.get("model", ""))
            if lid:
                desired[lid] = copy.deepcopy(lc)

        # Overlay inflight additions (sent but not yet confirmed/committed)
        inflight_adds = self._inflight_desired.get(provider_id, {})
        for lid, lc_dict in inflight_adds.items():
            desired[lid] = copy.deepcopy(lc_dict)

        # Apply inflight removals
        inflight_removes = self._inflight_removals.get(provider_id, set())
        for lid in inflight_removes:
            desired.pop(lid, None)

        # Apply the current mutation on top
        if remove_lane_id:
            desired.pop(remove_lane_id, None)

        if add_lane:
            lid = str(add_lane.get("lane_id") or add_lane.get("model", ""))
            if lid:
                desired[lid] = copy.deepcopy(add_lane)

        return list(desired.values())

    # ------------------------------------------------------------------
    # Inflight desired-state tracking helpers
    # ------------------------------------------------------------------

    def _record_inflight_add(
        self, provider_id: int, lane_id: str, lane_config: dict[str, Any],
    ) -> None:
        """Record an inflight lane addition so subsequent builds include it."""
        if provider_id not in self._inflight_desired:
            self._inflight_desired[provider_id] = {}
        self._inflight_desired[provider_id][lane_id] = copy.deepcopy(lane_config)
        # If this lane was previously marked for removal, cancel that
        inflight_rm = self._inflight_removals.get(provider_id)
        if inflight_rm:
            inflight_rm.discard(lane_id)

    def _clear_inflight_add(self, provider_id: int, lane_id: str) -> None:
        """Clear inflight addition after registry commit or failure."""
        inflight = self._inflight_desired.get(provider_id)
        if inflight:
            inflight.pop(lane_id, None)

    def _record_inflight_removal(self, provider_id: int, lane_id: str) -> None:
        """Record an inflight lane removal so subsequent builds exclude it."""
        if provider_id not in self._inflight_removals:
            self._inflight_removals[provider_id] = set()
        self._inflight_removals[provider_id].add(lane_id)
        # If this lane was previously marked for addition, cancel that
        inflight_add = self._inflight_desired.get(provider_id)
        if inflight_add:
            inflight_add.pop(lane_id, None)

    def _clear_inflight_removal(self, provider_id: int, lane_id: str) -> None:
        """Clear inflight removal after registry commit or failure."""
        inflight = self._inflight_removals.get(provider_id)
        if inflight:
            inflight.discard(lane_id)

    # ------------------------------------------------------------------
    # Per-lane action lock helpers
    # ------------------------------------------------------------------

    def _lane_lock(self, provider_id: int, lane_id: str) -> asyncio.Lock:
        """Get or create a per-lane lock for serializing operations."""
        key = (provider_id, lane_id)
        lock = self._lane_action_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._lane_action_locks[key] = lock
        return lock

    # ------------------------------------------------------------------
    # Cold lane marking helpers
    # ------------------------------------------------------------------

    def _mark_lane_cold(self, provider_id: int, lane_id: str) -> None:
        """Pre-mark lane as cold so scheduler stops routing new requests."""
        self._marked_cold_lanes.add((provider_id, lane_id))
        self._registry.mark_lane_cold(provider_id, lane_id)
        logger.info(
            "Marked lane %s on provider %s as cold (scheduler will exclude)",
            lane_id, provider_id,
        )

    def _unmark_lane_cold(self, provider_id: int, lane_id: str) -> None:
        """Restore lane to normal scheduling after aborted stop."""
        self._marked_cold_lanes.discard((provider_id, lane_id))
        self._registry.unmark_lane_cold(provider_id, lane_id)
        logger.info(
            "Unmarked lane %s on provider %s as cold (scheduler routing restored)",
            lane_id, provider_id,
        )

    def is_lane_marked_cold(self, provider_id: int, lane_id: str) -> bool:
        """Check if a lane is pre-marked as cold (for scheduler exclusion)."""
        return (provider_id, lane_id) in self._marked_cold_lanes

    # ------------------------------------------------------------------
    # Demand-preemptive drain helpers
    # ------------------------------------------------------------------

    # Drain smoothing: minimum queue depth before a drain is considered.
    # The work comparison (target_work > busy_work) is the primary
    # anti-thrashing mechanism — active requests on the incumbent count
    # as work, providing natural inertia against premature displacement.
    DRAIN_MIN_TARGET_QUEUE = 2        # target needs ≥2 queued before drain

    def _should_initiate_drain(
        self,
        provider_id: int,
        busy_lane: LaneSchedulerSignals,
        target: LaneSchedulerSignals,
        profiles: dict[str, "ModelProfile"],
    ) -> bool:
        """Decide whether to drain a busy lane so another model can load.

        Three logical gates (all must pass):

        0. **Tenure**: if the busy lane loaded/woke recently (within
           LANE_MIN_TENURE_SECONDS), don't drain it — let it serve its
           queue first.  Without this, a freshly-woken model gets drained
           before processing a single request.

        1. **Queue minimum**: target must have ≥ DRAIN_MIN_TARGET_QUEUE
           requests waiting.  This prevents draining for a single stray
           request that would finish quickly once the model wakes anyway.

        2. **Work comparison**: target_work > busy_remaining_queue.  Only
           the incumbent's unserved queue competes — active requests are
           in-progress and will finish regardless.

        Plus one physical constraint:
        3. GPU overlap — must share at least one GPU.

        VRAM feasibility is NOT checked here — it would block multi-lane
        drain where no single lane frees enough by itself.  Coverage is
        handled by _best_reclaim_plan() in _next_request_reclaim_action.
        """
        # 0. Tenure: recently loaded/woken lanes are protected
        lane_key = (provider_id, busy_lane.lane_id)
        # In-flight reservation means a wake/load is still completing
        if self._vram_ledger.has_active_reservation(provider_id, busy_lane.lane_id):
            logger.info(
                "Drain skip lane=%s: in-flight VRAM reservation",
                busy_lane.lane_id,
            )
            return False
        loaded_at = self._lane_loaded_at.get(lane_key)
        if loaded_at is not None:
            tenure_elapsed = time.time() - loaded_at
            min_tenure = self._get_effective_tenure()
            if tenure_elapsed < min_tenure:
                logger.info(
                    "Drain skip lane=%s: tenure %.1f/%.1fs",
                    busy_lane.lane_id, tenure_elapsed, min_tenure,
                )
                return False

        # 1. Queue minimum: don't drain for trivial backlog
        all_lanes = self._safe_get_lanes(provider_id)
        target_work = self._get_queue_depth_for_model(
            provider_id, target.model_name, all_lanes,
        )
        if target_work < self.DRAIN_MIN_TARGET_QUEUE:
            logger.info(
                "Drain skip lane=%s: target_work=%d < min_queue=%d",
                busy_lane.lane_id, target_work, self.DRAIN_MIN_TARGET_QUEUE,
            )
            return False

        # 2. Work comparison: target queue must exceed busy lane's remaining
        #    queue to justify preempting active work.  Uses queue depth (current
        #    need) instead of _effective_demand to avoid DemandTracker score
        #    asymmetry (loaded models accumulate history, queued models can't).
        busy_remaining = max(0, self._get_queue_depth_for_model(
            provider_id, busy_lane.model_name, all_lanes,
        ) - busy_lane.active_requests)
        if target_work <= busy_remaining:
            logger.info(
                "Drain skip lane=%s: target %s (work=%d) <= busy %s (remaining=%d)",
                busy_lane.lane_id, target.model_name, target_work,
                busy_lane.model_name, busy_remaining,
            )
            return False

        # 3. GPU overlap: busy lane must share GPUs with target
        target_gpu_ids = self._parse_gpu_device_ids(target.gpu_devices)
        busy_gpu_ids = self._parse_gpu_device_ids(busy_lane.gpu_devices)
        if target_gpu_ids and busy_gpu_ids and not (set(target_gpu_ids) & set(busy_gpu_ids)):
            logger.info(
                "Drain skip lane=%s: no GPU overlap (busy=%s, target=%s)",
                busy_lane.lane_id, busy_gpu_ids, target_gpu_ids,
            )
            return False

        # Gate 5 (VRAM feasibility) removed: the per-lane check blocked
        # multi-lane busy drain when no single lane frees enough by itself.
        # Coverage is handled by _best_reclaim_plan() which finds the minimum
        # subset of candidates that satisfies the shortfall.

        logger.info(
            "Drain approved: busy_lane=%s model=%s (remaining=%d, active=%d) "
            "→ target=%s (work=%d)",
            busy_lane.lane_id, busy_lane.model_name, busy_remaining,
            busy_lane.active_requests, target.model_name, target_work,
        )
        # NOTE: drain timestamp is recorded AFTER successful execution in
        # _record_confirmed_action_state, not here.
        return True


    # ------------------------------------------------------------------
    # VRAM ledger helpers
    # ------------------------------------------------------------------

    def _reserve_vram(
        self,
        provider_id: int,
        lane_id: str,
        operation: str,
        vram_mb: float,
        gpu_devices: str | None = None,
    ) -> str:
        """Create a VRAM reservation in the ledger.  Returns reservation_id."""
        return self._vram_ledger.reserve(
            provider_id, lane_id, operation, vram_mb, gpu_devices,
        )

    def _try_reserve_vram_atomic(
        self,
        provider_id: int,
        lane_id: str,
        operation: str,
        vram_mb: float,
        raw_available_mb: float,
        gpu_devices: str | None = None,
        per_gpu_free: dict[int, float] | None = None,
    ) -> str | None:
        """Atomic check-and-reserve.  Returns reservation_id or None."""
        return self._vram_ledger.try_reserve_atomic(
            provider_id, lane_id, operation, vram_mb,
            raw_available_mb, safety_margin=self.VRAM_SAFETY_MARGIN,
            gpu_devices=gpu_devices, per_gpu_free=per_gpu_free,
        )

    def _release_vram(self, reservation_id: str | None) -> None:
        """Release a VRAM reservation by ID (no-op if None)."""
        if reservation_id:
            self._vram_ledger.release(reservation_id)

    def get_pending_vram_mb(self, provider_id: int) -> float:
        """Get total VRAM committed by in-flight operations on a provider."""
        return self._vram_ledger.get_committed_mb(provider_id)

    def _get_per_gpu_free(self, provider_id: int) -> dict[int, float] | None:
        """Read per-GPU free memory from the runtime snapshot.

        Returns a dict mapping device_id (int) → free_mb, or None if the
        snapshot is unavailable.
        """
        if self._registry is None:
            return None
        snap = self._registry.peek_runtime_snapshot(provider_id)
        if snap is None:
            return None
        devices_info = (snap.get("runtime") or {}).get("devices") or {}
        device_list = devices_info.get("devices") or []
        if not isinstance(device_list, list) or not device_list:
            return None
        result: dict[int, float] = {}
        for dev in device_list:
            if not isinstance(dev, dict):
                continue
            # Prefer extra["index"] (integer GPU index set by the GPU collector).
            # device_id is the nvidia-smi UUID string (e.g. "GPU-abc123-..."),
            # not parseable as an integer, so we cannot use it directly.
            extra = dev.get("extra") or {}
            raw_id = extra.get("index")
            if raw_id is None:
                # Fallback: try device_id in case it's a plain integer string
                raw_id = dev.get("device_id", -1)
            try:
                dev_id = int(raw_id)
            except (ValueError, TypeError):
                continue
            if dev_id < 0:
                continue
            free_mb = float(dev.get("memory_free_mb", 0) or 0)
            if free_mb <= 0:
                total_mb = float(dev.get("memory_total_mb", 0) or 0)
                used_mb = float(dev.get("memory_used_mb", 0) or 0)
                if total_mb > 0 and used_mb >= 0:
                    free_mb = max(total_mb - used_mb, 0.0)
            free_mb = self._vram_ledger.get_gpu_effective_available_mb(
                provider_id, dev_id, free_mb,
            )
            result[dev_id] = free_mb
        return result if result else None

    def _lane_gpu_devices_str(
        self, provider_id: int, lane_id: str,
    ) -> str | None:
        """Get the gpu_devices string for an existing lane from the runtime snapshot."""
        lanes = self._safe_get_lanes(provider_id)
        for lane in lanes:
            if lane.lane_id == lane_id:
                return lane.gpu_devices
        return None

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

        # KV cache reconfiguration: mark cold (stop routing), sleep, reconfigure, unmark
        if action.action == "reconfigure_kv_cache":
            # Mark lane cold BEFORE sleeping so the scheduler immediately stops
            # routing new requests (prevents TOCTOU where requests land on a
            # lane that's about to sleep for KV reconfiguration).
            self._mark_lane_cold(action.provider_id, action.lane_id)
            try:
                logger.info(
                    "Sleeping lane %s before KV cache reconfigure (warm restart)",
                    action.lane_id,
                )
                await self._registry.send_command(
                    action.provider_id,
                    "sleep_lane",
                    {"lane_id": action.lane_id, "level": 1, "mode": "wait"},
                    timeout_seconds=120,
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
                    timeout_seconds=int(min(timeout_seconds, 120)),
                )
            except Exception:
                logger.exception(
                    "Failed to send reconfigure_lane for lane %s", action.lane_id,
                )
                self._unmark_lane_cold(action.provider_id, action.lane_id)
                return False

            confirmed = await self._poll_confirmation(action, timeout_seconds)
            # Unmark cold after reconfigure completes (lane will be loaded/running again)
            self._unmark_lane_cold(action.provider_id, action.lane_id)
            if not confirmed:
                logger.warning(
                    "Confirmation timeout for reconfigure_kv_cache on lane %s after %.0fs",
                    action.lane_id, timeout_seconds,
                )
            return confirmed

        # ----------------------------------------------------------
        # Track the VRAM reservation for this action.  load/wake
        # consume VRAM; sleep/stop free it (negative reservation).
        # ----------------------------------------------------------
        _reservation_id: str | None = action.vram_reservation_id
        _profiles = self._safe_get_profiles(action.provider_id)
        _profile = _profiles.get(action.model_name)
        _capacity = self._safe_get_capacity(action.provider_id)
        # Resolve GPU device placement for per-GPU reservation tracking
        _lane_gpus = self._lane_gpu_devices_str(action.provider_id, action.lane_id)
        # For loads, gpu_devices may come from the action params
        if _lane_gpus is None and action.params:
            _lane_gpus = action.params.get("gpu_devices")
        _per_gpu_free = self._get_per_gpu_free(action.provider_id)
        # For TP>1 loads with no explicit GPU assignment, infer the target GPU set
        # so the per-GPU ledger is updated and concurrent loads on the same GPUs
        # see the committed VRAM.  vLLM selects the top-tp GPUs by free memory,
        # so we mirror that selection here.
        if _lane_gpus is None and action.action == "load" and _per_gpu_free:
            _tp = 1
            if action.params:
                _vllm_cfg = action.params.get("vllm_config") or {}
                if isinstance(_vllm_cfg, dict):
                    _tp = int(_vllm_cfg.get("tensor_parallel_size") or 1)
            if _tp > 1 and len(_per_gpu_free) >= _tp:
                _sorted_gpus = sorted(_per_gpu_free, key=lambda g: _per_gpu_free[g], reverse=True)
                _lane_gpus = ",".join(str(g) for g in _sorted_gpus[:_tp])

        # Sleep/wake are lightweight individual commands.
        # Load/stop use declarative apply_lanes (unless additive loads enabled).
        #
        # IMPORTANT: The entire action+poll block is wrapped in try/finally to
        # guarantee VRAM reservation release even on asyncio.CancelledError
        # (which is BaseException, not Exception, in Python 3.9+).  Without
        # this, a task cancellation during send_command would bypass the
        # per-action `except Exception` handlers and leak the reservation.
        try:
          if action.action in ("sleep_l1", "sleep_l2"):
            if self._is_preemptive_sleep_action(action):
                key = self._lane_key(action.provider_id, action.lane_id)
                if key not in self._preemptive_sleep_ready:
                    logger.info(
                        "Skipping stale preemptive sleep for lane %s on provider %s: "
                        "paired preemptive load was not confirmed",
                        action.lane_id, action.provider_id,
                    )
                    return False

            # For request-time reclaim sleeps, mark the lane cold and drain
            # active requests BEFORE sending the sleep command.  Without this,
            # new requests can be routed to the lane between the idle check in
            # _next_request_reclaim_action and the actual sleep — those in-flight
            # streams get killed when the lane is subsequently stopped.
            _is_reclaim_sleep = bool(
                action.reason and "Request-time reclaim" in action.reason
            )
            if _is_reclaim_sleep:
                self._mark_lane_cold(action.provider_id, action.lane_id)
                drained = await self._drain_lane(
                    action.provider_id, action.lane_id, timeout_seconds=60.0,
                )
                if not drained:
                    logger.warning(
                        "Cannot sleep lane %s for reclaim: "
                        "active requests did not drain within 60s",
                        action.lane_id,
                    )
                    self._unmark_lane_cold(action.provider_id, action.lane_id)
                    return False

            # Sleeping frees VRAM: record a negative reservation so concurrent
            # load checks see the freed space immediately.
            if _reservation_id is None and _profile is not None:
                current_vram = self._estimate_model_loaded_vram(_profile)
                residual = float(_profile.sleeping_residual_mb or 0.0)
                freed = max(current_vram - residual, 0.0)
                if freed > 0:
                    _reservation_id = self._reserve_vram(
                        action.provider_id, action.lane_id,
                        f"reclaim_{action.action}", -freed,
                        gpu_devices=_lane_gpus,
                    )

            command_map = {
                "sleep_l1": ("sleep_lane", {"lane_id": action.lane_id, "level": 1}),
                "sleep_l2": ("sleep_lane", {"lane_id": action.lane_id, "level": 2}),
            }
            command_action, command_params = command_map[action.action]
            try:
                await self._registry.send_command(
                    action.provider_id, command_action, command_params,
                    timeout_seconds=int(min(timeout_seconds, 120)),
                )
            except Exception:
                logger.exception(
                    "Failed to send %s command for lane %s",
                    action.action, action.lane_id,
                )
                if _is_reclaim_sleep:
                    self._unmark_lane_cold(action.provider_id, action.lane_id)
                return False

          elif action.action == "wake":
            # Wake consumes VRAM: reserve the delta above sleeping residual.
            # E.g. model sleeping at 1.5 GB, fully loaded = 6 GB → reserve 4.5 GB.
            if _reservation_id is None and _profile is not None and _capacity is not None:
                current_vram = self._estimate_model_loaded_vram(_profile)
                residual = float(_profile.sleeping_residual_mb or 0.0)
                wake_delta = max(current_vram - residual, 0.0)
                if wake_delta > 0:
                    raw_avail = float(_capacity.available_vram_mb)
                    _reservation_id = self._try_reserve_vram_atomic(
                        action.provider_id, action.lane_id,
                        "wake", wake_delta, raw_avail,
                        gpu_devices=_lane_gpus,
                        per_gpu_free=_per_gpu_free,
                    )
                    if _reservation_id is None:
                        logger.warning(
                            "VRAM reservation denied for wake of %s on lane %s "
                            "(need=%.0fMB avail=%.0fMB committed=%.0fMB gpus=%s)",
                            action.model_name, action.lane_id, wake_delta,
                            raw_avail, self.get_pending_vram_mb(action.provider_id),
                            _lane_gpus or "unknown",
                        )
                        return False

            # Set loaded_at BEFORE sending the command so concurrent
            # ensure_capacity calls see tenure protection immediately.
            # Without this, there's a race: the worker transitions the
            # lane to "loaded" (visible in the runtime snapshot) but
            # _poll_confirmation hasn't run yet → _lane_loaded_at is
            # stale → a concurrent coroutine sleeps the freshly-woken
            # lane because it thinks tenure already expired.
            _wake_key = self._lane_key(action.provider_id, action.lane_id)
            self._lane_loaded_at[_wake_key] = time.time()

            try:
                await self._registry.send_command(
                    action.provider_id, "wake_lane",
                    {"lane_id": action.lane_id},
                    timeout_seconds=int(timeout_seconds),
                )
            except Exception as exc:
                self._mark_wake_failure(
                    action.provider_id,
                    action.lane_id,
                    details=str(exc),
                )
                logger.exception(
                    "Failed to send wake command for lane %s", action.lane_id,
                )
                return False

          elif action.action == "load":
            if self._is_preemptive_load_action(action) and self._lane_exists_in_runtime(
                action.provider_id, action.lane_id,
            ):
                logger.info(
                    "Skipping stale preemptive load for lane %s on provider %s: lane already exists",
                    action.lane_id, action.provider_id,
                )
                return False
            # Estimate VRAM and atomically reserve
            _estimated_load_vram = (
                self._estimate_action_vram(action, _profile, _capacity)
                if _capacity else 0.0
            )
            if _reservation_id is None and _estimated_load_vram > 0 and _capacity is not None:
                raw_avail = float(_capacity.available_vram_mb)
                _reservation_id = self._try_reserve_vram_atomic(
                    action.provider_id, action.lane_id,
                    "load", _estimated_load_vram, raw_avail,
                    gpu_devices=_lane_gpus,
                    per_gpu_free=_per_gpu_free,
                )
                if _reservation_id is None:
                    logger.warning(
                        "VRAM reservation denied for load of %s: "
                        "need=%.0fMB avail=%.0fMB committed=%.0fMB gpus=%s",
                        action.model_name, _estimated_load_vram,
                        raw_avail, self.get_pending_vram_mb(action.provider_id),
                        _lane_gpus or "unknown",
                    )
                    return False
            elif _reservation_id is None and _estimated_load_vram > 0:
                # No capacity info — unconditional reservation as fallback
                _reservation_id = self._reserve_vram(
                    action.provider_id, action.lane_id,
                    "load", _estimated_load_vram,
                    gpu_devices=_lane_gpus,
                )

            if self._use_additive_loads:
                try:
                    await self._registry.send_command(
                        action.provider_id, "add_lane", action.params,
                        timeout_seconds=int(timeout_seconds),
                    )
                    self._registry.update_desired_lane_add(
                        action.provider_id, action.params,
                    )
                except Exception:
                    logger.exception(
                        "Failed to send add_lane for lane %s", action.lane_id,
                    )
                    return False
            else:
                new_lane = {"lane_id": action.lane_id, "model": action.model_name}
                if action.params:
                    new_lane.update(action.params)

                # Record inflight addition before building desired set
                self._record_inflight_add(action.provider_id, action.lane_id, new_lane)

                desired = self._build_desired_lane_set(
                    action.provider_id, add_lane=new_lane,
                )
                try:
                    result = await self._registry.send_command(
                        action.provider_id, "apply_lanes",
                        {"lanes": desired},
                        timeout_seconds=int(timeout_seconds),
                    )
                    rolled_back = isinstance(result, dict) and result.get("rolled_back")
                    if rolled_back:
                        logger.warning(
                            "apply_lanes rolled back for load of %s on provider %s",
                            action.model_name, action.provider_id,
                        )
                        self._clear_inflight_add(action.provider_id, action.lane_id)
                        return False
                    self._registry.update_desired_lanes(action.provider_id, desired)
                    # Inflight entry now committed to registry — clear it
                    self._clear_inflight_add(action.provider_id, action.lane_id)
                except Exception:
                    logger.exception(
                        "Failed to send apply_lanes for load of %s", action.lane_id,
                    )
                    self._clear_inflight_add(action.provider_id, action.lane_id)
                    return False

          elif action.action == "stop":
            # Phase 1c: Reject stop if lane is within load cooldown
            if self._lane_is_in_load_cooldown(action.provider_id, action.lane_id):
                logger.info(
                    "Skipping stop of lane %s on provider %s: within %.0fs load cooldown",
                    action.lane_id, action.provider_id, self._load_cooldown_seconds,
                )
                return False

            # Stop frees VRAM: record a negative reservation so concurrent
            # load checks see the freed space immediately.
            if _reservation_id is None and _profile is not None:
                freed = self._estimate_model_loaded_vram(_profile)
                if freed > 0:
                    _reservation_id = self._reserve_vram(
                        action.provider_id, action.lane_id,
                        "reclaim_stop", -freed,
                        gpu_devices=_lane_gpus,
                    )

            # Phase 3a: Pre-mark lane as cold so scheduler stops routing to it
            self._mark_lane_cold(action.provider_id, action.lane_id)

            # Phase 3b: Drain active requests — abort if drain fails
            drained = await self._drain_lane(
                action.provider_id, action.lane_id, timeout_seconds=60.0,
            )
            if not drained:
                logger.warning(
                    "Cannot stop lane %s: active requests did not drain within timeout",
                    action.lane_id,
                )
                self._unmark_lane_cold(action.provider_id, action.lane_id)
                return False

            if self._use_additive_loads:
                try:
                    await self._registry.send_command(
                        action.provider_id, "delete_lane",
                        {"lane_id": action.lane_id},
                        timeout_seconds=int(min(timeout_seconds, 30)),
                    )
                    self._registry.update_desired_lane_remove(
                        action.provider_id, action.lane_id,
                    )
                except Exception:
                    logger.exception(
                        "Failed to send delete_lane for lane %s", action.lane_id,
                    )
                    self._unmark_lane_cold(action.provider_id, action.lane_id)
                    return False
            else:
                # Record inflight removal before building desired set
                self._record_inflight_removal(action.provider_id, action.lane_id)

                desired = self._build_desired_lane_set(
                    action.provider_id, remove_lane_id=action.lane_id,
                )
                try:
                    result = await self._registry.send_command(
                        action.provider_id, "apply_lanes",
                        {"lanes": desired},
                        timeout_seconds=int(min(timeout_seconds, 30)),
                    )
                    rolled_back = isinstance(result, dict) and result.get("rolled_back")
                    if rolled_back:
                        logger.warning(
                            "apply_lanes rolled back for stop of %s on provider %s",
                            action.lane_id, action.provider_id,
                        )
                        self._clear_inflight_removal(action.provider_id, action.lane_id)
                        self._unmark_lane_cold(action.provider_id, action.lane_id)
                        return False
                    self._registry.update_desired_lanes(action.provider_id, desired)
                    self._clear_inflight_removal(action.provider_id, action.lane_id)
                except Exception:
                    logger.exception(
                        "Failed to send apply_lanes for stop of %s", action.lane_id,
                    )
                    self._clear_inflight_removal(action.provider_id, action.lane_id)
                    self._unmark_lane_cold(action.provider_id, action.lane_id)
                    return False
          else:
            logger.warning("Unknown capacity action: %s", action.action)
            return False

          # Poll for confirmation
          confirmed = await self._poll_confirmation(action, timeout_seconds)
        finally:
            # Release VRAM reservation — runs even on CancelledError/BaseException.
            # The worker's actual VRAM usage is reflected in the next capacity snapshot.
            self._release_vram(_reservation_id)

        if not confirmed:
            if action.action == "wake":
                self._mark_wake_failure(
                    action.provider_id,
                    action.lane_id,
                    details="confirmation timeout",
                )
            # Sleep confirmation timeout: the command was sent, so the lane
            # is likely sleeping even though we couldn't verify.  Clear the
            # cold mark so it doesn't stay permanently excluded.  Sleeping
            # lanes aren't routable anyway, and the cold mark is re-set on
            # the next reclaim attempt if needed.
            if action.action in ("sleep_l1", "sleep_l2"):
                self._unmark_lane_cold(action.provider_id, action.lane_id)
            logger.warning(
                "Confirmation timeout for %s on lane %s after %.0fs",
                action.action, action.lane_id, timeout_seconds,
            )
        else:
            if action.action == "stop":
                # Lane is gone — clear the cold mark so that if the same lane_id
                # is reloaded later (planner lane IDs are deterministic from model name),
                # it is not permanently excluded from scheduling.
                self._unmark_lane_cold(action.provider_id, action.lane_id)
            elif action.action == "load":
                # A newly loaded lane should never inherit a stale cold mark from a
                # previous stop of the same lane_id.
                self._unmark_lane_cold(action.provider_id, action.lane_id)
            elif action.action == "wake":
                # Clear any cold mark left by a prior reclaim sleep so the
                # woken lane is routable again.
                self._unmark_lane_cold(action.provider_id, action.lane_id)

        if confirmed and action.action in ("load", "wake") and self._on_state_change is not None:
            # Notify scheduler to reevaluate queued requests for this model
            try:
                self._on_state_change(action.model_name)
            except Exception:
                logger.debug(
                    "on_state_change callback failed for model %s",
                    action.model_name, exc_info=True,
                )

        # After any confirmed reclaim, retry pending capacity for models whose
        # earlier fire-and-forget trigger failed — freed VRAM may now suffice.
        if confirmed and action.action in ("sleep_l1", "sleep_l2", "stop"):
            self._retry_pending_capacity(action.provider_id)

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

    def would_require_eviction(self, provider_id: int, model_name: str) -> bool:
        """Check if loading a model on a provider would require evicting another lane.

        Returns True if estimated model VRAM exceeds available free VRAM (with safety margin).
        Used by the ETTFT estimator to add eviction cost to cold-start scoring.
        Accounts for TP overhead when the model requires tensor parallelism.
        """
        capacity = self._safe_get_capacity(provider_id)
        if capacity is None:
            return False  # Can't tell, assume no eviction needed

        profile = self._safe_get_profiles(provider_id).get(model_name)
        estimated_mb: float
        if profile is not None:
            estimated_mb = self._estimate_model_loaded_vram(profile)
        else:
            from logos.sdi.models import (
                _base_residency_from_bytes,
                _estimated_disk_size_bytes_from_model_name,
            )
            disk = _estimated_disk_size_bytes_from_model_name(model_name)
            base = _base_residency_from_bytes(disk)
            estimated_mb = float(base) if base else 4096.0

        # Add TP overhead if model uses tensor parallelism
        tp = int(profile.tensor_parallel_size or 0) if profile else 0
        if tp <= 1 and profile is not None:
            inferred = self._infer_tensor_parallel(profile, capacity, provider_id)
            if inferred and inferred > 1:
                tp = inferred
        if tp > 1:
            estimated_mb *= (1.0 + self.TP_OVERHEAD_RATIO)

        available = float(capacity.available_vram_mb)
        return available < estimated_mb * self.VRAM_SAFETY_MARGIN

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
