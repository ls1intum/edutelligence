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

  1. Compute ``reserve_mb = sum(sleeping host_ram of every sleepable
     capability that is NOT already asleep)`` — what those lanes will hold
     when they sleep, not what they hold while awake. A model that is asleep
     right now is already paying for itself: its sleeping weights sit in
     host RAM and are therefore already subtracted from
     ``available_host_ram_mb``. Reserving its footprint on top of that would
     count the same RAM twice and shrink the budget by the size of every
     sleeping model — exactly the over-correction a re-plan must not do.
     At boot nobody is asleep (``asleep`` is empty) and the full reserve
     applies, as before.
  2. ``budget_mb = (available_host_ram_mb + cache_held_mb) − reserve_mb −
     safety_margin_mb``. The cache's own footprint is added back because it
     is reclaimable: a budget measured from ``MemAvailable`` alone is a
     budget measured after the cache already spent it, so a full cache
     reports no room, declines to cache anything more, and keeps every byte
     it has. Adding it back asks the question that matters — how much may
     the cache hold in total — and lets the answer come out lower than what
     it currently holds, which is what produces an eviction.
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
    # Host RAM this model holds *while asleep* — what the reserve has to
    # cover, since the reserve exists so every sleepable model can be in
    # sleep_l1 at once. Not the awake footprint: an awake lane's RAM is
    # spoken for whether or not the cache is holding anything, so counting
    # it here would reserve the same memory twice.
    sleeping_host_ram_mb: float
    size_bytes: int  # weights on disk; surrogate for tmpfs cost
    # How many sleep-capable lane replicas of this model are configured/live.
    # ``LaneSetRequest`` allows several uniquely named lanes for the same
    # model, and each vLLM process keeps its own weights in host RAM while
    # asleep, so the sleep reserve is this factor times the per-process
    # footprint. ``size_bytes`` (the shared tmpfs cache copy) is NOT
    # multiplied — the cache stores one copy per model no matter how many
    # replicas sleep.
    sleeping_replicas: int = 1


@dataclass(frozen=True)
class CachePlan:
    """Result of plan_cache_order: ordered list + the budget computation."""

    order: list[str]
    reserved_for_sleep_mb: float
    available_host_ram_mb: float
    cache_held_mb: float
    safety_margin_mb: float
    sleepable_tmpfs_budget_mb: float
    cached_unsleepable: list[str]
    cached_sleepable: list[str]
    skipped_sleepable: list[str]
    asleep: frozenset[str] = frozenset()


def plan_cache_order(
    candidates: list[CacheCandidate],
    *,
    available_host_ram_mb: float,
    safety_margin_mb: float,
    cache_held_mb: float = 0.0,
    asleep: dict[str, int] | set[str] | frozenset[str] | None = None,
) -> CachePlan:
    """Decide which models to pre-cache and in what order.

    Inputs:
      - ``candidates``: every calibrated capability model the worker knows
        about, with its sleep capability, sleeping host-RAM footprint, and
        tmpfs cost.
      - ``available_host_ram_mb``: worker's current MemAvailable.
      - ``safety_margin_mb``: host-RAM buffer for OS file cache, malloc
        fragmentation, vLLM mm processor caches, the cold-load spike, etc.
      - ``cache_held_mb``: what the tmpfs cache already holds. Added back
        into the pool because it is reclaimable — see the module docstring.
        Zero reproduces the original from-scratch behaviour.
      - ``asleep``: per-model count of lanes asleep right now (a
        ``dict`` of model -> count, or a set/frozenset of model names, each
        counting as one). An asleep lane's RAM is already out of
        ``available_host_ram_mb``, so its share of the sleep reserve is
        dropped — see the module docstring. With several same-model
        replicas only the awake ones stay reserved: ``(sleepable_replicas
        - asleep_replicas) * sleeping_host_ram_mb``.

    Returns a CachePlan describing the ordering and the budget arithmetic
    used to derive it. ``order`` is the list to pass to
    ``ModelRamCache.cache_models_by_priority``; anything cached but absent
    from it is what the caller should reclaim.
    """
    unsleepable = sorted(
        (c for c in candidates if not c.can_sleep),
        key=lambda c: c.size_bytes,
    )
    sleepable = sorted(
        (c for c in candidates if c.can_sleep),
        key=lambda c: c.size_bytes,
    )

    # Normalise the asleep input to per-model counts so a same-model replica
    # that is asleep drops exactly its own share of the reserve (a set/frozen
    # set counts every listed model as one).
    if asleep is None:
        asleep_counts: dict[str, int] = {}
    elif isinstance(asleep, dict):
        asleep_counts = {m: max(0, int(n)) for m, n in asleep.items() if n}
    else:
        asleep_counts = {m: 1 for m in asleep}

    # A lane that is already asleep is not reserved: its sleeping RAM is
    # already out of MemAvailable (see the module docstring), so reserving it
    # again would double-count. With several same-model replicas, each vLLM
    # process keeps its own weights in host RAM while asleep, so only the
    # awake replicas' footprints are reserved:
    # ``sleeping_host_ram_mb * (sleeping_replicas - asleep_replicas)``.
    reserved_for_sleep_mb = sum(
        c.sleeping_host_ram_mb * max(0, c.sleeping_replicas - asleep_counts.get(c.name, 0)) for c in sleepable
    )
    pool_mb = available_host_ram_mb + max(cache_held_mb, 0.0)
    sleepable_tmpfs_budget_mb = pool_mb - reserved_for_sleep_mb - safety_margin_mb

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
        cache_held_mb=cache_held_mb,
        safety_margin_mb=safety_margin_mb,
        sleepable_tmpfs_budget_mb=sleepable_tmpfs_budget_mb,
        cached_unsleepable=cached_unsleepable,
        cached_sleepable=cached_sleepable,
        skipped_sleepable=skipped_sleepable,
        asleep=frozenset(asleep_counts),
    )
