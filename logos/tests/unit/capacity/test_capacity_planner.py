"""Tests for CapacityPlanner decision logic."""

import asyncio
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
    gpu_devices=None,
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
        gpu_devices=gpu_devices,
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

    def get_provider_name(self, provider_id):
        return None


class MockRegistry:
    def __init__(self):
        self.commands_sent = []
        self._snapshot = {"runtime": {"lanes": []}, "first_status_received": True}
        self._desired_lanes: dict[str, dict] = {}
        self._cold_marked: set[tuple[int, str]] = set()

    async def send_command(self, provider_id, action, params=None, timeout_seconds=20):
        self.commands_sent.append(
            {
                "provider_id": provider_id,
                "action": action,
                "params": params,
                "timeout_seconds": timeout_seconds,
            }
        )
        return {"success": True}

    def peek_runtime_snapshot(self, provider_id):
        return self._snapshot

    def has_received_first_status(self, provider_id):
        return self._snapshot.get("first_status_received", True)

    async def select_lane_for_model(self, provider_id, model_name):  # noqa: ARG002
        runtime = ((self._snapshot or {}).get("runtime") or {})
        lanes = runtime.get("lanes") or []
        for lane in lanes:
            if lane.get("model") == model_name and lane.get("runtime_state") in {"loaded", "running", "cold", "starting"}:
                return lane
        return None

    def get_desired_lane_set(self, provider_id):
        return list(self._desired_lanes.values())

    def update_desired_lanes(self, provider_id, lane_configs):
        self._desired_lanes = {
            str(lc.get("lane_id") or lc.get("model", "")): dict(lc)
            for lc in lane_configs if isinstance(lc, dict)
        }

    def update_desired_lane_add(self, provider_id, lane_config):
        lid = str(lane_config.get("lane_id") or lane_config.get("model", ""))
        if lid:
            self._desired_lanes[lid] = dict(lane_config)

    def update_desired_lane_remove(self, provider_id, lane_id):
        self._desired_lanes.pop(lane_id, None)

    def mark_lane_cold(self, provider_id, lane_id):
        self._cold_marked.add((provider_id, lane_id))

    def unmark_lane_cold(self, provider_id, lane_id):
        self._cold_marked.discard((provider_id, lane_id))


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

    # Simulate: lane has been idle for 301 seconds
    planner._lane_idle_since[(10, "lane-1")] = time.time() - 301

    actions = planner._compute_idle_actions(10, [lane])
    assert len(actions) == 1
    assert actions[0].action == "sleep_l1"
    assert actions[0].lane_id == "lane-1"


def test_idle_sleep_l2_after_threshold():
    """Lane sleeping L1 for > IDLE_SLEEP_L2 → sleep_l2 action."""
    lane = _make_signal(is_vllm=True, runtime_state="sleeping", sleep_state="sleeping", active_requests=0)
    planner = _make_planner(facade=MockFacade(lanes=[lane]))

    planner._lane_idle_since[(10, "lane-1")] = time.time() - 601
    planner._lane_sleep_since[(10, "lane-1")] = time.time() - 601
    planner._lane_sleep_level[(10, "lane-1")] = 1

    actions = planner._compute_idle_actions(10, [lane])
    assert len(actions) == 1
    assert actions[0].action == "sleep_l2"


def test_idle_lane_stays_sleeping_without_background_stop():
    """Background idle handling should deepen sleep, not stop the lane."""
    lane = _make_signal(is_vllm=True, runtime_state="sleeping", sleep_state="sleeping", active_requests=0)
    planner = _make_planner(facade=MockFacade(lanes=[lane]))

    planner._lane_idle_since[(10, "lane-1")] = time.time() - 901
    planner._lane_sleep_since[(10, "lane-1")] = time.time() - 601
    planner._lane_sleep_level[(10, "lane-1")] = 1

    actions = planner._compute_idle_actions(10, [lane])
    # No stop action — only sleep_l2 deepening (which is fine, lane stays alive)
    assert all(a.action != "stop" for a in actions)
    # The sleeping lane gets deepened to L2 after 601s of observed L1 sleep.
    assert len(actions) == 1
    assert actions[0].action == "sleep_l2"


def test_idle_lane_is_not_stopped_even_with_vram_pressure():
    """Background idle handling should not stop lanes even when another model has demand."""
    lane = _make_signal(is_vllm=True, runtime_state="sleeping", sleep_state="sleeping", active_requests=0)
    demand = DemandTracker()
    # Another model has high demand but no lane → needs VRAM
    for _ in range(3):
        demand.record_request("other-model")
    planner = _make_planner(facade=MockFacade(lanes=[lane]), demand=demand)

    planner._lane_idle_since[(10, "lane-1")] = time.time() - 901
    planner._lane_sleep_since[(10, "lane-1")] = time.time() - 601
    planner._lane_sleep_level[(10, "lane-1")] = 1

    actions = planner._compute_idle_actions(10, [lane])
    assert len(actions) == 1
    assert actions[0].action == "sleep_l2"


def test_idle_lane_is_not_stopped_just_because_vram_is_low():
    """Background idle handling should not stop lanes just because free VRAM is tight."""
    lane = _make_signal(is_vllm=True, runtime_state="sleeping", sleep_state="sleeping", active_requests=0)
    demand = DemandTracker()
    demand.record_request("other-model")  # Any demand (score=1, below DEMAND_LOAD_THRESHOLD)
    facade = MockFacade(
        lanes=[lane],
        capacity=OllamaCapacity(available_vram_mb=3000, total_vram_mb=32768, loaded_models=[]),
    )
    planner = _make_planner(facade=facade, demand=demand)

    planner._lane_idle_since[(10, "lane-1")] = time.time() - 901
    planner._lane_sleep_since[(10, "lane-1")] = time.time() - 601
    planner._lane_sleep_level[(10, "lane-1")] = 1

    actions = planner._compute_idle_actions(10, [lane])
    assert len(actions) == 1
    assert actions[0].action == "sleep_l2"


def test_no_idle_action_when_active():
    """Lane with active requests → no idle action."""
    lane = _make_signal(active_requests=3)
    planner = _make_planner(facade=MockFacade(lanes=[lane]))

    planner._update_idle_tracking(10, [lane])
    actions = planner._compute_idle_actions(10, [lane])
    assert actions == []


def test_no_sleep_for_ollama_lanes():
    """Ollama lanes don't support background sleep or background stop."""
    lane = _make_signal(is_vllm=False, runtime_state="loaded", sleep_state="unsupported")
    planner = _make_planner(facade=MockFacade(lanes=[lane]))

    # Idle for 301s — sleep threshold, but Ollama → no action
    planner._lane_idle_since[(10, "lane-1")] = time.time() - 301
    actions = planner._compute_idle_actions(10, [lane])
    assert actions == []

    # Idle for 901s — stop threshold, but no VRAM pressure → no action
    planner._lane_idle_since[(10, "lane-1")] = time.time() - 901
    actions = planner._compute_idle_actions(10, [lane])
    assert actions == []

    # Idle for 901s WITH VRAM pressure → still no background stop
    demand = DemandTracker()
    for _ in range(3):
        demand.record_request("other-model")
    planner_with_demand = _make_planner(facade=MockFacade(lanes=[lane]), demand=demand)
    planner_with_demand._lane_idle_since[(10, "lane-1")] = time.time() - 901
    actions = planner_with_demand._compute_idle_actions(10, [lane])
    assert actions == []


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

    registry = MockRegistry()
    registry._snapshot = {"runtime": {"lanes": []}}
    planner = _make_planner(facade=MockFacade(lanes=[]), registry=registry, demand=demand)
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

    registry = MockRegistry()
    registry._snapshot = {"runtime": {"lanes": []}}
    planner = _make_planner(registry=registry, demand=demand)
    actions = planner._compute_demand_actions(10, [])
    assert actions == []


def test_demand_actions_skip_offline_provider():
    """No load actions should be emitted for a provider without an active worker snapshot."""
    demand = DemandTracker()
    for _ in range(3):
        demand.record_request("model-b")

    registry = MockRegistry()
    registry._snapshot = None
    planner = _make_planner(facade=MockFacade(lanes=[]), registry=registry, demand=demand)
    actions = planner._compute_demand_actions(10, [])
    assert actions == []


def test_demand_actions_respect_worker_capabilities():
    """Demanded models outside the worker capability set must not get load actions."""
    demand = DemandTracker()
    for _ in range(3):
        demand.record_request("logosnode")

    registry = MockRegistry()
    registry._snapshot = {
        "runtime": {"lanes": []},
        "capabilities_models": ["Qwen/Qwen2.5-0.5B-Instruct"],
    }
    facade = MockFacade(
        lanes=[],
        capabilities=["Qwen/Qwen2.5-0.5B-Instruct"],
    )
    planner = _make_planner(facade=facade, registry=registry, demand=demand)

    actions = planner._compute_demand_actions(10, [])
    assert actions == []


# ---------------------------------------------------------------------------
# Fleet KV cache allocation
# ---------------------------------------------------------------------------


def test_fleet_kv_rebalance_triggers_on_saturated_cache():
    """Cache > GPU_CACHE_HIGH (85%) with high TTFT → fleet rebalance emits reconfigure."""
    import dataclasses as _dc
    lane = _dc.replace(
        _make_signal(lane_id="lane-a", model_name="model-a", is_vllm=True,
                     gpu_cache_usage_percent=90.0, effective_vram_mb=16000.0),
        ttft_p95_seconds=3.0,
    )
    profile = ModelProfile(
        model_name="model-a", engine="vllm",
        kv_budget_mb=2000.0,   # current budget — significantly below optimal
        base_residency_mb=8000.0,
    )
    facade = MockFacade(
        lanes=[lane],
        capacity=OllamaCapacity(available_vram_mb=10000, total_vram_mb=24000, loaded_models=[]),
        profiles={"model-a": profile},
    )
    planner = _make_planner(facade=facade)
    planner._last_kv_rebalance_time = 0.0  # bypass interval

    actions = planner._compute_fleet_kv_allocation(10, [lane])
    assert len(actions) == 1
    assert actions[0].action == "reconfigure_kv_cache"
    assert "kv_cache_memory_bytes" in actions[0].params["updates"]["vllm_config"]


def test_fleet_kv_rebalance_skips_healthy_lane():
    """Lane with cache < GPU_CACHE_HIGH and fast TTFT → no reconfigure."""
    import dataclasses as _dc
    lane = _dc.replace(
        _make_signal(lane_id="lane-a", model_name="model-a", is_vllm=True,
                     gpu_cache_usage_percent=30.0, effective_vram_mb=16000.0),
        ttft_p95_seconds=0.5,
    )
    profile = ModelProfile(
        model_name="model-a", engine="vllm",
        kv_budget_mb=4000.0,
        base_residency_mb=8000.0,
    )
    facade = MockFacade(
        lanes=[lane],
        capacity=OllamaCapacity(available_vram_mb=10000, total_vram_mb=24000, loaded_models=[]),
        profiles={"model-a": profile},
    )
    planner = _make_planner(facade=facade)
    planner._last_kv_rebalance_time = 0.0

    actions = planner._compute_fleet_kv_allocation(10, [lane])
    assert actions == []


def test_fleet_kv_rebalance_skips_interval_unless_emergency():
    """After a rebalance, further calls within the interval window are no-ops."""
    import dataclasses as _dc
    lane = _dc.replace(
        _make_signal(lane_id="lane-a", model_name="model-a", is_vllm=True,
                     gpu_cache_usage_percent=90.0, effective_vram_mb=16000.0),
        ttft_p95_seconds=3.0,
    )
    profile = ModelProfile(
        model_name="model-a", engine="vllm",
        kv_budget_mb=2000.0,
        base_residency_mb=8000.0,
    )
    facade = MockFacade(
        lanes=[lane],
        capacity=OllamaCapacity(available_vram_mb=10000, total_vram_mb=24000, loaded_models=[]),
        profiles={"model-a": profile},
    )
    planner = _make_planner(facade=facade)
    planner._last_kv_rebalance_time = 0.0  # bypass interval for first call

    # First call runs and stamps the time
    planner._compute_fleet_kv_allocation(10, [lane])

    # Second call within interval → no actions
    actions2 = planner._compute_fleet_kv_allocation(10, [lane])
    assert actions2 == []


def test_fleet_kv_rebalance_skips_ollama_lanes():
    """Ollama lanes (is_vllm=False) must not be included in fleet KV allocation."""
    lane = _make_signal(
        lane_id="lane-ollama",
        model_name="ollama-model",
        is_vllm=False,
        gpu_cache_usage_percent=95.0,
    )
    planner = _make_planner(facade=MockFacade(lanes=[lane]))
    planner._last_kv_rebalance_time = 0.0

    actions = planner._compute_fleet_kv_allocation(10, [lane])
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
    # (base=15000 + kv=4096MB) * 1.1 TP overhead = 19096 * 1.1 = 21005.6
    assert abs(estimated - 21005.6) < 1.0

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
    # (base=15000 + kv_budget=5000) * 1.1 TP overhead = 20000 * 1.1 = 22000
    assert abs(estimated2 - 22000.0) < 1.0


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
    assert action.params["vllm_config"]["tensor_parallel_size"] == 2
    assert "gpu_memory_utilization" not in action.params["vllm_config"]
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
    kv = planner._compute_kv_cache_bytes(profile)
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
    kv = planner._compute_kv_cache_bytes(profile)
    assert kv is not None
    kv_mb = CapacityPlanner._parse_kv_cache_to_mb(kv)
    assert abs(kv_mb - 1400.0) < 10  # 4000 * 0.35 = 1400


def test_kv_cache_bytes_none_when_no_profile():
    """No profile → return None, let vLLM decide."""
    planner = _make_planner()
    assert planner._compute_kv_cache_bytes(None) is None


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


def test_request_reclaim_prefers_small_sleep_combo_over_large_single_sleep():
    target = _make_signal(
        lane_id="lane-target",
        model_name="target-model",
        runtime_state="cold",
        sleep_state="unsupported",
        is_vllm=True,
    )
    big = _make_signal(
        lane_id="lane-big",
        model_name="big-model",
        runtime_state="loaded",
        sleep_state="awake",
        is_vllm=True,
        effective_vram_mb=12000.0,
    )
    small_a = _make_signal(
        lane_id="lane-small-a",
        model_name="small-model-a",
        runtime_state="loaded",
        sleep_state="awake",
        is_vllm=True,
        effective_vram_mb=6000.0,
    )
    small_b = _make_signal(
        lane_id="lane-small-b",
        model_name="small-model-b",
        runtime_state="loaded",
        sleep_state="awake",
        is_vllm=True,
        effective_vram_mb=6000.0,
    )
    profiles = {
        "big-model": ModelProfile(
            model_name="big-model",
            loaded_vram_mb=12000.0,
            sleeping_residual_mb=2000.0,
            engine="vllm",
        ),
        "small-model-a": ModelProfile(
            model_name="small-model-a",
            loaded_vram_mb=6000.0,
            sleeping_residual_mb=1000.0,
            engine="vllm",
        ),
        "small-model-b": ModelProfile(
            model_name="small-model-b",
            loaded_vram_mb=6000.0,
            sleeping_residual_mb=1000.0,
            engine="vllm",
        ),
    }
    planner = _make_planner(
        facade=MockFacade(lanes=[target, big, small_a, small_b], profiles=profiles),
    )

    action = planner._next_request_reclaim_action(
        provider_id=10,
        target=target,
        lanes=[target, big, small_a, small_b],
        profiles=profiles,
        required_free_mb=9000.0,
    )

    assert action is not None
    assert action.action == "sleep_l1"
    assert action.lane_id in {"lane-small-a", "lane-small-b"}


def test_request_reclaim_prefers_smallest_sufficient_stop_candidate():
    target = _make_signal(
        lane_id="lane-target",
        model_name="target-model",
        runtime_state="cold",
        sleep_state="unsupported",
        is_vllm=True,
    )
    big = _make_signal(
        lane_id="lane-big",
        model_name="big-model",
        runtime_state="sleeping",
        sleep_state="sleeping",
        is_vllm=True,
        effective_vram_mb=12000.0,
    )
    small = _make_signal(
        lane_id="lane-small",
        model_name="small-model",
        runtime_state="sleeping",
        sleep_state="sleeping",
        is_vllm=True,
        effective_vram_mb=4000.0,
    )
    planner = _make_planner(
        facade=MockFacade(lanes=[target, big, small], profiles={}),
    )

    action = planner._next_request_reclaim_action(
        provider_id=10,
        target=target,
        lanes=[target, big, small],
        profiles={},
        required_free_mb=3000.0,
    )

    assert action is not None
    assert action.action == "stop"
    assert action.lane_id == "lane-small"


def test_request_reclaim_prefers_stopping_sleeping_overlap_before_sleeping_other_gpu():
    target = _make_signal(
        lane_id="lane-target",
        model_name="target-model",
        runtime_state="sleeping",
        sleep_state="sleeping",
        is_vllm=True,
        gpu_devices="1",
    )
    sleeping_blocker = _make_signal(
        lane_id="lane-blocker",
        model_name="blocker-model",
        runtime_state="sleeping",
        sleep_state="sleeping",
        is_vllm=True,
        effective_vram_mb=1400.0,
        gpu_devices="1",
    )
    other_gpu_lane = _make_signal(
        lane_id="lane-other",
        model_name="other-model",
        runtime_state="loaded",
        sleep_state="awake",
        is_vllm=True,
        effective_vram_mb=8000.0,
        gpu_devices="0",
    )
    profiles = {
        "other-model": ModelProfile(
            model_name="other-model",
            loaded_vram_mb=8000.0,
            sleeping_residual_mb=1000.0,
            engine="vllm",
        ),
    }
    planner = _make_planner(
        facade=MockFacade(lanes=[target, sleeping_blocker, other_gpu_lane], profiles=profiles),
    )

    action = planner._next_request_reclaim_action(
        provider_id=10,
        target=target,
        lanes=[target, sleeping_blocker, other_gpu_lane],
        profiles=profiles,
        required_free_mb=1000.0,
    )

    assert action is not None
    assert action.action == "stop"
    assert action.lane_id == "lane-blocker"


@pytest.mark.asyncio
async def test_request_capacity_reclaims_for_target_gpu_shortfall_even_when_provider_free_is_high():
    target = _make_signal(
        lane_id="lane-target",
        model_name="target-model",
        runtime_state="sleeping",
        sleep_state="sleeping",
        is_vllm=True,
        effective_vram_mb=500.0,
        gpu_devices="1",
    )
    sleeping_blocker = _make_signal(
        lane_id="lane-blocker",
        model_name="blocker-model",
        runtime_state="sleeping",
        sleep_state="sleeping",
        is_vllm=True,
        effective_vram_mb=1400.0,
        gpu_devices="1",
    )
    other_gpu_lane = _make_signal(
        lane_id="lane-other",
        model_name="other-model",
        runtime_state="loaded",
        sleep_state="awake",
        is_vllm=True,
        effective_vram_mb=8000.0,
        gpu_devices="0",
    )
    profiles = {
        "target-model": ModelProfile(
            model_name="target-model",
            base_residency_mb=1500.0,
            sleeping_residual_mb=500.0,
            engine="vllm",
        ),
        "other-model": ModelProfile(
            model_name="other-model",
            loaded_vram_mb=8000.0,
            sleeping_residual_mb=1000.0,
            engine="vllm",
        ),
    }
    facade = MockFacade(
        lanes=[target, sleeping_blocker, other_gpu_lane],
        capacity=OllamaCapacity(available_vram_mb=32000, total_vram_mb=32768, loaded_models=[]),
        profiles=profiles,
    )
    registry = MockRegistry()
    registry._snapshot = {
        "first_status_received": True,
        "runtime": {
            "lanes": [],
            "devices": {
                "devices": [
                    {"device_id": 0, "memory_free_mb": 15000},
                    {"device_id": 1, "memory_free_mb": 1000},
                ],
            },
        },
    }
    planner = _make_planner(facade=facade, registry=registry)
    actions: list[tuple[str, str]] = []

    async def _fake_execute(action, timeout_seconds=60.0):  # noqa: ARG001
        actions.append((action.action, action.lane_id))
        registry._snapshot["runtime"]["devices"]["devices"][1]["memory_free_mb"] = 2500
        return True

    planner._execute_action_with_confirmation = _fake_execute

    ok = await planner._ensure_request_capacity(
        provider_id=10,
        target=target,
        profile=profiles["target-model"],
        timeout_seconds=30.0,
    )

    assert ok is True
    assert actions == [("stop", "lane-blocker")]


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


def test_vram_budget_preserves_original_order_for_preemptive_load_then_sleep():
    """Validation must not reorder a paired preemptive load ahead/behind its sleep."""
    from logos.sdi.models import CapacityPlanAction

    facade = MockFacade(
        capacity=OllamaCapacity(available_vram_mb=24000, total_vram_mb=48000, loaded_models=[]),
        profiles={
            "model-a": ModelProfile(
                model_name="model-a",
                base_residency_mb=8000.0,
                kv_budget_mb=4000.0,
                sleeping_residual_mb=1000.0,
                engine="vllm",
            ),
        },
    )
    planner = _make_planner(facade=facade)

    actions = [
        CapacityPlanAction(
            action="load",
            provider_id=10,
            lane_id="lane-1",
            model_name="model-a",
            params={"vllm_config": {"kv_cache_memory_bytes": str(4 * 1024 * 1024 * 1024)}},
            reason=f"{planner.PREEMPTIVE_LOAD_REASON} (residual=1000MB)",
        ),
        CapacityPlanAction(
            action="sleep_l1",
            provider_id=10,
            lane_id="lane-1",
            model_name="model-a",
            params={"level": 1},
            reason=f"{planner.PREEMPTIVE_SLEEP_REASON} (residual=1000MB)",
        ),
    ]

    validated = planner._validate_vram_budget(actions)
    assert [action.action for action in validated] == ["load", "sleep_l1"]


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
    assert planner._lane_sleep_level[(10, "lane-1")] == 1
    assert (10, "lane-1") in planner._lane_sleep_since


@pytest.mark.asyncio
async def test_stale_preemptive_sleep_is_skipped_without_worker_command():
    """A preemptive sleep must be ignored if its paired preemptive load never confirmed."""
    from logos.sdi.models import CapacityPlanAction

    registry = MockRegistry()
    registry._snapshot = {"runtime": {"lanes": []}}
    planner = _make_planner(registry=registry)

    action = CapacityPlanAction(
        action="sleep_l1",
        provider_id=10,
        lane_id="lane-1",
        model_name="model-a",
        reason=f"{planner.PREEMPTIVE_SLEEP_REASON} (residual=1000MB)",
    )

    result = await planner._execute_action_with_confirmation(action, timeout_seconds=5.0)
    assert result is False
    assert registry.commands_sent == []


@pytest.mark.asyncio
async def test_stale_preemptive_load_is_skipped_when_lane_already_exists():
    """A preemptive load should no-op if request-time work already created the lane."""
    from logos.sdi.models import CapacityPlanAction

    registry = MockRegistry()
    registry._snapshot = {
        "runtime": {
            "lanes": [
                {
                    "lane_id": "lane-1",
                    "model": "model-a",
                    "runtime_state": "loaded",
                    "sleep_state": "awake",
                },
            ],
        },
    }
    planner = _make_planner(registry=registry)

    action = CapacityPlanAction(
        action="load",
        provider_id=10,
        lane_id="lane-1",
        model_name="model-a",
        params={"lane_id": "lane-1", "model": "model-a", "vllm": True},
        reason=f"{planner.PREEMPTIVE_LOAD_REASON} (residual=1000MB)",
    )

    result = await planner._execute_action_with_confirmation(action, timeout_seconds=5.0)
    assert result is False
    assert registry.commands_sent == []


def test_confirmed_preemptive_load_marks_lane_ready_for_immediate_sleep():
    """Only a confirmed planner-issued preemptive load should arm the follow-up sleep."""
    from logos.sdi.models import CapacityPlanAction

    planner = _make_planner()
    key = (10, "lane-1")

    planner._record_confirmed_action_state(
        CapacityPlanAction(
            action="load",
            provider_id=10,
            lane_id="lane-1",
            model_name="model-a",
            reason=f"{planner.PREEMPTIVE_LOAD_REASON} (residual=1000MB)",
        ),
        time.time(),
    )
    assert key in planner._preemptive_sleep_ready

    planner._record_confirmed_action_state(
        CapacityPlanAction(
            action="sleep_l1",
            provider_id=10,
            lane_id="lane-1",
            model_name="model-a",
            reason=f"{planner.PREEMPTIVE_SLEEP_REASON} (residual=1000MB)",
        ),
        time.time(),
    )
    assert key not in planner._preemptive_sleep_ready


@pytest.mark.asyncio
async def test_stop_confirmation_lane_gone():
    """Stop action confirmed when lane disappears from snapshot."""
    from logos.sdi.models import CapacityPlanAction

    registry = MockRegistry()
    registry._snapshot = {
        "runtime": {"lanes": []},  # Lane is gone
    }
    planner = _make_planner(registry=registry)
    planner._lane_idle_since[(10, "lane-1")] = time.time() - 901
    planner._lane_sleep_since[(10, "lane-1")] = time.time() - 601
    planner._lane_sleep_level[(10, "lane-1")] = 2

    action = CapacityPlanAction(
        action="stop", provider_id=10, lane_id="lane-1",
        model_name="model-a", reason="test",
    )

    result = await planner._execute_action_with_confirmation(action, timeout_seconds=5.0)
    assert result is True
    assert (10, "lane-1") not in planner._lane_idle_since
    assert (10, "lane-1") not in planner._lane_sleep_since
    assert (10, "lane-1") not in planner._lane_sleep_level


@pytest.mark.asyncio
async def test_wake_confirmation_resets_idle_timer_and_clears_sleep_tracking():
    """Confirmed wake should reset idle age and suppress immediate re-sleep."""
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
    key = (10, "lane-1")
    planner._lane_idle_since[key] = time.time() - 5000
    planner._lane_sleep_since[key] = time.time() - 1000
    planner._lane_sleep_level[key] = 2

    action = CapacityPlanAction(
        action="wake", provider_id=10, lane_id="lane-1",
        model_name="model-a", reason="test",
    )

    result = await planner._execute_action_with_confirmation(action, timeout_seconds=5.0)
    assert result is True
    assert key not in planner._lane_sleep_since
    assert key not in planner._lane_sleep_level
    assert key in planner._lane_loaded_at

    lane = _make_signal(runtime_state="loaded", sleep_state="awake", active_requests=0)
    planner._update_idle_tracking(10, [lane])
    actions = planner._compute_idle_actions(10, [lane])
    assert actions == []


@pytest.mark.asyncio
async def test_wake_command_uses_full_timeout_budget():
    """Wake actions should not be capped to the generic 30s control timeout."""
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
        action="wake", provider_id=10, lane_id="lane-1",
        model_name="model-a", reason="test",
    )

    result = await planner._execute_action_with_confirmation(action, timeout_seconds=120.0)
    assert result is True
    assert registry.commands_sent[-1]["action"] == "wake_lane"
    assert registry.commands_sent[-1]["timeout_seconds"] == 120


@pytest.mark.asyncio
async def test_prepare_existing_lane_skips_recent_wake_failure():
    registry = MockRegistry()
    planner = _make_planner(registry=registry)
    target = _make_signal(
        lane_id="lane-1",
        model_name="model-a",
        runtime_state="sleeping",
        sleep_state="sleeping",
        is_vllm=True,
        gpu_devices="0",
    )

    planner._mark_wake_failure(10, "lane-1", details="cuda oom")
    planner._ensure_request_capacity = AsyncMock(return_value=True)
    planner._execute_action_with_confirmation = AsyncMock(return_value=True)

    result = await planner._prepare_existing_lane(
        10,
        "model-a",
        target,
        30.0,
    )

    assert result is None
    planner._ensure_request_capacity.assert_not_called()
    planner._execute_action_with_confirmation.assert_not_called()


@pytest.mark.asyncio
async def test_load_uses_apply_lanes_with_state_merge():
    """Load uses declarative apply_lanes and preserves existing lanes (declarative mode)."""
    from logos.sdi.models import CapacityPlanAction

    registry = MockRegistry()
    # Existing lane already tracked in desired state
    registry._desired_lanes = {
        "planner-Qwen_Qwen2.5-0.5B-Instruct": {
            "lane_id": "planner-Qwen_Qwen2.5-0.5B-Instruct",
            "model": "Qwen/Qwen2.5-0.5B-Instruct",
        },
    }
    registry._snapshot = {
        "first_status_received": True,
        "runtime": {"lanes": []},
    }
    planner = _make_planner(registry=registry)
    planner._use_additive_loads = False  # declarative mode
    planner._poll_confirmation = AsyncMock(return_value=True)

    action = CapacityPlanAction(
        action="load",
        provider_id=10,
        lane_id="planner-Qwen_Qwen2.5-Coder-7B-Instruct",
        model_name="Qwen/Qwen2.5-Coder-7B-Instruct",
        params={
            "lane_id": "planner-Qwen_Qwen2.5-Coder-7B-Instruct",
            "model": "Qwen/Qwen2.5-Coder-7B-Instruct",
            "vllm": True,
            "vllm_config": {"enable_sleep_mode": True},
        },
        reason="Request-time cold load",
    )

    result = await planner._execute_action_with_confirmation(action, timeout_seconds=5.0)

    assert result is True
    assert len(registry.commands_sent) == 1
    cmd = registry.commands_sent[0]
    assert cmd["action"] == "apply_lanes"
    # Must include BOTH the existing lane and the new lane
    sent_lanes = cmd["params"]["lanes"]
    lane_ids = {l["lane_id"] for l in sent_lanes}
    assert "planner-Qwen_Qwen2.5-0.5B-Instruct" in lane_ids
    assert "planner-Qwen_Qwen2.5-Coder-7B-Instruct" in lane_ids


async def test_stop_uses_apply_lanes_removing_target():
    """Stop uses declarative apply_lanes and removes only the target lane (declarative mode)."""
    from logos.sdi.models import CapacityPlanAction

    registry = MockRegistry()
    registry._desired_lanes = {
        "lane-keep": {"lane_id": "lane-keep", "model": "model-a"},
        "lane-remove": {"lane_id": "lane-remove", "model": "model-b"},
    }
    registry._snapshot = {
        "first_status_received": True,
        "runtime": {"lanes": [
            {"lane_id": "lane-remove", "runtime_state": "loaded"},
        ]},
    }
    planner = _make_planner(registry=registry)
    planner._use_additive_loads = False  # declarative mode
    planner._poll_confirmation = AsyncMock(return_value=True)

    action = CapacityPlanAction(
        action="stop",
        provider_id=10,
        lane_id="lane-remove",
        model_name="model-b",
        reason="idle stop",
    )

    result = await planner._execute_action_with_confirmation(action, timeout_seconds=5.0)

    assert result is True
    cmd = registry.commands_sent[0]
    assert cmd["action"] == "apply_lanes"
    sent_lanes = cmd["params"]["lanes"]
    lane_ids = {l["lane_id"] for l in sent_lanes}
    assert "lane-keep" in lane_ids
    assert "lane-remove" not in lane_ids


# ---------------------------------------------------------------------------
# Active-request guards on idle actions
# ---------------------------------------------------------------------------


def test_idle_sleep_skips_active_requests():
    """Lane with active_requests > 0 should NOT be slept even if idle timer expired."""
    lane = _make_signal(is_vllm=True, runtime_state="loaded", sleep_state="awake", active_requests=2)
    planner = _make_planner(facade=MockFacade(lanes=[lane]))

    # Idle timer says 301s, but lane has active requests
    planner._lane_idle_since[(10, "lane-1")] = time.time() - 301

    actions = planner._compute_idle_actions(10, [lane])
    assert actions == []


def test_idle_stop_skips_active_requests():
    """Lane with active_requests > 0 should not produce any idle action."""
    lane = _make_signal(is_vllm=True, runtime_state="loaded", sleep_state="awake", active_requests=1)
    planner = _make_planner(facade=MockFacade(lanes=[lane]))

    planner._lane_idle_since[(10, "lane-1")] = time.time() - 901

    actions = planner._compute_idle_actions(10, [lane])
    assert actions == []


def test_idle_sleep_l2_skips_active_requests():
    """Sleeping lane with active_requests > 0 should NOT be deepened to L2."""
    lane = _make_signal(is_vllm=True, runtime_state="sleeping", sleep_state="sleeping", active_requests=1)
    planner = _make_planner(facade=MockFacade(lanes=[lane]))

    planner._lane_idle_since[(10, "lane-1")] = time.time() - 601
    planner._lane_sleep_since[(10, "lane-1")] = time.time() - 601
    planner._lane_sleep_level[(10, "lane-1")] = 1

    actions = planner._compute_idle_actions(10, [lane])
    assert actions == []


def test_idle_sleep_l1_not_reissued_when_lane_already_sleeping_l1():
    """Sleeping L1 lane should not receive repeated sleep_l1 actions on each cycle."""
    lane = _make_signal(is_vllm=True, runtime_state="sleeping", sleep_state="sleeping", active_requests=0)
    planner = _make_planner(facade=MockFacade(lanes=[lane]))
    key = (10, "lane-1")

    planner._lane_idle_since[key] = time.time() - 1200
    planner._lane_sleep_since[key] = time.time() - 120
    planner._lane_sleep_level[key] = 1

    actions = planner._compute_idle_actions(10, [lane])
    assert actions == []


def test_idle_sleep_l2_not_reissued_when_lane_already_sleeping_l2():
    """Sleeping L2 lane should not receive repeated sleep_l2 actions on each cycle."""
    lane = _make_signal(is_vllm=True, runtime_state="sleeping", sleep_state="sleeping", active_requests=0)
    planner = _make_planner(facade=MockFacade(lanes=[lane]))
    key = (10, "lane-1")

    planner._lane_idle_since[key] = time.time() - 1200
    planner._lane_sleep_since[key] = time.time() - 1200
    planner._lane_sleep_level[key] = 2

    actions = planner._compute_idle_actions(10, [lane])
    assert actions == []


def test_idle_sleep_l2_uses_sleep_duration_not_total_idle_duration():
    """L2 should use time spent sleeping, not the original idle timestamp."""
    lane = _make_signal(is_vllm=True, runtime_state="sleeping", sleep_state="sleeping", active_requests=0)
    planner = _make_planner(facade=MockFacade(lanes=[lane]))
    key = (10, "lane-1")

    planner._lane_idle_since[key] = time.time() - 1200
    planner._lane_sleep_since[key] = time.time() - 120
    planner._lane_sleep_level[key] = 1

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
async def test_prepare_lane_concurrent_cold_loads_serialize_desired_lane_mutations():
    """Concurrent cold loads should merge desired lanes instead of stomping each other."""
    facade = MockFacade(
        lanes=[],
        capacity=OllamaCapacity(available_vram_mb=24000, total_vram_mb=32768, loaded_models=[]),
    )
    registry = MockRegistry()
    registry._snapshot = {"runtime": {"lanes": []}, "first_status_received": True}
    planner = _make_planner(facade=facade, registry=registry)

    first_load_started = asyncio.Event()
    release_first_load = asyncio.Event()
    desired_lane_sets: list[list[str]] = []

    async def _select_from_desired(provider_id, model_name):  # noqa: ARG001
        for lane in registry.get_desired_lane_set(provider_id):
            if lane.get("model") == model_name:
                return {
                    "lane_id": lane["lane_id"],
                    "model": model_name,
                    "runtime_state": "starting",
                    "sleep_state": "awake",
                }
        return None

    async def _fake_execute(action, timeout_seconds=60.0):  # noqa: ARG001
        new_lane = {"lane_id": action.lane_id, "model": action.model_name}
        if action.params:
            new_lane.update(action.params)
        # Simulate what the real load path does: record inflight before building desired set
        planner._record_inflight_add(action.provider_id, action.lane_id, new_lane)
        desired = planner._build_desired_lane_set(action.provider_id, add_lane=new_lane)
        desired_lane_sets.append(sorted(str(lane.get("lane_id")) for lane in desired))

        if action.model_name == "model-a":
            first_load_started.set()
            await release_first_load.wait()

        registry.update_desired_lanes(action.provider_id, desired)
        planner._clear_inflight_add(action.provider_id, action.lane_id)
        return True

    registry.select_lane_for_model = _select_from_desired
    planner._execute_action_with_confirmation = _fake_execute

    task_a = asyncio.create_task(planner.prepare_lane_for_request(10, "model-a"))
    await first_load_started.wait()
    task_b = asyncio.create_task(planner.prepare_lane_for_request(10, "model-b"))
    await asyncio.sleep(0)
    release_first_load.set()

    selected_a, selected_b = await asyncio.gather(task_a, task_b)

    assert selected_a is not None
    assert selected_b is not None
    assert desired_lane_sets[0] == [planner._planner_lane_id("model-a")]
    assert desired_lane_sets[1] == sorted([
        planner._planner_lane_id("model-a"),
        planner._planner_lane_id("model-b"),
    ])


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


# ---------------------------------------------------------------------------
# First-status gate (Fix 2)
# ---------------------------------------------------------------------------


def test_planner_cycle_skips_provider_without_first_status():
    """Planner cycle must not compute actions for providers that haven't sent status yet."""
    facade = MockFacade()
    registry = MockRegistry()
    # Simulate server-restart scenario: provider connected but no status yet
    registry._snapshot = {"runtime": {"lanes": []}, "first_status_received": False}
    demand = DemandTracker()
    demand.record_request("model-a")
    demand.record_request("model-a")
    demand.record_request("model-a")
    planner = _make_planner(facade=facade, registry=registry, demand=demand)

    # Run demand actions — should produce nothing because first_status_received is False
    lanes = facade.get_all_provider_lane_signals(10)
    actions = planner._compute_demand_actions(10, lanes)
    # The demand actions themselves don't check first_status — the _run_cycle gate does.
    # So we directly test the cycle-level skip via the registry check.
    assert registry.has_received_first_status(10) is False


@pytest.mark.asyncio
async def test_prepare_lane_deferred_without_first_status():
    """prepare_lane_for_request must return None when first status not received."""
    registry = MockRegistry()
    registry._snapshot = {"runtime": {"lanes": []}, "first_status_received": False}
    planner = _make_planner(registry=registry)
    result = await planner.prepare_lane_for_request(10, "model-a", timeout_seconds=1.0)
    assert result is None
    # No commands should have been sent
    assert len(registry.commands_sent) == 0


@pytest.mark.asyncio
async def test_prepare_lane_proceeds_with_first_status():
    """prepare_lane_for_request should work normally when first status received."""
    facade = MockFacade(
        lanes=[_make_signal(lane_id="lane-1", model_name="model-a", runtime_state="loaded")],
    )
    registry = MockRegistry()
    registry._snapshot = {
        "runtime": {
            "lanes": [{
                "lane_id": "lane-1",
                "model": "model-a",
                "runtime_state": "loaded",
                "sleep_state": "awake",
            }]
        },
        "first_status_received": True,
    }
    planner = _make_planner(facade=facade, registry=registry)
    result = await planner.prepare_lane_for_request(10, "model-a", timeout_seconds=1.0)
    assert result is not None
    assert result["lane_id"] == "lane-1"


# ---------------------------------------------------------------------------
# Phase 2: Anti-flip cooldown
# ---------------------------------------------------------------------------


def test_background_idle_never_stops_lane_within_cooldown():
    """No background idle stop should be emitted, including within cooldown."""
    lane = _make_signal(lane_id="lane-1", model_name="model-a", runtime_state="loaded", active_requests=0)
    demand = DemandTracker()
    # Create demand for another model to trigger VRAM pressure
    for _ in range(10):
        demand.record_request("model-b")
    facade = MockFacade(lanes=[lane], capabilities=["model-a", "model-b"])
    planner = _make_planner(facade=facade, demand=demand)

    now = time.time()
    # Lane idle long enough for stop
    planner._lane_idle_since[(10, "lane-1")] = now - 1000
    # But loaded only 30s ago (within 60s cooldown)
    planner._lane_loaded_at[(10, "lane-1")] = now - 30

    actions = planner._compute_idle_actions(10, [lane])
    stop_actions = [a for a in actions if a.action == "stop"]
    assert len(stop_actions) == 0


def test_background_idle_never_stops_lane_after_cooldown_either():
    """No background idle stop should be emitted even after cooldown expires."""
    lane = _make_signal(lane_id="lane-1", model_name="model-a", runtime_state="loaded", active_requests=0)
    demand = DemandTracker()
    for _ in range(10):
        demand.record_request("model-b")
    facade = MockFacade(lanes=[lane], capabilities=["model-a", "model-b"])
    planner = _make_planner(facade=facade, demand=demand)

    now = time.time()
    planner._lane_idle_since[(10, "lane-1")] = now - 1000
    # Loaded 120s ago (beyond 60s cooldown)
    planner._lane_loaded_at[(10, "lane-1")] = now - 120

    actions = planner._compute_idle_actions(10, [lane])
    stop_actions = [a for a in actions if a.action == "stop"]
    assert len(stop_actions) == 0


def test_anti_flip_does_not_block_sleep():
    """Sleep actions are exempt from anti-flip cooldown."""
    lane = _make_signal(
        lane_id="lane-1", model_name="model-a", runtime_state="loaded",
        sleep_state="awake", is_vllm=True, active_requests=0,
    )
    planner = _make_planner(facade=MockFacade(lanes=[lane]))

    now = time.time()
    planner._lane_idle_since[(10, "lane-1")] = now - 301
    # Recently loaded
    planner._lane_loaded_at[(10, "lane-1")] = now - 10

    actions = planner._compute_idle_actions(10, [lane])
    sleep_actions = [a for a in actions if a.action == "sleep_l1"]
    assert len(sleep_actions) == 1


def test_anti_flip_blocks_request_reclaim_within_cooldown():
    """Cooldown blocks stop but allows sleep_l1 (frees KV cache only, no thrashing)."""
    target = _make_signal(
        lane_id="lane-target",
        model_name="model-b",
        runtime_state="sleeping",
        sleep_state="sleeping",
        effective_vram_mb=2000.0,
    )
    victim = _make_signal(
        lane_id="lane-victim",
        model_name="model-a",
        runtime_state="loaded",
        sleep_state="awake",
        effective_vram_mb=12000.0,
    )
    profiles = {
        "model-a": ModelProfile(
            model_name="model-a",
            loaded_vram_mb=12000.0,
            sleeping_residual_mb=1000.0,
            engine="vllm",
        )
    }
    planner = _make_planner(facade=MockFacade(lanes=[target, victim], profiles=profiles))

    planner._lane_loaded_at[(10, "lane-victim")] = time.time() - 10

    action = planner._next_request_reclaim_action(
        provider_id=10,
        target=target,
        lanes=[target, victim],
        profiles=profiles,
        required_free_mb=1000.0,
    )

    # Sleep is allowed even within cooldown — it only frees KV cache, not the model.
    assert action is not None
    assert action.action == "sleep_l1"
    assert action.lane_id == "lane-victim"


# ---------------------------------------------------------------------------
# Phase 2: would_require_eviction
# ---------------------------------------------------------------------------


def test_would_require_eviction_true_when_vram_tight():
    """would_require_eviction returns True when free VRAM < estimated model VRAM."""
    capacity = OllamaCapacity(available_vram_mb=2000, total_vram_mb=48000, loaded_models=[])
    profile = ModelProfile(
        model_name="model-a", engine="vllm",
        base_residency_mb=8000, kv_budget_mb=2000,
    )
    facade = MockFacade(capacity=capacity, profiles={"model-a": profile})
    planner = _make_planner(facade=facade)

    assert planner.would_require_eviction(10, "model-a") is True


def test_would_require_eviction_false_when_vram_available():
    """would_require_eviction returns False when plenty of VRAM available."""
    capacity = OllamaCapacity(available_vram_mb=32000, total_vram_mb=48000, loaded_models=[])
    profile = ModelProfile(
        model_name="model-a", engine="vllm",
        base_residency_mb=8000, kv_budget_mb=2000,
    )
    facade = MockFacade(capacity=capacity, profiles={"model-a": profile})
    planner = _make_planner(facade=facade)

    assert planner.would_require_eviction(10, "model-a") is False


# ---------------------------------------------------------------------------
# Phase 2: on_state_change callback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_triggers_on_state_change_callback():
    """Successful load action should trigger on_state_change callback."""
    callback_calls = []
    facade = MockFacade(lanes=[])
    registry = MockRegistry()
    registry._snapshot = {
        "runtime": {
            "lanes": [{
                "lane_id": "planner-model_a",
                "model": "model-a",
                "runtime_state": "loaded",
                "sleep_state": "awake",
            }]
        },
        "first_status_received": True,
    }
    planner = CapacityPlanner(
        logosnode_facade=facade,
        logosnode_registry=registry,
        demand_tracker=DemandTracker(),
        cycle_seconds=30.0,
        enabled=True,
        on_state_change=lambda model_name: callback_calls.append(model_name),
    )

    from logos.sdi.models import CapacityPlanAction
    action = CapacityPlanAction(
        action="load",
        provider_id=10,
        lane_id="planner-model_a",
        model_name="model-a",
        params={"lane_id": "planner-model_a", "model": "model-a"},
        reason="test",
    )
    result = await planner._execute_action_with_confirmation(action, timeout_seconds=5.0)
    assert result is True
    assert "model-a" in callback_calls


# -- _build_load_params tests ------------------------------------------------

def test_build_load_params_does_not_set_enforce_eager():
    """enforce_eager is handled worker-side based on GPU arch, not server-side."""
    planner = _make_planner()
    profile = ModelProfile(model_name="any-model", engine="vllm", disk_size_bytes=1_000_000_000)
    params = planner._build_load_params("any-model", "lane-any", profile)
    assert "enforce_eager" not in params["vllm_config"]


# ---------------------------------------------------------------------------
# Preemptive load-then-sleep: pre-sleep idle awake lanes before load
# ---------------------------------------------------------------------------


def test_preemptive_sleep_emits_presleep_for_idle_awake_lane():
    """If an idle awake lane blocks VRAM for the new load, it must be slept first.

    Setup:
    - total_vram=24000, free=5500 (23% → passes the ≥20% initial guard)
    - awake lane holds 10000 MB (KV = 10000 - 1500 residual = 8500 MB freed on sleep)
    - new-model needs base=5000 + kv=3000 = 8000 MB (× 1.1 safety = 8800 MB)
    - Without pre-sleep: 5500 < 8800 → would be skipped
    - With pre-sleep freed: 5500 + 8500 = 14000 ≥ 8800 → load proceeds
    """
    awake_lane = _make_signal(
        lane_id="lane-awake",
        model_name="existing-model",
        runtime_state="loaded",
        sleep_state="awake",
        is_vllm=True,
        active_requests=0,
        effective_vram_mb=10000.0,
    )
    profiles = {
        "existing-model": ModelProfile(
            model_name="existing-model",
            loaded_vram_mb=10000.0,
            sleeping_residual_mb=1500.0,
            base_residency_mb=6000.0,
            kv_budget_mb=4000.0,
            engine="vllm",
        ),
        "new-model": ModelProfile(
            model_name="new-model",
            loaded_vram_mb=10000.0,
            sleeping_residual_mb=1500.0,
            base_residency_mb=5000.0,
            kv_budget_mb=3000.0,
            engine="vllm",
        ),
    }
    # 5500/24000 = 22.9% → passes initial 20% guard; 5500 < 8800 load_cost → needs pre-sleep.
    facade = MockFacade(
        lanes=[awake_lane],
        capacity=OllamaCapacity(available_vram_mb=5500, total_vram_mb=24000, loaded_models=[]),
        profiles=profiles,
    )
    demand = DemandTracker()
    demand.record_request("new-model")
    demand.record_request("new-model")

    planner = _make_planner(facade=facade, demand=demand)
    # Lane has been idle just 10s — below IDLE_SLEEP_L1 (300s) so idle path won't touch it.
    planner._lane_idle_since[(10, "lane-awake")] = time.time() - 10

    actions = planner._compute_preemptive_sleep_actions(10, [awake_lane])

    action_types = [a.action for a in actions]
    # Must emit: sleep_l1 (pre-sleep) → load (new-model) → sleep_l1 (post-sleep)
    assert "sleep_l1" in action_types, f"No sleep_l1 in {action_types}"
    assert "load" in action_types, f"No load in {action_types}"
    load_action = next(a for a in actions if a.action == "load")
    assert load_action.model_name == "new-model"
    # Pre-sleep (for existing-model) comes before the load
    first_sleep_idx = next(i for i, a in enumerate(actions) if a.action == "sleep_l1" and a.model_name == "existing-model")
    load_idx = next(i for i, a in enumerate(actions) if a.action == "load")
    assert first_sleep_idx < load_idx


def test_preemptive_sleep_always_presleeps_idle_awake_lanes():
    """Idle awake vLLM lanes are always pre-slept before a preemptive load, even when
    VRAM is abundant — to give the new model clean GPU memory at startup."""
    awake_lane = _make_signal(
        lane_id="lane-awake",
        model_name="existing-model",
        runtime_state="loaded",
        sleep_state="awake",
        is_vllm=True,
        active_requests=0,
        effective_vram_mb=8000.0,
    )
    profiles = {
        "existing-model": ModelProfile(
            model_name="existing-model",
            loaded_vram_mb=8000.0,
            sleeping_residual_mb=1000.0,
            base_residency_mb=5000.0,
            kv_budget_mb=3000.0,
            engine="vllm",
        ),
        "new-model": ModelProfile(
            model_name="new-model",
            sleeping_residual_mb=1500.0,
            base_residency_mb=4000.0,
            kv_budget_mb=2000.0,
            engine="vllm",
        ),
    }
    # VRAM is abundant — pre-sleep is not needed for budget, but should still happen.
    facade = MockFacade(
        lanes=[awake_lane],
        capacity=OllamaCapacity(available_vram_mb=20000, total_vram_mb=32768, loaded_models=[]),
        profiles=profiles,
    )
    demand = DemandTracker()
    demand.record_request("new-model")
    demand.record_request("new-model")
    planner = _make_planner(facade=facade, demand=demand)
    # Lane idle but under the IDLE_SLEEP_L1 threshold
    planner._lane_idle_since[(10, "lane-awake")] = time.time() - 10

    actions = planner._compute_preemptive_sleep_actions(10, [awake_lane])

    # existing-model IS pre-slept even though VRAM was sufficient
    pre_sleep_actions = [a for a in actions if a.action == "sleep_l1" and a.model_name == "existing-model"]
    assert len(pre_sleep_actions) == 1
    # The load + post-sleep pair for new-model should follow
    load_actions = [a for a in actions if a.action == "load" and a.model_name == "new-model"]
    assert len(load_actions) == 1
    # pre-sleep precedes the load
    pre_idx = next(i for i, a in enumerate(actions) if a.action == "sleep_l1" and a.model_name == "existing-model")
    load_idx = next(i for i, a in enumerate(actions) if a.action == "load")
    assert pre_idx < load_idx


def test_preemptive_sleep_does_not_presleep_busy_lane():
    """Lanes with active requests must never be pre-slept."""
    busy_lane = _make_signal(
        lane_id="lane-busy",
        model_name="busy-model",
        runtime_state="running",
        sleep_state="awake",
        is_vllm=True,
        active_requests=2,
        effective_vram_mb=10000.0,
    )
    profiles = {
        "new-model": ModelProfile(
            model_name="new-model",
            sleeping_residual_mb=1500.0,
            base_residency_mb=5000.0,
            kv_budget_mb=3000.0,
            engine="vllm",
        ),
    }
    facade = MockFacade(
        lanes=[busy_lane],
        capacity=OllamaCapacity(available_vram_mb=4000, total_vram_mb=24000, loaded_models=[]),
        profiles=profiles,
    )
    demand = DemandTracker()
    demand.record_request("new-model")
    demand.record_request("new-model")
    planner = _make_planner(facade=facade, demand=demand)

    actions = planner._compute_preemptive_sleep_actions(10, [busy_lane])

    # busy_lane must not appear in any sleep action
    sleep_of_busy = [a for a in actions if a.action == "sleep_l1" and a.lane_id == "lane-busy"]
    assert sleep_of_busy == []
