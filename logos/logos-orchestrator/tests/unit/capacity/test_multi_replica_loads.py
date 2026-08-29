"""Multiple lanes of one model on a worker, placed dynamically.

Issue #789 — "Can a model be deployed multiple times on one node?" There is
no configured replica count anywhere (no ``models.replicas``, no worker
entry): the planner derives scale-out from the live signals, the same
principle that dropped ``models.parallel``. A model's additional lane on a
worker that already runs it is speculative scale-out — the same deal as the
cross-provider replication pass: behind ``LOGOS_REPLICATE_ON_FREE_VRAM``,
sustained demand (``DEMAND_REPLICATION_FLOOR``), free VRAM without eviction,
and the cluster-wide copy cap. The operator's manual "Load lane" adds one
more lane instead of no-opping once a lane exists.

The pieces under test:

* lane id allocation — replica 1 keeps the historical id (``planner-<alias>``)
  so lanes placed before scale-out existed stay addressable, replicas from
  two on append ``-<index>``;
* the manual load path — adds one lane on the next free id, a no-op only
  once that id exists (re-checked under the per-lane lock);
* the demand path — the first lane keeps the full load semantics; an
  additional lane needs the replication flag + sustained demand + no
  eviction + cluster cap headroom.
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


# ---------------------------------------------------------------------------
# Manual "Load lane"
# ---------------------------------------------------------------------------


def _manual_load_planner(lanes: List[LaneSchedulerSignals]) -> CapacityPlanner:
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


class TestManualLoadLane:
    def test_adds_a_second_lane_to_an_already_loaded_model(self):
        planner = _manual_load_planner([_lane("planner-org_model-a", "org/model-a", "running")])
        dispatched = _with_capture(planner)

        assert asyncio.run(planner.load_lane_manually(1, "org/model-a")) is True
        assert dispatched == ["planner-org_model-a-2"]

    def test_an_errored_lane_does_not_fill_the_slot(self):
        """A model whose only lane is in error is not really running — the
        operator may load a fresh one, and it gets the next free id (the
        broken lane still holds replica 1's)."""
        planner = _manual_load_planner([_lane("planner-org_model-a", "org/model-a", "error")])
        dispatched = _with_capture(planner)

        assert asyncio.run(planner.load_lane_manually(1, "org/model-a")) is True
        assert dispatched == ["planner-org_model-a-2"]

    def test_a_second_click_is_a_no_op_once_the_first_is_dispatched(self):
        """The API answers 202 and the load runs in the background, so a
        second click arrives while the first is in flight. Both derive the
        same next-free lane id — the in-lock re-read against the runtime
        turns the second into a no-op instead of a duplicate lane."""
        planner = _manual_load_planner([_lane("planner-org_model-a", "org/model-a", "running")])
        dispatched = _with_capture(planner)

        assert asyncio.run(planner.load_lane_manually(1, "org/model-a")) is True
        assert asyncio.run(planner.load_lane_manually(1, "org/model-a")) is False
        assert dispatched == ["planner-org_model-a-2"]

    def test_no_op_when_the_lane_id_already_exists_under_the_lock(self):
        """A concurrent planner load — or another click — took the id while
        this load waited for the per-lane lock. The in-lock re-read catches
        it even when the lane-signal feed has not caught up yet."""
        planner = _manual_load_planner([_lane("planner-org_model-a", "org/model-a", "running")])
        dispatched = _with_capture(planner)
        planner._lane_exists_in_runtime = lambda provider_id, lane_id: lane_id == "planner-org_model-a-2"

        assert asyncio.run(planner.load_lane_manually(1, "org/model-a")) is False
        assert dispatched == []

    def test_refuses_without_a_capacity_snapshot(self):
        """No capacity snapshot → the lane cannot be checked against free
        VRAM → the load is refused with the reason the operator gets."""
        planner = _manual_load_planner([_lane("planner-org_model-a", "org/model-a", "running")])
        dispatched = _with_capture(planner)
        planner._facade.get_capacity_info.return_value = None

        assert asyncio.run(planner.load_lane_manually(1, "org/model-a")) is False
        assert dispatched == []
        assert "No capacity information" in planner.manual_load_rejection_reason(1)


# ---------------------------------------------------------------------------
# Demand path: the planner scales a model out by one additional lane
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


def _planner(provider: _MockProvider, *, score: float = 2.0, replicate: bool = False) -> CapacityPlanner:
    """Harness for the per-worker demand pass. ``replicate`` maps to the
    ``LOGOS_REPLICATE_ON_FREE_VRAM`` flag the scale-out gate reads."""
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
    planner._replicate_on_free_vram = replicate
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
    # The gate under test is the scale-out decision, not feasibility: with the
    # profile shape above the real gate would additionally parse KV pairs the
    # stub profile does not carry.
    planner._passes_minimum_load_feasibility = lambda *a, **k: True
    return planner


class TestDemandPathAdditionalLane:
    def test_first_lane_keeps_full_load_semantics(self):
        """No lane yet: the first load needs only the load floor (1.0) and no
        replication flag — score 1.2 loads onto the historical id even with
        replication off. One lane per cycle; scale-out follows later."""
        provider = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[],
            capabilities=["X"],
            available_vram_mb=50_000,
            profiles={"X": _profile()},
        )
        planner = _planner(provider, score=1.2, replicate=False)

        actions = planner._compute_demand_actions(1, provider.lanes)

        kinds = [(a.action, a.lane_id) for a in actions]
        assert ("load", "planner-X") in kinds
        assert all(lane_id == "planner-X" for _a, lane_id in kinds if "X" in lane_id)

    def test_additional_lane_requires_the_replication_flag(self):
        """The model runs hot (2.5 ≥ replication floor) and VRAM is free, but
        the rollout flag is off: no second lane — the pre-scale-out
        behaviour is preserved by default."""
        provider = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[_lane("planner-X", "X", "running")],
            capabilities=["X"],
            available_vram_mb=50_000,
            profiles={"X": _profile()},
        )
        planner = _planner(provider, score=2.5, replicate=False)

        assert planner._compute_demand_actions(1, provider.lanes) == []

    def test_additional_lane_loads_on_sustained_demand_and_free_vram(self):
        provider = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[_lane("planner-X", "X", "running")],
            capabilities=["X"],
            available_vram_mb=50_000,
            profiles={"X": _profile()},
        )
        planner = _planner(provider, score=2.5, replicate=True)

        actions = planner._compute_demand_actions(1, provider.lanes)

        kinds = [(a.action, a.provider_id, a.lane_id) for a in actions]
        assert ("load", 1, "planner-X-2") in kinds
        # The id the first lane holds is not planned again.
        assert ("load", 1, "planner-X") not in kinds

    def test_additional_lane_needs_sustained_demand(self):
        """1.2 is hot enough for a first lane but below the replication
        floor (2.0): no second copy — scale-out is for sustained load, not
        a single spike."""
        provider = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[_lane("planner-X", "X", "running")],
            capabilities=["X"],
            available_vram_mb=50_000,
            profiles={"X": _profile()},
        )
        planner = _planner(provider, score=1.2, replicate=True)

        assert planner._compute_demand_actions(1, provider.lanes) == []

    def test_additional_lane_never_evicts(self):
        """An extra copy must not push out another model's lane: when the
        placement needs an eviction set, the scale-out is skipped outright."""
        provider = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[
                _lane("planner-X", "X", "running"),
                _lane("planner-other", "other", "running"),
            ],
            capabilities=["X", "other"],
            available_vram_mb=50_000,
            profiles={"X": _profile(), "other": _profile()},
        )
        planner = _planner(provider, score=2.5, replicate=True)
        planner._pick_cold_load_placement = lambda *a, **k: ("0", [(_lane("planner-other", "other"), "stop", None)])

        assert planner._compute_demand_actions(1, provider.lanes) == []

    def test_additional_lane_respects_the_cluster_copy_cap(self):
        """The model already has MAX_REPLICAS_PER_MODEL copies cluster-wide —
        this worker would be the 4th: the scale-out stops at the cap, same
        as the cross-provider pass."""
        provider = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[_lane("planner-X", "X", "running")],
            capabilities=["X"],
            available_vram_mb=50_000,
            profiles={"X": _profile()},
        )
        planner = _planner(provider, score=2.5, replicate=True)

        actions = planner._compute_demand_actions(
            1, provider.lanes, cluster_lanes_by_model={"X": CapacityPlanner.MAX_REPLICAS_PER_MODEL}
        )

        assert actions == []

    def test_sleeper_wakes_even_while_siblings_run(self):
        """Waking the model's own sleeping lane is not an additional copy —
        it stays subject to the wake floor (0.5), not the replication gate:
        score 0.7 wakes it with replication off, and no cold load is emitted
        on top."""
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
        )
        planner = _planner(provider, score=0.7, replicate=False)

        actions = planner._compute_demand_actions(1, provider.lanes)

        kinds = [(a.action, a.lane_id) for a in actions]
        assert ("wake", "planner-X-2") in kinds
        assert all(action == "wake" for action, _ in kinds)

    def test_single_sleeper_still_wakes(self):
        """Base case: the model's one lane is sleeping — waking it does not
        add a lane, it reactivates the model's only copy."""
        provider = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[_lane("planner-X", "X", "loaded", sleep_state="sleeping")],
            capabilities=["X"],
            available_vram_mb=50_000,
            profiles={"X": _profile()},
        )
        planner = _planner(provider, score=0.7, replicate=False)

        actions = planner._compute_demand_actions(1, provider.lanes)

        assert [(a.action, a.lane_id) for a in actions] == [("wake", "planner-X")]
