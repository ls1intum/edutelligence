"""Tests for plan_cache_order — the host-RAM-aware tmpfs cache planner.

The operator rule the planner enforces:

    Load as many models into the tmpfs cache as possible WITHOUT lowering
    the number of models that can be sleeping simultaneously.

Concretely: reserve ``sum(host_ram of every sleepable capability model)``
from the host's available RAM, then pack the leftover with cache candidates
(unsleepable first because they cannot be brought back via sleep_l1; smallest
first within each group to maximise count).
"""

from __future__ import annotations

from logos_worker_node.cache_planner import CacheCandidate, plan_cache_order

_MB = 1024 * 1024


def _c(
    name: str, *, can_sleep: bool, host_ram_mb: float, size_bytes: int
) -> CacheCandidate:
    return CacheCandidate(
        name=name,
        can_sleep=can_sleep,
        host_ram_mb=host_ram_mb,
        size_bytes=size_bytes,
    )


def test_no_candidates_returns_empty_plan():
    plan = plan_cache_order(
        [],
        available_host_ram_mb=100_000.0,
        safety_margin_mb=4096.0,
    )
    assert plan.order == []
    assert plan.reserved_for_sleep_mb == 0.0
    assert plan.cached_unsleepable == []
    assert plan.cached_sleepable == []


def test_single_unsleepable_is_cached_regardless_of_budget():
    """Unsleepable models don't enter the sleep reserve and are always queued
    for caching — the operator rule protects sleep capacity, and unsleepable
    models aren't in it."""
    plan = plan_cache_order(
        [_c("u", can_sleep=False, host_ram_mb=50_000.0, size_bytes=50 * _MB)],
        available_host_ram_mb=10.0,  # absurdly low — doesn't matter
        safety_margin_mb=4096.0,
    )
    assert plan.order == ["u"]
    assert plan.reserved_for_sleep_mb == 0.0


def test_all_sleepable_fit_in_budget_get_cached():
    """Three small sleepable models, lots of host RAM → all reserved AND all
    cached. (reserve takes 6GB, budget = 100GB − 6GB − 8GB = 86GB, the three
    weigh ~3 GB on disk and pack easily.)"""
    cands = [
        _c("a", can_sleep=True, host_ram_mb=2_000.0, size_bytes=int(1.5 * 1024) * _MB),
        _c("b", can_sleep=True, host_ram_mb=2_000.0, size_bytes=int(1.0 * 1024) * _MB),
        _c("c", can_sleep=True, host_ram_mb=2_000.0, size_bytes=int(0.5 * 1024) * _MB),
    ]
    plan = plan_cache_order(
        cands,
        available_host_ram_mb=100_000.0,
        safety_margin_mb=8192.0,
    )
    assert plan.reserved_for_sleep_mb == 6_000.0
    # Smallest-first within sleepable group
    assert plan.order == ["c", "b", "a"]
    assert plan.skipped_sleepable == []


def test_sleepable_skipped_when_tmpfs_budget_exhausted():
    """Tight host RAM — reserve eats most of it. Only the smallest sleepable
    fits in the remaining budget; larger ones are skipped."""
    cands = [
        _c("small", can_sleep=True, host_ram_mb=20_000.0, size_bytes=5_000 * _MB),
        _c("large", can_sleep=True, host_ram_mb=20_000.0, size_bytes=15_000 * _MB),
    ]
    # reserve = 40GB; available − reserve − margin = 60GB − 40GB − 4GB = 16GB
    plan = plan_cache_order(
        cands,
        available_host_ram_mb=60_000.0,
        safety_margin_mb=4096.0,
    )
    assert plan.reserved_for_sleep_mb == 40_000.0
    assert plan.sleepable_tmpfs_budget_mb == 60_000.0 - 40_000.0 - 4096.0
    assert plan.cached_sleepable == ["small"]
    assert plan.skipped_sleepable == ["large"]
    assert plan.order == ["small"]


def test_unsleepable_precedes_sleepable_in_order():
    """Ordering rule: every unsleepable comes before any sleepable, regardless
    of size."""
    cands = [
        _c("sleep-tiny", can_sleep=True, host_ram_mb=1_000.0, size_bytes=100 * _MB),
        _c(
            "no-sleep-huge",
            can_sleep=False,
            host_ram_mb=80_000.0,
            size_bytes=80_000 * _MB,
        ),
        _c("sleep-medium", can_sleep=True, host_ram_mb=2_000.0, size_bytes=2_000 * _MB),
    ]
    plan = plan_cache_order(
        cands,
        available_host_ram_mb=200_000.0,
        safety_margin_mb=4096.0,
    )
    # Unsleepable first, then sleepable smallest-first
    assert plan.order == ["no-sleep-huge", "sleep-tiny", "sleep-medium"]


def test_reserve_can_be_larger_than_available_no_sleepable_cached():
    """Overcommitted: every sleepable can't fit in host RAM even by itself.
    Budget goes negative → no sleepable is cached. Unsleepables still queue."""
    cands = [
        _c("over-1", can_sleep=True, host_ram_mb=80_000.0, size_bytes=80_000 * _MB),
        _c("over-2", can_sleep=True, host_ram_mb=80_000.0, size_bytes=80_000 * _MB),
        _c("u", can_sleep=False, host_ram_mb=10_000.0, size_bytes=10_000 * _MB),
    ]
    plan = plan_cache_order(
        cands,
        available_host_ram_mb=100_000.0,
        safety_margin_mb=4096.0,
    )
    assert plan.reserved_for_sleep_mb == 160_000.0
    assert plan.sleepable_tmpfs_budget_mb < 0
    assert plan.cached_sleepable == []
    assert plan.cached_unsleepable == ["u"]
    assert plan.order == ["u"]


def test_safety_margin_is_subtracted_before_packing():
    """4 GB safety margin → a sleepable that would just fit without margin
    must be skipped."""
    cands = [
        # reserve = 50GB; available 60GB − 50GB − 8GB margin = 2GB budget.
        # Sleepable is 5GB on disk — doesn't fit.
        _c(
            "just-too-big", can_sleep=True, host_ram_mb=50_000.0, size_bytes=5_000 * _MB
        ),
    ]
    plan = plan_cache_order(
        cands,
        available_host_ram_mb=60_000.0,
        safety_margin_mb=8192.0,
    )
    assert plan.cached_sleepable == []
    assert plan.skipped_sleepable == ["just-too-big"]


def test_plan_is_deterministic_for_identical_inputs():
    """Same inputs → identical CachePlan, every time."""
    cands = [
        _c("a", can_sleep=True, host_ram_mb=5_000.0, size_bytes=5_000 * _MB),
        _c("b", can_sleep=False, host_ram_mb=10_000.0, size_bytes=10_000 * _MB),
        _c("c", can_sleep=True, host_ram_mb=3_000.0, size_bytes=3_000 * _MB),
    ]
    first = plan_cache_order(
        cands, available_host_ram_mb=100_000.0, safety_margin_mb=4096.0
    )
    second = plan_cache_order(
        cands, available_host_ram_mb=100_000.0, safety_margin_mb=4096.0
    )
    third = plan_cache_order(
        cands, available_host_ram_mb=100_000.0, safety_margin_mb=4096.0
    )
    assert first.order == second.order == third.order
    assert (
        first.cached_unsleepable
        == second.cached_unsleepable
        == third.cached_unsleepable
    )
    assert first.cached_sleepable == second.cached_sleepable == third.cached_sleepable


def test_smallest_first_within_each_group():
    cands = [
        _c("u-big", can_sleep=False, host_ram_mb=20_000.0, size_bytes=20_000 * _MB),
        _c("u-small", can_sleep=False, host_ram_mb=2_000.0, size_bytes=2_000 * _MB),
        _c("u-medium", can_sleep=False, host_ram_mb=10_000.0, size_bytes=10_000 * _MB),
        _c("s-big", can_sleep=True, host_ram_mb=20_000.0, size_bytes=20_000 * _MB),
        _c("s-small", can_sleep=True, host_ram_mb=2_000.0, size_bytes=2_000 * _MB),
    ]
    plan = plan_cache_order(
        cands,
        available_host_ram_mb=200_000.0,
        safety_margin_mb=4096.0,
    )
    assert plan.cached_unsleepable == ["u-small", "u-medium", "u-big"]
    assert plan.cached_sleepable == ["s-small", "s-big"]
    assert plan.order == [
        "u-small",
        "u-medium",
        "u-big",
        "s-small",
        "s-big",
    ]
