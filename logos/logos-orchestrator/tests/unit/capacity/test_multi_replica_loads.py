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
import time
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
    """The lowest replica id no lane on the worker holds.

    The reservation is worker-wide, not per-model: the replica suffix scheme
    is not unique across models (``planner-foo-2`` is replica 2 of ``foo``
    and replica 1 of ``foo-2``), and the worker keys lanes by id alone.
    """

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

    def test_other_models_lanes_do_not_block_a_free_replica_one(self):
        lanes = [_lane("planner-org_model-a-2", "other/model")]
        planner = self._planner(lanes)
        assert planner._next_lane_id_for_model(1, "org/model-a") == "planner-org_model-a"

    def test_other_models_lanes_block_their_ids(self):
        """foo's replica 2 and foo-2's replica 1 share one id. A worker that
        holds it for one form must not be handed a load for the other under
        the same id — the reservation spans every lane on the worker."""
        lanes = [
            _lane("planner-foo", "foo", "running"),
            _lane("planner-foo-2", "foo-2", "running"),
        ]
        planner = self._planner(lanes)
        # foo's replica-2 id is held by foo-2's replica 1 → skip to 3.
        assert planner._next_lane_id_for_model(1, "foo") == "planner-foo-3"
        # foo-2's replica-1 id is held (by itself) → its next id is 2.
        assert planner._next_lane_id_for_model(1, "foo-2") == "planner-foo-2-2"


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


# ---------------------------------------------------------------------------
# Backoff when a replica lands in error
# ---------------------------------------------------------------------------


class TestErroredLaneBackoff:
    """A replica load the worker accepted can still fail afterwards: the lane
    lands in ``error`` and keeps holding its lane id. Without a backoff the
    allocator skips that id, the per-lane cooldown never covers the fresh
    suffix, and the copy cap does not count the errored lane — sustained
    demand then leaves a fresh errored lane behind every cycle."""

    def test_errored_replica_blocks_the_next_suffix(self):
        """Replica 1 runs, replica 2 errored, demand is hot and the scale-out
        flag is on. The next cycle must not allocate planner-X-3 — it backs
        off until the errored lane goes away."""
        provider = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[_lane("planner-X", "X", "running"), _lane("planner-X-2", "X", "error")],
            capabilities=["X"],
            available_vram_mb=50_000,
            profiles={"X": _profile()},
        )
        planner = _planner(provider, score=2.5, replicate=True)

        assert planner._compute_demand_actions(1, provider.lanes) == []

    def test_errored_first_lane_blocks_a_reload_on_a_fresh_id(self):
        """The model's only lane errored and nothing serves it: a first load
        would take the next free id (the broken lane still holds replica
        1's). That must back off too, or the same failure replays under a
        fresh suffix."""
        provider = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[_lane("planner-X", "X", "error")],
            capabilities=["X"],
            available_vram_mb=50_000,
            profiles={"X": _profile()},
        )
        planner = _planner(provider, score=1.2, replicate=False)

        assert planner._compute_demand_actions(1, provider.lanes) == []

    def test_cooldown_on_any_lane_of_the_model_blocks(self):
        """Confirmation-timeout window: the load was marked failed but the
        lane has not landed in error yet (still starting). Any lane of the
        model in load-failure cooldown blocks the next suffix."""
        provider = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[_lane("planner-X", "X", "running"), _lane("planner-X-2", "X", "starting")],
            capabilities=["X"],
            available_vram_mb=50_000,
            profiles={"X": _profile()},
        )
        planner = _planner(provider, score=2.5, replicate=True)
        planner._lane_load_failure_until[planner._lane_key(1, "planner-X-2")] = time.time() + 60

        assert planner._compute_demand_actions(1, provider.lanes) == []

    def test_other_models_errored_lanes_do_not_block(self):
        provider = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[_lane("planner-X", "X", "running"), _lane("planner-Y", "Y", "error")],
            capabilities=["X", "Y"],
            available_vram_mb=50_000,
            profiles={"X": _profile(), "Y": _profile()},
        )
        planner = _planner(provider, score=2.5, replicate=True)

        actions = planner._compute_demand_actions(1, provider.lanes)
        kinds = [(a.action, a.lane_id) for a in actions]

        assert ("load", "planner-X-2") in kinds

    def test_ranker_excludes_a_worker_with_an_errored_lane(self):
        planner = _planner(
            _MockProvider(provider_id=1, name="A", lanes=[], capabilities=["X"], available_vram_mb=50_000),
            score=2.5,
        )
        capacity = SimpleNamespace(available_vram_mb=50_000, total_vram_mb=96_000, loaded_models=[])
        profiles = {"X": _profile()}

        # No lane: a plain cold load — the ranker scores it.
        assert planner._estimate_demand_action_cost(1, "X", [], profiles, capacity) is not None
        # An errored replica makes the worker infeasible for the model.
        assert (
            planner._estimate_demand_action_cost(1, "X", [_lane("planner-X", "X", "error")], profiles, capacity) is None
        )
        # ... but a sleeping lane is a wake, which keeps its own cooldown —
        # the error backoff does not eat the wake path.
        assert (
            planner._estimate_demand_action_cost(
                1, "X", [_lane("planner-X", "X", "loaded", sleep_state="sleeping")], profiles, capacity
            )
            is not None
        )

    def test_errored_lane_is_marked_in_cooldown_without_remarking(self):
        provider = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[_lane("planner-X", "X", "running"), _lane("planner-X-2", "X", "error")],
            capabilities=["X"],
            available_vram_mb=50_000,
            profiles={"X": _profile()},
        )
        planner = _planner(provider, score=2.5, replicate=True)

        planner._reconcile_load_failures(1, provider.lanes)
        assert planner._lane_is_in_load_failure_cooldown(1, "planner-X-2") is True
        assert planner._lane_is_in_load_failure_cooldown(1, "planner-X") is False

        # A persistently errored lane is not re-marked while already cooling
        # down — one log line per cooldown window, not one per cycle.
        key = planner._lane_key(1, "planner-X-2")
        until_before = planner._lane_load_failure_until[key]
        planner._reconcile_load_failures(1, provider.lanes)
        assert planner._lane_load_failure_until[key] == until_before

    def test_replication_skips_a_worker_whose_copy_errored(self):
        """The cross-provider pass loads replica 1's id on a worker that does
        not host the model; an errored lane still holds that id, so the
        worker is skipped rather than getting a rejected add_lane."""
        healthy = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[_lane("planner-X", "X", "running")],
            capabilities=["X"],
            available_vram_mb=50_000,
            profiles={"X": _profile()},
        )
        broken = _MockProvider(
            provider_id=2,
            name="B",
            lanes=[_lane("planner-X", "X", "error")],
            capabilities=["X"],
            available_vram_mb=50_000,
            profiles={"X": _profile()},
        )
        planner = _planner(healthy, score=2.5, replicate=True)
        planner._facade = _MockFacade([healthy, broken])

        actions = planner._compute_replication_actions([1, 2], [("X", 2.5)], {"X": 1}, set())
        assert actions == []

        # Same worker with the broken lane gone is a valid replica target.
        broken.lanes = []
        actions = planner._compute_replication_actions([1, 2], [("X", 2.5)], {"X": 1}, set())
        assert [(a.provider_id, a.lane_id) for a in actions] == [(2, "planner-X")]


# ---------------------------------------------------------------------------
# A load that timed out in starting: the marker outlives the cooldown
# ---------------------------------------------------------------------------


class TestStuckStartingBackoff:
    """A load the worker accepted can time out in confirmation and leave its
    lane in ``starting`` indefinitely. The per-lane cooldown expires after
    120s on a timer — but the lane is still stuck and still holding its id.
    The persistent load-failure marker therefore blocks allocation until the
    lane serves again or leaves the worker, not until the clock runs out."""

    @staticmethod
    def _expire(planner: CapacityPlanner, provider_id: int, lane_id: str) -> None:
        planner._mark_load_failure(provider_id, lane_id, details="load confirmation timed out")
        planner._lane_load_failure_until[planner._lane_key(provider_id, lane_id)] = time.time() - 1

    def test_stuck_replica_still_blocks_after_cooldown_expiry(self):
        """Replica 1 runs, replica 2 timed out in starting, and its cooldown
        has run out: the cycle must NOT allocate a fresh suffix on top —
        before the marker it saw the lane as active and cooled down."""
        provider = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[_lane("planner-X", "X", "running"), _lane("planner-X-2", "X", "starting")],
            capabilities=["X"],
            available_vram_mb=50_000,
            profiles={"X": _profile()},
        )
        planner = _planner(provider, score=2.5, replicate=True)
        self._expire(planner, 1, "planner-X-2")

        assert planner._compute_demand_actions(1, provider.lanes) == []

    def test_gate_names_the_stuck_lane_not_the_expired_cooldown(self):
        provider = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[_lane("planner-X", "X", "running"), _lane("planner-X-2", "X", "starting")],
            capabilities=["X"],
            available_vram_mb=50_000,
            profiles={"X": _profile()},
        )
        planner = _planner(provider, score=2.5, replicate=True)
        self._expire(planner, 1, "planner-X-2")

        reason = planner._model_cold_load_blocked_reason(1, "X", provider.lanes)
        assert reason is not None
        assert "planner-X-2" in reason
        assert "not serving" in reason

    def test_stuck_first_lane_blocks_a_reload_on_a_fresh_id(self):
        """The model's only lane timed out in starting and its cooldown is
        gone: without the marker the planner treats the stuck lane as active
        and plans an *additional* lane under a fresh suffix instead of
        backing off the whole model."""
        provider = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[_lane("planner-X", "X", "starting")],
            capabilities=["X"],
            available_vram_mb=50_000,
            profiles={"X": _profile()},
        )
        planner = _planner(provider, score=2.5, replicate=True)
        self._expire(planner, 1, "planner-X")

        assert planner._compute_demand_actions(1, provider.lanes) == []

    def test_stuck_lane_keeps_the_cooldown_alive_across_cycles(self):
        """A lane still ``starting`` with a marker re-arms the per-lane
        cooldown every cycle, so the cooldown readers (gate, ranker,
        pre-pass) agree with the marker even after the timer ran out."""
        provider = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[_lane("planner-X", "X", "running"), _lane("planner-X-2", "X", "starting")],
            capabilities=["X"],
            available_vram_mb=50_000,
            profiles={"X": _profile()},
        )
        planner = _planner(provider, score=2.5, replicate=True)
        self._expire(planner, 1, "planner-X-2")

        planner._reconcile_load_failures(1, provider.lanes)

        assert planner._lane_is_in_load_failure_cooldown(1, "planner-X-2") is True

    def test_lane_reaching_serving_state_clears_the_marker(self):
        """The load that timed out in confirmation finishes afterwards: the
        lane reports running, the marker and the cooldown drop, and the model
        can scale out again on the next free suffix."""
        provider = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[_lane("planner-X", "X", "running"), _lane("planner-X-2", "X", "starting")],
            capabilities=["X"],
            available_vram_mb=50_000,
            profiles={"X": _profile()},
        )
        planner = _planner(provider, score=2.5, replicate=True)
        self._expire(planner, 1, "planner-X-2")
        planner._reconcile_load_failures(1, provider.lanes)
        assert (1, "planner-X-2") in planner._load_failed_lane_ids

        provider.lanes = [_lane("planner-X", "X", "running"), _lane("planner-X-2", "X", "running")]
        planner._reconcile_load_failures(1, provider.lanes)
        assert (1, "planner-X-2") not in planner._load_failed_lane_ids
        assert planner._lane_is_in_load_failure_cooldown(1, "planner-X-2") is False

        actions = planner._compute_demand_actions(1, provider.lanes)
        assert ("load", 1, "planner-X-3") in [(a.action, a.provider_id, a.lane_id) for a in actions]

    def test_confirmed_load_action_clears_the_marker(self):
        """The execution path confirms the load: the marker drops with the
        cooldown, whatever the next cycle's reconciliation would do."""
        planner = _planner(
            _MockProvider(
                provider_id=1,
                name="A",
                lanes=[_lane("planner-X", "X", "starting")],
                capabilities=["X"],
                available_vram_mb=50_000,
                profiles={"X": _profile()},
            ),
            score=2.5,
            replicate=True,
        )
        self._expire(planner, 1, "planner-X")
        planner._lane_was_cold_loaded = {}

        from logos.sdi.models import CapacityPlanAction

        planner._record_confirmed_action_state(
            CapacityPlanAction(
                action="load",
                provider_id=1,
                lane_id="planner-X",
                model_name="X",
                params={},
                reason="test",
            ),
            time.time(),
        )
        assert (1, "planner-X") not in planner._load_failed_lane_ids
        assert planner._lane_is_in_load_failure_cooldown(1, "planner-X") is False

    def test_marker_pruned_when_the_lane_leaves_the_worker(self):
        """The stuck lane is gone from the worker (crashed away, manually
        removed): its marker drops with it and the id is free for a fresh
        first lane."""
        planner = _planner(
            _MockProvider(
                provider_id=1,
                name="A",
                lanes=[_lane("planner-X", "X", "starting")],
                capabilities=["X"],
                available_vram_mb=50_000,
                profiles={"X": _profile()},
            ),
            score=2.5,
            replicate=True,
        )
        self._expire(planner, 1, "planner-X")

        planner._reconcile_load_failures(1, [])
        assert (1, "planner-X") not in planner._load_failed_lane_ids

        provider_lanes: List[LaneSchedulerSignals] = []
        actions = planner._compute_demand_actions(1, provider_lanes)
        assert ("load", 1, "planner-X") in [(a.action, a.provider_id, a.lane_id) for a in actions]

    def test_starting_lane_without_a_marker_is_not_blocked(self):
        """Guard against over-blocking: a plain in-flight load (no failure
        ever marked) still counts as active and still allows scale-out —
        the marker, not the ``starting`` state, is what blocks."""
        provider = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[_lane("planner-X", "X", "running"), _lane("planner-X-2", "X", "starting")],
            capabilities=["X"],
            available_vram_mb=50_000,
            profiles={"X": _profile()},
        )
        planner = _planner(provider, score=2.5, replicate=True)

        actions = planner._compute_demand_actions(1, provider.lanes)
        assert ("load", 1, "planner-X-3") in [(a.action, a.provider_id, a.lane_id) for a in actions]


# ---------------------------------------------------------------------------
# Cycle-wide dedup: an additional lane must not shadow a first lane
# ---------------------------------------------------------------------------


class TestCycleDedupAdditionalLanes:
    """Same-node speculative loads and the cross-provider replication pass
    used to share one cycle-wide set, so an *additional* lane planned on a
    worker that already hosts the model suppressed the *first* lane on a
    worker without it. Additional lanes are now tagged separately, and the
    per-cycle cluster count is kept current so the copy cap holds within a
    cycle even with the dedup off."""

    def test_first_lane_proceeds_despite_additional_planned_elsewhere(self):
        """Worker A hosts X and plans a speculative second lane; worker B
        does not host X at all. B's demand-driven first lane must not be
        displaced by A's opportunistic copy — with dedup on."""
        host = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[_lane("planner-X", "X", "running")],
            capabilities=["X"],
            available_vram_mb=50_000,
            profiles={"X": _profile()},
        )
        empty = _MockProvider(
            provider_id=2,
            name="B",
            lanes=[],
            capabilities=["X"],
            available_vram_mb=50_000,
            profiles={"X": _profile()},
        )
        host_planner = _planner(host, score=2.5, replicate=True)
        empty_planner = _planner(empty, score=2.5, replicate=True)
        host_planner._cross_provider_dedup = True
        empty_planner._cross_provider_dedup = True
        cycle_planned_models: set = set()
        cycle_planned_additional_models: set = set()
        cluster = {"X": 1}

        host_actions = host_planner._compute_demand_actions(
            1,
            host.lanes,
            cycle_planned_models=cycle_planned_models,
            cycle_planned_additional_models=cycle_planned_additional_models,
            cluster_lanes_by_model=cluster,
        )
        assert ("load", 1, "planner-X-2") in [(a.action, a.provider_id, a.lane_id) for a in host_actions]
        assert "X" in cycle_planned_additional_models

        empty_actions = empty_planner._compute_demand_actions(
            2,
            empty.lanes,
            cycle_planned_models=cycle_planned_models,
            cycle_planned_additional_models=cycle_planned_additional_models,
            cluster_lanes_by_model=cluster,
        )
        # B's first lane is the necessary action — it proceeds.
        assert ("load", 2, "planner-X") in [(a.action, a.provider_id, a.lane_id) for a in empty_actions]

    def test_first_lane_planned_elsewhere_still_suppresses(self):
        """The dedup itself still works: worker A plans the first lane, so
        worker B's second first lane for the same model is skipped —
        one cold load per model per cycle."""
        empty_a = _MockProvider(
            provider_id=1, name="A", lanes=[], capabilities=["X"], available_vram_mb=50_000, profiles={"X": _profile()}
        )
        empty_b = _MockProvider(
            provider_id=2, name="B", lanes=[], capabilities=["X"], available_vram_mb=50_000, profiles={"X": _profile()}
        )
        planner_a = _planner(empty_a, score=2.5, replicate=False)
        planner_b = _planner(empty_b, score=2.5, replicate=False)
        planner_a._cross_provider_dedup = True
        planner_b._cross_provider_dedup = True
        cycle_planned_models: set = set()
        cycle_planned_additional_models: set = set()

        actions_a = planner_a._compute_demand_actions(
            1,
            empty_a.lanes,
            cycle_planned_models=cycle_planned_models,
            cycle_planned_additional_models=cycle_planned_additional_models,
        )
        assert ("load", 1, "planner-X") in [(a.action, a.provider_id, a.lane_id) for a in actions_a]
        assert "X" not in cycle_planned_additional_models  # first lane, not an extra copy

        actions_b = planner_b._compute_demand_actions(
            2,
            empty_b.lanes,
            cycle_planned_models=cycle_planned_models,
            cycle_planned_additional_models=cycle_planned_additional_models,
        )
        assert actions_b == []

    def test_replication_places_a_copy_when_only_an_additional_was_planned(self):
        """The cross-provider pass runs after the demand pass. A speculative
        additional lane on the host worker must not suppress the pass's
        first lane on a worker without the model."""
        healthy = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[_lane("planner-X", "X", "running")],
            capabilities=["X"],
            available_vram_mb=50_000,
            profiles={"X": _profile()},
        )
        empty = _MockProvider(
            provider_id=2,
            name="B",
            lanes=[],
            capabilities=["X"],
            available_vram_mb=50_000,
            profiles={"X": _profile()},
        )
        planner = _planner(healthy, score=2.5, replicate=True)
        planner._facade = _MockFacade([healthy, empty])

        # Only an additional lane was planned this cycle → the pass proceeds.
        actions = planner._compute_replication_actions([1, 2], [("X", 2.5)], {"X": 1}, {"X"}, {"X"})
        assert [(a.provider_id, a.lane_id) for a in actions] == [(2, "planner-X")]

        # A demand-driven first lane was planned → the pass stays out.
        actions = planner._compute_replication_actions([1, 2], [("X", 2.5)], {"X": 1}, {"X"}, set())
        assert actions == []

    def test_cluster_copy_cap_holds_across_workers_in_one_cycle(self):
        """Two workers each host one copy of X (cluster count 2 of the cap
        3) and both want a speculative second copy. The first worker's
        planned lane must bump the cycle's cluster count, so the second
        worker sees the cap and stands down — with the dedup off, so only
        the count can save it."""
        worker_a = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[_lane("planner-X", "X", "running")],
            capabilities=["X"],
            available_vram_mb=50_000,
            profiles={"X": _profile()},
        )
        worker_b = _MockProvider(
            provider_id=2,
            name="B",
            lanes=[_lane("planner-X", "X", "running")],
            capabilities=["X"],
            available_vram_mb=50_000,
            profiles={"X": _profile()},
        )
        planner_a = _planner(worker_a, score=2.5, replicate=True)
        planner_b = _planner(worker_b, score=2.5, replicate=True)
        cycle_planned_models: set = set()
        cycle_planned_additional_models: set = set()
        cluster = {"X": 2}

        actions_a = planner_a._compute_demand_actions(
            1,
            worker_a.lanes,
            cycle_planned_models=cycle_planned_models,
            cycle_planned_additional_models=cycle_planned_additional_models,
            cluster_lanes_by_model=cluster,
        )
        actions_b = planner_b._compute_demand_actions(
            2,
            worker_b.lanes,
            cycle_planned_models=cycle_planned_models,
            cycle_planned_additional_models=cycle_planned_additional_models,
            cluster_lanes_by_model=cluster,
        )

        loads = [a for a in actions_a + actions_b if a.action == "load" and a.model_name == "X"]
        assert len(loads) == 1
        assert loads[0].provider_id == 1


# ---------------------------------------------------------------------------
# Lane id reservation is worker-wide, not per-model
# ---------------------------------------------------------------------------


class TestWorkerWideLaneIdReservation:
    """The replica suffix scheme is not unique across models:
    ``planner-foo-2`` is replica 2 of ``foo`` and replica 1 of ``foo-2``.
    Every planner-owned emission must reserve its id against *all* lanes the
    worker holds — the worker keys lanes by id alone and refuses a
    duplicate — or a worker hosting one form gets a rejected load for the
    other."""

    def test_additional_lane_skips_an_id_held_by_another_model(self):
        """foo replica 2 and foo-2 planned on the same worker: the worker
        already holds planner-foo-2 for foo-2, so foo's additional lane
        must land on planner-foo-3, not the id the worker already has."""
        provider = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[
                _lane("planner-foo", "foo", "running"),
                _lane("planner-foo-2", "foo-2", "running"),
            ],
            capabilities=["foo", "foo-2"],
            available_vram_mb=50_000,
            profiles={"foo": _profile(), "foo-2": _profile()},
        )
        planner = _planner(provider, score=2.5, replicate=True)
        planner._demand.get_ranked_models.return_value = [("foo", 2.5)]

        actions = planner._compute_demand_actions(1, provider.lanes)
        kinds = [(a.action, a.lane_id) for a in actions if a.model_name == "foo"]

        assert ("load", "planner-foo-3") in kinds
        assert all(lane_id != "planner-foo-2" for _a, lane_id in kinds)

    def test_replication_lane_skips_an_id_held_by_another_model(self):
        """The target worker does not host foo-2, but it holds
        planner-foo-2 for foo's replica 2: the speculative replica of
        foo-2 must not reuse that id."""
        host = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[_lane("planner-foo-2", "foo-2", "running")],
            capabilities=["foo-2"],
            available_vram_mb=50_000,
            profiles={"foo-2": _profile()},
        )
        target = _MockProvider(
            provider_id=2,
            name="B",
            lanes=[
                _lane("planner-foo", "foo", "running"),
                _lane("planner-foo-2", "foo", "running"),
            ],
            capabilities=["foo-2"],
            available_vram_mb=50_000,
            profiles={"foo-2": _profile()},
        )
        planner = _planner(host, score=2.5, replicate=True)
        planner._facade = _MockFacade([host, target])

        actions = planner._compute_replication_actions([1, 2], [("foo-2", 2.5)], {"foo-2": 1}, set())
        assert [(a.provider_id, a.lane_id) for a in actions] == [(2, "planner-foo-2-2")]


# ---------------------------------------------------------------------------
# Cycle accounting: first lanes count and end the additional-only tag
# ---------------------------------------------------------------------------


class TestCycleAccountingFirstLanes:
    """The per-cycle cluster count and the "additional only" tag must track
    first lanes too: with the cross-provider best-first ranker off, the
    cycle-wide dedup and the copy cap are all that keeps a hot model from
    loading past MAX_REPLICAS_PER_MODEL in one cycle."""

    @staticmethod
    def _provider(provider_id: int, name: str, lanes: List[LaneSchedulerSignals]) -> _MockProvider:
        return _MockProvider(
            provider_id=provider_id,
            name=name,
            lanes=lanes,
            capabilities=["foo"],
            available_vram_mb=50_000,
            profiles={"foo": _profile()},
        )

    @staticmethod
    def _planner_for(provider: _MockProvider, *, dedup: bool) -> CapacityPlanner:
        planner = _planner(provider, score=2.5, replicate=True)
        planner._demand.get_ranked_models.return_value = [("foo", 2.5)]
        planner._cross_provider_dedup = dedup
        planner._cross_provider_best_first = False
        return planner

    def test_first_lane_untags_the_model_for_later_workers(self):
        """Worker A plans a speculative additional lane; worker B's first
        lane is the necessary one and proceeds; worker C's first lane would
        be a second first lane in the same cycle and is suppressed — the
        additional-only tag ends the moment B's first lane is planned."""
        host = self._provider(1, "A", [_lane("planner-foo", "foo", "running")])
        empty_b = self._provider(2, "B", [])
        empty_c = self._provider(3, "C", [])
        planner_a = self._planner_for(host, dedup=True)
        planner_b = self._planner_for(empty_b, dedup=True)
        planner_c = self._planner_for(empty_c, dedup=True)
        cycle_planned_models: set = set()
        cycle_planned_additional_models: set = set()
        cluster = {"foo": 1}

        actions_a = planner_a._compute_demand_actions(
            1,
            host.lanes,
            cycle_planned_models=cycle_planned_models,
            cycle_planned_additional_models=cycle_planned_additional_models,
            cluster_lanes_by_model=cluster,
        )
        assert ("load", 1, "planner-foo-2") in [(a.action, a.provider_id, a.lane_id) for a in actions_a]
        assert "foo" in cycle_planned_additional_models

        actions_b = planner_b._compute_demand_actions(
            2,
            [],
            cycle_planned_models=cycle_planned_models,
            cycle_planned_additional_models=cycle_planned_additional_models,
            cluster_lanes_by_model=cluster,
        )
        assert ("load", 2, "planner-foo") in [(a.action, a.provider_id, a.lane_id) for a in actions_b]
        # B's first lane ends the model's additional-only status.
        assert "foo" not in cycle_planned_additional_models

        actions_c = planner_c._compute_demand_actions(
            3,
            [],
            cycle_planned_models=cycle_planned_models,
            cycle_planned_additional_models=cycle_planned_additional_models,
            cluster_lanes_by_model=cluster,
        )
        assert actions_c == []

    def test_first_load_counts_towards_the_cap_for_later_additional_gates(self):
        """Two live copies (A, C) plus B's demand-driven first lane reach
        the cap before A's and C's passes run: both additional lanes must
        stand down. With the count ignoring first loads, A's additional
        would still pass its gate and push the cluster to four copies."""
        host_a = self._provider(1, "A", [_lane("planner-foo", "foo", "running")])
        empty_b = self._provider(2, "B", [])
        host_c = self._provider(3, "C", [_lane("planner-foo", "foo", "running")])
        # Dedup off: only the cap — fed by the cycle's cluster count — can
        # save this one.
        planner_a = self._planner_for(host_a, dedup=False)
        planner_b = self._planner_for(empty_b, dedup=False)
        planner_c = self._planner_for(host_c, dedup=False)
        cycle_planned_models: set = set()
        cycle_planned_additional_models: set = set()
        cluster = {"foo": 2}

        # Provider pass order: B (first lane) before A and C (additional).
        actions_b = planner_b._compute_demand_actions(
            2,
            [],
            cycle_planned_models=cycle_planned_models,
            cycle_planned_additional_models=cycle_planned_additional_models,
            cluster_lanes_by_model=cluster,
        )
        actions_a = planner_a._compute_demand_actions(
            1,
            host_a.lanes,
            cycle_planned_models=cycle_planned_models,
            cycle_planned_additional_models=cycle_planned_additional_models,
            cluster_lanes_by_model=cluster,
        )
        actions_c = planner_c._compute_demand_actions(
            3,
            host_c.lanes,
            cycle_planned_models=cycle_planned_models,
            cycle_planned_additional_models=cycle_planned_additional_models,
            cluster_lanes_by_model=cluster,
        )

        loads = [a for a in actions_a + actions_b + actions_c if a.action == "load" and a.model_name == "foo"]
        assert [(a.provider_id, a.lane_id) for a in loads] == [(2, "planner-foo")]
