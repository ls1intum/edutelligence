"""Sequential model switchover: a queued request must be able to evict a cooled-down idle lane.

when requests for model A stop completely and model B is then
requested (sequentially — one request in flight at a time), the switchover
never happened: A's lane stayed awake forever and B's requests timed out in
the scheduler queue.

Root cause: the contention branch of ``_compute_demand_actions`` bypasses the
competitive ratio only when the target has queued demand AND
``eff >= DEMAND_LOAD_FLOOR``.  A single queued request contributes
``QUEUE_WEIGHT (0.5)`` to eff and its base score decays (0.7 per 10 s cycle)
below 0.5 within two cycles — so a lone waiting request can never clear the
1.0 load floor, no matter how long it waits or how fully the victim has
cooled down.  The "queued demand + idle victims" bypass was therefore
deadlocked for exactly one queued request, and the incumbent stuck.

These tests drive the full ``_compute_demand_actions`` path (placement +
eviction-set picker + gate) and pin down:

* one queued request for B + cooled-down idle A → sleep(A) + load(B) planned;
* the anti-thrash brake still holds while A's demand is genuinely hot;
* multi-request queues keep switching (pre-existing behaviour);
* the wake path with one queued request keeps working;
* the legacy v1 gate has the same guarantee.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from types import ModuleType, SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import MagicMock

# The planner imports `prometheus_client` at module load time. In CI / docker
# it's installed; locally we stub it so the planner module is importable for
# unit tests that don't actually exercise metrics.
if "prometheus_client" not in sys.modules:
    _prom_stub = ModuleType("prometheus_client")

    class _MetricStub:
        def __init__(self, *a, **kw):
            pass

        def labels(self, *a, **kw):
            return self

        def inc(self, *a, **kw):
            pass

        def dec(self, *a, **kw):
            pass

        def set(self, *a, **kw):
            pass

        def observe(self, *a, **kw):
            pass

    _prom_stub.Counter = _MetricStub  # type: ignore[attr-defined]
    _prom_stub.Gauge = _MetricStub  # type: ignore[attr-defined]
    _prom_stub.Histogram = _MetricStub  # type: ignore[attr-defined]
    _prom_stub.Summary = _MetricStub  # type: ignore[attr-defined]
    _prom_stub.CollectorRegistry = MagicMock  # type: ignore[attr-defined]
    _prom_stub.REGISTRY = MagicMock()  # type: ignore[attr-defined]
    _prom_stub.CONTENT_TYPE_LATEST = "text/plain"  # type: ignore[attr-defined]
    _prom_stub.generate_latest = lambda *a, **kw: b""  # type: ignore[attr-defined]
    sys.modules["prometheus_client"] = _prom_stub

from logos import CapacityPlanner  # noqa: E402
from logos import LaneSchedulerSignals  # noqa: E402

# ---------------------------------------------------------------------------
# Mock facade / provider state
# ---------------------------------------------------------------------------


@dataclass
class _MockProvider:
    provider_id: int
    name: str
    lanes: List[LaneSchedulerSignals] = field(default_factory=list)
    profiles: Dict[str, Any] = field(default_factory=dict)
    capabilities: List[str] = field(default_factory=list)
    available_vram_mb: float = 0.0


class _MockFacade:
    def __init__(self, providers: List[_MockProvider], queue_depths: Dict[str, int]):
        self._providers = {p.provider_id: p for p in providers}
        self._queue_depths = queue_depths

    def get_all_provider_lane_signals(self, provider_id: int) -> List[LaneSchedulerSignals]:
        return list(self._providers[provider_id].lanes)

    def get_model_profiles(self, provider_id: int) -> Dict[str, Any]:
        return dict(self._providers[provider_id].profiles)

    def get_worker_capabilities(self, provider_id: int) -> List[str]:
        return list(self._providers[provider_id].capabilities)

    def get_capacity_info(self, provider_id: int):
        p = self._providers[provider_id]
        return SimpleNamespace(available_vram_mb=p.available_vram_mb, total_vram_mb=96_000.0)

    def get_provider_name(self, provider_id: int) -> str:
        return self._providers[provider_id].name

    def provider_ids(self) -> List[int]:
        return list(self._providers.keys())

    def get_scheduler_queue_depth_by_model_name(self, model_name: str, provider_id: int) -> int:
        return self._queue_depths.get(model_name, 0)

    def has_cold_queued_entries_by_model_name(self, model_name: str, provider_id: int) -> bool:
        return False


def _lane(
    *,
    lane_id: str,
    model_name: str,
    runtime_state: str = "loaded",
    sleep_state: str = "awake",
    effective_vram_mb: float = 20_000.0,
    gpu_devices: str = "0",
    active_requests: int = 0,
    queue_waiting: float = 0.0,
) -> LaneSchedulerSignals:
    return LaneSchedulerSignals(
        lane_id=lane_id,
        model_name=model_name,
        runtime_state=runtime_state,
        sleep_state=sleep_state,
        active_requests=active_requests,
        queue_waiting=queue_waiting,
        requests_running=0.0,
        gpu_cache_usage_percent=None,
        ttft_p95_seconds=0.0,
        e2e_latency_p50_seconds=0.0,
        effective_vram_mb=effective_vram_mb,
        num_parallel=0,
        gpu_devices=gpu_devices,
    )


def _profile(loaded_vram_mb: float, sleeping_residual_mb: float = 500.0):
    """Build a profile-shaped object with the fields the planner reads."""
    return SimpleNamespace(
        loaded_vram_mb=loaded_vram_mb,
        sleeping_residual_mb=sleeping_residual_mb,
        base_residency_mb=loaded_vram_mb,
        kv_budget_mb=0.0,
        tensor_parallel_size=1,
        residency_source="calibrated",
        engine="vllm",
        estimate_base_residency_mb=lambda: loaded_vram_mb,
    )


def _snapshot_with_one_gpu() -> dict:
    """One 96 GB GPU with 70 GB in use (lane A) → 26 GB free per device."""
    return {
        "runtime": {
            "lanes": [],
            "devices": {
                "total_memory_mb": 96_000.0,
                "devices": [
                    {
                        "device_id": "GPU-abc",
                        "extra": {"index": 0},
                        "memory_total_mb": 96_000.0,
                        "memory_used_mb": 70_000.0,
                    },
                ],
            },
        }
    }


def _planner(
    providers: List[_MockProvider],
    scores: Dict[str, float],
    queue_depths: Dict[str, int],
    *,
    eviction_gate_v2: bool = True,
) -> CapacityPlanner:
    """Planner wired for the full ``_compute_demand_actions`` path.

    ``scores`` models the DemandTracker after several decayed cycles: the
    value is what ``get_score`` returns at decision time (i.e. post-decay).
    ``queue_depths`` models requests waiting in the Logos scheduler queue.
    """
    facade = _MockFacade(providers, queue_depths)
    registry = MagicMock()
    registry.has_received_first_status.return_value = True
    registry.is_calibrating.return_value = False
    registry.peek_runtime_snapshot.return_value = _snapshot_with_one_gpu()

    demand = MagicMock()
    demand.get_ranked_models.return_value = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    demand.get_score.side_effect = lambda name: scores.get(name, 0.0)

    planner = CapacityPlanner.__new__(CapacityPlanner)
    planner._facade = facade
    planner._registry = registry
    planner._demand = demand
    planner._lane_wake_failure_until = {}
    planner._lane_load_failure_until = {}
    planner._lane_loaded_at = {}
    planner._lane_idle_since = {}
    planner._lane_sleep_since = {}
    planner._lane_sleep_level = {}
    planner._load_cooldown_seconds = 0.0
    planner._eviction_gate_v2 = eviction_gate_v2
    planner._stop_dedup_siblings = False
    planner._cross_provider_dedup = False
    planner._cross_provider_best_first = True
    planner._replica_first_eviction = True
    planner._replicate_on_free_vram = False
    planner._announced_use = {}
    planner._provider_capacity_lock = lambda pid: SimpleNamespace(locked=lambda: False)
    planner._vram_ledger = SimpleNamespace(
        get_committed_mb=lambda pid: 0.0,
        has_overlapping_reservation=lambda *a, **k: False,
        get_gpu_effective_available_mb=lambda pid, g, f: f,
    )
    planner._build_load_params = lambda *a, **k: {}
    planner._enabled = False
    planner._tick_event = None
    return planner


def _switchover_scenario(
    *,
    score_a: float,
    queue_b: int,
    score_b: float = 0.02,
    b_sleeping_lane: bool = False,
    eviction_gate_v2: bool = True,
):
    """Worker with lane A (70 GB, idle) and no lane for B (needs 60 GB).

    ``score_a`` is A's decayed demand at decision time: ~0 means the
    benchmark finished minutes ago (cooled down), 50 means A was hot until
    moments ago.  ``queue_b`` is the number of B requests waiting in the
    scheduler queue.
    """
    lane_a = _lane(lane_id="A-inc", model_name="model-a", effective_vram_mb=70_000.0)
    lanes = [lane_a]
    profiles = {"model-a": _profile(70_000.0), "model-b": _profile(60_000.0)}
    if b_sleeping_lane:
        lanes.append(
            _lane(
                lane_id="B-s",
                model_name="model-b",
                runtime_state="sleeping",
                sleep_state="sleeping",
                effective_vram_mb=500.0,
            )
        )
    provider = _MockProvider(
        provider_id=1,
        name="W",
        lanes=lanes,
        profiles=profiles,
        capabilities=["model-a", "model-b"],
        available_vram_mb=26_000.0,
    )
    scores = {"model-a": score_a, "model-b": score_b}
    planner = _planner(
        [provider],
        scores,
        {"model-b": queue_b},
        eviction_gate_v2=eviction_gate_v2,
    )
    return planner, provider


class TestSequentialSwitchover:
    """A's benchmark ends, B is requested one-at-a-time.

    The victim's demand has decayed below the load floor (cooled down) and
    exactly one B request waits in the scheduler queue. The planner must
    sleep A and cold-load B — otherwise that request sits in the queue until
    it times out, the queue drains, and the next request hits the same wall:
    the incumbent sticks forever.
    """

    def test_single_queued_request_evicts_cooled_idle_lane(self):
        planner, provider = _switchover_scenario(score_a=0.3, queue_b=1)

        actions = planner._compute_demand_actions(1, provider.lanes)

        kinds = [(a.action, a.lane_id) for a in actions]
        assert (
            "sleep_l1",
            "A-inc",
        ) in kinds, f"cooled-down idle lane A must be slept for the queued B request; got {kinds}"
        assert ("load", "planner-model-b") in kinds, f"queued B request must trigger the cold load; got {kinds}"
        # Victim first, then the load that reclaims its VRAM.
        assert kinds.index(("sleep_l1", "A-inc")) < kinds.index(("load", "planner-model-b"))

    def test_hot_incumbent_is_not_evicted_for_a_single_queued_request(self):
        """Anti-thrash brake: A was hot until moments ago (score 50). Its lane
        is idle, but evicting it on the strength of one queued B request would
        flip-flop the moment A's next benchmark batch lands. The victim must
        cool down (score < floor) first."""
        planner, provider = _switchover_scenario(score_a=50.0, queue_b=1)

        actions = planner._compute_demand_actions(1, provider.lanes)

        assert actions == [], f"a still-hot incumbent must not be evicted for one queued request; got {actions}"

    def test_multi_request_queue_still_switches(self):
        """Pre-existing behaviour: a queue of several B requests already
        cleared the load floor via QUEUE_WEIGHT × depth — must keep working."""
        planner, provider = _switchover_scenario(score_a=0.3, queue_b=8)

        actions = planner._compute_demand_actions(1, provider.lanes)

        kinds = [(a.action, a.lane_id) for a in actions]
        assert ("sleep_l1", "A-inc") in kinds
        assert ("load", "planner-model-b") in kinds

    def test_wake_path_single_queued_request(self):
        """B has a sleeping lane: the wake branch gates on DEMAND_WAKE_FLOOR
        (0.5), which a single queued request reaches (QUEUE_WEIGHT = 0.5).
        Pins the wake behaviour next to the load fix."""
        planner, provider = _switchover_scenario(score_a=0.3, queue_b=1, b_sleeping_lane=True)

        actions = planner._compute_demand_actions(1, provider.lanes)

        kinds = [(a.action, a.lane_id) for a in actions]
        assert ("wake", "B-s") in kinds, f"queued B request must wake the sleeping lane; got {kinds}"
        assert ("sleep_l1", "A-inc") in kinds

    def test_legacy_v1_gate_single_queued_request(self):
        """LOGOS_EVICTION_GATE_V2=false (legacy fallback) must not deadlock
        the same way."""
        planner, provider = _switchover_scenario(score_a=0.3, queue_b=1, eviction_gate_v2=False)

        actions = planner._compute_demand_actions(1, provider.lanes)

        kinds = [(a.action, a.lane_id) for a in actions]
        assert ("sleep_l1", "A-inc") in kinds
        assert ("load", "planner-model-b") in kinds


class TestLaneWaiterWithoutDemand:
    """A request waits for B's sleeping lane, but B has no demand score.

    The pipeline records demand only for the top classification choice, so
    a fallback model can be waited for without ever being ranked, and a
    score decays while the request waits. The waiter itself must make B a
    candidate, or the cycles it triggers never consider B.
    """

    def test_a_waiter_alone_wakes_the_sleeping_lane(self):
        planner, provider = _switchover_scenario(score_a=0.3, queue_b=0, b_sleeping_lane=True)
        planner._demand.get_ranked_models.return_value = [("model-a", 0.3)]
        planner._demand.get_score.side_effect = lambda name: 0.3 if name == "model-a" else 0.0

        assert planner._compute_demand_actions(1, provider.lanes) == []

        planner.register_lane_waiter("req-b", 1, "model-b")
        actions = planner._compute_demand_actions(1, provider.lanes)

        kinds = [(a.action, a.lane_id) for a in actions]
        assert ("wake", "B-s") in kinds, f"the waiter must wake B's sleeping lane; got {kinds}"

    def test_a_waiter_on_another_worker_is_not_a_candidate_here(self):
        planner, provider = _switchover_scenario(score_a=0.3, queue_b=0, b_sleeping_lane=True)
        planner._demand.get_ranked_models.return_value = [("model-a", 0.3)]
        planner._demand.get_score.side_effect = lambda name: 0.3 if name == "model-a" else 0.0

        planner.register_lane_waiter("req-b", 2, "model-b")

        assert planner._compute_demand_actions(1, provider.lanes) == []


class TestLockedLaneThatNeedsRoom:
    """B's sleeping lane is locked warm but its wake needs the memory of A's idle lane.

    The standalone lock wake never evicts, so it fails validation every cycle.
    It must not keep the demand pass from reclaiming A and waking B for a
    waiting request, and B must then be woken once.
    """

    def _scenario(self):
        planner, provider = _switchover_scenario(score_a=0.3, queue_b=0, b_sleeping_lane=True)
        planner.apply_lane_lock(1, "B-s", True, 1)
        planner._cross_provider_dedup = True
        planner._safe_get_profiles = lambda pid: provider.profiles
        planner._safe_get_capacity = lambda pid: planner._facade.get_capacity_info(pid)
        planner._lane_is_in_wake_failure_cooldown = lambda *a: False
        planner.register_lane_waiter("req-b", 1, "model-b")
        return planner, provider

    def test_a_lock_wake_that_cannot_fit_leaves_the_model_to_the_demand_pass(self):
        planner, provider = self._scenario()
        planned: set[str] = set()

        lock_wakes = planner._compute_lock_wake_actions(1, provider.lanes, planned)
        assert [(a.action, a.lane_id) for a in lock_wakes] == [("wake", "B-s")]
        assert "model-b" not in planned

        demand = planner._compute_demand_actions(1, provider.lanes, cycle_planned_models=planned)
        kinds = [(a.action, a.lane_id) for a in demand]
        assert ("sleep_l1", "A-inc") in kinds, f"the idle unlocked lane must be reclaimed; got {kinds}"
        assert ("wake", "B-s") in kinds, f"the locked lane must be woken for the waiter; got {kinds}"

        merged = [(a.action, a.lane_id) for a in planner._merge_lock_wakes(lock_wakes, demand)]
        assert merged.count(("wake", "B-s")) == 1
        assert merged.index(("sleep_l1", "A-inc")) < merged.index(("wake", "B-s"))

    def test_a_lock_wake_that_fits_still_claims_the_model_for_this_cycle(self):
        planner, provider = self._scenario()
        provider.available_vram_mb = 90_000.0
        planner._get_per_gpu_free = lambda pid: {0: 90_000.0}
        planned: set[str] = set()

        planner._compute_lock_wake_actions(1, provider.lanes, planned)

        assert "model-b" in planned

    def test_free_memory_on_another_gpu_does_not_make_the_lock_wake_fit(self):
        """B's lane sits on GPU 0 with 2 GB free; GPU 1 has 70 GB free. The
        aggregate fits, but the wake reserves on GPU 0, so the model must be
        left to the demand pass."""
        planner, provider = self._scenario()
        provider.available_vram_mb = 72_000.0
        planner._get_per_gpu_free = lambda pid: {0: 2_000.0, 1: 70_000.0}
        planned: set[str] = set()

        planner._compute_lock_wake_actions(1, provider.lanes, planned)

        assert "model-b" not in planned

    def test_free_memory_on_the_lanes_own_gpu_makes_the_lock_wake_fit(self):
        planner, provider = self._scenario()
        provider.available_vram_mb = 72_000.0
        planner._get_per_gpu_free = lambda pid: {0: 70_000.0, 1: 2_000.0}
        planned: set[str] = set()

        planner._compute_lock_wake_actions(1, provider.lanes, planned)

        assert "model-b" in planned
