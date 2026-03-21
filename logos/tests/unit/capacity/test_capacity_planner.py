"""Tests for CapacityPlanner decision logic."""

import time
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from logos.capacity.capacity_planner import CapacityPlanner
from logos.capacity.demand_tracker import DemandTracker
from logos.sdi.models import LaneSchedulerSignals, OllamaCapacity, ModelProfile


def _make_signal(
    lane_id="lane-1",
    model_name="model-a",
    runtime_state="loaded",
    sleep_state="awake",
    is_vllm=True,
    active_requests=0,
    queue_waiting=0.0,
    gpu_cache_usage_percent=None,
    gpu_memory_utilization=None,
    effective_vram_mb=8000.0,
):
    return LaneSchedulerSignals(
        lane_id=lane_id,
        model_name=model_name,
        runtime_state=runtime_state,
        sleep_state=sleep_state,
        is_vllm=is_vllm,
        active_requests=active_requests,
        queue_waiting=queue_waiting,
        requests_running=float(active_requests),
        gpu_cache_usage_percent=gpu_cache_usage_percent,
        ttft_p95_seconds=0.1,
        effective_vram_mb=effective_vram_mb,
        num_parallel=4,
        gpu_memory_utilization=gpu_memory_utilization,
    )


class MockFacade:
    def __init__(self, lanes=None, capacity=None, profiles=None, capabilities=None):
        self._lanes = lanes or []
        self._capacity = capacity or OllamaCapacity(
            available_vram_mb=32000, total_vram_mb=48000, loaded_models=[],
        )
        self._profiles = profiles or {}
        self._capabilities = capabilities or []

    def provider_ids(self):
        return [10]

    def get_all_provider_lane_signals(self, provider_id):
        return self._lanes

    def get_capacity_info(self, provider_id):
        return self._capacity

    def get_model_profiles(self, provider_id):
        return self._profiles

    def get_worker_capabilities(self, provider_id):
        return self._capabilities


class MockRegistry:
    def __init__(self):
        self.commands_sent = []
        self._snapshot = None

    async def send_command(self, provider_id, action, params=None, timeout_seconds=20):
        self.commands_sent.append({"provider_id": provider_id, "action": action, "params": params})
        return {"success": True}

    def peek_runtime_snapshot(self, provider_id):
        return self._snapshot

    async def select_lane_for_model(self, provider_id, model_name):  # noqa: ARG002
        runtime = ((self._snapshot or {}).get("runtime") or {})
        lanes = runtime.get("lanes") or []
        for lane in lanes:
            if lane.get("model") == model_name and lane.get("runtime_state") in {"loaded", "running", "cold", "starting"}:
                return lane
        return None


def _make_planner(facade=None, registry=None, demand=None, cycle_seconds=30.0):
    return CapacityPlanner(
        logosnode_facade=facade or MockFacade(),
        logosnode_registry=registry or MockRegistry(),
        demand_tracker=demand or DemandTracker(),
        cycle_seconds=cycle_seconds,
        enabled=True,
    )


# ---------------------------------------------------------------------------
# Idle tier transitions
# ---------------------------------------------------------------------------


def test_idle_sleep_l1_after_threshold():
    """Lane idle for > IDLE_SLEEP_L1 → sleep_l1 action."""
    lane = _make_signal(is_vllm=True, runtime_state="loaded", sleep_state="awake", active_requests=0)
    planner = _make_planner(facade=MockFacade(lanes=[lane]))

    # Simulate: lane has been idle for 61 seconds
    planner._lane_idle_since[(10, "lane-1")] = time.time() - 61

    actions = planner._compute_idle_actions(10, [lane])
    assert len(actions) == 1
    assert actions[0].action == "sleep_l1"
    assert actions[0].lane_id == "lane-1"


def test_idle_sleep_l2_after_threshold():
    """Lane sleeping L1 for > IDLE_SLEEP_L2 → sleep_l2 action."""
    lane = _make_signal(is_vllm=True, runtime_state="sleeping", sleep_state="sleeping", active_requests=0)
    planner = _make_planner(facade=MockFacade(lanes=[lane]))

    planner._lane_idle_since[(10, "lane-1")] = time.time() - 301

    actions = planner._compute_idle_actions(10, [lane])
    assert len(actions) == 1
    assert actions[0].action == "sleep_l2"


def test_idle_stop_requires_vram_pressure():
    """Lane idle for > IDLE_STOP without VRAM pressure → no stop, stays sleeping."""
    lane = _make_signal(is_vllm=True, runtime_state="sleeping", sleep_state="sleeping", active_requests=0)
    planner = _make_planner(facade=MockFacade(lanes=[lane]))

    planner._lane_idle_since[(10, "lane-1")] = time.time() - 901

    actions = planner._compute_idle_actions(10, [lane])
    # No stop action — only sleep_l2 deepening (which is fine, lane stays alive)
    assert all(a.action != "stop" for a in actions)
    # The sleeping lane gets deepened to L2 since 901 > IDLE_SLEEP_L2 (300)
    assert len(actions) == 1
    assert actions[0].action == "sleep_l2"


def test_idle_stop_with_vram_pressure():
    """Lane idle for > IDLE_STOP WITH VRAM pressure from another model → stop action."""
    lane = _make_signal(is_vllm=True, runtime_state="sleeping", sleep_state="sleeping", active_requests=0)
    demand = DemandTracker()
    # Another model has high demand but no lane → needs VRAM
    for _ in range(3):
        demand.record_request("other-model")
    planner = _make_planner(facade=MockFacade(lanes=[lane]), demand=demand)

    planner._lane_idle_since[(10, "lane-1")] = time.time() - 901

    actions = planner._compute_idle_actions(10, [lane])
    assert len(actions) == 1
    assert actions[0].action == "stop"


def test_idle_stop_with_low_vram():
    """Lane idle for > IDLE_STOP with low available VRAM and any other demand → stop."""
    lane = _make_signal(is_vllm=True, runtime_state="sleeping", sleep_state="sleeping", active_requests=0)
    demand = DemandTracker()
    demand.record_request("other-model")  # Any demand (score=1, below DEMAND_LOAD_THRESHOLD)
    facade = MockFacade(
        lanes=[lane],
        capacity=OllamaCapacity(available_vram_mb=3000, total_vram_mb=32768, loaded_models=[]),
    )
    planner = _make_planner(facade=facade, demand=demand)

    planner._lane_idle_since[(10, "lane-1")] = time.time() - 901

    actions = planner._compute_idle_actions(10, [lane])
    assert len(actions) == 1
    assert actions[0].action == "stop"


def test_no_idle_action_when_active():
    """Lane with active requests → no idle action."""
    lane = _make_signal(active_requests=3)
    planner = _make_planner(facade=MockFacade(lanes=[lane]))

    planner._update_idle_tracking(10, [lane])
    actions = planner._compute_idle_actions(10, [lane])
    assert actions == []


def test_no_sleep_for_ollama_lanes():
    """Ollama lanes don't support sleep. Stop only happens with VRAM pressure."""
    lane = _make_signal(is_vllm=False, runtime_state="loaded", sleep_state="unsupported")
    planner = _make_planner(facade=MockFacade(lanes=[lane]))

    # Idle for 61s — sleep threshold, but Ollama → no action
    planner._lane_idle_since[(10, "lane-1")] = time.time() - 61
    actions = planner._compute_idle_actions(10, [lane])
    assert actions == []

    # Idle for 901s — stop threshold, but no VRAM pressure → no action
    planner._lane_idle_since[(10, "lane-1")] = time.time() - 901
    actions = planner._compute_idle_actions(10, [lane])
    assert actions == []

    # Idle for 901s WITH VRAM pressure → stop action
    demand = DemandTracker()
    for _ in range(3):
        demand.record_request("other-model")
    planner_with_demand = _make_planner(facade=MockFacade(lanes=[lane]), demand=demand)
    planner_with_demand._lane_idle_since[(10, "lane-1")] = time.time() - 901
    actions = planner_with_demand._compute_idle_actions(10, [lane])
    assert len(actions) == 1
    assert actions[0].action == "stop"


# ---------------------------------------------------------------------------
# Demand-based actions
# ---------------------------------------------------------------------------


def test_demand_wake_sleeping_lane():
    """Demand above wake threshold with sleeping lane → wake action."""
    lane = _make_signal(model_name="model-a", runtime_state="sleeping", sleep_state="sleeping")
    demand = DemandTracker()
    demand.record_request("model-a")
    demand.record_request("model-a")  # score=2.0 > threshold

    planner = _make_planner(facade=MockFacade(lanes=[lane]), demand=demand)
    actions = planner._compute_demand_actions(10, [lane])
    assert len(actions) == 1
    assert actions[0].action == "wake"
    assert actions[0].model_name == "model-a"


def test_demand_load_new_model():
    """High demand for model not present → load action."""
    demand = DemandTracker()
    for _ in range(3):
        demand.record_request("model-b")  # score=3.0 > DEMAND_LOAD_THRESHOLD

    planner = _make_planner(facade=MockFacade(lanes=[]), demand=demand)
    actions = planner._compute_demand_actions(10, [])
    assert len(actions) == 1
    assert actions[0].action == "load"
    assert actions[0].model_name == "model-b"


def test_demand_below_threshold_no_action():
    """Low demand → no action."""
    demand = DemandTracker()
    demand.record_request("model-a")
    # Decay to push below threshold
    for _ in range(50):
        demand.decay_all()

    planner = _make_planner(demand=demand)
    actions = planner._compute_demand_actions(10, [])
    assert actions == []


# ---------------------------------------------------------------------------
# GPU utilization tuning
# ---------------------------------------------------------------------------


def test_kv_cache_increase_on_high_cache():
    """Cache > 85% → increase kv_cache_memory_bytes."""
    lane = _make_signal(is_vllm=True, gpu_cache_usage_percent=90.0, model_name="model-a")
    profile = ModelProfile(
        model_name="model-a", engine="vllm", kv_budget_mb=4096.0,
        base_residency_mb=14000.0,
    )
    planner = _make_planner(facade=MockFacade(lanes=[lane], profiles={"model-a": profile}))

    actions = planner._compute_kv_cache_tuning_actions(10, [lane])
    assert len(actions) == 1
    assert actions[0].action == "reconfigure_kv_cache"
    assert "kv_cache_memory_bytes" in actions[0].params["updates"]["vllm_config"]


def test_kv_cache_decrease_on_low_cache_with_demand():
    """Cache < 40% and other models have demand → decrease KV cache."""
    lane = _make_signal(
        model_name="model-a",
        is_vllm=True,
        gpu_cache_usage_percent=30.0,
    )
    profile = ModelProfile(
        model_name="model-a", engine="vllm", kv_budget_mb=4096.0,
        base_residency_mb=14000.0,
    )
    demand = DemandTracker()
    demand.record_request("model-b")  # Other model has demand

    planner = _make_planner(
        facade=MockFacade(lanes=[lane], profiles={"model-a": profile}),
        demand=demand,
    )
    actions = planner._compute_kv_cache_tuning_actions(10, [lane])
    assert len(actions) == 1
    assert actions[0].action == "reconfigure_kv_cache"


def test_kv_cache_no_decrease_without_competing_demand():
    """Cache low but no other demand → no action."""
    lane = _make_signal(model_name="model-a", is_vllm=True, gpu_cache_usage_percent=30.0)
    profile = ModelProfile(
        model_name="model-a", engine="vllm", kv_budget_mb=4096.0,
        base_residency_mb=14000.0,
    )
    planner = _make_planner(facade=MockFacade(lanes=[lane], profiles={"model-a": profile}))

    actions = planner._compute_kv_cache_tuning_actions(10, [lane])
    assert actions == []


def test_kv_cache_tuning_not_for_ollama():
    """Ollama lanes → no KV cache tuning."""
    lane = _make_signal(is_vllm=False, gpu_cache_usage_percent=95.0)
    planner = _make_planner()

    actions = planner._compute_kv_cache_tuning_actions(10, [lane])
    assert actions == []


# ---------------------------------------------------------------------------
# VRAM budget validation
# ---------------------------------------------------------------------------


def test_vram_budget_rejects_over_capacity():
    """Load action exceeding VRAM → rejected."""
    from logos.sdi.models import CapacityPlanAction

    facade = MockFacade(
        capacity=OllamaCapacity(available_vram_mb=5000, total_vram_mb=48000, loaded_models=[]),
        profiles={"big-model": ModelProfile(model_name="big-model", loaded_vram_mb=10000.0)},
    )
    planner = _make_planner(facade=facade)

    actions = [
        CapacityPlanAction(
            action="load", provider_id=10, lane_id="new",
            model_name="big-model", reason="test",
        ),
    ]
    validated = planner._validate_vram_budget(actions)
    # 5000 < 10000 * 1.1 → rejected
    load_actions = [a for a in validated if a.action == "load"]
    assert load_actions == []


def test_vram_budget_accepts_within_capacity():
    """Load action within VRAM → accepted."""
    from logos.sdi.models import CapacityPlanAction

    facade = MockFacade(
        capacity=OllamaCapacity(available_vram_mb=20000, total_vram_mb=48000, loaded_models=[]),
        profiles={"small-model": ModelProfile(model_name="small-model", loaded_vram_mb=6000.0)},
    )
    planner = _make_planner(facade=facade)

    actions = [
        CapacityPlanAction(
            action="load", provider_id=10, lane_id="new",
            model_name="small-model", reason="test",
        ),
    ]
    validated = planner._validate_vram_budget(actions)
    load_actions = [a for a in validated if a.action == "load"]
    assert len(load_actions) == 1


def test_vram_wake_costs_net_increase():
    """Wake action costs loaded_vram - sleeping_residual."""
    from logos.sdi.models import CapacityPlanAction

    facade = MockFacade(
        capacity=OllamaCapacity(available_vram_mb=5000, total_vram_mb=48000, loaded_models=[]),
        profiles={
            "model-a": ModelProfile(
                model_name="model-a",
                loaded_vram_mb=8000.0,
                sleeping_residual_mb=3500.0,
            ),
        },
    )
    planner = _make_planner(facade=facade)

    actions = [
        CapacityPlanAction(
            action="wake", provider_id=10, lane_id="lane-1",
            model_name="model-a", reason="test",
        ),
    ]
    validated = planner._validate_vram_budget(actions)
    # Net cost = 8000 - 3500 = 4500, with margin = 4500 * 1.1 = 4950, available = 5000 → accepted
    wake_actions = [a for a in validated if a.action == "wake"]
    assert len(wake_actions) == 1


def test_vllm_vram_estimate_uses_base_plus_kv():
    """vLLM load cost = base_residency + kv_cache (from action params or profile)."""
    from logos.sdi.models import CapacityPlanAction

    facade = MockFacade(
        capacity=OllamaCapacity(available_vram_mb=35000, total_vram_mb=48000, loaded_models=[]),
        profiles={
            "qwen-coder": ModelProfile(
                model_name="qwen-coder",
                loaded_vram_mb=30508.0,
                base_residency_mb=15000.0,
                kv_budget_mb=5000.0,
                engine="vllm",
                tensor_parallel_size=2,
            ),
        },
    )
    planner = _make_planner(facade=facade)

    # Action with explicit kv_cache_memory_bytes in vllm_config
    action_with_kv = CapacityPlanAction(
        action="load",
        provider_id=10,
        lane_id="planner-qwen",
        model_name="qwen-coder",
        params={
            "vllm": True,
            "vllm_config": {
                "gpu_memory_utilization": 0.95,
                "kv_cache_memory_bytes": "4G",
                "tensor_parallel_size": 2,
            },
        },
        reason="test",
    )
    profile = facade.get_model_profiles(10)["qwen-coder"]
    cap = facade.get_capacity_info(10)
    estimated = planner._estimate_action_vram(action_with_kv, profile, cap)
    # base=15000 + kv=4096MB (4G) = 19096
    assert abs(estimated - 19096.0) < 1.0

    # Action without kv_cache_memory_bytes → falls back to profile's kv_budget_mb
    action_no_kv = CapacityPlanAction(
        action="load",
        provider_id=10,
        lane_id="planner-qwen",
        model_name="qwen-coder",
        params={"vllm": True, "vllm_config": {"gpu_memory_utilization": 0.95}},
        reason="test",
    )
    estimated2 = planner._estimate_action_vram(action_no_kv, profile, cap)
    # base=15000 + kv_budget=5000 = 20000
    assert abs(estimated2 - 20000.0) < 1.0


def test_vllm_load_params_are_built_from_profile():
    """Planner load action should carry lane_id and vLLM params when the model profile says vLLM."""
    demand = DemandTracker()
    for _ in range(3):
        demand.record_request("qwen-coder")

    facade = MockFacade(
        profiles={
            "qwen-coder": ModelProfile(
                model_name="qwen-coder",
                engine="vllm",
                base_residency_mb=15000.0,
                tensor_parallel_size=2,
            ),
        },
        capacity=OllamaCapacity(available_vram_mb=32000, total_vram_mb=32768, loaded_models=[]),
    )
    planner = _make_planner(facade=facade, demand=demand)

    actions = planner._compute_demand_actions(10, [])
    assert len(actions) == 1
    action = actions[0]
    assert action.action == "load"
    assert action.params["lane_id"] == action.lane_id
    assert action.params["vllm"] is True
    # gpu_memory_utilization is 0.70 when kv_cache_memory_bytes is set (startup guard bypass)
    assert action.params["vllm_config"]["gpu_memory_utilization"] == 0.70
    assert action.params["vllm_config"]["tensor_parallel_size"] == 2
    # kv_cache_memory_bytes = base_residency * 0.35 = 15000 * 0.35 = 5250 MB
    kv_str = action.params["vllm_config"]["kv_cache_memory_bytes"]
    assert kv_str  # should be set
    kv_mb = CapacityPlanner._parse_kv_cache_to_mb(kv_str)
    assert abs(kv_mb - 5250.0) < 10


def test_kv_cache_bytes_from_observed_budget():
    """When profile has observed kv_budget_mb, use it directly."""
    planner = _make_planner()
    profile = ModelProfile(
        model_name="qwen-7b",
        engine="vllm",
        base_residency_mb=15000.0,
        kv_budget_mb=8000.0,
        tensor_parallel_size=1,
    )
    capacity = OllamaCapacity(available_vram_mb=32000, total_vram_mb=32768, loaded_models=[])
    kv = planner._compute_kv_cache_bytes(profile, capacity)
    assert kv is not None
    kv_mb = CapacityPlanner._parse_kv_cache_to_mb(kv)
    assert abs(kv_mb - 8000.0) < 10


def test_kv_cache_bytes_from_headroom_ratio():
    """When no observed kv_budget, estimate from base_residency * 0.35."""
    planner = _make_planner()
    profile = ModelProfile(
        model_name="tiny-1b",
        engine="vllm",
        base_residency_mb=4000.0,
        tensor_parallel_size=1,
    )
    capacity = OllamaCapacity(available_vram_mb=32000, total_vram_mb=32768, loaded_models=[])
    kv = planner._compute_kv_cache_bytes(profile, capacity)
    assert kv is not None
    kv_mb = CapacityPlanner._parse_kv_cache_to_mb(kv)
    assert abs(kv_mb - 1400.0) < 10  # 4000 * 0.35 = 1400


def test_kv_cache_bytes_none_when_no_profile():
    """No profile → return None, let vLLM decide."""
    planner = _make_planner()
    assert planner._compute_kv_cache_bytes(None, None) is None


def test_gpu_util_always_ceiling():
    """_recommended_vllm_gpu_util always returns GPU_UTIL_MAX (0.95)."""
    planner = _make_planner()
    profile = ModelProfile(
        model_name="qwen-coder",
        engine="vllm",
        base_residency_mb=4000.0,
        tensor_parallel_size=1,
    )
    capacity = OllamaCapacity(available_vram_mb=32000, total_vram_mb=32768, loaded_models=[])
    assert planner._recommended_vllm_gpu_util(profile, capacity) == 0.95


@pytest.mark.asyncio
async def test_prepare_lane_for_request_wakes_sleeping_lane():
    lane = _make_signal(
        lane_id="lane-sleep",
        model_name="qwen-coder",
        runtime_state="sleeping",
        sleep_state="sleeping",
        is_vllm=True,
    )
    facade = MockFacade(
        lanes=[lane],
        capacity=OllamaCapacity(available_vram_mb=24000, total_vram_mb=32768, loaded_models=[]),
        profiles={
            "qwen-coder": ModelProfile(
                model_name="qwen-coder",
                loaded_vram_mb=12000.0,
                sleeping_residual_mb=2000.0,
                base_residency_mb=7000.0,
                kv_budget_mb=5000.0,
                engine="vllm",
                observed_gpu_memory_utilization=0.8,
            ),
        },
    )
    registry = MockRegistry()
    registry._snapshot = {
        "runtime": {
            "lanes": [
                {
                    "lane_id": "lane-sleep",
                    "model": "qwen-coder",
                    "runtime_state": "sleeping",
                    "sleep_state": "sleeping",
                }
            ]
        }
    }
    planner = _make_planner(facade=facade, registry=registry)

    async def _fake_execute(action, timeout_seconds=60.0):  # noqa: ARG001
        assert action.action == "wake"
        registry._snapshot["runtime"]["lanes"][0]["runtime_state"] = "loaded"
        registry._snapshot["runtime"]["lanes"][0]["sleep_state"] = "awake"
        return True

    planner._execute_action_with_confirmation = _fake_execute
    selected = await planner.prepare_lane_for_request(10, "qwen-coder")
    assert selected is not None
    assert selected["lane_id"] == "lane-sleep"
    assert selected["runtime_state"] == "loaded"


@pytest.mark.asyncio
async def test_prepare_lane_for_request_reclaims_idle_competitor_first():
    target = _make_signal(
        lane_id="lane-target",
        model_name="qwen-coder",
        runtime_state="sleeping",
        sleep_state="sleeping",
        is_vllm=True,
        effective_vram_mb=2000.0,
    )
    victim = _make_signal(
        lane_id="lane-victim",
        model_name="llama",
        runtime_state="loaded",
        sleep_state="awake",
        is_vllm=True,
        effective_vram_mb=12000.0,
    )
    facade = MockFacade(
        lanes=[target, victim],
        capacity=OllamaCapacity(available_vram_mb=5000, total_vram_mb=32768, loaded_models=[]),
        profiles={
            "qwen-coder": ModelProfile(
                model_name="qwen-coder",
                loaded_vram_mb=12000.0,
                sleeping_residual_mb=2000.0,
                base_residency_mb=7000.0,
                kv_budget_mb=5000.0,
                engine="vllm",
                observed_gpu_memory_utilization=0.8,
            ),
            "llama": ModelProfile(
                model_name="llama",
                loaded_vram_mb=12000.0,
                sleeping_residual_mb=1000.0,
                base_residency_mb=7000.0,
                kv_budget_mb=5000.0,
                engine="vllm",
                observed_gpu_memory_utilization=0.8,
            ),
        },
    )
    registry = MockRegistry()
    registry._snapshot = {
        "runtime": {
            "lanes": [
                {"lane_id": "lane-target", "model": "qwen-coder", "runtime_state": "sleeping", "sleep_state": "sleeping"},
                {"lane_id": "lane-victim", "model": "llama", "runtime_state": "loaded", "sleep_state": "awake"},
            ]
        }
    }
    planner = _make_planner(facade=facade, registry=registry)
    actions = []

    async def _fake_execute(action, timeout_seconds=60.0):  # noqa: ARG001
        actions.append(action.action)
        if action.action == "sleep_l1":
            facade._lanes[1] = _make_signal(
                lane_id="lane-victim",
                model_name="llama",
                runtime_state="sleeping",
                sleep_state="sleeping",
                is_vllm=True,
                effective_vram_mb=1000.0,
            )
            facade._capacity = OllamaCapacity(available_vram_mb=16000, total_vram_mb=32768, loaded_models=[])
            registry._snapshot["runtime"]["lanes"][1]["runtime_state"] = "sleeping"
            registry._snapshot["runtime"]["lanes"][1]["sleep_state"] = "sleeping"
            return True
        if action.action == "wake":
            registry._snapshot["runtime"]["lanes"][0]["runtime_state"] = "loaded"
            registry._snapshot["runtime"]["lanes"][0]["sleep_state"] = "awake"
            return True
        return True

    planner._execute_action_with_confirmation = _fake_execute
    selected = await planner.prepare_lane_for_request(10, "qwen-coder")
    assert selected is not None
    assert selected["lane_id"] == "lane-target"
    assert actions == ["sleep_l1", "wake"]


def test_vram_no_profile_uses_fallback():
    """No profile → conservative 4096 MB estimate."""
    from logos.sdi.models import CapacityPlanAction

    facade = MockFacade(
        capacity=OllamaCapacity(available_vram_mb=3000, total_vram_mb=48000, loaded_models=[]),
    )
    planner = _make_planner(facade=facade)

    actions = [
        CapacityPlanAction(
            action="load", provider_id=10, lane_id="new",
            model_name="unknown-model", reason="test",
        ),
    ]
    validated = planner._validate_vram_budget(actions)
    # 3000 < 4096 * 1.1 = 4505 → rejected
    load_actions = [a for a in validated if a.action == "load"]
    assert load_actions == []


def test_vram_cumulative_tracking():
    """Second action tracked against remaining VRAM after first."""
    from logos.sdi.models import CapacityPlanAction

    facade = MockFacade(
        capacity=OllamaCapacity(available_vram_mb=15000, total_vram_mb=48000, loaded_models=[]),
        profiles={
            "model-a": ModelProfile(model_name="model-a", loaded_vram_mb=6000.0),
            "model-b": ModelProfile(model_name="model-b", loaded_vram_mb=6000.0),
        },
    )
    planner = _make_planner(facade=facade)

    actions = [
        CapacityPlanAction(action="load", provider_id=10, lane_id="new-a", model_name="model-a", reason=""),
        CapacityPlanAction(action="load", provider_id=10, lane_id="new-b", model_name="model-b", reason=""),
    ]
    validated = planner._validate_vram_budget(actions)
    load_actions = [a for a in validated if a.action == "load"]
    # 15000 - 6000 = 9000 remaining after first. 9000 >= 6000*1.1=6600 → both accepted
    assert len(load_actions) == 2


def test_sleep_stop_always_allowed():
    """Sleep/stop actions always pass VRAM validation."""
    from logos.sdi.models import CapacityPlanAction

    facade = MockFacade(
        capacity=OllamaCapacity(available_vram_mb=0, total_vram_mb=48000, loaded_models=[]),
    )
    planner = _make_planner(facade=facade)

    actions = [
        CapacityPlanAction(action="sleep_l1", provider_id=10, lane_id="lane-1", model_name="model-a", reason=""),
        CapacityPlanAction(action="stop", provider_id=10, lane_id="lane-2", model_name="model-b", reason=""),
    ]
    validated = planner._validate_vram_budget(actions)
    assert len(validated) == 2


# ---------------------------------------------------------------------------
# Worker offline handling
# ---------------------------------------------------------------------------


def test_worker_offline_skipped_gracefully():
    """Provider offline → skipped, planner continues."""
    class OfflineFacade(MockFacade):
        def get_all_provider_lane_signals(self, provider_id):
            raise ConnectionError("worker offline")

    planner = _make_planner(facade=OfflineFacade())

    # Should not raise
    import asyncio
    asyncio.get_event_loop().run_until_complete(planner._run_cycle())


# ---------------------------------------------------------------------------
# Confirmation timeout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirmation_timeout_returns_false():
    """Snapshot never shows expected state → returns False."""
    from logos.sdi.models import CapacityPlanAction

    registry = MockRegistry()
    registry._snapshot = {
        "runtime": {
            "lanes": [
                {"lane_id": "lane-1", "runtime_state": "loaded", "sleep_state": "awake"},
            ],
        },
    }
    planner = _make_planner(registry=registry)

    action = CapacityPlanAction(
        action="sleep_l1", provider_id=10, lane_id="lane-1",
        model_name="model-a", reason="test",
    )

    # With very short timeout → should return False (lane never shows sleeping)
    result = await planner._execute_action_with_confirmation(action, timeout_seconds=3.0)
    assert result is False
    assert len(registry.commands_sent) == 1


@pytest.mark.asyncio
async def test_confirmation_success():
    """Snapshot shows expected state → returns True."""
    from logos.sdi.models import CapacityPlanAction

    registry = MockRegistry()
    # After command, lane transitions to sleeping
    registry._snapshot = {
        "runtime": {
            "lanes": [
                {"lane_id": "lane-1", "runtime_state": "sleeping", "sleep_state": "sleeping"},
            ],
        },
    }
    planner = _make_planner(registry=registry)

    action = CapacityPlanAction(
        action="sleep_l1", provider_id=10, lane_id="lane-1",
        model_name="model-a", reason="test",
    )

    result = await planner._execute_action_with_confirmation(action, timeout_seconds=5.0)
    assert result is True


@pytest.mark.asyncio
async def test_stop_confirmation_lane_gone():
    """Stop action confirmed when lane disappears from snapshot."""
    from logos.sdi.models import CapacityPlanAction

    registry = MockRegistry()
    registry._snapshot = {
        "runtime": {"lanes": []},  # Lane is gone
    }
    planner = _make_planner(registry=registry)

    action = CapacityPlanAction(
        action="stop", provider_id=10, lane_id="lane-1",
        model_name="model-a", reason="test",
    )

    result = await planner._execute_action_with_confirmation(action, timeout_seconds=5.0)
    assert result is True


# ---------------------------------------------------------------------------
# Active-request guards on idle actions
# ---------------------------------------------------------------------------


def test_idle_sleep_skips_active_requests():
    """Lane with active_requests > 0 should NOT be slept even if idle timer expired."""
    lane = _make_signal(is_vllm=True, runtime_state="loaded", sleep_state="awake", active_requests=2)
    planner = _make_planner(facade=MockFacade(lanes=[lane]))

    # Idle timer says 61s, but lane has active requests
    planner._lane_idle_since[(10, "lane-1")] = time.time() - 61

    actions = planner._compute_idle_actions(10, [lane])
    assert actions == []


def test_idle_stop_skips_active_requests():
    """Lane with active_requests > 0 should NOT be stopped even if idle timer expired."""
    lane = _make_signal(is_vllm=True, runtime_state="loaded", sleep_state="awake", active_requests=1)
    planner = _make_planner(facade=MockFacade(lanes=[lane]))

    planner._lane_idle_since[(10, "lane-1")] = time.time() - 901

    actions = planner._compute_idle_actions(10, [lane])
    assert actions == []


def test_idle_sleep_l2_skips_active_requests():
    """Sleeping lane with active_requests > 0 should NOT be deepened to L2."""
    lane = _make_signal(is_vllm=True, runtime_state="sleeping", sleep_state="sleeping", active_requests=1)
    planner = _make_planner(facade=MockFacade(lanes=[lane]))

    planner._lane_idle_since[(10, "lane-1")] = time.time() - 301

    actions = planner._compute_idle_actions(10, [lane])
    assert actions == []


# ---------------------------------------------------------------------------
# Request-time cold load
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prepare_lane_cold_load():
    """When no lane exists, prepare_lane_for_request cold-loads the model."""
    facade = MockFacade(
        lanes=[],  # No lanes at all
        capacity=OllamaCapacity(available_vram_mb=24000, total_vram_mb=32768, loaded_models=[]),
        profiles={
            "qwen-coder": ModelProfile(
                model_name="qwen-coder",
                loaded_vram_mb=12000.0,
                base_residency_mb=7000.0,
                engine="vllm",
                observed_gpu_memory_utilization=0.8,
                tensor_parallel_size=1,
            ),
        },
    )
    registry = MockRegistry()
    registry._snapshot = {
        "runtime": {"lanes": []}
    }
    planner = _make_planner(facade=facade, registry=registry)
    actions = []

    async def _fake_execute(action, timeout_seconds=60.0):  # noqa: ARG001
        actions.append(action.action)
        if action.action == "load":
            registry._snapshot = {
                "runtime": {
                    "lanes": [
                        {
                            "lane_id": action.lane_id,
                            "model": "qwen-coder",
                            "runtime_state": "loaded",
                            "sleep_state": "awake",
                        }
                    ]
                }
            }
            return True
        return True

    planner._execute_action_with_confirmation = _fake_execute
    selected = await planner.prepare_lane_for_request(10, "qwen-coder")
    assert selected is not None
    assert selected["model"] == "qwen-coder"
    assert "load" in actions


@pytest.mark.asyncio
async def test_prepare_lane_cold_load_insufficient_vram():
    """Cold load is rejected when VRAM budget is insufficient and no reclaimable lanes."""
    facade = MockFacade(
        lanes=[],
        capacity=OllamaCapacity(available_vram_mb=2000, total_vram_mb=32768, loaded_models=[]),
        profiles={
            "big-model": ModelProfile(
                model_name="big-model",
                loaded_vram_mb=30000.0,
                base_residency_mb=25000.0,
            ),
        },
    )
    registry = MockRegistry()
    registry._snapshot = {"runtime": {"lanes": []}}
    planner = _make_planner(facade=facade, registry=registry)

    selected = await planner.prepare_lane_for_request(10, "big-model")
    assert selected is None


# ---------------------------------------------------------------------------
# Preemptive load-then-sleep
# ---------------------------------------------------------------------------


def test_preemptive_sleep_loads_previously_served_model():
    """Model with known sleeping_residual_mb and no lane → load + sleep_l1 actions."""
    facade = MockFacade(
        lanes=[],  # No lanes running
        capacity=OllamaCapacity(available_vram_mb=24000, total_vram_mb=32768, loaded_models=[]),
        profiles={
            "qwen-coder": ModelProfile(
                model_name="qwen-coder",
                loaded_vram_mb=12000.0,
                sleeping_residual_mb=2000.0,
                base_residency_mb=7000.0,
                engine="vllm",
                observed_gpu_memory_utilization=0.8,
                tensor_parallel_size=1,
            ),
        },
    )
    demand = DemandTracker()
    demand.record_request("qwen-coder")  # Some demand
    planner = _make_planner(facade=facade, demand=demand)

    actions = planner._compute_preemptive_sleep_actions(10, [])
    assert len(actions) == 2
    assert actions[0].action == "load"
    assert actions[0].model_name == "qwen-coder"
    assert actions[1].action == "sleep_l1"
    assert actions[1].model_name == "qwen-coder"


def test_preemptive_sleep_skips_non_vllm():
    """Ollama models don't support sleep, so they shouldn't be preemptively loaded."""
    facade = MockFacade(
        lanes=[],
        capacity=OllamaCapacity(available_vram_mb=24000, total_vram_mb=32768, loaded_models=[]),
        profiles={
            "ollama-model": ModelProfile(
                model_name="ollama-model",
                loaded_vram_mb=4000.0,
                sleeping_residual_mb=500.0,
                engine="ollama",
            ),
        },
    )
    demand = DemandTracker()
    demand.record_request("ollama-model")
    planner = _make_planner(facade=facade, demand=demand)

    actions = planner._compute_preemptive_sleep_actions(10, [])
    assert actions == []


def test_preemptive_sleep_skips_when_vram_tight():
    """Don't preemptively load when VRAM headroom is below 20%."""
    facade = MockFacade(
        lanes=[],
        capacity=OllamaCapacity(available_vram_mb=5000, total_vram_mb=32768, loaded_models=[]),
        profiles={
            "qwen-coder": ModelProfile(
                model_name="qwen-coder",
                loaded_vram_mb=12000.0,
                sleeping_residual_mb=2000.0,
                base_residency_mb=7000.0,
                engine="vllm",
            ),
        },
    )
    planner = _make_planner(facade=facade)

    actions = planner._compute_preemptive_sleep_actions(10, [])
    assert actions == []


def test_preemptive_sleep_skips_model_with_active_lane():
    """Don't preemptively load a model that already has a lane."""
    lane = _make_signal(model_name="qwen-coder", runtime_state="sleeping", sleep_state="sleeping")
    facade = MockFacade(
        lanes=[lane],
        capacity=OllamaCapacity(available_vram_mb=24000, total_vram_mb=32768, loaded_models=[]),
        profiles={
            "qwen-coder": ModelProfile(
                model_name="qwen-coder",
                sleeping_residual_mb=2000.0,
                engine="vllm",
            ),
        },
    )
    planner = _make_planner(facade=facade)

    actions = planner._compute_preemptive_sleep_actions(10, [lane])
    assert actions == []


# ---------------------------------------------------------------------------
# Capability seeding
# ---------------------------------------------------------------------------

def test_capability_seeding_zero_lane_worker():
    """Worker with zero lanes but capabilities should get load actions for in-demand models."""
    demand = DemandTracker()
    demand.record_request("qwen-coder")

    facade = MockFacade(
        lanes=[],
        capacity=OllamaCapacity(available_vram_mb=32000, total_vram_mb=48000, loaded_models=[]),
        profiles={},
        capabilities=["qwen-coder", "llama-8b"],
    )
    planner = _make_planner(facade=facade, demand=demand)

    actions = planner._compute_demand_actions(10, [])
    # qwen-coder has demand, llama-8b doesn't
    load_actions = [a for a in actions if a.action == "load"]
    assert len(load_actions) == 1
    assert load_actions[0].model_name == "qwen-coder"
    assert "Capability seeding" in load_actions[0].reason


def test_capability_seeding_skips_when_lanes_exist():
    """Worker with existing lanes should not trigger capability seeding."""
    demand = DemandTracker()
    demand.record_request("qwen-coder")

    lane = _make_signal(model_name="other-model", runtime_state="loaded")
    facade = MockFacade(
        lanes=[lane],
        capacity=OllamaCapacity(available_vram_mb=32000, total_vram_mb=48000, loaded_models=[]),
        profiles={},
        capabilities=["qwen-coder"],
    )
    planner = _make_planner(facade=facade, demand=demand)

    actions = planner._compute_demand_actions(10, [lane])
    # Normal demand load might fire (score >= 2.0), but capability seeding should not
    cap_actions = [a for a in actions if "Capability seeding" in (a.reason or "")]
    assert cap_actions == []


def test_capability_seeding_no_demand():
    """Capabilities with no demand should not trigger load."""
    facade = MockFacade(
        lanes=[],
        capabilities=["qwen-coder"],
    )
    planner = _make_planner(facade=facade)

    actions = planner._compute_demand_actions(10, [])
    assert actions == []


# ---------------------------------------------------------------------------
# Feasibility check
# ---------------------------------------------------------------------------

def test_feasibility_rejects_oom():
    """Model too large for available VRAM → feasibility fails."""
    planner = _make_planner()
    profile = ModelProfile(
        model_name="huge-model",
        engine="vllm",
        base_residency_mb=40000.0,
    )
    capacity = OllamaCapacity(available_vram_mb=20000, total_vram_mb=24000, loaded_models=[])
    assert not planner._passes_minimum_load_feasibility("huge-model", profile, capacity)


def test_feasibility_passes():
    """Model fits in available VRAM → feasibility passes."""
    planner = _make_planner()
    profile = ModelProfile(
        model_name="small-model",
        engine="vllm",
        base_residency_mb=5000.0,
        kv_budget_mb=2000.0,
    )
    capacity = OllamaCapacity(available_vram_mb=20000, total_vram_mb=24000, loaded_models=[])
    assert planner._passes_minimum_load_feasibility("small-model", profile, capacity)


def test_feasibility_no_profile_allows():
    """No profile → can't estimate, allow the load."""
    planner = _make_planner()
    capacity = OllamaCapacity(available_vram_mb=20000, total_vram_mb=24000, loaded_models=[])
    assert planner._passes_minimum_load_feasibility("unknown-model", None, capacity)


# ---------------------------------------------------------------------------
# Exact KV cache from kv_per_token_bytes
# ---------------------------------------------------------------------------

def test_kv_cache_from_per_token_calculation():
    """KV cache computed from kv_per_token_bytes × context × concurrency."""
    planner = _make_planner()
    # Qwen2.5-7B: 57344 bytes/token × 8192 ctx × 4 seq = 1,879,048,192 bytes ≈ 1792M
    profile = ModelProfile(
        model_name="qwen-7b",
        engine="vllm",
        kv_per_token_bytes=57344,
        max_context_length=32768,
        base_residency_mb=15000.0,
    )
    kv = planner._compute_kv_cache_bytes(profile)
    assert kv is not None
    kv_mb = CapacityPlanner._parse_kv_cache_to_mb(kv)
    # 57344 * 8192 * 4 / 1024² = 1792 MB (context capped at DEFAULT_CONTEXT_CAP=8192)
    assert abs(kv_mb - 1792.0) < 10


def test_kv_cache_observed_budget_takes_priority():
    """Observed kv_budget_mb takes priority over per-token calculation."""
    planner = _make_planner()
    profile = ModelProfile(
        model_name="qwen-7b",
        engine="vllm",
        kv_budget_mb=5000.0,
        kv_per_token_bytes=57344,
        max_context_length=32768,
        base_residency_mb=15000.0,
    )
    kv = planner._compute_kv_cache_bytes(profile)
    assert kv is not None
    kv_mb = CapacityPlanner._parse_kv_cache_to_mb(kv)
    assert abs(kv_mb - 5000.0) < 10  # uses observed, not calculated


def test_kv_cache_falls_back_to_headroom_ratio():
    """Without kv_per_token or observed budget, falls back to headroom ratio."""
    planner = _make_planner()
    profile = ModelProfile(
        model_name="unknown-model",
        engine="vllm",
        base_residency_mb=10000.0,
    )
    kv = planner._compute_kv_cache_bytes(profile)
    assert kv is not None
    kv_mb = CapacityPlanner._parse_kv_cache_to_mb(kv)
    assert abs(kv_mb - 3500.0) < 10  # 10000 * 0.35


def test_feasibility_uses_per_token_kv():
    """Feasibility check uses kv_per_token_bytes when available."""
    planner = _make_planner()
    # Gemma2-2B: 106496 bytes/token × 8192 × 4 = ~3.2 GB KV
    profile = ModelProfile(
        model_name="gemma2-2b",
        engine="vllm",
        base_residency_mb=5000.0,
        kv_per_token_bytes=106496,
        max_context_length=8192,
    )
    # Need: 5000 + 3328 ≈ 8328 MB × 1.1 margin ≈ 9161 MB
    capacity_ok = OllamaCapacity(available_vram_mb=10000, total_vram_mb=24000, loaded_models=[])
    assert planner._passes_minimum_load_feasibility("gemma2-2b", profile, capacity_ok)

    capacity_tight = OllamaCapacity(available_vram_mb=8000, total_vram_mb=24000, loaded_models=[])
    assert not planner._passes_minimum_load_feasibility("gemma2-2b", profile, capacity_tight)


# ---------------------------------------------------------------------------
# Sleep-before-reconfigure
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reconfigure_kv_cache_sleeps_before_restart():
    """reconfigure_kv_cache should sleep the lane before sending reconfigure_lane."""
    from logos.sdi.models import CapacityPlanAction

    registry = MockRegistry()
    # Set up snapshot so confirmation polling sees loaded state
    registry._snapshot = {
        "runtime": {
            "lanes": [{"lane_id": "lane-1", "runtime_state": "loaded", "model": "model-a"}]
        }
    }
    planner = _make_planner(registry=registry)

    action = CapacityPlanAction(
        action="reconfigure_kv_cache",
        provider_id=10,
        lane_id="lane-1",
        model_name="model-a",
        params={"updates": {"vllm_config": {"kv_cache_memory_bytes": "2048M"}}},
        reason="test",
    )

    result = await planner._execute_action_with_confirmation(action, timeout_seconds=5.0)
    assert result is True

    # Verify: first command is sleep_lane, second is reconfigure_lane
    assert len(registry.commands_sent) == 2
    assert registry.commands_sent[0]["action"] == "sleep_lane"
    assert registry.commands_sent[0]["params"]["lane_id"] == "lane-1"
    assert registry.commands_sent[0]["params"]["mode"] == "wait"
    assert registry.commands_sent[1]["action"] == "reconfigure_lane"
    assert registry.commands_sent[1]["params"]["lane_id"] == "lane-1"
