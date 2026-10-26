"""Residency policy switch (LOGOS_RESIDENCY_POLICY).

"demand" (default) orders eviction victims by effective demand; "lru" is an
ablation baseline that orders them by idle time (least recently used first).
Both keep the sleep-before-stop preference; only the victim heuristic differs.
"""

from __future__ import annotations

import time

import pytest

from logos import CapacityPlanner

from .test_best_first_scenarios import _lane, _MockProvider, _planner, _profile


def _two_idle_lanes_provider() -> _MockProvider:
    """Two awake, idle lanes on GPU 0; evicting either one covers the deficit."""
    return _MockProvider(
        provider_id=1,
        name="A",
        lanes=[
            _lane(lane_id="A-hot", model_name="Hot", effective_vram_mb=20_000, gpu_devices="0"),
            _lane(lane_id="A-cold", model_name="Cold", effective_vram_mb=20_000, gpu_devices="0"),
        ],
        profiles={
            "Hot": _profile(loaded_vram_mb=20_000, sleeping_residual_mb=500.0),
            "Cold": _profile(loaded_vram_mb=20_000, sleeping_residual_mb=500.0),
        },
    )


def _evict_one(planner: CapacityPlanner, provider: _MockProvider) -> str:
    eviction = planner._find_eviction_set(
        provider_id=1,
        required_gpus=frozenset({0}),
        per_gpu_deficit={0: 5_000.0},
        lanes=provider.lanes,
        profiles=provider.profiles,
    )
    assert eviction is not None and len(eviction) == 1
    lane, action, _eff = eviction[0]
    assert action == "sleep_l1"
    return lane.model_name


def _setup(policy: str | None) -> tuple[CapacityPlanner, _MockProvider]:
    provider = _two_idle_lanes_provider()
    planner = _planner([provider])
    if policy is not None:
        planner._residency_policy = policy
    now = time.time()
    # "Hot" was idle for a long time (least recently used) but carries high
    # demand; "Cold" was used a moment ago but has no demand. The two policies
    # must therefore pick different victims.
    planner._lane_idle_since = {
        planner._lane_key(1, "A-hot"): now - 600.0,
        planner._lane_key(1, "A-cold"): now - 5.0,
    }
    planner._demand.get_score = lambda model, *_a, **_k: 5.0 if model == "Hot" else 0.0
    return planner, provider


class TestParseResidencyPolicy:
    @pytest.mark.parametrize("raw", [None, "", "demand", "DEMAND", " demand "])
    def test_defaults_to_demand(self, raw):
        assert CapacityPlanner._parse_residency_policy(raw) == "demand"

    @pytest.mark.parametrize("raw", ["lru", "LRU", " lru "])
    def test_accepts_lru(self, raw):
        assert CapacityPlanner._parse_residency_policy(raw) == "lru"

    def test_unknown_value_falls_back_to_demand(self):
        assert CapacityPlanner._parse_residency_policy("fifo") == "demand"


class TestEvictionOrder:
    def test_planner_without_attribute_uses_demand_policy(self):
        planner, _ = _setup(policy=None)
        assert planner.residency_policy == "demand"

    def test_demand_policy_evicts_lowest_demand(self):
        planner, provider = _setup(policy="demand")
        assert _evict_one(planner, provider) == "Cold"

    def test_lru_policy_evicts_least_recently_used(self):
        planner, provider = _setup(policy="lru")
        assert _evict_one(planner, provider) == "Hot"

    def test_lru_policy_still_prefers_sleep_over_stop(self):
        """A lane that can only be stopped must not be chosen ahead of a
        sleepable one, even if it has been idle longer."""
        planner, provider = _setup(policy="lru")
        # Make the long-idle lane an eligible "stop" candidate: a lane started
        # without sleep support can only be stopped, and stopping it is only
        # allowed while its model's demand is below the load floor.
        hot_lane = next(lane for lane in provider.lanes if lane.model_name == "Hot")
        hot_lane.sleep_state = "unsupported"
        planner._demand.get_score = lambda *_a, **_k: 0.0

        def _evict(target_lane_id: str | None = None):
            return planner._find_eviction_set(
                provider_id=1,
                required_gpus=frozenset({0}),
                per_gpu_deficit={0: 5_000.0},
                lanes=provider.lanes,
                profiles=provider.profiles,
                target_lane_id=target_lane_id,
            )

        # Precondition: with the sleepable lane out of the way, Hot is a
        # valid victim on its own, and its only action is "stop".
        alone = _evict(target_lane_id="A-cold")
        assert alone is not None and len(alone) == 1
        assert alone[0][0].model_name == "Hot"
        assert alone[0][1] == "stop"

        # With both lanes eligible, the newer sleepable lane wins over the
        # older stop-only one.
        eviction = _evict()
        assert eviction is not None and len(eviction) == 1
        first_lane, first_action, _ = eviction[0]
        assert first_action == "sleep_l1"
        assert first_lane.model_name == "Cold"
