"""Scenario tests for the cross-provider best-first ranker (`59616004`).

Each test mirrors one of the entries in the decision-flow matrix the operator
walked through:

  1. 2 providers warm with target, both idle               (sticky-tie)
  2. All full, no provider has X                           (cold-load + evict)
  3. All full, 1 has X loaded                              (warm wins, replica gap)
  4. All full, 1 has X sleeping                            (wake wins, evict-aware)
  5. All full, 2 have X loaded, many requests              (routing balances)
  6. Free VRAM on provider B, X loaded on A                (replica gap)
  9. Both sleeping, A no-evict, B evict                    (cheapest wake wins)
 10. Both sleeping, both need evict                        (free-VRAM tie-break)
 12. Empty-startup multi-model swarm                       (spread, not pile)
 15. Both loaded with low-demand X, request for Y w/ evict (only one X stops)
 16. Heterogeneous GPUs, idle, model on slower             (sticky-tie)

The ranker is the contract under test. Higher-level orchestration (full
planner cycles, request dispatch) needs end-to-end fixtures that aren't
in scope for these unit tests; the scenarios that depend on those are
marked xfail with a TODO.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from types import ModuleType, SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

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

from logos.capacity.capacity_planner import CapacityPlanner  # noqa: E402
from logos.sdi.models import LaneSchedulerSignals  # noqa: E402


# ---------------------------------------------------------------------------
# Minimal mock facade — only implements what the ranker needs
# ---------------------------------------------------------------------------


@dataclass
class _MockProvider:
    """Per-provider state container."""
    provider_id: int
    name: str
    lanes: List[LaneSchedulerSignals] = field(default_factory=list)
    profiles: Dict[str, Any] = field(default_factory=dict)
    capabilities: List[str] = field(default_factory=list)
    available_vram_mb: float = 0.0
    total_vram_mb: float = 96_000.0


class _MockFacade:
    """Implements just the surface the ranker calls.

    See `_rank_providers_for_demanded_models` and
    `_estimate_demand_action_cost` for the methods invoked.
    """

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
        # Tests don't exercise queue depth; eviction-set gates treat 0 as "idle".
        return 0


def _lane(
    *,
    lane_id: str,
    model_name: str,
    runtime_state: str = "loaded",
    sleep_state: str = "awake",
    effective_vram_mb: float = 20_000.0,
    gpu_devices: str = "0",
    is_vllm: bool = True,
    active_requests: int = 0,
    queue_waiting: float = 0.0,
) -> LaneSchedulerSignals:
    return LaneSchedulerSignals(
        lane_id=lane_id,
        model_name=model_name,
        runtime_state=runtime_state,
        sleep_state=sleep_state,
        is_vllm=is_vllm,
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


def _profile(loaded_vram_mb: float = 20_000.0, sleeping_residual_mb: float = 500.0,
             tensor_parallel_size: int = 1):
    """Build a profile-shaped object with the fields the planner reads."""
    return SimpleNamespace(
        loaded_vram_mb=loaded_vram_mb,
        sleeping_residual_mb=sleeping_residual_mb,
        base_residency_mb=loaded_vram_mb,
        kv_budget_mb=0.0,
        tensor_parallel_size=tensor_parallel_size,
        residency_source="calibrated",
        engine="vllm",
        estimate_base_residency_mb=lambda: loaded_vram_mb,
    )


def _planner(providers: List[_MockProvider]) -> CapacityPlanner:
    """Build a planner with mocked dependencies that satisfies the ranker
    and the eviction-set picker. Enough surface for the in-cycle helpers
    (_count_loaded_lanes_per_model, _estimate_demand_action_cost,
    _rank_providers_for_demanded_models, _find_eviction_set) but not the
    full apply/dispatch path.
    """
    facade = _MockFacade(providers)
    registry = MagicMock()
    registry.has_received_first_status.return_value = True
    registry.peek_runtime_snapshot.return_value = {"runtime": {"lanes": [], "devices": {}}}
    demand = MagicMock()
    demand.get_ranked_models.return_value = []
    demand.get_score.return_value = 0.0

    planner = CapacityPlanner.__new__(CapacityPlanner)
    planner._facade = facade
    planner._registry = registry
    planner._demand = demand
    planner._lane_wake_failure_until = {}
    planner._cross_provider_best_first = True
    planner._replica_first_eviction = True
    # Eviction-picker dependencies
    planner._lane_loaded_at = {}
    planner._lane_idle_since = {}
    planner._lane_sleep_since = {}
    planner._lane_sleep_level = {}
    planner._load_cooldown_seconds = 0.0
    planner._eviction_gate_v2 = True
    planner._stop_dedup_siblings = False
    return planner


# ---------------------------------------------------------------------------
# Cost-estimator unit tests
# ---------------------------------------------------------------------------


class TestEstimateDemandActionCost:
    """Direct tests for `_estimate_demand_action_cost`."""

    def test_awake_lane_returns_zero_cost(self):
        """Scenario 3/5: an awake usable lane → cost 0, no planner action needed."""
        provider = _MockProvider(
            provider_id=1, name="A",
            lanes=[_lane(lane_id="A-x", model_name="X", runtime_state="loaded")],
            available_vram_mb=50_000.0,
        )
        planner = _planner([provider])
        result = planner._estimate_demand_action_cost(
            provider.provider_id, "X", provider.lanes, {}, planner._facade.get_capacity_info(1),
        )
        assert result is not None
        cost, free_vram = result
        assert cost == 0.0
        assert free_vram == 50_000.0

    def test_sleeping_lane_with_free_vram_costs_wake(self):
        """Scenario 4 / 9 (no-evict side): sleeping with free VRAM → wake cost only."""
        provider = _MockProvider(
            provider_id=1, name="A",
            lanes=[_lane(lane_id="A-x", model_name="X", runtime_state="sleeping",
                         sleep_state="sleeping", effective_vram_mb=500)],
            profiles={"X": _profile(loaded_vram_mb=20_000.0, sleeping_residual_mb=500.0)},
            available_vram_mb=50_000.0,
        )
        planner = _planner([provider])
        result = planner._estimate_demand_action_cost(
            1, "X", provider.lanes, provider.profiles, planner._facade.get_capacity_info(1),
        )
        assert result is not None
        cost, _ = result
        assert cost == pytest.approx(CapacityPlanner.TARGET_ACTION_COST_S["wake"])

    def test_sleeping_lane_needing_sleep_evict(self):
        """Scenario 9 (evict side): wake target + sleep_l1 of victim."""
        lanes = [
            _lane(lane_id="A-x", model_name="X", runtime_state="sleeping",
                  sleep_state="sleeping", effective_vram_mb=500),
            _lane(lane_id="A-y", model_name="Y", runtime_state="loaded", sleep_state="awake",
                  effective_vram_mb=10_000),
        ]
        provider = _MockProvider(
            provider_id=1, name="A", lanes=lanes,
            profiles={
                "X": _profile(loaded_vram_mb=20_000.0, sleeping_residual_mb=500.0),
                "Y": _profile(loaded_vram_mb=10_000.0, sleeping_residual_mb=300.0),
            },
            available_vram_mb=2_000.0,  # not enough for wake without evicting Y
        )
        planner = _planner([provider])
        result = planner._estimate_demand_action_cost(
            1, "X", provider.lanes, provider.profiles, planner._facade.get_capacity_info(1),
        )
        assert result is not None
        cost, _ = result
        # wake(2) + sleep_l1(1) = 3
        assert cost == pytest.approx(
            CapacityPlanner.TARGET_ACTION_COST_S["wake"]
            + CapacityPlanner.VICTIM_ACTION_COST_S["sleep_l1"]
        )

    def test_cold_load_with_free_vram(self):
        """Scenario 2 / 12: no lane, plenty of free VRAM → cost = load(90)."""
        provider = _MockProvider(
            provider_id=1, name="A",
            lanes=[],
            profiles={"X": _profile(loaded_vram_mb=20_000.0)},
            available_vram_mb=80_000.0,
        )
        planner = _planner([provider])
        result = planner._estimate_demand_action_cost(
            1, "X", provider.lanes, provider.profiles, planner._facade.get_capacity_info(1),
        )
        assert result is not None
        cost, _ = result
        assert cost == pytest.approx(CapacityPlanner.TARGET_ACTION_COST_S["load"])

    def test_cold_load_with_stop_only_eviction(self):
        """Scenario 22-ish: no lane, need to stop a non-sleepable lane → 90 + 30 = 120."""
        lanes = [
            _lane(lane_id="A-z", model_name="Z", runtime_state="loaded", sleep_state="unsupported",
                  effective_vram_mb=80_000),
        ]
        provider = _MockProvider(
            provider_id=1, name="A", lanes=lanes,
            profiles={
                "X": _profile(loaded_vram_mb=80_000.0),
                "Z": _profile(loaded_vram_mb=80_000.0, sleeping_residual_mb=0.0),
            },
            available_vram_mb=5_000.0,
        )
        planner = _planner([provider])
        result = planner._estimate_demand_action_cost(
            1, "X", provider.lanes, provider.profiles, planner._facade.get_capacity_info(1),
        )
        assert result is not None
        cost, _ = result
        assert cost == pytest.approx(
            CapacityPlanner.TARGET_ACTION_COST_S["load"]
            + CapacityPlanner.VICTIM_ACTION_COST_S["stop"]
        )

    def test_no_lane_no_evict_target_returns_none(self):
        """Pathological: needs eviction but no displaceable lanes → None (infeasible)."""
        provider = _MockProvider(
            provider_id=1, name="A",
            lanes=[],
            profiles={"X": _profile(loaded_vram_mb=80_000.0)},
            available_vram_mb=5_000.0,  # under needed
        )
        planner = _planner([provider])
        result = planner._estimate_demand_action_cost(
            1, "X", provider.lanes, provider.profiles, planner._facade.get_capacity_info(1),
        )
        assert result is None


# ---------------------------------------------------------------------------
# Cross-provider ranker tests
# ---------------------------------------------------------------------------


class TestRankProvidersForDemandedModels:
    """Tests for `_rank_providers_for_demanded_models` end-to-end."""

    def test_warm_provider_beats_cold_provider(self):
        """Scenario 3: A has X loaded, B is cold with capability → A wins."""
        a = _MockProvider(
            provider_id=1, name="A",
            lanes=[_lane(lane_id="A-x", model_name="X", runtime_state="loaded")],
            capabilities=["X"], available_vram_mb=50_000,
            profiles={"X": _profile(loaded_vram_mb=20_000)},
        )
        b = _MockProvider(
            provider_id=2, name="B",
            lanes=[], capabilities=["X"], available_vram_mb=80_000,
            profiles={"X": _profile(loaded_vram_mb=20_000)},
        )
        planner = _planner([a, b])
        winners = planner._rank_providers_for_demanded_models(
            [a.provider_id, b.provider_id], [("X", 1.5)],
        )
        assert winners == {"X": a.provider_id}

    def test_sleeping_provider_beats_cold_provider(self):
        """Scenario 4: A has X sleeping (with eviction), B is cold (no eviction).

        Wake-with-sleep_l1 (cost 3) beats cold-load no-evict (cost 90).
        """
        a = _MockProvider(
            provider_id=1, name="A",
            lanes=[
                _lane(lane_id="A-x", model_name="X", runtime_state="sleeping",
                      sleep_state="sleeping", effective_vram_mb=500),
                _lane(lane_id="A-y", model_name="Y", runtime_state="loaded", sleep_state="awake"),
            ],
            capabilities=["X"], available_vram_mb=2_000,
            profiles={
                "X": _profile(loaded_vram_mb=20_000),
                "Y": _profile(loaded_vram_mb=10_000),
            },
        )
        b = _MockProvider(
            provider_id=2, name="B",
            lanes=[], capabilities=["X"], available_vram_mb=80_000,
            profiles={"X": _profile(loaded_vram_mb=20_000)},
        )
        planner = _planner([a, b])
        winners = planner._rank_providers_for_demanded_models(
            [a.provider_id, b.provider_id], [("X", 1.5)],
        )
        assert winners == {"X": a.provider_id}

    def test_tied_cold_workers_break_by_free_vram(self):
        """Scenario 12: two cold workers, both can host X. More-free-VRAM wins."""
        a = _MockProvider(
            provider_id=1, name="A",
            lanes=[], capabilities=["X"], available_vram_mb=30_000,
            profiles={"X": _profile(loaded_vram_mb=20_000)},
        )
        b = _MockProvider(
            provider_id=2, name="B",
            lanes=[], capabilities=["X"], available_vram_mb=80_000,
            profiles={"X": _profile(loaded_vram_mb=20_000)},
        )
        planner = _planner([a, b])
        winners = planner._rank_providers_for_demanded_models(
            [a.provider_id, b.provider_id], [("X", 1.5)],
        )
        assert winners == {"X": b.provider_id}

    def test_tied_cost_and_vram_break_by_provider_id(self):
        """Deterministic tie-break: lower provider_id wins after cost and VRAM ties."""
        a = _MockProvider(
            provider_id=2, name="A",
            lanes=[], capabilities=["X"], available_vram_mb=50_000,
            profiles={"X": _profile(loaded_vram_mb=20_000)},
        )
        b = _MockProvider(
            provider_id=1, name="B",
            lanes=[], capabilities=["X"], available_vram_mb=50_000,
            profiles={"X": _profile(loaded_vram_mb=20_000)},
        )
        planner = _planner([a, b])
        winners = planner._rank_providers_for_demanded_models(
            [a.provider_id, b.provider_id], [("X", 1.5)],
        )
        assert winners == {"X": b.provider_id}  # provider_id=1 < 2

    def test_capability_required(self):
        """A worker that does not advertise capability for the model is skipped."""
        a = _MockProvider(
            provider_id=1, name="A",
            lanes=[], capabilities=["OTHER"], available_vram_mb=80_000,
            profiles={},
        )
        b = _MockProvider(
            provider_id=2, name="B",
            lanes=[], capabilities=["X"], available_vram_mb=80_000,
            profiles={"X": _profile(loaded_vram_mb=20_000)},
        )
        planner = _planner([a, b])
        winners = planner._rank_providers_for_demanded_models(
            [a.provider_id, b.provider_id], [("X", 1.5)],
        )
        assert winners == {"X": b.provider_id}

    def test_no_feasible_provider_returns_no_entry(self):
        """If no worker can host the model (no capability anywhere), model is dropped."""
        a = _MockProvider(provider_id=1, name="A", capabilities=["OTHER"])
        planner = _planner([a])
        winners = planner._rank_providers_for_demanded_models(
            [a.provider_id], [("X", 1.5)],
        )
        assert "X" not in winners

    def test_two_warm_replicas_ties_to_higher_vram(self):
        """Scenario 1/5/16: two workers, both have X loaded. Cost 0 for both.

        Tie-break: more free VRAM wins, then provider_id. Captures the
        idle-tie behaviour; if we later add an observed-p50 tiebreaker
        (sticky-tie fix) this test should be updated.
        """
        a = _MockProvider(
            provider_id=1, name="A",
            lanes=[_lane(lane_id="A-x", model_name="X", runtime_state="loaded")],
            capabilities=["X"], available_vram_mb=30_000,
            profiles={"X": _profile(loaded_vram_mb=20_000)},
        )
        b = _MockProvider(
            provider_id=2, name="B",
            lanes=[_lane(lane_id="B-x", model_name="X", runtime_state="loaded")],
            capabilities=["X"], available_vram_mb=50_000,
            profiles={"X": _profile(loaded_vram_mb=20_000)},
        )
        planner = _planner([a, b])
        winners = planner._rank_providers_for_demanded_models(
            [a.provider_id, b.provider_id], [("X", 1.5)],
        )
        assert winners == {"X": b.provider_id}


# ---------------------------------------------------------------------------
# Gaps that the matrix identified but the current code does not yet handle
# ---------------------------------------------------------------------------


class TestKnownGaps:
    """Documents behaviors we know are not yet covered; xfail by design.

    Remove the xfail marker as each is implemented.
    """

    @pytest.mark.xfail(
        reason="No proactive replication on free VRAM (Part A from prior conversation): "
               "when X is loaded on A and B has free VRAM with capability, the ranker "
               "picks A (cost 0) and B is skipped. Idle B is left unused under load."
    )
    def test_replicates_to_free_vram_under_high_demand(self):
        """Scenario 7/13: A has X loaded with many queued, B is idle with capability+VRAM.

        Expected: planner replicates X onto B so routing can balance.
        Actual today: B is skipped (cost 0 wins everything).
        """
        a = _MockProvider(
            provider_id=1, name="A",
            lanes=[_lane(
                lane_id="A-x", model_name="X", runtime_state="running",
                active_requests=4, queue_waiting=20.0,
            )],
            capabilities=["X"], available_vram_mb=5_000,
            profiles={"X": _profile(loaded_vram_mb=20_000)},
        )
        b = _MockProvider(
            provider_id=2, name="B",
            lanes=[], capabilities=["X"], available_vram_mb=80_000,
            profiles={"X": _profile(loaded_vram_mb=20_000)},
        )
        planner = _planner([a, b])
        winners = planner._rank_providers_for_demanded_models(
            [a.provider_id, b.provider_id], [("X", 3.0)],
        )
        # When replication is implemented, both providers should be in winners.
        assert b.provider_id in winners.values()

    @pytest.mark.xfail(
        reason="No tie-break by observed e2e_p50 or GPU class (Fallacy #1/16): "
               "ties on cost+free_vram go to lower provider_id arbitrarily; "
               "should prefer the faster GPU when its p50 is lower."
    )
    def test_heterogeneous_gpu_tie_breaks_to_faster(self):
        """Scenario 16: two warm replicas, one on Blackwell, one on A6000.

        Expected: faster GPU wins (lower observed p50).
        Actual today: provider_id ascending wins.
        """
        a6000 = _MockProvider(
            provider_id=1, name="a6000",
            lanes=[_lane(
                lane_id="a6000-x", model_name="X", runtime_state="loaded",
            )],
            capabilities=["X"], available_vram_mb=50_000,
            profiles={"X": _profile(loaded_vram_mb=20_000)},
        )
        # Simulate Blackwell as having observed-lower e2e_p50 via lane signal.
        blackwell_lane = _lane(
            lane_id="blackwell-x", model_name="X", runtime_state="loaded",
        )
        # If we add p50 to the signal model, this is where the test would
        # express that the faster lane has a lower p50.
        blackwell = _MockProvider(
            provider_id=2, name="blackwell",
            lanes=[blackwell_lane],
            capabilities=["X"], available_vram_mb=50_000,
            profiles={"X": _profile(loaded_vram_mb=20_000)},
        )
        planner = _planner([a6000, blackwell])
        winners = planner._rank_providers_for_demanded_models(
            [a6000.provider_id, blackwell.provider_id], [("X", 1.5)],
        )
        assert winners["X"] == blackwell.provider_id

    # NOTE: the previous xfail `test_does_not_stop_last_replica_of_demanded_model`
    # is superseded by TestReplicaFirstEviction below, which exercises the
    # two-pass picker implemented in the replicas-first commit.


# ---------------------------------------------------------------------------
# Replicas-first eviction (Part B from prior conversation)
# ---------------------------------------------------------------------------


class TestReplicaFirstEviction:
    """Tests for the two-pass replicas-first eviction picker.

    Part B from the design discussion: when looking for memory for a
    load/wake, first try to evict only lanes whose model has another
    loaded copy elsewhere in the cluster. The last loaded copy of any
    model is preserved during this pass. Fall back to the global pool
    only when replicas alone can't cover the deficit.
    """

    def test_count_loaded_lanes_per_model_counts_only_running_states(self):
        """The helper counts only loaded/running lanes — sleeping doesn't count."""
        a = _MockProvider(
            provider_id=1, name="A",
            lanes=[
                _lane(lane_id="A-x", model_name="X", runtime_state="loaded"),
                _lane(lane_id="A-y", model_name="Y", runtime_state="sleeping",
                      sleep_state="sleeping"),
            ],
        )
        b = _MockProvider(
            provider_id=2, name="B",
            lanes=[
                _lane(lane_id="B-x", model_name="X", runtime_state="running"),
                _lane(lane_id="B-z", model_name="Z", runtime_state="stopped"),
            ],
        )
        planner = _planner([a, b])
        counts = planner._count_loaded_lanes_per_model()
        # X loaded on A + running on B = 2
        # Y sleeping → not counted
        # Z stopped → not counted
        assert counts == {"X": 2}

    def test_replicas_only_skips_last_loaded_copy(self):
        """Pass-1 invariant: a lane whose model has no other loaded copy is
        skipped as 'primary'. The two-pass caller falls back to global."""
        # Build candidates that all look evictable in normal mode, but where
        # one model has only one loaded copy in the cluster.
        provider = _MockProvider(
            provider_id=1, name="A",
            lanes=[
                _lane(lane_id="A-x", model_name="X", runtime_state="loaded",
                      effective_vram_mb=20_000),
                _lane(lane_id="A-z", model_name="Z", runtime_state="loaded",
                      effective_vram_mb=20_000),
            ],
            profiles={
                "X": _profile(loaded_vram_mb=20_000, sleeping_residual_mb=500.0),
                "Z": _profile(loaded_vram_mb=20_000, sleeping_residual_mb=500.0),
            },
        )
        planner = _planner([provider])
        # X has 1 loaded copy (the lane below); Z has 2 (the lane plus a
        # sibling on another conceptual provider — represented here just by
        # the cluster_lanes_by_model count).
        cluster = {"X": 1, "Z": 2}

        # Make eviction gates permissive: no demand, no cooldown, no busy.
        planner._eviction_gate_v2 = True
        planner._stop_dedup_siblings = False
        planner._lane_loaded_at = {}
        planner._demand.get_score = lambda *_: 0.0

        eviction = planner._find_eviction_set(
            provider_id=1,
            required_gpus=frozenset({0}),
            per_gpu_deficit={0: 5000.0},
            lanes=provider.lanes,
            profiles=provider.profiles,
            replicas_only=True,
            cluster_lanes_by_model=cluster,
        )
        assert eviction is not None
        evicted_models = {lane.model_name for lane, _action, _eff in eviction}
        # Z should be picked (it has a sibling replica).
        assert "Z" in evicted_models
        # X must NOT be picked in replicas-only mode (it's the last copy).
        assert "X" not in evicted_models

    def test_replicas_only_decrements_count_on_pick(self):
        """The picker keeps decrementing as it picks so it never takes the
        final copy of a model even when several replicas exist."""
        provider = _MockProvider(
            provider_id=1, name="A",
            lanes=[
                _lane(lane_id="A-x1", model_name="X", runtime_state="loaded",
                      effective_vram_mb=20_000, gpu_devices="0"),
                _lane(lane_id="A-x2", model_name="X", runtime_state="loaded",
                      effective_vram_mb=20_000, gpu_devices="0"),
                _lane(lane_id="A-x3", model_name="X", runtime_state="loaded",
                      effective_vram_mb=20_000, gpu_devices="0"),
            ],
            profiles={"X": _profile(loaded_vram_mb=20_000, sleeping_residual_mb=500.0)},
        )
        planner = _planner([provider])
        planner._eviction_gate_v2 = True
        planner._stop_dedup_siblings = False
        planner._lane_loaded_at = {}
        planner._demand.get_score = lambda *_: 0.0
        # Three loaded copies cluster-wide. With a large deficit we'd
        # potentially want to take all three, but the picker should stop
        # at two — leaving one as the surviving primary.
        cluster = {"X": 3}
        eviction = planner._find_eviction_set(
            provider_id=1,
            required_gpus=frozenset({0}),
            per_gpu_deficit={0: 200_000.0},   # would consume everything
            lanes=provider.lanes,
            profiles=provider.profiles,
            replicas_only=True,
            cluster_lanes_by_model=cluster,
        )
        # Either we cover by picking 2 X lanes and leave 1 (returns the
        # list), or we can't cover (returns None). The invariant we care
        # about: when a list is returned, it never contains all three X
        # lanes — leaving at least one as primary.
        if eviction is not None:
            picked_ids = {lane.lane_id for lane, _a, _e in eviction}
            assert len(picked_ids & {"A-x1", "A-x2", "A-x3"}) <= 2

    def test_global_pass_used_when_replicas_alone_insufficient(self):
        """When no replicas exist (every model has count==1), Pass 1 returns
        None and the cold-load placement falls back to the global picker."""
        # Single provider, two models each with exactly one lane.
        provider = _MockProvider(
            provider_id=1, name="A",
            lanes=[
                _lane(lane_id="A-x", model_name="X", runtime_state="loaded",
                      effective_vram_mb=20_000),
                _lane(lane_id="A-z", model_name="Z", runtime_state="loaded",
                      effective_vram_mb=20_000),
            ],
            profiles={
                "X": _profile(loaded_vram_mb=20_000, sleeping_residual_mb=500.0),
                "Z": _profile(loaded_vram_mb=20_000, sleeping_residual_mb=500.0),
            },
        )
        planner = _planner([provider])
        planner._eviction_gate_v2 = True
        planner._stop_dedup_siblings = False
        planner._lane_loaded_at = {}
        planner._demand.get_score = lambda *_: 0.0
        cluster = {"X": 1, "Z": 1}
        eviction = planner._find_eviction_set(
            provider_id=1,
            required_gpus=frozenset({0}),
            per_gpu_deficit={0: 5000.0},
            lanes=provider.lanes,
            profiles=provider.profiles,
            replicas_only=True,
            cluster_lanes_by_model=cluster,
        )
        # Pass 1 must produce no candidates (both lanes are primaries).
        assert eviction is None
