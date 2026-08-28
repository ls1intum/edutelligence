"""Per-model replica counts: a model may hold more than one lane on a worker.

Issue #789 — "Can a model be deployed multiple times on one node?" The
capacity planner loads extra lanes of a model up to its configured replica
count (``models.replicas``, default 1), and the operator's manual "Load lane"
adds one more lane instead of no-opping once a lane exists.

The pieces under test:

* lane id allocation — replica 1 keeps the historical id (``planner-<alias>``)
  so lanes placed before the count existed stay addressable, replicas from two
  on append ``-<index>``;
* "taken" vs "live" accounting — every lane the worker holds for the model,
  in any runtime state, blocks its id (the worker refuses ``add_lane`` for an
  existing id), but only lanes in a live state count toward the model's
  replica demand (an errored lane must not mask a reload);
* the manual load path — adds one lane up to the count, a no-op at the cap,
  re-checking the count under the per-lane lock;
* the demand path — emits an extra load for a model that has fewer live
  lanes than it wants, on the next free id.
"""

from __future__ import annotations

import asyncio
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

from logos import CapacityPlanner, LaneSchedulerSignals  # noqa: E402


def _lane(
    lane_id: str,
    model_name: str,
    runtime_state: str = "loaded",
    sleep_state: str = "awake",
) -> LaneSchedulerSignals:
    return LaneSchedulerSignals(
        lane_id=lane_id,
        model_name=model_name,
        runtime_state=runtime_state,
        sleep_state=sleep_state,
        is_vllm=True,
        active_requests=0,
        queue_waiting=0.0,
        requests_running=0.0,
        gpu_cache_usage_percent=None,
        ttft_p95_seconds=0.0,
        e2e_latency_p50_seconds=0.0,
        effective_vram_mb=20_000.0,
        num_parallel=0,
        gpu_devices="0",
    )


class TestPlannerLaneId:
    """Replica lane ids: historical id for replica 1, ``-<index>`` for the rest."""

    def _planner(self) -> CapacityPlanner:
        return CapacityPlanner.__new__(CapacityPlanner)

    def test_replica_one_keeps_the_historical_id(self):
        planner = self._planner()
        assert planner._planner_lane_id("org/model-a") == "planner-org_model-a"
        assert planner._planner_lane_id("org/model-a", 1) == "planner-org_model-a"

    def test_sanitizes_separators(self):
        planner = self._planner()
        assert planner._planner_lane_id("org:sub model/x", 2) == "planner-org_sub_model_x-2"

    def test_replicas_from_two_on_append_the_index(self):
        planner = self._planner()
        assert planner._planner_lane_id("m", 2) == "planner-m-2"
        assert planner._planner_lane_id("m", 3) == "planner-m-3"
        assert planner._planner_lane_id("m", 16) == "planner-m-16"

    def test_index_below_one_collapses_to_replica_one(self):
        planner = self._planner()
        assert planner._planner_lane_id("m", 0) == "planner-m"
        assert planner._planner_lane_id("m", -3) == "planner-m"


class TestNextLaneIdForModel:
    """The lowest replica id the worker does not hold for the model."""

    def _planner(self, lanes: List[LaneSchedulerSignals]) -> CapacityPlanner:
        planner = CapacityPlanner.__new__(CapacityPlanner)
        facade = MagicMock()
        facade.get_all_provider_lane_signals.return_value = lanes
        planner._facade = facade
        return planner

    def test_first_load_lands_on_replica_one_id(self):
        planner = self._planner([])
        assert planner._next_lane_id_for_model(1, "org/model-a") == "planner-org_model-a"

    def test_occupied_replica_one_moves_to_two(self):
        lanes = [_lane("planner-org_model-a", "org/model-a", "loaded")]
        planner = self._planner(lanes)
        assert planner._next_lane_id_for_model(1, "org/model-a") == "planner-org_model-a-2"

    def test_an_errored_lane_still_holds_its_id(self):
        """The worker keys lanes by id and refuses add_lane for an existing
        handle — even one in error state. The new lane must get a fresh id."""
        lanes = [_lane("planner-org_model-a", "org/model-a", "error")]
        planner = self._planner(lanes)
        assert planner._next_lane_id_for_model(1, "org/model-a") == "planner-org_model-a-2"

    def test_skips_to_the_lowest_free_index(self):
        lanes = [
            _lane("planner-m", "m", "running"),
            _lane("planner-m-2", "m", "loaded"),
        ]
        planner = self._planner(lanes)
        assert planner._next_lane_id_for_model(1, "m") == "planner-m-3"

    def test_a_gap_after_an_unload_is_reused(self):
        """Replica 2 was unloaded (lane gone from the worker) → its id is free
        again and the next load takes it, not 3."""
        lanes = [_lane("planner-m", "m", "running"), _lane("planner-m-3", "m", "loaded")]
        planner = self._planner(lanes)
        assert planner._next_lane_id_for_model(1, "m") == "planner-m-2"

    def test_other_models_lanes_do_not_block(self):
        lanes = [_lane("planner-org_model-a-2", "other/model")]
        planner = self._planner(lanes)
        assert planner._next_lane_id_for_model(1, "org/model-a") == "planner-org_model-a"


class TestDesiredReplicas:
    """The configured count, with a fallback to the historical single lane."""

    def _planner(self, facade) -> CapacityPlanner:
        planner = CapacityPlanner.__new__(CapacityPlanner)
        planner._facade = facade
        return planner

    def test_reads_the_configured_count(self):
        facade = MagicMock()
        facade.get_model_replicas.return_value = 3
        assert self._planner(facade)._desired_replicas("m") == 3

    def test_zero_and_negative_degrade_to_one(self):
        facade = MagicMock()
        facade.get_model_replicas.return_value = 0
        assert self._planner(facade)._desired_replicas("m") == 1

    def test_missing_method_falls_back_to_one(self):
        """A facade without the method (pre-upgrade, or a test double) must
        degrade to the single-lane behaviour, not break the planner cycle."""
        assert self._planner(SimpleNamespace())._desired_replicas("m") == 1


class TestCountLiveLanesForModel:
    """Live = everything except stopped and error; a sleeper keeps its slot."""

    def _planner(self, lanes: List[LaneSchedulerSignals]) -> CapacityPlanner:
        planner = CapacityPlanner.__new__(CapacityPlanner)
        facade = MagicMock()
        facade.get_all_provider_lane_signals.return_value = lanes
        planner._facade = facade
        return planner

    def test_counts_all_live_states(self):
        lanes = [
            _lane("planner-m", "m", "running"),
            _lane("planner-m-2", "m", "loaded"),
            _lane("planner-m-3", "m", "loaded", sleep_state="sleeping"),
            _lane("planner-m-4", "m", "starting"),
        ]
        assert self._planner(lanes)._count_live_lanes_for_model(1, "m") == 4

    def test_stopped_and_error_do_not_count(self):
        lanes = [
            _lane("planner-m", "m", "running"),
            _lane("planner-m-2", "m", "error"),
            _lane("planner-m-3", "m", "stopped"),
        ]
        assert self._planner(lanes)._count_live_lanes_for_model(1, "m") == 1

    def test_other_models_are_excluded(self):
        lanes = [_lane("planner-m", "m", "running"), _lane("planner-other", "other", "running")]
        assert self._planner(lanes)._count_live_lanes_for_model(1, "m") == 1


# ---------------------------------------------------------------------------
# Manual "Load lane"
# ---------------------------------------------------------------------------


def _manual_load_planner(
    lanes: List[LaneSchedulerSignals],
    *,
    replicas: Any = "unset",
) -> CapacityPlanner:
    """Planner with a mock facade reporting exactly `lanes`."""
    planner = CapacityPlanner.__new__(CapacityPlanner)
    registry = MagicMock()
    registry.is_calibrating.return_value = False
    registry.has_received_first_status.return_value = True
    planner._registry = registry
    facade = MagicMock()
    facade.get_capacity_info.return_value = object()
    facade.get_provider_name.return_value = "worker-a"
    facade.get_all_provider_lane_signals.return_value = lanes
    if replicas != "unset":
        facade.get_model_replicas.return_value = replicas
    else:
        # A plain MagicMock's __int__ is 1: the "no count configured" case.
        pass
    planner._facade = facade
    planner._lane_action_locks = {}
    planner._safe_get_profiles = MagicMock(return_value={})
    planner._build_load_params = MagicMock(return_value={})
    return planner


def _with_capture(planner: CapacityPlanner) -> List[str]:
    """Route the dispatch through a recorder; the runtime "sees" a lane the
    moment its command goes out."""
    dispatched: List[str] = []

    async def execute(action, timeout_seconds=None):
        dispatched.append(action.lane_id)
        return True

    planner._execute_action_with_confirmation = execute
    planner._lane_exists_in_runtime = lambda provider_id, lane_id: lane_id in dispatched
    return dispatched


class TestManualLoadReplicas:
    def test_adds_a_second_lane_when_replicas_allow(self):
        planner = _manual_load_planner(
            [_lane("planner-org_model-a", "org/model-a", "running")],
            replicas=2,
        )
        dispatched = _with_capture(planner)

        assert asyncio.run(planner.load_lane_manually(1, "org/model-a")) is True
        assert dispatched == ["planner-org_model-a-2"]

    def test_is_a_no_op_at_the_full_replica_set(self):
        planner = _manual_load_planner(
            [
                _lane("planner-org_model-a", "org/model-a", "running"),
                _lane("planner-org_model-a-2", "org/model-a", "loaded"),
            ],
            replicas=2,
        )
        dispatched = _with_capture(planner)

        assert asyncio.run(planner.load_lane_manually(1, "org/model-a")) is False
        assert dispatched == []

    def test_default_stays_single_lane(self):
        """Without a configured count the historical rule holds: a model with
        a lane is not loaded a second time by the operator's button."""
        planner = _manual_load_planner([_lane("planner-org_model-a", "org/model-a", "running")])
        dispatched = _with_capture(planner)

        assert asyncio.run(planner.load_lane_manually(1, "org/model-a")) is False
        assert dispatched == []

    def test_an_errored_lane_does_not_fill_the_slot(self):
        """A model whose only lane is in error is short of its demand — the
        operator may reload it, and the new lane gets the next free id."""
        planner = _manual_load_planner([_lane("planner-org_model-a", "org/model-a", "error")], replicas=1)
        dispatched = _with_capture(planner)

        assert asyncio.run(planner.load_lane_manually(1, "org/model-a")) is True
        assert dispatched == ["planner-org_model-a-2"]

    def test_a_sleeping_replica_still_counts(self):
        """A sleeping lane holds its VRAM residual — loading another one on
        top would exceed the configured count's memory budget."""
        planner = _manual_load_planner(
            [
                _lane("planner-org_model-a", "org/model-a", "loaded"),
                _lane("planner-org_model-a-2", "org/model-a", "loaded", sleep_state="sleeping"),
            ],
            replicas=2,
        )
        dispatched = _with_capture(planner)

        assert asyncio.run(planner.load_lane_manually(1, "org/model-a")) is False
        assert dispatched == []

    def test_rechecks_the_count_under_the_lane_lock(self):
        """A second click — or a planner cycle — can fill the last slot while
        this load waits for the per-lane lock. The in-lock re-read turns it
        into a no-op instead of a duplicate lane."""
        lanes_before = [_lane("planner-org_model-a", "org/model-a", "running")]
        planner = _manual_load_planner(lanes_before, replicas=2)
        facade = planner._facade
        # Pre-lock read sees one lane; the dispatch-time re-read sees the
        # sibling load that landed while the lock was held.
        facade.get_all_provider_lane_signals.side_effect = [
            lanes_before,
            [
                _lane("planner-org_model-a", "org/model-a", "running"),
                _lane("planner-org_model-a-2", "org/model-a", "starting"),
            ],
        ]
        dispatched = _with_capture(planner)

        assert asyncio.run(planner.load_lane_manually(1, "org/model-a")) is False
        assert dispatched == []


# ---------------------------------------------------------------------------
# Demand path: the planner loads a model's next replica
# ---------------------------------------------------------------------------


@dataclass
class _MockProvider:
    provider_id: int
    name: str
    lanes: List[LaneSchedulerSignals] = field(default_factory=list)
    profiles: Dict[str, Any] = field(default_factory=dict)
    capabilities: List[str] = field(default_factory=list)
    available_vram_mb: float = 0.0
    total_vram_mb: float = 96_000.0
    replicas: Dict[str, int] = field(default_factory=dict)


class _MockFacade:
    def __init__(self, providers: List[_MockProvider]):
        self._providers = {p.provider_id: p for p in providers}

    def get_all_provider_lane_signals(self, provider_id: int) -> List[LaneSchedulerSignals]:
        return list(self._providers[provider_id].lanes)

    def get_model_profiles(self, provider_id: int) -> Dict[str, Any]:
        return dict(self._providers[provider_id].profiles)

    def get_worker_capabilities(self, provider_id: int) -> List[str]:
        return list(self._providers[provider_id].capabilities)

    def get_capacity_info(self, provider_id: int):
        p = self._providers[provider_id]
        return SimpleNamespace(
            available_vram_mb=p.available_vram_mb,
            total_vram_mb=p.total_vram_mb,
            loaded_models=[],
        )

    def get_provider_name(self, provider_id: int) -> str:
        return self._providers[provider_id].name

    def provider_ids(self) -> List[int]:
        return list(self._providers.keys())

    def get_scheduler_queue_depth_by_model_name(self, model_name: str, provider_id: int) -> int:
        return 0

    def get_model_replicas(self, model_name: str) -> int:
        for p in self._providers.values():
            if model_name in p.replicas:
                return p.replicas[model_name]
        return 1


def _profile(loaded_vram_mb: float = 20_000.0) -> SimpleNamespace:
    return SimpleNamespace(
        loaded_vram_mb=loaded_vram_mb,
        sleeping_residual_mb=500.0,
        base_residency_mb=loaded_vram_mb,
        kv_budget_mb=0.0,
        tensor_parallel_size=1,
        residency_source="calibrated",
        engine="vllm",
        estimate_base_residency_mb=lambda: loaded_vram_mb,
    )


def _planner(provider: _MockProvider, *, score: float = 2.0) -> CapacityPlanner:
    facade = _MockFacade([provider])
    registry = MagicMock()
    registry.has_received_first_status.return_value = True
    registry.is_calibrating.return_value = False
    registry.peek_runtime_snapshot.return_value = {"runtime": {"lanes": [], "devices": {}}}
    demand = MagicMock()
    demand.get_ranked_models.return_value = [("X", score)]
    demand.get_score.return_value = score

    planner = CapacityPlanner.__new__(CapacityPlanner)
    planner._facade = facade
    planner._registry = registry
    planner._demand = demand
    planner._lane_wake_failure_until = {}
    planner._lane_load_failure_until = {}
    planner._cross_provider_best_first = True
    planner._replica_first_eviction = True
    planner._cross_provider_dedup = False
    planner._lane_loaded_at = {}
    planner._lane_idle_since = {}
    planner._lane_sleep_since = {}
    planner._lane_sleep_level = {}
    planner._load_cooldown_seconds = 0.0
    planner._eviction_gate_v2 = True
    planner._stop_dedup_siblings = False
    planner._announced_use = {}
    planner._provider_capacity_lock = lambda pid: SimpleNamespace(locked=lambda: False)
    planner._vram_ledger = SimpleNamespace(
        get_committed_mb=lambda pid: 0.0,
        has_overlapping_reservation=lambda *a, **k: False,
        get_gpu_effective_available_mb=lambda pid, g, f: f,
    )
    planner._get_queue_depth_across_deployments = lambda *_: 0
    planner._build_load_params = lambda *a, **k: {}
    # The gate under test is lane-id allocation, not feasibility: with the
    # profile shape above the real gate would additionally parse KV pairs the
    # stub profile does not carry.
    planner._passes_minimum_load_feasibility = lambda *a, **k: True
    return planner


class TestDemandPathSecondLane:
    def test_loads_the_second_replica_on_the_next_free_id(self):
        provider = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[_lane("planner-X", "X", "running")],
            capabilities=["X"],
            available_vram_mb=50_000,
            profiles={"X": _profile()},
            replicas={"X": 2},
        )
        planner = _planner(provider)

        actions = planner._compute_demand_actions(1, provider.lanes)

        kinds = [(a.action, a.provider_id, a.lane_id) for a in actions]
        assert ("load", 1, "planner-X-2") in kinds
        # The id the first replica holds is not planned again.
        assert ("load", 1, "planner-X") not in kinds

    def test_no_second_load_below_the_configured_count(self):
        """replicas=1 (the historical default): a model with its one lane
        gets no further load — the pre-#789 behaviour is preserved."""
        provider = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[_lane("planner-X", "X", "running")],
            capabilities=["X"],
            available_vram_mb=50_000,
            profiles={"X": _profile()},
            replicas={"X": 1},
        )
        planner = _planner(provider)

        assert planner._compute_demand_actions(1, provider.lanes) == []

    def test_surplus_sleeper_stays_asleep_at_the_replica_cap(self):
        """The operator lowered the count: the model runs its full set of two
        lanes and a third, sleeping surplus lane exists. The wake path must
        not raise the active set past the configured count — the surplus
        sleeper stays asleep (and no cold load tops it up either)."""
        provider = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[
                _lane("planner-X", "X", "running"),
                _lane("planner-X-2", "X", "running"),
                _lane("planner-X-3", "X", "loaded", sleep_state="sleeping"),
            ],
            capabilities=["X"],
            available_vram_mb=50_000,
            profiles={"X": _profile()},
            replicas={"X": 2},
        )
        planner = _planner(provider)

        actions = planner._compute_demand_actions(1, provider.lanes)

        assert actions == []

    def test_sleeper_still_wakes_below_the_cap(self):
        """The sleeping lane is one of the model's configured set (one awake
        lane, count 2) — waking it brings the model up to its count, the
        pre-#789 behaviour."""
        provider = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[
                _lane("planner-X", "X", "running"),
                _lane("planner-X-2", "X", "loaded", sleep_state="sleeping"),
            ],
            capabilities=["X"],
            available_vram_mb=50_000,
            profiles={"X": _profile()},
            replicas={"X": 2},
        )
        planner = _planner(provider)

        actions = planner._compute_demand_actions(1, provider.lanes)

        kinds = [(a.action, a.lane_id) for a in actions]
        assert ("wake", "planner-X-2") in kinds
        assert all(action == "wake" for action, _ in kinds)

    def test_single_sleeper_still_wakes_at_the_default_count(self):
        """Base case the cap check must not break: replicas=1 (default), the
        model's one lane is sleeping — waking it does not add a lane, it
        reactivates the model's only replica."""
        provider = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[_lane("planner-X", "X", "loaded", sleep_state="sleeping")],
            capabilities=["X"],
            available_vram_mb=50_000,
            profiles={"X": _profile()},
        )
        planner = _planner(provider)

        actions = planner._compute_demand_actions(1, provider.lanes)

        assert [(a.action, a.lane_id) for a in actions] == [("wake", "planner-X")]

    def test_first_load_still_lands_on_the_historical_id(self):
        provider = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[],
            capabilities=["X"],
            available_vram_mb=50_000,
            profiles={"X": _profile()},
            replicas={"X": 2},
        )
        planner = _planner(provider)

        actions = planner._compute_demand_actions(1, provider.lanes)

        kinds = [(a.action, a.lane_id) for a in actions]
        assert ("load", "planner-X") in kinds
        # One lane per cycle: the second replica follows once the first is up.
        assert all(lane_id == "planner-X" for _a, lane_id in kinds if "X" in lane_id)
