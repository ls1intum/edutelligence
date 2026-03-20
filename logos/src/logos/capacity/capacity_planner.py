# src/logos/capacity/capacity_planner.py
"""
Background capacity planner that monitors demand patterns
and proactively manages worker node lane configurations.

Runs on a configurable cycle (default 30s). Independently ablatable
via LOGOS_CAPACITY_PLANNER_ENABLED=false.
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from logos.logosnode_registry import LogosNodeRuntimeRegistry
from logos.sdi.logosnode_facade import LogosNodeSchedulingDataFacade
from logos.sdi.models import CapacityPlanAction, LaneSchedulerSignals, ModelProfile

from .demand_tracker import DemandTracker

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
    IDLE_SLEEP_L1 = 60       # vLLM lane idle 1min → sleep level 1
    IDLE_SLEEP_L2 = 300      # vLLM lane sleeping L1 for 5min → sleep level 2
    IDLE_STOP = 900          # any lane idle 15min → stop/remove

    # Demand thresholds
    DEMAND_WAKE_THRESHOLD = 1.0
    DEMAND_LOAD_THRESHOLD = 2.0

    # GPU utilization tuning
    GPU_UTIL_MIN = 0.50
    GPU_UTIL_MAX = 0.95
    GPU_UTIL_STEP = 0.05
    GPU_CACHE_HIGH = 85.0
    GPU_CACHE_LOW = 40.0
    GPU_UTIL_CHANGE_THRESHOLD = 0.05
    DEFAULT_VLLM_LOAD_GPU_UTIL = 0.65

    # VRAM safety margin
    VRAM_SAFETY_MARGIN = 1.1  # 10% margin

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
        self._demand.decay_all()
        all_actions: List[CapacityPlanAction] = []

        for provider_id in self._facade.provider_ids():
            try:
                lanes = self._facade.get_all_provider_lane_signals(provider_id)
            except Exception:
                logger.debug("Provider %s offline, skipping", provider_id)
                continue

            self._update_idle_tracking(provider_id, lanes)
            all_actions.extend(self._compute_idle_actions(provider_id, lanes))
            all_actions.extend(self._compute_demand_actions(provider_id, lanes))
            all_actions.extend(self._compute_gpu_util_actions(provider_id, lanes))

        validated = self._validate_vram_budget(all_actions)

        for action in validated:
            try:
                await self._execute_action_with_confirmation(action)
            except Exception:
                logger.exception(
                    "Failed to execute capacity action: %s on lane %s",
                    action.action, action.lane_id,
                )

    async def prepare_lane_for_request(
        self,
        provider_id: int,
        model_name: str,
        timeout_seconds: float = 60.0,
    ) -> dict[str, Any] | None:
        """Prepare an existing lane for request-time execution.

        This path is synchronous to the request. It can wake a sleeping lane and
        reclaim memory from idle competing lanes before the request is sent.
        It intentionally does not invent brand-new lane configs for models that
        currently have no lane.
        """
        target = self._pick_request_target_lane(provider_id, model_name)
        if target is None:
            return None

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
                timeout_seconds=min(timeout_seconds, 45.0),
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

    # ------------------------------------------------------------------
    # Idle tracking
    # ------------------------------------------------------------------

    def _update_idle_tracking(self, provider_id: int, lanes: List[LaneSchedulerSignals]) -> None:
        """Track idle durations per lane."""
        now = time.time()
        active_keys = set()
        for lane in lanes:
            key = (provider_id, lane.lane_id)
            active_keys.add(key)
            if lane.active_requests > 0 or lane.queue_waiting > 0:
                self._lane_idle_since[key] = now  # Reset idle timer
            elif key not in self._lane_idle_since:
                self._lane_idle_since[key] = now  # Start tracking idle

        # Clean up lanes that no longer exist
        stale = [k for k in self._lane_idle_since if k[0] == provider_id and k not in active_keys]
        for k in stale:
            del self._lane_idle_since[k]

    def _compute_idle_actions(
        self, provider_id: int, lanes: List[LaneSchedulerSignals]
    ) -> List[CapacityPlanAction]:
        """Compute sleep/stop actions for idle lanes."""
        now = time.time()
        actions = []

        for lane in lanes:
            key = (provider_id, lane.lane_id)
            idle_start = self._lane_idle_since.get(key)
            if idle_start is None:
                continue
            idle_seconds = now - idle_start

            # Skip lanes that are already stopped/error
            if lane.runtime_state in ("stopped", "error", "cold"):
                continue

            # Stop after 15 minutes idle
            if idle_seconds >= self.IDLE_STOP:
                actions.append(CapacityPlanAction(
                    action="stop",
                    provider_id=provider_id,
                    lane_id=lane.lane_id,
                    model_name=lane.model_name,
                    reason=f"Idle for {idle_seconds:.0f}s (threshold {self.IDLE_STOP}s)",
                ))
                continue

            # Only vLLM lanes support sleep
            if not lane.is_vllm:
                continue

            # Sleep L2 after 5 minutes of L1 sleep
            if (
                lane.sleep_state == "sleeping"
                and idle_seconds >= self.IDLE_SLEEP_L2
            ):
                actions.append(CapacityPlanAction(
                    action="sleep_l2",
                    provider_id=provider_id,
                    lane_id=lane.lane_id,
                    model_name=lane.model_name,
                    params={"level": 2},
                    reason=f"Sleeping L1 for {idle_seconds:.0f}s, deepening to L2",
                ))
                continue

            # Sleep L1 after 1 minute idle (only if awake)
            if (
                lane.sleep_state == "awake"
                and lane.runtime_state in ("loaded", "running")
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

    # ------------------------------------------------------------------
    # Demand-based actions
    # ------------------------------------------------------------------

    def _compute_demand_actions(
        self, provider_id: int, lanes: List[LaneSchedulerSignals]
    ) -> List[CapacityPlanAction]:
        """Compute wake/load actions based on demand patterns."""
        actions = []
        ranked = self._demand.get_ranked_models()
        try:
            profiles = self._facade.get_model_profiles(provider_id)
        except Exception:
            profiles = {}
        try:
            capacity = self._facade.get_capacity_info(provider_id)
        except Exception:
            capacity = None

        # Build index of current lanes by model
        lanes_by_model: dict[str, List[LaneSchedulerSignals]] = {}
        for lane in lanes:
            lanes_by_model.setdefault(lane.model_name, []).append(lane)

        for model_name, score in ranked:
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
                    continue

            # Load a new lane if demand is high and no lane exists
            if score >= self.DEMAND_LOAD_THRESHOLD and not model_lanes:
                lane_id = self._planner_lane_id(model_name)
                profile = profiles.get(model_name)
                actions.append(CapacityPlanAction(
                    action="load",
                    provider_id=provider_id,
                    lane_id=lane_id,
                    model_name=model_name,
                    params=self._build_load_params(model_name, lane_id, profile, capacity),
                    reason=f"Demand score={score:.2f} >= {self.DEMAND_LOAD_THRESHOLD}, preemptive load",
                ))

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

    def _compute_gpu_util_actions(
        self, provider_id: int, lanes: List[LaneSchedulerSignals]
    ) -> List[CapacityPlanAction]:
        """Tune gpu_memory_utilization based on KV cache pressure."""
        actions = []

        for lane in lanes:
            if not lane.is_vllm:
                continue
            if lane.gpu_cache_usage_percent is None:
                continue
            if lane.runtime_state not in ("loaded", "running"):
                continue

            cache_pct = lane.gpu_cache_usage_percent
            current_util = lane.gpu_memory_utilization or self.DEFAULT_VLLM_LOAD_GPU_UTIL

            if cache_pct > self.GPU_CACHE_HIGH:
                target_util = min(self.GPU_UTIL_MAX, current_util + self.GPU_UTIL_STEP)
                if abs(target_util - current_util) < self.GPU_UTIL_CHANGE_THRESHOLD:
                    continue
                actions.append(CapacityPlanAction(
                    action="reconfigure_gpu_util",
                    provider_id=provider_id,
                    lane_id=lane.lane_id,
                    model_name=lane.model_name,
                    params={
                        "updates": {
                            "vllm_config": {
                                "gpu_memory_utilization": round(target_util, 3),
                            }
                        }
                    },
                    reason=(
                        f"GPU cache pressure high ({cache_pct:.1f}% > {self.GPU_CACHE_HIGH}%), "
                        f"increasing gpu_memory_utilization to {target_util:.2f}"
                    ),
                ))
            elif cache_pct < self.GPU_CACHE_LOW:
                # Decrease GPU utilization (only if other models need VRAM)
                other_demand = any(
                    score > 0
                    for model_name, score in self._demand.get_ranked_models()
                    if model_name != lane.model_name
                )
                if other_demand:
                    target_util = max(self.GPU_UTIL_MIN, current_util - self.GPU_UTIL_STEP)
                    if abs(target_util - current_util) < self.GPU_UTIL_CHANGE_THRESHOLD:
                        continue
                    actions.append(CapacityPlanAction(
                        action="reconfigure_gpu_util",
                        provider_id=provider_id,
                        lane_id=lane.lane_id,
                        model_name=lane.model_name,
                        params={
                            "updates": {
                                "vllm_config": {
                                    "gpu_memory_utilization": round(target_util, 3),
                                }
                            }
                        },
                        reason=(
                            f"GPU cache low ({cache_pct:.1f}% < {self.GPU_CACHE_LOW}%), "
                            f"other models need VRAM, lowering gpu_memory_utilization to {target_util:.2f}"
                        ),
                    ))

        return actions

    # ------------------------------------------------------------------
    # VRAM budget validation
    # ------------------------------------------------------------------

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
        params["vllm_config"] = {
            "gpu_memory_utilization": self._recommended_vllm_gpu_util(profile, capacity),
            "tensor_parallel_size": max(1, int(profile.tensor_parallel_size or 1)),
        }
        return params

    def _recommended_vllm_gpu_util(self, profile: Optional[ModelProfile], capacity=None) -> float:
        total_vram_mb = float(getattr(capacity, "total_vram_mb", 0) or 0)
        base_residency_mb = profile.estimate_base_residency_mb() if profile is not None else None
        if base_residency_mb is None or total_vram_mb <= 0:
            target = self.DEFAULT_VLLM_LOAD_GPU_UTIL
            return self._apply_vllm_load_floor(profile, target)

        fraction = base_residency_mb / total_vram_mb
        if fraction >= 0.60:
            target = 0.50
        elif fraction >= 0.45:
            target = 0.55
        elif fraction >= 0.30:
            target = 0.65
        elif fraction >= 0.15:
            target = 0.75
        else:
            target = 0.80
        target = max(self.GPU_UTIL_MIN, min(self.GPU_UTIL_MAX, target))
        return self._apply_vllm_load_floor(profile, target)

    def _apply_vllm_load_floor(self, profile: Optional[ModelProfile], target: float) -> float:
        if profile is None:
            return target
        floor = profile.min_gpu_memory_utilization_to_load
        if floor is None:
            return target
        return max(target, max(self.GPU_UTIL_MIN, min(self.GPU_UTIL_MAX, float(floor))))

    def _estimate_vllm_target_utilization(
        self,
        action: CapacityPlanAction,
        profile: Optional[ModelProfile],
    ) -> float:
        params = action.params or {}
        vllm_config = params.get("vllm_config") if isinstance(params.get("vllm_config"), dict) else {}
        target = vllm_config.get("gpu_memory_utilization")
        if target is None and action.action == "wake":
            target = profile.observed_gpu_memory_utilization if profile is not None else None
        if target is None:
            target = self._recommended_vllm_gpu_util(profile, None)
        return max(self.GPU_UTIL_MIN, min(self.GPU_UTIL_MAX, float(target)))

    def _estimate_action_vram(
        self,
        action: CapacityPlanAction,
        profile: Optional[ModelProfile],
        capacity,
    ) -> float:
        """Estimate VRAM cost of an action."""
        if (
            profile is not None
            and profile.engine == "vllm"
            and int(getattr(capacity, "total_vram_mb", 0) or 0) > 0
        ):
            target_util = self._estimate_vllm_target_utilization(action, profile)
            base_residency = float(profile.estimate_base_residency_mb() or 0.0)
            observed_reservation = float(profile.loaded_vram_mb or 0.0)
            observed_util = float(profile.observed_gpu_memory_utilization or 0.0)
            if observed_reservation > 0 and observed_util > 0:
                observed_kv_budget = float(profile.kv_budget_mb or max(observed_reservation - base_residency, 0.0))
                loaded_vram = base_residency + (observed_kv_budget * (target_util / observed_util))
            else:
                loaded_vram = max(base_residency, float(capacity.total_vram_mb) * target_util)
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

        command_map = {
            "sleep_l1": ("sleep_lane", {"lane_id": action.lane_id, "level": 1}),
            "sleep_l2": ("sleep_lane", {"lane_id": action.lane_id, "level": 2}),
            "wake": ("wake_lane", {"lane_id": action.lane_id}),
            "stop": ("delete_lane", {"lane_id": action.lane_id}),
            "load": ("apply_lanes", {"lanes": [{"model": action.model_name, **action.params}]}),
            "reconfigure_gpu_util": (
                "reconfigure_lane",
                {"lane_id": action.lane_id, **action.params},
            ),
        }

        command_entry = command_map.get(action.action)
        if command_entry is None:
            logger.warning("Unknown capacity action: %s", action.action)
            return False

        command_action, command_params = command_entry

        try:
            await self._registry.send_command(
                action.provider_id,
                command_action,
                command_params,
                timeout_seconds=int(min(timeout_seconds, 30)),
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
        if action.action == "reconfigure_gpu_util":
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
            "demand": self._demand.get_stats(),
        }
