"""Decide which capability models to pre-populate into the tmpfs RAM cache.

The rule (per operator design):

    Load as many models into the tmpfs cache as possible WITHOUT lowering
    the number of models that can be in sleep_l1 simultaneously.

Why this rule exists:

  - vLLM sleep_l1 keeps a lane's model weights resident in **host RAM** so
    the next wake completes in ~2 s instead of a 30–90 s cold reload.
  - The tmpfs cache ALSO consumes host RAM (tmpfs is a RAM-backed filesystem
    on Linux). If the cache eats too much, fewer lanes can sleep
    simultaneously and the planner is forced to either stop them (slow
    recovery) or block new loads (deioma incident).
  - So: reserve enough host RAM for every sleepable capability model to be
    sleeping at the same time, then use any leftover RAM for the cache.

The algorithm is deterministic — same inputs always produce the same output:

  1. Compute ``reserve_mb = sum(host_ram of every sleepable capability)``.
  2. ``budget_mb = available_host_ram_mb − reserve_mb − safety_margin_mb``.
     If non-positive: budget is zero (only the unsleepable models, which are
     unaffected by the sleep reserve, may still get cached up to tmpfs limits;
     see step 4).
  3. Priority list: unsleepable models first (smallest → largest), then
     sleepable models (smallest → largest). Unsleepable models benefit most
     from the cache because their only path back to "loaded" is a cold reload
     from disk; sleepable models can fall back to a fast sleep_l1 wake.
  4. Greedy pack: walk the priority list, accumulating into the budget.
     Sleepable models are skipped once the running tmpfs budget would go
     negative. Unsleepable models are always included regardless of budget —
     they don't enter the sleep reserve (they can't sleep) and the operator's
     rule explicitly does not protect anyone else's sleep capacity from
     them. The tmpfs free-space safety margin (10 %) inside
     ``model_cache.cache_models_by_priority`` still acts as a hard backstop.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CacheCandidate:
    """Inputs the planner needs about a single capability model."""

    name: str
    can_sleep: bool
    host_ram_mb: float  # projected host-RAM footprint when loaded
    size_bytes: int  # weights on disk; surrogate for tmpfs cost


@dataclass(frozen=True)
class CachePlan:
    """Result of plan_cache_order: ordered list + the budget computation."""

    order: list[str]
    reserved_for_sleep_mb: float
    available_host_ram_mb: float
    safety_margin_mb: float
    sleepable_tmpfs_budget_mb: float
    cached_unsleepable: list[str]
    cached_sleepable: list[str]
    skipped_sleepable: list[str]


def plan_cache_order(
    candidates: list[CacheCandidate],
    *,
    available_host_ram_mb: float,
    safety_margin_mb: float,
) -> CachePlan:
    """Decide which models to pre-cache and in what order.

    Inputs:
      - ``candidates``: every calibrated capability model the worker knows
        about, with its sleep capability, projected host-RAM footprint, and
        tmpfs cost.
      - ``available_host_ram_mb``: worker's MemAvailable at startup.
      - ``safety_margin_mb``: fixed host-RAM buffer for OS file cache,
        malloc fragmentation, vLLM mm processor caches, etc.

    Returns a CachePlan describing the ordering and the budget arithmetic
    used to derive it. ``order`` is the list to pass to
    ``ModelRamCache.cache_models_by_priority``.
    """
    unsleepable = sorted(
        (c for c in candidates if not c.can_sleep),
        key=lambda c: c.size_bytes,
    )
    sleepable = sorted(
        (c for c in candidates if c.can_sleep),
        key=lambda c: c.size_bytes,
    )

    reserved_for_sleep_mb = sum(c.host_ram_mb for c in sleepable)
    sleepable_tmpfs_budget_mb = available_host_ram_mb - reserved_for_sleep_mb - safety_margin_mb

    # Unsleepable models are always queued — they can't sleep, so they cannot
    # reduce anyone else's sleep capacity by being in the cache (the rule
    # protects sleepable count, and they aren't in it). The tmpfs free-space
    # safety margin still bounds the actual copy.
    cached_unsleepable = [c.name for c in unsleepable]

    # Sleepable models consume tmpfs budget — pack greedily by size until the
    # budget is exhausted. Models whose host_ram_mb is unknown (0) consume
    # nothing from the reserve; we treat their tmpfs cost as the model size.
    cached_sleepable: list[str] = []
    skipped_sleepable: list[str] = []
    remaining_budget_mb = max(sleepable_tmpfs_budget_mb, 0.0)
    for c in sleepable:
        size_mb = c.size_bytes / (1024 * 1024)
        if size_mb <= remaining_budget_mb:
            cached_sleepable.append(c.name)
            remaining_budget_mb -= size_mb
        else:
            skipped_sleepable.append(c.name)

    order = cached_unsleepable + cached_sleepable
    return CachePlan(
        order=order,
        reserved_for_sleep_mb=reserved_for_sleep_mb,
        available_host_ram_mb=available_host_ram_mb,
        safety_margin_mb=safety_margin_mb,
        sleepable_tmpfs_budget_mb=sleepable_tmpfs_budget_mb,
        cached_unsleepable=cached_unsleepable,
        cached_sleepable=cached_sleepable,
        skipped_sleepable=skipped_sleepable,
    )
