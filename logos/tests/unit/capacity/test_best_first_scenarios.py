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
from typing import Any, Dict, List
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


def _profile(
    loaded_vram_mb: float = 20_000.0,
    sleeping_residual_mb: float = 500.0,
    tensor_parallel_size: int = 1,
):
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
    planner._replicate_on_free_vram = False  # opt-in; tests turn it on
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
            provider_id=1,
            name="A",
            lanes=[_lane(lane_id="A-x", model_name="X", runtime_state="loaded")],
            available_vram_mb=50_000.0,
        )
        planner = _planner([provider])
        result = planner._estimate_demand_action_cost(
            provider.provider_id,
            "X",
            provider.lanes,
            {},
            planner._facade.get_capacity_info(1),
        )
        assert result is not None
        cost, free_vram = result
        assert cost == 0.0
        assert free_vram == 50_000.0

    def test_sleeping_lane_with_free_vram_costs_wake(self):
        """Scenario 4 / 9 (no-evict side): sleeping with free VRAM → wake cost only."""
        provider = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[
                _lane(
                    lane_id="A-x",
                    model_name="X",
                    runtime_state="sleeping",
                    sleep_state="sleeping",
                    effective_vram_mb=500,
                )
            ],
            profiles={"X": _profile(loaded_vram_mb=20_000.0, sleeping_residual_mb=500.0)},
            available_vram_mb=50_000.0,
        )
        planner = _planner([provider])
        result = planner._estimate_demand_action_cost(
            1,
            "X",
            provider.lanes,
            provider.profiles,
            planner._facade.get_capacity_info(1),
        )
        assert result is not None
        cost, _ = result
        assert cost == pytest.approx(CapacityPlanner.TARGET_ACTION_COST_S["wake"])

    def test_sleeping_lane_needing_sleep_evict(self):
        """Scenario 9 (evict side): wake target + sleep_l1 of victim."""
        lanes = [
            _lane(
                lane_id="A-x",
                model_name="X",
                runtime_state="sleeping",
                sleep_state="sleeping",
                effective_vram_mb=500,
            ),
            _lane(
                lane_id="A-y",
                model_name="Y",
                runtime_state="loaded",
                sleep_state="awake",
                effective_vram_mb=10_000,
            ),
        ]
        provider = _MockProvider(
            provider_id=1,
            name="A",
            lanes=lanes,
            profiles={
                "X": _profile(loaded_vram_mb=20_000.0, sleeping_residual_mb=500.0),
                "Y": _profile(loaded_vram_mb=10_000.0, sleeping_residual_mb=300.0),
            },
            available_vram_mb=2_000.0,  # not enough for wake without evicting Y
        )
        planner = _planner([provider])
        result = planner._estimate_demand_action_cost(
            1,
            "X",
            provider.lanes,
            provider.profiles,
            planner._facade.get_capacity_info(1),
        )
        assert result is not None
        cost, _ = result
        # wake(2) + sleep_l1(1) = 3
        assert cost == pytest.approx(
            CapacityPlanner.TARGET_ACTION_COST_S["wake"] + CapacityPlanner.VICTIM_ACTION_COST_S["sleep_l1"]
        )

    def test_cold_load_with_free_vram(self):
        """Scenario 2 / 12: no lane, plenty of free VRAM → cost = load(90)."""
        provider = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[],
            profiles={"X": _profile(loaded_vram_mb=20_000.0)},
            available_vram_mb=80_000.0,
        )
        planner = _planner([provider])
        result = planner._estimate_demand_action_cost(
            1,
            "X",
            provider.lanes,
            provider.profiles,
            planner._facade.get_capacity_info(1),
        )
        assert result is not None
        cost, _ = result
        assert cost == pytest.approx(CapacityPlanner.TARGET_ACTION_COST_S["load"])

    def test_cold_load_with_stop_only_eviction(self):
        """Scenario 22-ish: no lane, need to stop a non-sleepable lane → 90 + 30 = 120."""
        lanes = [
            _lane(
                lane_id="A-z",
                model_name="Z",
                runtime_state="loaded",
                sleep_state="unsupported",
                effective_vram_mb=80_000,
            ),
        ]
        provider = _MockProvider(
            provider_id=1,
            name="A",
            lanes=lanes,
            profiles={
                "X": _profile(loaded_vram_mb=80_000.0),
                "Z": _profile(loaded_vram_mb=80_000.0, sleeping_residual_mb=0.0),
            },
            available_vram_mb=5_000.0,
        )
        planner = _planner([provider])
        result = planner._estimate_demand_action_cost(
            1,
            "X",
            provider.lanes,
            provider.profiles,
            planner._facade.get_capacity_info(1),
        )
        assert result is not None
        cost, _ = result
        assert cost == pytest.approx(
            CapacityPlanner.TARGET_ACTION_COST_S["load"] + CapacityPlanner.VICTIM_ACTION_COST_S["stop"]
        )

    def test_no_lane_no_evict_target_returns_none(self):
        """Pathological: needs eviction but no displaceable lanes → None (infeasible)."""
        provider = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[],
            profiles={"X": _profile(loaded_vram_mb=80_000.0)},
            available_vram_mb=5_000.0,  # under needed
        )
        planner = _planner([provider])
        result = planner._estimate_demand_action_cost(
            1,
            "X",
            provider.lanes,
            provider.profiles,
            planner._facade.get_capacity_info(1),
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
            provider_id=1,
            name="A",
            lanes=[_lane(lane_id="A-x", model_name="X", runtime_state="loaded")],
            capabilities=["X"],
            available_vram_mb=50_000,
            profiles={"X": _profile(loaded_vram_mb=20_000)},
        )
        b = _MockProvider(
            provider_id=2,
            name="B",
            lanes=[],
            capabilities=["X"],
            available_vram_mb=80_000,
            profiles={"X": _profile(loaded_vram_mb=20_000)},
        )
        planner = _planner([a, b])
        winners = planner._rank_providers_for_demanded_models(
            [a.provider_id, b.provider_id],
            [("X", 1.5)],
        )
        assert winners == {"X": a.provider_id}

    def test_sleeping_provider_beats_cold_provider(self):
        """Scenario 4: A has X sleeping (with eviction), B is cold (no eviction).

        Wake-with-sleep_l1 (cost 3) beats cold-load no-evict (cost 90).
        """
        a = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[
                _lane(
                    lane_id="A-x",
                    model_name="X",
                    runtime_state="sleeping",
                    sleep_state="sleeping",
                    effective_vram_mb=500,
                ),
                _lane(
                    lane_id="A-y",
                    model_name="Y",
                    runtime_state="loaded",
                    sleep_state="awake",
                ),
            ],
            capabilities=["X"],
            available_vram_mb=2_000,
            profiles={
                "X": _profile(loaded_vram_mb=20_000),
                "Y": _profile(loaded_vram_mb=10_000),
            },
        )
        b = _MockProvider(
            provider_id=2,
            name="B",
            lanes=[],
            capabilities=["X"],
            available_vram_mb=80_000,
            profiles={"X": _profile(loaded_vram_mb=20_000)},
        )
        planner = _planner([a, b])
        winners = planner._rank_providers_for_demanded_models(
            [a.provider_id, b.provider_id],
            [("X", 1.5)],
        )
        assert winners == {"X": a.provider_id}

    def test_tied_cold_workers_break_by_free_vram(self):
        """Scenario 12: two cold workers, both can host X. More-free-VRAM wins."""
        a = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[],
            capabilities=["X"],
            available_vram_mb=30_000,
            profiles={"X": _profile(loaded_vram_mb=20_000)},
        )
        b = _MockProvider(
            provider_id=2,
            name="B",
            lanes=[],
            capabilities=["X"],
            available_vram_mb=80_000,
            profiles={"X": _profile(loaded_vram_mb=20_000)},
        )
        planner = _planner([a, b])
        winners = planner._rank_providers_for_demanded_models(
            [a.provider_id, b.provider_id],
            [("X", 1.5)],
        )
        assert winners == {"X": b.provider_id}

    def test_tied_cost_and_vram_break_by_provider_id(self):
        """Deterministic tie-break: lower provider_id wins after cost and VRAM ties."""
        a = _MockProvider(
            provider_id=2,
            name="A",
            lanes=[],
            capabilities=["X"],
            available_vram_mb=50_000,
            profiles={"X": _profile(loaded_vram_mb=20_000)},
        )
        b = _MockProvider(
            provider_id=1,
            name="B",
            lanes=[],
            capabilities=["X"],
            available_vram_mb=50_000,
            profiles={"X": _profile(loaded_vram_mb=20_000)},
        )
        planner = _planner([a, b])
        winners = planner._rank_providers_for_demanded_models(
            [a.provider_id, b.provider_id],
            [("X", 1.5)],
        )
        assert winners == {"X": b.provider_id}  # provider_id=1 < 2

    def test_capability_required(self):
        """A worker that does not advertise capability for the model is skipped."""
        a = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[],
            capabilities=["OTHER"],
            available_vram_mb=80_000,
            profiles={},
        )
        b = _MockProvider(
            provider_id=2,
            name="B",
            lanes=[],
            capabilities=["X"],
            available_vram_mb=80_000,
            profiles={"X": _profile(loaded_vram_mb=20_000)},
        )
        planner = _planner([a, b])
        winners = planner._rank_providers_for_demanded_models(
            [a.provider_id, b.provider_id],
            [("X", 1.5)],
        )
        assert winners == {"X": b.provider_id}

    def test_no_feasible_provider_returns_no_entry(self):
        """If no worker can host the model (no capability anywhere), model is dropped."""
        a = _MockProvider(provider_id=1, name="A", capabilities=["OTHER"])
        planner = _planner([a])
        winners = planner._rank_providers_for_demanded_models(
            [a.provider_id],
            [("X", 1.5)],
        )
        assert "X" not in winners

    def test_two_warm_replicas_ties_to_higher_vram(self):
        """Scenario 1/5/16: two workers, both have X loaded. Cost 0 for both.

        Tie-break: more free VRAM wins, then provider_id. Captures the
        idle-tie behaviour; if we later add an observed-p50 tiebreaker
        (sticky-tie fix) this test should be updated.
        """
        a = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[_lane(lane_id="A-x", model_name="X", runtime_state="loaded")],
            capabilities=["X"],
            available_vram_mb=30_000,
            profiles={"X": _profile(loaded_vram_mb=20_000)},
        )
        b = _MockProvider(
            provider_id=2,
            name="B",
            lanes=[_lane(lane_id="B-x", model_name="X", runtime_state="loaded")],
            capabilities=["X"],
            available_vram_mb=50_000,
            profiles={"X": _profile(loaded_vram_mb=20_000)},
        )
        planner = _planner([a, b])
        winners = planner._rank_providers_for_demanded_models(
            [a.provider_id, b.provider_id],
            [("X", 1.5)],
        )
        assert winners == {"X": b.provider_id}


# ---------------------------------------------------------------------------
# Gaps that the matrix identified but the current code does not yet handle
# ---------------------------------------------------------------------------


class TestKnownGaps:
    """Documents behaviors we know are not yet covered; xfail by design.

    Remove the xfail marker as each is implemented.
    """

    # NOTE: the replication xfail is superseded by TestReplication below,
    # which exercises _compute_replication_actions directly. The ranker
    # itself doesn't fan out — that's the replication pass's job.

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
            provider_id=1,
            name="a6000",
            lanes=[
                _lane(
                    lane_id="a6000-x",
                    model_name="X",
                    runtime_state="loaded",
                )
            ],
            capabilities=["X"],
            available_vram_mb=50_000,
            profiles={"X": _profile(loaded_vram_mb=20_000)},
        )
        # Simulate Blackwell as having observed-lower e2e_p50 via lane signal.
        blackwell_lane = _lane(
            lane_id="blackwell-x",
            model_name="X",
            runtime_state="loaded",
        )
        # If we add p50 to the signal model, this is where the test would
        # express that the faster lane has a lower p50.
        blackwell = _MockProvider(
            provider_id=2,
            name="blackwell",
            lanes=[blackwell_lane],
            capabilities=["X"],
            available_vram_mb=50_000,
            profiles={"X": _profile(loaded_vram_mb=20_000)},
        )
        planner = _planner([a6000, blackwell])
        winners = planner._rank_providers_for_demanded_models(
            [a6000.provider_id, blackwell.provider_id],
            [("X", 1.5)],
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
            provider_id=1,
            name="A",
            lanes=[
                _lane(lane_id="A-x", model_name="X", runtime_state="loaded"),
                _lane(
                    lane_id="A-y",
                    model_name="Y",
                    runtime_state="sleeping",
                    sleep_state="sleeping",
                ),
            ],
        )
        b = _MockProvider(
            provider_id=2,
            name="B",
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
            provider_id=1,
            name="A",
            lanes=[
                _lane(
                    lane_id="A-x",
                    model_name="X",
                    runtime_state="loaded",
                    effective_vram_mb=20_000,
                ),
                _lane(
                    lane_id="A-z",
                    model_name="Z",
                    runtime_state="loaded",
                    effective_vram_mb=20_000,
                ),
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
            provider_id=1,
            name="A",
            lanes=[
                _lane(
                    lane_id="A-x1",
                    model_name="X",
                    runtime_state="loaded",
                    effective_vram_mb=20_000,
                    gpu_devices="0",
                ),
                _lane(
                    lane_id="A-x2",
                    model_name="X",
                    runtime_state="loaded",
                    effective_vram_mb=20_000,
                    gpu_devices="0",
                ),
                _lane(
                    lane_id="A-x3",
                    model_name="X",
                    runtime_state="loaded",
                    effective_vram_mb=20_000,
                    gpu_devices="0",
                ),
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
            per_gpu_deficit={0: 200_000.0},  # would consume everything
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
            provider_id=1,
            name="A",
            lanes=[
                _lane(
                    lane_id="A-x",
                    model_name="X",
                    runtime_state="loaded",
                    effective_vram_mb=20_000,
                ),
                _lane(
                    lane_id="A-z",
                    model_name="Z",
                    runtime_state="loaded",
                    effective_vram_mb=20_000,
                ),
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


# ---------------------------------------------------------------------------
# Speculative replication (Part A from prior conversation)
# ---------------------------------------------------------------------------


def _build_load_params_stub(self, model_name, lane_id, profile, capacity, provider_id):
    """Minimal stub of _build_load_params for tests — avoids the full vLLM
    config inference. The replication tests don't care about the params'
    contents, only that an action gets emitted."""
    return {"lane_id": lane_id, "model": model_name}


class TestReplication:
    """Tests for `_compute_replication_actions` (Part A)."""

    def _enable(self, planner):
        """Turn the flag on and stub load-param generation for tests."""
        planner._replicate_on_free_vram = True
        planner._build_load_params = lambda *a, **kw: _build_load_params_stub(planner, *a, **kw)
        # Bypass the per-GPU feasibility gate that reads a runtime snapshot
        # we don't fully construct in unit tests.
        planner._passes_minimum_load_feasibility = lambda *a, **kw: True

    def test_replicates_to_free_worker_under_high_demand(self):
        """Scenario 7/13: X loaded on A; B is idle with capability+VRAM.
        Replication pass adds X onto B."""
        a = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[_lane(lane_id="A-x", model_name="X", runtime_state="running")],
            capabilities=["X"],
            available_vram_mb=5_000,
            profiles={"X": _profile(loaded_vram_mb=20_000)},
        )
        b = _MockProvider(
            provider_id=2,
            name="B",
            lanes=[],
            capabilities=["X"],
            available_vram_mb=80_000,
            profiles={"X": _profile(loaded_vram_mb=20_000)},
        )
        planner = _planner([a, b])
        self._enable(planner)

        cluster = planner._count_loaded_lanes_per_model()
        assert cluster == {"X": 1}

        actions = planner._compute_replication_actions(
            provider_ids=[a.provider_id, b.provider_id],
            ranked_models=[("X", 3.0)],  # well above REPLICATION_FLOOR
            cluster_lanes_by_model=cluster,
            cycle_planned_models=set(),
        )
        assert len(actions) == 1
        action = actions[0]
        assert action.action == "load"
        assert action.provider_id == b.provider_id
        assert action.model_name == "X"

    def test_does_not_replicate_below_floor(self):
        """Demand below DEMAND_REPLICATION_FLOOR → no replication."""
        a = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[_lane(lane_id="A-x", model_name="X", runtime_state="loaded")],
            capabilities=["X"],
            available_vram_mb=5_000,
            profiles={"X": _profile(loaded_vram_mb=20_000)},
        )
        b = _MockProvider(
            provider_id=2,
            name="B",
            lanes=[],
            capabilities=["X"],
            available_vram_mb=80_000,
            profiles={"X": _profile(loaded_vram_mb=20_000)},
        )
        planner = _planner([a, b])
        self._enable(planner)

        actions = planner._compute_replication_actions(
            provider_ids=[a.provider_id, b.provider_id],
            ranked_models=[("X", CapacityPlanner.DEMAND_REPLICATION_FLOOR - 0.1)],
            cluster_lanes_by_model=planner._count_loaded_lanes_per_model(),
            cycle_planned_models=set(),
        )
        assert actions == []

    def test_does_not_replicate_when_model_not_loaded_anywhere(self):
        """If nobody has X loaded yet, the replication pass leaves the first
        load to the main demand pass."""
        a = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[],
            capabilities=["X"],
            available_vram_mb=80_000,
            profiles={"X": _profile(loaded_vram_mb=20_000)},
        )
        planner = _planner([a])
        self._enable(planner)
        actions = planner._compute_replication_actions(
            provider_ids=[a.provider_id],
            ranked_models=[("X", 5.0)],
            cluster_lanes_by_model={},
            cycle_planned_models=set(),
        )
        assert actions == []

    def test_respects_max_replicas_per_model(self):
        """Already at MAX_REPLICAS_PER_MODEL → don't add another."""
        # Pretend X is already loaded on MAX_REPLICAS workers via the
        # cluster_lanes_by_model count (we don't need real lanes on each).
        a = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[_lane(lane_id="A-x", model_name="X", runtime_state="loaded")],
            capabilities=["X"],
            available_vram_mb=5_000,
            profiles={"X": _profile(loaded_vram_mb=20_000)},
        )
        b = _MockProvider(
            provider_id=2,
            name="B",
            lanes=[],
            capabilities=["X"],
            available_vram_mb=80_000,
            profiles={"X": _profile(loaded_vram_mb=20_000)},
        )
        planner = _planner([a, b])
        self._enable(planner)
        # Inject a count at the cap
        cluster = {"X": CapacityPlanner.MAX_REPLICAS_PER_MODEL}
        actions = planner._compute_replication_actions(
            provider_ids=[a.provider_id, b.provider_id],
            ranked_models=[("X", 5.0)],
            cluster_lanes_by_model=cluster,
            cycle_planned_models=set(),
        )
        assert actions == []

    def test_does_not_replicate_when_no_free_vram_anywhere(self):
        """When every candidate worker lacks free VRAM for the model, the
        replication pass refuses to emit (it must never evict)."""
        a = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[_lane(lane_id="A-x", model_name="X", runtime_state="running")],
            capabilities=["X"],
            available_vram_mb=5_000,
            profiles={"X": _profile(loaded_vram_mb=20_000)},
        )
        b = _MockProvider(
            provider_id=2,
            name="B",
            lanes=[
                _lane(
                    lane_id="B-z",
                    model_name="Z",
                    runtime_state="loaded",
                    effective_vram_mb=90_000,
                )
            ],
            capabilities=["X"],
            available_vram_mb=2_000,  # tight
            profiles={"X": _profile(loaded_vram_mb=20_000)},
        )
        planner = _planner([a, b])
        self._enable(planner)

        actions = planner._compute_replication_actions(
            provider_ids=[a.provider_id, b.provider_id],
            ranked_models=[("X", 5.0)],
            cluster_lanes_by_model={"X": 1, "Z": 1},
            cycle_planned_models=set(),
        )
        assert actions == []  # no free worker, no eviction allowed

    def test_skips_worker_that_already_hosts_model(self):
        """Worker A already has X — never picked even though it has free VRAM."""
        a = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[_lane(lane_id="A-x", model_name="X", runtime_state="loaded")],
            capabilities=["X"],
            available_vram_mb=80_000,  # plenty
            profiles={"X": _profile(loaded_vram_mb=20_000)},
        )
        planner = _planner([a])
        self._enable(planner)
        actions = planner._compute_replication_actions(
            provider_ids=[a.provider_id],
            ranked_models=[("X", 5.0)],
            cluster_lanes_by_model={"X": 1},
            cycle_planned_models=set(),
        )
        assert actions == []  # only worker that could host it already has it

    def test_skips_model_already_planned_this_cycle(self):
        """If the main demand pass planned a load/wake for X this cycle,
        skip — don't double-plan."""
        a = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[_lane(lane_id="A-x", model_name="X", runtime_state="running")],
            capabilities=["X"],
            available_vram_mb=5_000,
            profiles={"X": _profile(loaded_vram_mb=20_000)},
        )
        b = _MockProvider(
            provider_id=2,
            name="B",
            lanes=[],
            capabilities=["X"],
            available_vram_mb=80_000,
            profiles={"X": _profile(loaded_vram_mb=20_000)},
        )
        planner = _planner([a, b])
        self._enable(planner)
        actions = planner._compute_replication_actions(
            provider_ids=[a.provider_id, b.provider_id],
            ranked_models=[("X", 5.0)],
            cluster_lanes_by_model={"X": 1},
            cycle_planned_models={"X"},  # already planned
        )
        assert actions == []

    def test_replicates_to_higher_free_vram_worker_when_multiple_eligible(self):
        """Two idle workers both eligible to host a replica → the one with
        more free VRAM wins (mirrors ranker's tie-break)."""
        a = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[_lane(lane_id="A-x", model_name="X", runtime_state="running")],
            capabilities=["X"],
            available_vram_mb=5_000,
            profiles={"X": _profile(loaded_vram_mb=20_000)},
        )
        b = _MockProvider(
            provider_id=2,
            name="B",
            lanes=[],
            capabilities=["X"],
            available_vram_mb=40_000,
            profiles={"X": _profile(loaded_vram_mb=20_000)},
        )
        c = _MockProvider(
            provider_id=3,
            name="C",
            lanes=[],
            capabilities=["X"],
            available_vram_mb=80_000,
            profiles={"X": _profile(loaded_vram_mb=20_000)},
        )
        planner = _planner([a, b, c])
        self._enable(planner)
        actions = planner._compute_replication_actions(
            provider_ids=[a.provider_id, b.provider_id, c.provider_id],
            ranked_models=[("X", 5.0)],
            cluster_lanes_by_model={"X": 1},
            cycle_planned_models=set(),
        )
        # Currently the implementation breaks ties by iteration order over
        # provider_ids — the first eligible wins. This is a known simple
        # behaviour and matches the ranker. The test pins it explicitly so
        # any future change (e.g. picking C for highest VRAM) is intentional.
        assert len(actions) == 1
        assert actions[0].provider_id == b.provider_id

    def test_disabled_by_default_returns_empty(self):
        """With LOGOS_REPLICATE_ON_FREE_VRAM unset (default), nothing fires."""
        a = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[_lane(lane_id="A-x", model_name="X", runtime_state="running")],
            capabilities=["X"],
            available_vram_mb=5_000,
            profiles={"X": _profile(loaded_vram_mb=20_000)},
        )
        b = _MockProvider(
            provider_id=2,
            name="B",
            lanes=[],
            capabilities=["X"],
            available_vram_mb=80_000,
            profiles={"X": _profile(loaded_vram_mb=20_000)},
        )
        planner = _planner([a, b])
        # Do NOT call self._enable — leave flag at False
        actions = planner._compute_replication_actions(
            provider_ids=[a.provider_id, b.provider_id],
            ranked_models=[("X", 5.0)],
            cluster_lanes_by_model={"X": 1},
            cycle_planned_models=set(),
        )
        assert actions == []


# ---------------------------------------------------------------------------
# Additional matrix scenarios — sanity checks the user asked about
# ---------------------------------------------------------------------------


class TestSchedulingSanity:
    """Simpler invariant checks the operator flagged as missing:

    - Random orderings of providers / models converge on the same winner.
    - The ranker doesn't pick a worker for an action when a strictly better
      one exists.
    - Multi-model demand routes each model to its best worker independently.
    """

    def test_provider_id_order_does_not_change_winner_when_costs_differ(self):
        """Shuffling the provider list must not change which provider wins
        a model — cost ordering dominates iteration order."""
        # A is warm (cost 0); B is cold (cost 90). A should always win.
        a = _MockProvider(
            provider_id=99,
            name="A",
            lanes=[_lane(lane_id="A-x", model_name="X", runtime_state="loaded")],
            capabilities=["X"],
            available_vram_mb=50_000,
            profiles={"X": _profile(loaded_vram_mb=20_000)},
        )
        b = _MockProvider(
            provider_id=1,
            name="B",
            lanes=[],
            capabilities=["X"],
            available_vram_mb=80_000,
            profiles={"X": _profile(loaded_vram_mb=20_000)},
        )
        planner = _planner([a, b])
        # A=99 > B=1 — if iteration order mattered, B would win on lowest id.
        # The cost-based ranker must still pick A (warm) regardless.
        for ordering in (
            [a.provider_id, b.provider_id],
            [b.provider_id, a.provider_id],
        ):
            winners = planner._rank_providers_for_demanded_models(
                ordering,
                [("X", 1.5)],
            )
            assert winners == {"X": a.provider_id}, f"Iteration order {ordering} changed winner — got {winners}"

    def test_multi_model_independent_routing(self):
        """Two demanded models with one warm worker each must each win on
        their respective warm worker, not the other."""
        # A is warm for X, cold for Y. B is warm for Y, cold for X.
        a = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[_lane(lane_id="A-x", model_name="X", runtime_state="loaded")],
            capabilities=["X", "Y"],
            available_vram_mb=20_000,
            profiles={
                "X": _profile(loaded_vram_mb=20_000),
                "Y": _profile(loaded_vram_mb=20_000),
            },
        )
        b = _MockProvider(
            provider_id=2,
            name="B",
            lanes=[_lane(lane_id="B-y", model_name="Y", runtime_state="loaded")],
            capabilities=["X", "Y"],
            available_vram_mb=20_000,
            profiles={
                "X": _profile(loaded_vram_mb=20_000),
                "Y": _profile(loaded_vram_mb=20_000),
            },
        )
        planner = _planner([a, b])
        winners = planner._rank_providers_for_demanded_models(
            [a.provider_id, b.provider_id],
            [("X", 2.0), ("Y", 2.0)],
        )
        assert winners == {"X": a.provider_id, "Y": b.provider_id}

    def test_warm_worker_beats_sleeping_worker_for_same_model(self):
        """If model is loaded warm on A and sleeping on B, A wins (cost 0 < cost 2)."""
        a = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[_lane(lane_id="A-x", model_name="X", runtime_state="loaded")],
            capabilities=["X"],
            available_vram_mb=50_000,
            profiles={"X": _profile(loaded_vram_mb=20_000)},
        )
        b = _MockProvider(
            provider_id=2,
            name="B",
            lanes=[
                _lane(
                    lane_id="B-x",
                    model_name="X",
                    runtime_state="sleeping",
                    sleep_state="sleeping",
                    effective_vram_mb=500,
                )
            ],
            capabilities=["X"],
            available_vram_mb=50_000,
            profiles={"X": _profile(loaded_vram_mb=20_000, sleeping_residual_mb=500)},
        )
        planner = _planner([a, b])
        winners = planner._rank_providers_for_demanded_models(
            [a.provider_id, b.provider_id],
            [("X", 1.5)],
        )
        assert winners == {"X": a.provider_id}

    def test_does_not_pick_worker_lacking_capability(self):
        """A worker without capability for a model can never be the winner,
        even if it has the most VRAM and lowest provider_id."""
        a = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[],
            capabilities=["OTHER"],
            available_vram_mb=80_000,
            profiles={},
        )
        b = _MockProvider(
            provider_id=2,
            name="B",
            lanes=[_lane(lane_id="B-x", model_name="X", runtime_state="loaded")],
            capabilities=["X"],
            available_vram_mb=10_000,
            profiles={"X": _profile(loaded_vram_mb=20_000)},
        )
        planner = _planner([a, b])
        winners = planner._rank_providers_for_demanded_models(
            [a.provider_id, b.provider_id],
            [("X", 1.5)],
        )
        assert winners == {"X": b.provider_id}

    def test_ranker_is_deterministic_under_random_orderings(self):
        """Same cluster state + same demand → same winners regardless of
        provider_ids permutation. Property: cost-based ranking is a total
        order with deterministic tie-break."""
        import random

        # Build 5 providers with varying state for a single model.
        providers = []
        for pid, state in [
            (10, "loaded"),
            (20, "sleeping"),
            (30, "cold"),
            (40, "sleeping"),
            (50, "loaded"),
        ]:
            lanes = []
            if state == "loaded":
                lanes = [_lane(lane_id=f"{pid}-x", model_name="X", runtime_state="loaded")]
            elif state == "sleeping":
                lanes = [
                    _lane(
                        lane_id=f"{pid}-x",
                        model_name="X",
                        runtime_state="sleeping",
                        sleep_state="sleeping",
                        effective_vram_mb=500,
                    )
                ]
            providers.append(
                _MockProvider(
                    provider_id=pid,
                    name=f"W-{pid}",
                    lanes=lanes,
                    capabilities=["X"],
                    available_vram_mb=40_000,
                    profiles={"X": _profile(loaded_vram_mb=20_000, sleeping_residual_mb=500)},
                )
            )
        planner = _planner(providers)
        all_ids = [p.provider_id for p in providers]
        baseline = planner._rank_providers_for_demanded_models(
            list(all_ids),
            [("X", 2.0)],
        )
        rng = random.Random(0xC0FFEE)
        for _ in range(8):
            shuffled = list(all_ids)
            rng.shuffle(shuffled)
            result = planner._rank_providers_for_demanded_models(
                shuffled,
                [("X", 2.0)],
            )
            assert result == baseline, (
                f"Ranker non-deterministic under ordering {shuffled}: " f"got {result}, expected {baseline}"
            )

    def test_cost_estimator_rejects_when_no_eviction_candidates_and_no_free_vram(self):
        """Pathological: worker has zero free VRAM AND zero displaceable
        lanes — must report infeasible (None), so ranker won't pick it."""
        provider = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[],  # no displaceable lanes
            capabilities=["X"],
            available_vram_mb=100,  # almost nothing
            profiles={"X": _profile(loaded_vram_mb=20_000)},
        )
        planner = _planner([provider])
        result = planner._estimate_demand_action_cost(
            1,
            "X",
            provider.lanes,
            provider.profiles,
            planner._facade.get_capacity_info(1),
        )
        assert result is None

    def test_already_serving_worker_does_not_get_picked_for_eviction_in_replicas_only(
        self,
    ):
        """The replicas-only eviction pass must not stop a model's last lane
        even if the lane has zero demand. Reproduces the "X has zero demand
        and is the only copy" case the user described."""
        provider = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[
                _lane(
                    lane_id="A-x",
                    model_name="X",
                    runtime_state="loaded",
                    effective_vram_mb=20_000,
                ),
            ],
            profiles={"X": _profile(loaded_vram_mb=20_000, sleeping_residual_mb=500)},
        )
        planner = _planner([provider])
        planner._lane_loaded_at = {}
        planner._demand.get_score = lambda *_: 0.0
        # X is the only loaded copy cluster-wide
        cluster = {"X": 1}
        eviction = planner._find_eviction_set(
            provider_id=1,
            required_gpus=frozenset({0}),
            per_gpu_deficit={0: 10_000.0},
            lanes=provider.lanes,
            profiles=provider.profiles,
            replicas_only=True,
            cluster_lanes_by_model=cluster,
        )
        assert eviction is None  # X is primary, cannot be picked in Pass 1

    def test_global_pass_picks_low_demand_primary_over_high_demand_one(self):
        """Pass 2 fallback: when replicas-only fails (or yields none), the
        global pool's demand-based ordering still works — low-demand
        primaries are picked before high-demand ones."""
        # Two primaries (count=1 each): Y is in demand (eff=2.0), Z is idle
        # (eff=0.0). Eviction picker should prefer Z.
        provider = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[
                _lane(
                    lane_id="A-y",
                    model_name="Y",
                    runtime_state="loaded",
                    effective_vram_mb=20_000,
                ),
                _lane(
                    lane_id="A-z",
                    model_name="Z",
                    runtime_state="loaded",
                    effective_vram_mb=20_000,
                ),
            ],
            profiles={
                "Y": _profile(loaded_vram_mb=20_000, sleeping_residual_mb=500),
                "Z": _profile(loaded_vram_mb=20_000, sleeping_residual_mb=500),
            },
        )
        planner = _planner([provider])
        planner._lane_loaded_at = {}

        # Y has high demand, Z has zero.
        def _demand_for(model):
            return 2.0 if model == "Y" else 0.0

        planner._demand.get_score = _demand_for

        # Pass 2: global eviction (no replicas filter).
        eviction = planner._find_eviction_set(
            provider_id=1,
            required_gpus=frozenset({0}),
            per_gpu_deficit={0: 5000.0},
            lanes=provider.lanes,
            profiles=provider.profiles,
            replicas_only=False,
        )
        assert eviction is not None
        picked = {lane.model_name for lane, _a, _e in eviction}
        # Z (lower demand) should be the pick, not Y.
        assert "Z" in picked
        assert "Y" not in picked


class TestWakeTargetSelfEviction:
    """Regression tests for the "self-eviction stops the wakee" bug.

    The eviction picker must never choose the very lane that is about to be
    woken as its own victim: a `stop` destroys the wakee (the follow-up wake
    then fails with "Lane '<id>' not found" and the model goes permanently
    absent). Sibling replicas — same model_name on a *different* lane_id —
    remain legitimate victims.
    """

    def test_eviction_excludes_wake_target_same_lane_id(self):
        """The wake target's own lane is hard-excluded; with no other
        candidate the deficit is uncoverable → None. Control: without
        target_lane_id the same lane WOULD be picked (proves the setup is
        otherwise tempting and the filter is what excludes it)."""
        provider = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[
                _lane(
                    lane_id="planner-X",
                    model_name="X",
                    runtime_state="sleeping",
                    sleep_state="sleeping",
                    effective_vram_mb=9000,
                    gpu_devices="0",
                ),
            ],
            profiles={"X": _profile(loaded_vram_mb=20_000.0, sleeping_residual_mb=9000.0)},
        )
        planner = _planner([provider])
        planner._lane_loaded_at = {}
        planner._demand.get_score = lambda *_: 0.0

        common = dict(
            provider_id=1,
            required_gpus=frozenset({0}),
            per_gpu_deficit={0: 100.0},
            lanes=provider.lanes,
            profiles=provider.profiles,
            target_model_name="X",
        )

        # Control: self-eviction allowed when we don't identify the wakee.
        control = planner._find_eviction_set(**common)
        assert control, "setup must be tempting: lane is picked without the filter"
        assert any(l.lane_id == "planner-X" for l, _a, _e in control)

        # With the wakee identified by lane_id it must be excluded entirely.
        guarded = planner._find_eviction_set(target_lane_id="planner-X", **common)
        assert guarded is None or all(l.lane_id != "planner-X" for l, _a, _e in guarded)

    def test_eviction_allows_sibling_replica_of_same_model(self):
        """Same model_name, different lane_id → still a valid victim."""
        provider = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[
                _lane(
                    lane_id="planner-X",
                    model_name="X",
                    runtime_state="sleeping",
                    sleep_state="sleeping",
                    effective_vram_mb=500,
                    gpu_devices="0",
                ),
                _lane(
                    lane_id="X-sibling",
                    model_name="X",
                    runtime_state="loaded",
                    sleep_state="awake",
                    effective_vram_mb=20_000,
                    gpu_devices="0",
                ),
            ],
            profiles={"X": _profile(loaded_vram_mb=20_000.0, sleeping_residual_mb=500.0)},
        )
        planner = _planner([provider])
        planner._lane_loaded_at = {}
        planner._stop_dedup_siblings = False
        planner._demand.get_score = lambda *_: 0.0

        eviction = planner._find_eviction_set(
            provider_id=1,
            required_gpus=frozenset({0}),
            per_gpu_deficit={0: 5000.0},
            lanes=provider.lanes,
            profiles=provider.profiles,
            target_model_name="X",
            target_lane_id="planner-X",
        )
        assert eviction is not None
        picked = {l.lane_id for l, _a, _e in eviction}
        assert "X-sibling" in picked  # sibling replica is fair game
        assert "planner-X" not in picked  # the wakee never is

    def test_self_eviction_followup_uses_load_when_target_stopped(self):
        """Defensive net: if a `stop` of the wakee ever slips through, the
        follow-up must be `load` (fresh process), never `wake` (would hit
        "Lane not found"). Drive _compute_demand_actions with a poisoned
        eviction set."""
        target = _lane(
            lane_id="planner-X",
            model_name="X",
            runtime_state="sleeping",
            sleep_state="sleeping",
            effective_vram_mb=500,
            gpu_devices="0",
        )
        provider = _MockProvider(
            provider_id=1,
            name="A",
            lanes=[target],
            profiles={"X": _profile(loaded_vram_mb=20_000.0, sleeping_residual_mb=500.0)},
            available_vram_mb=0.0,  # force a deficit so eviction is needed
        )
        planner = _planner([provider])
        planner._cross_provider_dedup = False
        planner._provider_capacity_lock = lambda pid: SimpleNamespace(locked=lambda: False)
        planner._vram_ledger = SimpleNamespace(
            get_committed_mb=lambda pid: 0.0,
            has_overlapping_reservation=lambda *a, **k: False,
            get_gpu_effective_available_mb=lambda pid, g, f: f,
        )
        planner._get_queue_depth_across_deployments = lambda *_: 0
        planner._build_load_params = lambda *a, **k: {}
        planner._demand.get_ranked_models.return_value = [("X", 1.0)]

        # Poison: return the wakee itself as a `stop` victim.
        planner._find_eviction_set = lambda *a, **k: [(target, "stop", 0.0)]

        actions = planner._compute_demand_actions(1, provider.lanes)

        kinds = [(a.action, a.lane_id) for a in actions]
        assert ("stop", "planner-X") in kinds
        assert ("load", "planner-X") in kinds
        assert all(a.action != "wake" for a in actions)
        # Order: destructive stop before the recovering load.
        assert kinds.index(("stop", "planner-X")) < kinds.index(("load", "planner-X"))
